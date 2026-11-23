"""Where received images go.

DicomDestination     C-STORE to a DICOM node on the network (a PACS, a cloud
                     PACS communicator such as PostDICOM's, an Orthanc server).
DicomWebDestination  STOW-RS over HTTPS to any DICOMweb server, streamed
                     from disk as multipart/related.
Plugins can add more (see ``labsync.plugins``).

Every destination has ``id``, ``name``, ``configured`` and ``send(rows)``.
send() returns one outcome per instance:
  stored  delivered (or already there)
  hold    the destination is not ready for it yet (e.g. no matching order): try again later
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


class Unreachable(Exception):
    pass


def describe_network_error(exc: Exception, name: str) -> str:
    """Plain words for the status page; the full error goes to the log."""
    logger.info("network error: %r", exc)
    if isinstance(exc, requests.exceptions.SSLError):
        return f"Can't reach {name}: the secure connection failed (certificate problem)"
    if isinstance(exc, requests.exceptions.Timeout):
        return f"Can't reach {name}: the connection timed out"
    if isinstance(exc, requests.exceptions.ConnectionError):
        return f"Can't reach {name}: no connection (check this computer's network access)"
    return f"Can't reach {name}: {exc.__class__.__name__}"


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


class DicomDestination:
    """C-STORE SCU to another node. Uses our AE title as the calling AE, so
    add LabSync as a node on the other side."""

    def __init__(self, config, spec: dict):
        self.config = config
        self.spec = spec
        self.id = spec["id"]
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

    def test(self) -> str:
        problem = self.echo()
        if problem:
            raise Unreachable(problem)
        return f"C-ECHO answered by {self.spec['ae_title']} at {self.spec['host']}:{self.spec['port']}"


# DICOM status codes a STOW-RS server can give per failed instance (PS3.18 / PS3.4)
_DUPLICATE = (0x0111,)


def _failure_outcome(code: int | None, name: str) -> Outcome:
    if code is None:
        return Outcome(RETRY, f"{name} did not store it (no reason given)")
    if code in _DUPLICATE:
        return Outcome(STORED, "already there")
    if 0xA700 <= code <= 0xA7FF or code == 0x0110:
        return Outcome(RETRY, f"{name} could not store it right now (0x{code:04X})")
    if code == 0x0122 or 0xA900 <= code <= 0xA9FF or 0xC000 <= code <= 0xCFFF:
        return Outcome(REJECT, f"{name} does not accept this image (0x{code:04X})")
    return Outcome(RETRY, f"{name} refused it (0x{code:04X})")


def _tag_value(item: dict, tag: str):
    try:
        return item[tag]["Value"][0]
    except (KeyError, IndexError, TypeError):
        return None


class DicomWebDestination:
    """STOW-RS (POST {url}/studies) to any DICOMweb server.

    ``spec``: url (the DICOMweb root, e.g. https://pacs.example.org/dicom-web),
    auth {method none|basic|bearer|api_key, ...}, verify_tls, ca_bundle, headers.
    """

    def __init__(self, config, spec: dict):
        self.config = config
        self.spec = spec
        self.id = spec["id"]
        self.name = spec.get("name") or "DICOMweb server"
        self.session = requests.Session()

    @property
    def configured(self) -> bool:
        return bool(self.spec.get("enabled", True) and self.spec.get("url"))

    def _verify(self):
        if not self.spec.get("verify_tls", True):
            return False
        return self.spec.get("ca_bundle") or True

    def _headers(self, accept: str = "application/dicom+json") -> dict:
        h = {"User-Agent": f"LabSync/{__version__} (imaging)", "Accept": accept, **(self.spec.get("headers") or {})}
        auth = self.spec.get("auth") or {}
        method = auth.get("method", "none")
        if method == "bearer" and auth.get("token"):
            h["Authorization"] = f"Bearer {auth['token']}"
        elif method == "api_key" and auth.get("api_key"):
            h[auth.get("header") or "X-API-Key"] = auth["api_key"]
        return h

    def _auth(self):
        auth = self.spec.get("auth") or {}
        if auth.get("method") == "basic":
            return (auth.get("username", ""), auth.get("password", ""))
        return None

    def _root(self) -> str:
        return str(self.spec.get("url", "")).rstrip("/")

    def test(self) -> str:
        try:
            r = self.session.get(self._root() + "/studies", params={"limit": 1}, headers=self._headers(),
                                 auth=self._auth(), timeout=20, verify=self._verify())
        except requests.RequestException as exc:
            raise Unreachable(describe_network_error(exc, self.name)) from exc
        if r.status_code in (401, 403):
            raise Unreachable(f"{self.name} refused the credentials ({r.status_code})")
        if r.status_code >= 400:
            raise Unreachable(f"{self.name} answered {r.status_code}")
        return f"{self.name} answered ({r.status_code})"

    def send(self, rows: list) -> list[Outcome]:
        boundary = "lsy" + uuid.uuid4().hex
        body = MultipartStream([r["path"] for r in rows], boundary)
        headers = {**self._headers(),
                   "Content-Type": f'multipart/related; type="application/dicom"; boundary={boundary}'}
        try:
            r = self.session.post(self._root() + "/studies", data=body, headers=headers, auth=self._auth(),
                                  verify=self._verify(),
                                  timeout=(30, int(self.config.get("request_timeout_seconds") or 300)))
        except requests.RequestException as exc:
            raise Unreachable(describe_network_error(exc, self.name)) from exc
        finally:
            body.close()
        if r.status_code in (401, 403):
            raise Unreachable(f"{self.name} refused the credentials ({r.status_code}). Check the destination's sign-in.")
        if r.status_code == 413:
            if len(rows) > 1:
                return [Outcome(RETRY, "Too large for one request; sending separately")] * len(rows)
            return [Outcome(REJECT, f"{self.name} refused this file as too large (413)")]
        if r.status_code >= 500 or r.status_code in (408, 429):
            raise Unreachable(f"{self.name} is busy or unavailable ({r.status_code})")
        if r.status_code == 200:
            return [Outcome(STORED)] * len(rows)
        if r.status_code in (202, 409):
            failed: dict[str, int | None] = {}
            try:
                answer = r.json()
                if isinstance(answer, list):
                    answer = answer[0] if answer else {}
                for item in (answer.get("00081198") or {}).get("Value") or []:
                    uid = _tag_value(item, "00081155")
                    if uid:
                        failed[str(uid)] = _tag_value(item, "00081197")
            except Exception:
                logger.info("STOW-RS answer from %s was not DICOM JSON", self.name)
                if r.status_code == 409:
                    return [Outcome(RETRY, f"{self.name} did not store them (409)")] * len(rows)
            out = []
            for row in rows:
                uid = str(row["sop_instance_uid"])
                if uid in failed:
                    code = failed[uid]
                    out.append(_failure_outcome(int(code) if code is not None else None, self.name))
                elif r.status_code == 409 and not failed:
                    out.append(Outcome(RETRY, f"{self.name} did not store it (409)"))
                else:
                    out.append(Outcome(STORED))
            return out
        if r.status_code == 415:
            return [Outcome(REJECT, f"{self.name} does not accept this kind of upload (415)")] * len(rows)
        return [Outcome(RETRY, f"{self.name} answered {r.status_code}: {r.text[:200]}")] * len(rows)


def make_destination(spec: dict, imaging_config, plugin_lookup=None):
    """The destination object for one entry of ``imaging.destinations``.

    ``plugin_lookup(type) -> (plugin, settings) | None`` resolves plugin types."""
    dest_type = spec.get("type", "dicom")
    if dest_type == "dicom":
        return DicomDestination(imaging_config, spec)
    if dest_type == "dicomweb":
        return DicomWebDestination(imaging_config, spec)
    owner = plugin_lookup(dest_type) if plugin_lookup else None
    if owner is None:
        return None
    plugin, settings = owner
    return plugin.make_imaging_destination(spec, settings, imaging_config)
