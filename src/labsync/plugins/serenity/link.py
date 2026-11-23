"""Pairing code, device key and the status heartbeat for Serenity.

One LabSync install is one device in Serenity's Devices screen. Its key
authenticates everything it sends:

  POST {url}/device-gateway/heartbeat        status out; allowed imaging devices back
  POST {url}/device-gateway/dicom/instances  received images (imaging destination)
  POST {url}/device-gateway/lab-results      analyzer results (lab destination)

``url`` is the platform's API address including its version prefix. The
setup code shown once in Serenity holds both:
``SRN1.<base64url JSON {"url", "key", "device", "device_id", "organization"}>``.

The heartbeat runs whether or not the platform is reachable; nothing else
waits on it. The last list of allowed imaging devices is kept on disk by the
imaging module, so LabSync starts and works with no internet connection.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import time
from typing import Any

import requests

from ... import __version__
from .. import Link

log = logging.getLogger("labsync.plugins.serenity")

HEARTBEAT_SECONDS = 60
NAME = "Serenity"


def check_url(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    if not url.startswith("https://") and not (url.startswith("http://") and os.environ.get("LABSYNC_ALLOW_HTTP")):
        raise ValueError(f"{NAME}'s address must start with https://")
    if len(url) > 300 or " " in url:
        raise ValueError("That doesn't look like a web address")
    return url


def decode_setup_code(code: str) -> dict[str, Any]:
    """The setup code from Serenity's Devices screen: SRN1.<base64url JSON>."""
    code = (code or "").strip()
    if not code.startswith("SRN1."):
        raise ValueError(f"That is not a {NAME} setup code (it should start with SRN1.)")
    raw = code[5:]
    try:
        payload = json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
    except Exception:
        raise ValueError(f"The setup code is damaged. Copy it again from {NAME}.") from None
    if not isinstance(payload, dict) or not payload.get("url") or not str(payload.get("key", "")).startswith("sdk_"):
        raise ValueError("The setup code is missing the address or the device key")
    check_url(str(payload["url"]))
    return payload


def apply_setup_code(settings: dict[str, Any], code: str) -> dict[str, Any]:
    """Return a copy of the plugin settings paired with this setup code."""
    payload = decode_setup_code(code)
    return {
        **settings,
        "enabled": True,
        "url": str(payload["url"]).rstrip("/"),
        "device_key": payload["key"],
        "device_id": str(payload.get("device_id") or ""),
        "device_name": str(payload.get("device") or ""),
        "organization": str(payload.get("organization") or ""),
    }


def is_configured(settings: dict[str, Any] | None) -> bool:
    s = settings or {}
    return bool(s.get("url") and s.get("device_key"))


def network_words(exc: Exception) -> str:
    """Plain words for the status bar; the full error goes to the log."""
    log.info("network error: %r", exc)
    if isinstance(exc, requests.exceptions.SSLError):
        return f"Can't reach {NAME}: the secure connection failed (certificate problem)"
    if isinstance(exc, requests.exceptions.Timeout):
        return f"Can't reach {NAME}: the connection timed out"
    if isinstance(exc, requests.exceptions.ConnectionError):
        return f"Can't reach {NAME}: no connection (check this computer's internet access)"
    return f"Can't reach {NAME}: {exc.__class__.__name__}"


def headers(settings: dict[str, Any], what: str = "") -> dict[str, str]:
    return {"X-Device-Key": settings.get("device_key") or "",
            "User-Agent": f"LabSync/{__version__}" + (f" ({what})" if what else ""),
            "Accept": "application/json"}


class SerenityLink(Link):
    """Heartbeat client. Blocking (requests); the engine calls it from a worker thread."""

    def __init__(self, settings: dict[str, Any]):
        super().__init__(settings)
        self.session = requests.Session()
        self.interval_seconds = int(settings.get("heartbeat_seconds") or HEARTBEAT_SECONDS)

    def _fail(self, text: str) -> None:
        self.state.ok, self.state.at, self.state.text = False, time.time(), text

    def check(self, report: dict[str, Any]) -> dict[str, Any] | None:
        """Send status; return the answer, or None when not reachable/set up."""
        if not is_configured(self.settings):
            self.state.ok, self.state.text = None, "not paired yet (Settings > Integrations, setup code)"
            return None
        url = self.settings["url"].rstrip("/") + "/device-gateway/heartbeat"
        try:
            r = self.session.post(url, json={"version": __version__, "report": report}, headers=headers(self.settings),
                                  timeout=30, verify=self.settings.get("ca_bundle") or True)
        except requests.RequestException as exc:
            self._fail(network_words(exc))
            return None
        if r.status_code == 401:
            self._fail(f"{NAME} did not accept the device key. Issue a new key under Devices in {NAME}.")
            return None
        if r.status_code >= 400:
            self._fail(f"{NAME} answered {r.status_code}: {r.text[:200]}")
            return None
        try:
            answer = r.json()
        except ValueError:
            self._fail(f"Unexpected answer from {NAME}")
            return None
        org = (answer.get("organization") or {}).get("name", "") or self.settings.get("organization", "")
        device = (answer.get("device") or {}).get("name", "")
        self.state.ok, self.state.at = True, time.time()
        self.state.text = f"connected ({org})" if org else "connected"
        self.state.details = {"organization": org, "device": device}
        return answer

    def remote_nodes(self, answer: dict[str, Any]) -> list[dict[str, Any]] | None:
        return allowed_modalities(answer)

    def close(self) -> None:
        self.session.close()


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
