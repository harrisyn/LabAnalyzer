"""The DICOM side: a Storage SCP that modalities send to on the local network.

- Answers C-ECHO ("test connection") and C-STORE for all standard storage
  SOP classes in any transfer syntax.
- Refuses associations whose called AE title isn't ours, and (unless
  "accept unknown nodes" is on) callers that are neither in the local nodes
  list nor sent down by an integration plugin's platform, or that
  connect from an address other than the one registered.
- Writes each instance to disk (temp file, fsync, rename) and records it in
  the queue before answering Success, so a stored image is never lost even
  if the power fails right after. Low disk space is answered with "Out of
  resources", which modalities retry later.
"""

import ipaddress
import logging
import os
import re
import shutil
import threading
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from pynetdicom import AE, ALL_TRANSFER_SYNTAXES, AllStoragePresentationContexts, evt
from pynetdicom import _config as pynetdicom_config
from pynetdicom.sop_class import Verification
from pynetdicom.transport import ThreadedAssociationServer

from .store import Store, fsync_dir

logger = logging.getLogger(__name__)

STATUS_SUCCESS = 0x0000
STATUS_OUT_OF_RESOURCES = 0xA700
STATUS_CANNOT_UNDERSTAND = 0xC000

# A-ASSOCIATE-RJ reasons (PS3.8 9.3.4): rejected-permanent, service-user
REJECT_CALLING_AE = 0x03
REJECT_CALLED_AE = 0x07

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _tag(ds, name: str) -> str:
    try:
        return str(getattr(ds, name, "") or "").strip()
    except Exception:
        return ""


def ip_matches(ip: str, allowed: str) -> bool:
    allowed = (allowed or "").strip()
    if not allowed:
        return True
    try:
        return ipaddress.ip_address(ip) in ipaddress.ip_network(allowed, strict=False)
    except ValueError:
        return False


class Receiver:
    def __init__(self, config, store: Store, images_dir: Path, destinations: Callable[[], list[str]],
                 on_received: Callable[[], None] | None = None):
        self.config = config
        self.store = store
        self.images_dir = Path(images_dir)
        self.images_dir.mkdir(parents=True, exist_ok=True)
        self.destinations = destinations
        self.on_received = on_received
        self._server = None
        self._lock = threading.Lock()
        self.error: str | None = None
        self.listening_on: tuple | None = None
        self.last_received_at: float | None = None
        self.last_refused: str | None = None

    # ── who may send ──────────────────────────────────────────────────────

    def allowed_nodes(self) -> list[dict]:
        nodes = [dict(n, source="local") for n in self.config.get("local_nodes") or []]
        for source, remote in (self.config.get("remote_nodes") or {}).items():
            nodes += [dict(n, source=source) for n in remote or []]
        return nodes

    def is_allowed(self, calling_ae: str, ip: str) -> tuple[bool, str]:
        if self.config.get("accept_unknown_nodes"):
            return True, ""
        calling_ae = (calling_ae or "").strip().upper()
        matches = [n for n in self.allowed_nodes() if str(n.get("ae_title") or "").strip().upper() == calling_ae]
        if not matches:
            return False, f"AE title {calling_ae or '(blank)'} is not an allowed device"
        for node in matches:
            ips = node.get("allowed_ips") if node.get("source") != "local" else [node.get("ip") or ""]
            ips = [i for i in (ips or []) if str(i).strip()] or [""]
            if any(ip_matches(ip, a) for a in ips):
                return True, ""
        return False, f"AE title {calling_ae} is allowed, but not from address {ip}"

    def _on_request(self, event) -> None:
        """Refuse unknown callers at association time, as PACS do, so the
        modality shows 'association rejected' rather than failed images."""
        requestor = event.assoc.requestor
        primitive = requestor.primitive  # the A-ASSOCIATE-RQ, before negotiation
        calling = str(primitive.calling_ae_title or "").strip()
        called = str(primitive.called_ae_title or "").strip()
        ip = str(requestor.address or "")
        our_ae = self.config.get("ae_title").strip().upper()
        reason = None
        if called.upper() != our_ae:
            reason = f"called AE title {called} is not ours ({our_ae})"
            code = REJECT_CALLED_AE
        else:
            ok, why = self.is_allowed(calling, ip)
            if not ok:
                reason, code = why, REJECT_CALLING_AE
        if reason:
            self.last_refused = f"{time.strftime('%H:%M:%S')} {calling}@{ip}: {reason}"
            logger.warning("refused association from %s@%s: %s", calling, ip, reason)
            self.store.log_event("warning", f"Refused {calling} at {ip}: {reason}")
            # As pynetdicom does for its own rejections: send the A-ASSOCIATE-RJ,
            # then stop the association once the PDU has gone out.
            event.assoc.acse.send_reject(0x01, 0x01, code)
            event.assoc.kill()

    # ── storing ───────────────────────────────────────────────────────────

    def _free_mb(self) -> float:
        return shutil.disk_usage(self.images_dir).free / (1024 * 1024)

    def _on_store(self, event) -> int:
        try:
            if self._free_mb() < float(self.config.get("min_free_disk_mb") or 0):
                self.store.log_event("error", "Disk almost full: refusing images until space is freed")
                logger.error("disk almost full, refusing C-STORE")
                return STATUS_OUT_OF_RESOURCES
            ds = event.dataset
            ds.file_meta = event.file_meta
            sop_uid = _tag(ds, "SOPInstanceUID")
            if not sop_uid:
                return STATUS_CANNOT_UNDERSTAND
            study_uid = _tag(ds, "StudyInstanceUID") or "unknown-study"
            day = time.strftime("%Y%m%d")
            folder = self.images_dir / day / _SAFE.sub("_", study_uid)[:64]
            folder.mkdir(parents=True, exist_ok=True)
            final = folder / f"{_SAFE.sub('_', sop_uid)[:96]}.dcm"
            if final.exists():
                final = folder / f"{_SAFE.sub('_', sop_uid)[:80]}-{uuid.uuid4().hex[:8]}.dcm"
            tmp = folder / f".{uuid.uuid4().hex}.part"
            # The exact bytes the modality sent (file meta + dataset): never re-encoded
            raw = event.encoded_dataset(include_meta=True)
            with open(tmp, "wb") as fh:
                fh.write(raw)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, final)
            fsync_dir(folder)

            requestor = event.assoc.requestor
            meta = {
                "sop_instance_uid": sop_uid,
                "sop_class_uid": _tag(ds, "SOPClassUID"),
                "study_instance_uid": study_uid,
                "series_instance_uid": _tag(ds, "SeriesInstanceUID"),
                "accession_number": _tag(ds, "AccessionNumber"),
                "patient_id": _tag(ds, "PatientID"),
                "patient_name": _tag(ds, "PatientName").replace("^", " ").strip(),
                "study_description": _tag(ds, "StudyDescription"),
                "modality": _tag(ds, "Modality"),
                "calling_ae": str(requestor.ae_title or "").strip(),
                "peer_ip": str(requestor.address or ""),
                "path": str(final),
                "size": len(raw),
            }
            _, superseded_path = self.store.add_instance(meta, self.destinations())
            if superseded_path:
                try:
                    os.remove(superseded_path)
                except OSError:
                    pass
            self.last_received_at = time.time()
            if self.on_received:
                self.on_received()
            return STATUS_SUCCESS
        except Exception:
            logger.exception("C-STORE failed")
            return STATUS_OUT_OF_RESOURCES

    def _on_echo(self, event) -> int:
        logger.info("C-ECHO from %s@%s", str(event.assoc.requestor.ae_title).strip(), event.assoc.requestor.address)
        return STATUS_SUCCESS

    # ── lifecycle ─────────────────────────────────────────────────────────

    def start(self) -> None:
        with self._lock:
            self._stop_locked()
            pynetdicom_config.STORE_RECV_CHUNKED_DATASET = False
            ae = AE(ae_title=self.config.get("ae_title"))
            ae.maximum_pdu_size = 0  # unlimited
            ae.network_timeout = 120
            ae.acse_timeout = 60
            ae.dimse_timeout = 300
            ae.maximum_associations = 20
            # Our AE title is checked in _on_request with a proper reject code
            ae.require_called_aet = False
            for context in AllStoragePresentationContexts:
                ae.add_supported_context(context.abstract_syntax, ALL_TRANSFER_SYNTAXES)
            ae.add_supported_context(Verification)
            address = (self.config.get("bind_address") or "0.0.0.0", int(self.config.get("port")))
            try:
                self._server = ae.make_server(
                    address,
                    evt_handlers=[
                        (evt.EVT_REQUESTED, self._on_request),
                        (evt.EVT_C_STORE, self._on_store),
                        (evt.EVT_C_ECHO, self._on_echo),
                    ],
                    server_class=ExclusiveAssociationServer,
                )
                threading.Thread(target=self._server.serve_forever, name="dicom-acceptor", daemon=True).start()
                self.listening_on = address
                self.error = None
                logger.info("listening as %s on %s:%s", self.config.get("ae_title"), *address)
                self.store.log_event("info", f"Listening as {self.config.get('ae_title')} on port {address[1]}")
            except OSError as exc:
                self._server = None
                self.listening_on = None
                self.error = f"Could not listen on port {address[1]}: {exc}. Is another program (for example the PostDICOM communicator) using it?"
                logger.error(self.error)
                self.store.log_event("error", self.error)

    def _stop_locked(self) -> None:
        if self._server is not None:
            try:
                self._server.shutdown()
            except Exception:
                pass
            self._server = None
            self.listening_on = None

    def stop(self) -> None:
        with self._lock:
            self._stop_locked()

    def reconcile(self) -> int:
        """Re-queue files left on disk but missing from the queue (a crash
        between writing the file and recording it) and remove partial files."""
        import pydicom

        known = self.store.known_paths()
        added = 0
        for path in self.images_dir.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix == ".part":
                try:
                    path.unlink()
                except OSError:
                    pass
                continue
            if path.suffix != ".dcm" or str(path) in known:
                continue
            try:
                ds = pydicom.dcmread(str(path), stop_before_pixels=True)
            except Exception:
                logger.warning("unreadable file left on disk: %s", path)
                continue
            meta = {
                "sop_instance_uid": _tag(ds, "SOPInstanceUID"),
                "sop_class_uid": _tag(ds, "SOPClassUID"),
                "study_instance_uid": _tag(ds, "StudyInstanceUID"),
                "series_instance_uid": _tag(ds, "SeriesInstanceUID"),
                "accession_number": _tag(ds, "AccessionNumber"),
                "patient_id": _tag(ds, "PatientID"),
                "patient_name": _tag(ds, "PatientName").replace("^", " ").strip(),
                "study_description": _tag(ds, "StudyDescription"),
                "modality": _tag(ds, "Modality"),
                "calling_ae": "",
                "peer_ip": "",
                "path": str(path),
                "size": path.stat().st_size,
                "received_at": path.stat().st_mtime,
            }
            if not meta["sop_instance_uid"]:
                continue
            self.store.add_instance(meta, self.destinations())
            added += 1
        if added:
            self.store.log_event("warning", f"Recovered {added} image(s) found on disk after a restart")
        return added


class ExclusiveAssociationServer(ThreadedAssociationServer):
    """pynetdicom binds with SO_REUSEADDR, which on Windows lets a second
    program bind a port that is already listening (silently taking images
    meant for, say, the PostDICOM communicator), or lets another program join
    ours later. Bind exclusively instead, so a taken port is an error and
    nobody can share ours while we listen."""

    def server_bind(self) -> None:
        import socket
        import sys

        if sys.platform == "win32":
            self.socket.setsockopt(socket.SOL_SOCKET, getattr(socket, "SO_EXCLUSIVEADDRUSE", -5), 1)
        else:
            # Linux and macOS refuse a port that is listening even with
            # SO_REUSEADDR; it only avoids false alarms from TIME_WAIT.
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        if self.ae.network_timeout is not None:
            self.socket.settimeout(self.ae.network_timeout)
        self.socket.bind(self.server_address)
        self.server_address = self.socket.getsockname()
