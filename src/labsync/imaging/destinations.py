"""Where received images go.

SerenityDestination  HTTPS to Serenity's device gateway
                     (POST {url}/device-gateway/dicom/instances, X-Device-Key),
                     STOW-RS style multipart/related, streamed from disk.
DicomDestination     C-STORE to another DICOM node on the network, e.g. the
                     PostDICOM communicator, for modalities that can only send
                     to one place.

send() returns one outcome per instance:
  stored  delivered (or already there)
  hold    Serenity has no matching order yet / patient mismatch: try again later
  retry   temporary problem: try again soon
  reject  will never be accepted (not a readable DICOM file)
and raises Unreachable when the destination could not be reached at all, so
the forwarder pauses that destination instead of counting a failure per image.
"""

import io
import logging
import os
import uuid
from dataclasses import dataclass

import requests

from .. import __version__

logger = logging.getLogger(__name__)

STORED, HOLD, RETRY, REJECT = "stored", "hold", "retry", "reject"
SERENITY = "serenity"


class Unreachable(Exception):
    pass


def describe_network_error(exc: Exception) -> str:
    """Plain words for the status page; the full error goes to the log."""
    logger.info("network error: %r", exc)
    if isinstance(exc, requests.exceptions.SSLError):
        return "Can't reach Serenity: the secure connection failed (certificate problem)"
    if isinstance(exc, requests.exceptions.Timeout):
        return "Can't reach Serenity: the connection timed out"
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "Can't reach Serenity: no connection (check this computer's internet access)"
    return f"Can't reach Serenity: {exc.__class__.__name__}"


@dataclass
class Outcome:
    outcome: str
    detail: str = ""


class MultipartStream(io.RawIOBase):
    """multipart/related body read straight from the files, with a known
    length so it is sent with Content-Length (no chunked encoding)."""

    def __init__(self, paths: list[str], boundary: str):
        self._pieces = []
        for path in paths:
            self._pieces.append(("bytes", f"--{boundary}\r\nContent-Type: application/dicom\r\n\r\n".encode()))
            self._pieces.append(("file", path))
            self._pieces.append(("bytes", b"\r\n"))
        self._pieces.append(("bytes", f"--{boundary}--\r\n".encode()))
        self._length = sum(len(p) if kind == "bytes" else os.path.getsize(p) for kind, p in self._pieces)
        self._index = 0
        self._current = None
        self._position = 0

    def __len__(self) -> int:
        return self._length

    def tell(self) -> int:
        # requests sizes the body as len() - tell(); must be 0 before sending
        return self._position

    def readable(self) -> bool:
        return True

    def _next(self):
        if self._current is not None:
            self._current.close()
            self._current = None
        if self._index >= len(self._pieces):
            return False
        kind, value = self._pieces[self._index]
        self._index += 1
        self._current = io.BytesIO(value) if kind == "bytes" else open(value, "rb")  # noqa: SIM115 - closed in _next()/close()
        return True

    def read(self, size: int = -1) -> bytes:
        if self._current is None and not self._next():
            return b""
        out = bytearray()
        while size < 0 or len(out) < size:
            chunk = self._current.read(-1 if size < 0 else size - len(out))
            if chunk:
                out += chunk
                continue
            if not self._next():
                break
        self._position += len(out)
        return bytes(out)

    def close(self) -> None:
        if self._current is not None:
            self._current.close()
        super().close()


class SerenityDestination:
    id = SERENITY
    name = "Serenity"

    def __init__(self, config):
        self.config = config
        self.session = requests.Session()

    def _headers(self) -> dict:
        return {
            "X-Device-Key": self.config.get("device_key"),
            "User-Agent": f"LabSync/{__version__} (imaging)",
            "Accept": "application/json",
        }

    def _verify(self):
        return self.config.get("ca_bundle") or True

    @property
    def configured(self) -> bool:
        return bool(self.config.get("serenity_url") and self.config.get("device_key"))

    def heartbeat(self, report: dict) -> dict:
        url = self.config.get("serenity_url").rstrip("/") + "/device-gateway/heartbeat"
        try:
            r = self.session.post(url, json={"version": __version__, "report": report}, headers=self._headers(),
                                  timeout=30, verify=self._verify())
        except requests.RequestException as exc:
            raise Unreachable(describe_network_error(exc)) from exc
        if r.status_code == 401:
            raise PermissionError("Serenity did not accept the device key. Issue a new key under Devices in Serenity.")
        if r.status_code >= 400:
            raise Unreachable(f"Serenity answered {r.status_code}: {r.text[:200]}")
        return r.json()

    def send(self, rows: list) -> list[Outcome]:
        if not self.configured:
            raise Unreachable("Serenity is not set up yet (enter the setup code)")
        url = self.config.get("serenity_url").rstrip("/") + "/device-gateway/dicom/instances"
        boundary = "srn" + uuid.uuid4().hex
        body = MultipartStream([r["path"] for r in rows], boundary)
        headers = {
            **self._headers(),
            "Content-Type": f'multipart/related; type="application/dicom"; boundary={boundary}',
        }
        sources = {r["calling_ae"] for r in rows if r["calling_ae"]}
        if len(sources) == 1:
            headers["X-Source-AE-Title"] = sources.pop()
        try:
            r = self.session.post(url, data=body, headers=headers, verify=self._verify(),
                                  timeout=(30, int(self.config.get("request_timeout_seconds") or 300)))
        except requests.RequestException as exc:
            raise Unreachable(describe_network_error(exc)) from exc
        finally:
            body.close()
        if r.status_code == 401:
            raise Unreachable("Serenity did not accept the device key. Issue a new key under Devices in Serenity.")
        if r.status_code == 413:
            # Too big for one request: send them one at a time next round
            if len(rows) > 1:
                return [Outcome(RETRY, "Too large for one request; sending separately")] * len(rows)
            return [Outcome(REJECT, "Serenity refused this file as too large (413). Ask the Serenity team to raise the upload limit.")]
        if r.status_code in (200, 202, 409):
            try:
                results = r.json()["results"]
            except Exception:
                raise Unreachable(f"Unexpected answer from Serenity ({r.status_code})") from None
            if len(results) != len(rows):
                raise Unreachable("Serenity's answer did not match what was sent")
            return [Outcome(x.get("outcome", RETRY), x.get("detail") or x.get("status") or "") for x in results]
        if r.status_code >= 500 or r.status_code in (408, 429):
            raise Unreachable(f"Serenity is busy or unavailable ({r.status_code})")
        return [Outcome(RETRY, f"Serenity answered {r.status_code}: {r.text[:200]}")] * len(rows)


class DicomDestination:
    """C-STORE SCU to another node. Uses our AE title as the calling AE, so
    add LabSync as a node on the other side."""

    def __init__(self, config, spec: dict):
        self.config = config
        self.spec = spec
        self.id = f"dicom:{spec['id']}"
        self.name = spec.get("name") or spec.get("ae_title")

    @property
    def configured(self) -> bool:
        return bool(self.spec.get("enabled", True) and self.spec.get("host") and self.spec.get("port"))

    def echo(self) -> str | None:
        from pynetdicom import AE
        from pynetdicom.sop_class import Verification

        ae = AE(ae_title=self.config.get("ae_title"))
        ae.add_requested_context(Verification)
        assoc = ae.associate(self.spec["host"], int(self.spec["port"]), ae_title=self.spec["ae_title"])
        if not assoc.is_established:
            return "Could not connect (association rejected or no answer)"
        status = assoc.send_c_echo()
        assoc.release()
        return None if status and status.Status == 0 else "Echo failed"

    def send(self, rows: list) -> list[Outcome]:
        import pydicom
        from pynetdicom import AE

        datasets = []
        for row in rows:
            try:
                datasets.append(pydicom.dcmread(row["path"]))
            except Exception as exc:
                datasets.append(exc)
        ae = AE(ae_title=self.config.get("ae_title"))
        ae.network_timeout = 60
        ae.dimse_timeout = 300
        contexts = set()
        for ds in datasets:
            if not isinstance(ds, Exception):
                contexts.add((str(ds.SOPClassUID), str(ds.file_meta.TransferSyntaxUID)))
        for sop_class, syntax in list(contexts)[:120]:
            ae.add_requested_context(sop_class, [syntax])
        assoc = ae.associate(self.spec["host"], int(self.spec["port"]), ae_title=self.spec["ae_title"])
        if not assoc.is_established:
            raise Unreachable(f"Could not connect to {self.name} at {self.spec['host']}:{self.spec['port']}")
        outcomes = []
        try:
            for ds in datasets:
                if isinstance(ds, Exception):
                    outcomes.append(Outcome(REJECT, f"Unreadable file: {ds}"))
                    continue
                try:
                    status = assoc.send_c_store(ds)
                except Exception as exc:
                    outcomes.append(Outcome(RETRY, str(exc)))
                    continue
                code = getattr(status, "Status", None) if status else None
                if code is None:
                    outcomes.append(Outcome(RETRY, "No answer"))
                elif code == 0 or code in (0xB000, 0xB007, 0xB006):  # success / warnings
                    outcomes.append(Outcome(STORED))
                elif 0xA700 <= code <= 0xA7FF:
                    outcomes.append(Outcome(RETRY, f"{self.name} is out of resources (0x{code:04X})"))
                else:
                    outcomes.append(Outcome(RETRY, f"{self.name} refused it (0x{code:04X})"))
        finally:
            assoc.release()
        return outcomes
