"""Shared helpers for the imaging and plugin tests: a fake Serenity device
gateway, a fake DICOMweb (STOW-RS) server, DICOM test images and a modality
(pynetdicom SCU)."""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pydicom
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid

os.environ["LABSYNC_ALLOW_HTTP"] = "1"

KEY = "sdk_test-key-123"


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def make_dataset(accession="OK1", patient_id="MR001", study_uid=None, sop_uid=None, modality="US", rows=64):
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.6.1"  # US image storage
    meta.MediaStorageSOPInstanceUID = sop_uid or generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = Dataset()
    ds.file_meta = meta
    ds.SOPClassUID = meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.StudyInstanceUID = study_uid or generate_uid()
    ds.SeriesInstanceUID = generate_uid()
    ds.AccessionNumber = accession
    ds.PatientID = patient_id
    ds.PatientName = "Test^Patient"
    ds.Modality = modality
    ds.StudyDescription = "Abdomen"
    ds.Rows = rows
    ds.Columns = rows
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = "MONOCHROME2"
    ds.BitsAllocated = 8
    ds.BitsStored = 8
    ds.HighBit = 7
    ds.PixelRepresentation = 0
    ds.PixelData = bytes(range(256)) * (rows * rows // 256)
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    return ds


def split_multipart(body: bytes, content_type: str) -> list[bytes]:
    boundary = content_type.split("boundary=")[1].strip().strip('"').encode()
    parts = []
    for chunk in body.split(b"--" + boundary)[1:]:
        if chunk.startswith(b"--"):
            break
        content = chunk[chunk.find(b"\r\n\r\n") + 4:]
        parts.append(content[:-2] if content.endswith(b"\r\n") else content)
    return parts


class FakeSerenity:
    """Serenity's device gateway, deciding by accession number:
    OK*  stored   HOLD*  hold   FLAKY*  retry once, then stored   BAD*  reject"""

    def __init__(self):
        self.port = free_port()
        self.received: list[dict] = []  # stored instances
        self.requests = 0
        self.heartbeats: list[dict] = []
        self.status_override = None
        self.modalities = []
        self.flaky_seen: set = set()
        self.lab_results: list[dict] = []
        self.hold_release: set = set()  # accession numbers whose order now exists
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _reply(self, code, data):
                body = json.dumps(data).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length)
                if self.headers.get("X-Device-Key") != KEY:
                    return self._reply(401, {"detail": "bad key"})
                if outer.status_override:
                    return self._reply(outer.status_override, {"detail": "down"})
                if self.path.endswith("/device-gateway/heartbeat"):
                    outer.heartbeats.append(json.loads(body))
                    return self._reply(200, {"device": {"name": "GW"}, "organization": {"name": "Test Clinic"},
                                             "modalities": outer.modalities})
                if self.path.endswith("/device-gateway/lab-results"):
                    payload = json.loads(body)
                    key = self.headers.get("Idempotency-Key")
                    duplicate = key in {r["key"] for r in outer.lab_results}
                    if not duplicate:
                        outer.lab_results.append({"key": key, "body": payload})
                    return self._reply(200, {"id": len(outer.lab_results), "accession_number": payload["patient"]["sample_id"]})
                if self.path.endswith("/device-gateway/dicom/instances"):
                    outer.requests += 1
                    results = []
                    for raw in split_multipart(body, self.headers["Content-Type"]):
                        import io

                        try:
                            ds = pydicom.dcmread(io.BytesIO(raw))
                        except Exception:
                            results.append({"outcome": "reject", "status": "unreadable"})
                            continue
                        acc = str(ds.AccessionNumber)
                        sop = str(ds.SOPInstanceUID)
                        if acc.startswith("HOLD") and acc not in outer.hold_release:
                            results.append({"outcome": "hold", "status": "order_not_found", "detail": f"No active order for {acc}"})
                        elif acc.startswith("FLAKY") and sop not in outer.flaky_seen:
                            outer.flaky_seen.add(sop)
                            results.append({"outcome": "retry", "status": "error", "detail": "S3 timeout"})
                        elif acc.startswith("BAD"):
                            results.append({"outcome": "reject", "status": "unreadable", "detail": "bad"})
                        else:
                            outer.received.append({"sop": sop, "accession": acc, "bytes": raw})
                            results.append({"outcome": "stored", "status": "stored"})
                    stored = sum(1 for r in results if r["outcome"] == "stored")
                    code = 200 if stored == len(results) else (202 if stored else 409)
                    return self._reply(code, {"stored": stored, "failed": len(results) - stored, "results": results})
                self._reply(404, {})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        self.thread = None

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}/v2"

    def start(self):
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()

    def restart(self):
        handler = self.httpd.RequestHandlerClass
        self.httpd = ThreadingHTTPServer(("127.0.0.1", self.port), handler)
        self.start()


class FakeDicomWeb:
    """A DICOMweb server's STOW-RS endpoint (POST /dicom-web/studies), deciding by accession number:
    OK*  stored   BUSY*  out of resources once, then stored   BAD*  SOP class not supported."""

    def __init__(self, username: str = "", password: str = ""):
        self.port = free_port()
        self.received: list[dict] = []
        self.requests = 0
        self.busy_seen: set = set()
        self.auth = None
        outer = self
        if username:
            import base64

            self.auth = "Basic " + base64.b64encode(f"{username}:{password}".encode()).decode()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _reply(self, code, data=None):
                body = json.dumps(data).encode() if data is not None else b""
                self.send_response(code)
                self.send_header("Content-Type", "application/dicom+json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _authorised(self):
                return outer.auth is None or self.headers.get("Authorization") == outer.auth

            def do_GET(self):
                if not self._authorised():
                    return self._reply(401)
                return self._reply(200, []) if self.path.startswith("/dicom-web/studies") else self._reply(404)

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length)
                if not self._authorised():
                    return self._reply(401)
                if self.path != "/dicom-web/studies":
                    return self._reply(404)
                outer.requests += 1
                ok, failed = [], []
                import io

                for raw in split_multipart(body, self.headers["Content-Type"]):
                    ds = pydicom.dcmread(io.BytesIO(raw))
                    acc, sop = str(ds.AccessionNumber), str(ds.SOPInstanceUID)
                    if acc.startswith("BUSY") and sop not in outer.busy_seen:
                        outer.busy_seen.add(sop)
                        failed.append((sop, 0xA700))
                    elif acc.startswith("BAD"):
                        failed.append((sop, 0x0122))
                    else:
                        outer.received.append({"sop": sop, "accession": acc})
                        ok.append(sop)
                answer = {
                    "00081199": {"vr": "SQ", "Value": [{"00081155": {"vr": "UI", "Value": [u]}} for u in ok]},
                    "00081198": {"vr": "SQ", "Value": [{"00081155": {"vr": "UI", "Value": [u]},
                                                        "00081197": {"vr": "US", "Value": [c]}} for u, c in failed]},
                }
                return self._reply(200 if not failed else (202 if ok else 409), answer)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}/dicom-web"

    def start(self):
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def wait_until(fn, timeout=10.0, interval=0.05):
    end = time.time() + timeout
    while time.time() < end:
        if fn():
            return True
        time.sleep(interval)
    return False


def send(port, datasets, calling="US_ROOM1", called="LABSYNC"):
    """Send like a modality would (pynetdicom SCU). Returns DIMSE statuses, or None if rejected."""
    from pynetdicom import AE

    ae = AE(ae_title=calling)
    for ds in datasets:
        ae.add_requested_context(ds.SOPClassUID, ExplicitVRLittleEndian)
    assoc = ae.associate("127.0.0.1", port, ae_title=called)
    if not assoc.is_established:
        return None
    statuses = [assoc.send_c_store(ds).Status for ds in datasets]
    assoc.release()
    return statuses
