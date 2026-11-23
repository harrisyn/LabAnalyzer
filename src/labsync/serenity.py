"""The link to Serenity: setup code, device key and the heartbeat.

One LabSync install is one device in Serenity's Devices screen (kind
"Serenity communicator"). Its key authenticates everything it sends:

  POST {url}/device-gateway/heartbeat        status out; allowed imaging devices and settings back
  POST {url}/device-gateway/dicom/instances  received images (imaging module)
  POST {url}/device-gateway/lab-results      analyzer results ("serenity" destination)

``url`` is Serenity's API address including the /v2 prefix, for example
https://api.serenity.health/v2. The setup code shown once in Serenity holds
both: ``SRN1.<base64url JSON {"url", "key", "device", "device_id", "organization"}>``.

The heartbeat runs whether or not Serenity is reachable; nothing else waits on
it. The last answer (allowed imaging devices) is kept on disk, so LabSync
starts and works with no internet connection.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from typing import Any

import requests

from . import __version__

log = logging.getLogger("labsync.serenity")

HEARTBEAT_SECONDS = 60


def check_serenity_url(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    if not url.startswith("https://") and not (url.startswith("http://") and os.environ.get("LABSYNC_ALLOW_HTTP")):
        raise ValueError("Serenity's address must start with https://")
    if len(url) > 300 or " " in url:
        raise ValueError("That doesn't look like a web address")
    return url


def decode_setup_code(code: str) -> dict[str, Any]:
    """The setup code from Serenity's Devices screen: SRN1.<base64url JSON>."""
    code = (code or "").strip()
    if not code.startswith("SRN1."):
        raise ValueError("That is not a Serenity setup code (it should start with SRN1.)")
    raw = code[5:]
    try:
        payload = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    except Exception:
        raise ValueError("The setup code is damaged. Copy it again from Serenity.") from None
    if not isinstance(payload, dict) or not payload.get("url") or not str(payload.get("key", "")).startswith("sdk_"):
        raise ValueError("The setup code is missing the Serenity address or key")
    check_serenity_url(str(payload["url"]))
    return payload


def apply_setup_code(cfg: dict[str, Any], code: str) -> dict[str, Any]:
    """Return a copy of the configuration connected to Serenity with this setup code."""
    payload = decode_setup_code(code)
    serenity = dict(cfg.get("serenity") or {})
    serenity.update({
        "enabled": True,
        "url": str(payload["url"]).rstrip("/"),
        "device_key": payload["key"],
        "device_id": str(payload.get("device_id") or ""),
        "device_name": str(payload.get("device") or ""),
        "organization": str(payload.get("organization") or ""),
    })
    return {**cfg, "serenity": serenity}


def is_configured(serenity: dict[str, Any] | None) -> bool:
    s = serenity or {}
    return bool(s.get("enabled", True) and s.get("url") and s.get("device_key"))


class SerenityLink:
    """Heartbeat client. Blocking (requests); the engine calls it from a worker thread."""

    def __init__(self, settings: dict[str, Any]):
        self.settings = settings
        self.session = requests.Session()
        self.state: dict[str, Any] = {"ok": None, "at": None, "error": "", "organization": "", "device": ""}

    @property
    def configured(self) -> bool:
        return is_configured(self.settings)

    def _verify(self) -> Any:
        return self.settings.get("ca_bundle") or True

    def heartbeat(self, report: dict[str, Any]) -> dict[str, Any] | None:
        """Send status; return Serenity's answer, or None when not reachable/set up."""
        if not self.configured:
            self.state.update(ok=None, error="Not connected to Serenity yet (enter the setup code)")
            return None
        url = self.settings["url"].rstrip("/") + "/device-gateway/heartbeat"
        headers = {"X-Device-Key": self.settings["device_key"], "User-Agent": f"LabSync/{__version__}",
                   "Accept": "application/json"}
        try:
            r = self.session.post(url, json={"version": __version__, "report": report}, headers=headers,
                                  timeout=30, verify=self._verify())
        except requests.RequestException as exc:
            log.info("heartbeat failed: %r", exc)
            self.state.update(ok=False, at=time.time(), error=_network_words(exc))
            return None
        if r.status_code == 401:
            self.state.update(ok=False, at=time.time(),
                              error="Serenity did not accept the device key. Issue a new key under Devices in Serenity.")
            return None
        if r.status_code >= 400:
            self.state.update(ok=False, at=time.time(), error=f"Serenity answered {r.status_code}: {r.text[:200]}")
            return None
        try:
            answer = r.json()
        except ValueError:
            self.state.update(ok=False, at=time.time(), error="Unexpected answer from Serenity")
            return None
        self.state.update(ok=True, at=time.time(), error="",
                          organization=(answer.get("organization") or {}).get("name", ""),
                          device=(answer.get("device") or {}).get("name", ""))
        return answer

    def close(self) -> None:
        self.session.close()


def _network_words(exc: Exception) -> str:
    if isinstance(exc, requests.exceptions.SSLError):
        return "Can't reach Serenity: the secure connection failed (certificate problem)"
    if isinstance(exc, requests.exceptions.Timeout):
        return "Can't reach Serenity: the connection timed out"
    if isinstance(exc, requests.exceptions.ConnectionError):
        return "Can't reach Serenity: no connection (check this computer's internet access)"
    return f"Can't reach Serenity: {exc.__class__.__name__}"


def allowed_modalities(answer: dict[str, Any]) -> list[dict[str, Any]] | None:
    """Imaging devices registered in Serenity to send through this LabSync."""
    nodes = answer.get("modalities")
    if not isinstance(nodes, list):
        return None
    return [
        {"name": n.get("name") or "", "ae_title": (n.get("ae_title") or "").strip().upper(),
         "allowed_ips": n.get("allowed_ips") or [], "modality": n.get("modality") or ""}
        for n in nodes if isinstance(n, dict) and n.get("ae_title")
    ]
