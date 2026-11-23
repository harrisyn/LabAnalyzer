"""Images to Serenity's device gateway (POST {url}/device-gateway/dicom/instances).

STOW-RS style multipart/related, streamed from disk, with an answer per
instance so "no matching order yet" can be held and tried again later.
"""

from __future__ import annotations

import uuid
from typing import Any

import requests

from ...imaging.destinations import HOLD, REJECT, RETRY, MultipartStream, Outcome, Unreachable
from .link import NAME, headers, is_configured, network_words


class SerenityDestination:
    def __init__(self, spec: dict[str, Any], settings: dict[str, Any], imaging_config):
        self.spec = spec
        self.settings = settings
        self.config = imaging_config
        self.id = spec.get("id") or "serenity"
        self.name = spec.get("name") or NAME
        self.session = requests.Session()

    @property
    def configured(self) -> bool:
        return bool(self.spec.get("enabled", True) and is_configured(self.settings))

    def send(self, rows: list) -> list[Outcome]:
        if not is_configured(self.settings):
            raise Unreachable(f"{NAME} is not paired yet (enter the setup code)")
        url = self.settings["url"].rstrip("/") + "/device-gateway/dicom/instances"
        boundary = "lsy" + uuid.uuid4().hex
        body = MultipartStream([r["path"] for r in rows], boundary)
        hdrs = {**headers(self.settings, "imaging"),
                "Content-Type": f'multipart/related; type="application/dicom"; boundary={boundary}'}
        sources = {r["calling_ae"] for r in rows if r["calling_ae"]}
        if len(sources) == 1:
            hdrs["X-Source-AE-Title"] = sources.pop()
        try:
            r = self.session.post(url, data=body, headers=hdrs, verify=self.settings.get("ca_bundle") or True,
                                  timeout=(30, int(self.config.get("request_timeout_seconds") or 300)))
        except requests.RequestException as exc:
            raise Unreachable(network_words(exc)) from exc
        finally:
            body.close()
        if r.status_code == 401:
            raise Unreachable(f"{NAME} did not accept the device key. Issue a new key under Devices in {NAME}.")
        if r.status_code == 413:
            # Too big for one request: send them one at a time next round
            if len(rows) > 1:
                return [Outcome(RETRY, "Too large for one request; sending separately")] * len(rows)
            return [Outcome(REJECT, f"{NAME} refused this file as too large (413). Ask for a higher upload limit.")]
        if r.status_code in (200, 202, 409):
            try:
                results = r.json()["results"]
            except Exception:
                raise Unreachable(f"Unexpected answer from {NAME} ({r.status_code})") from None
            if len(results) != len(rows):
                raise Unreachable(f"{NAME}'s answer did not match what was sent")
            return [Outcome(x.get("outcome", RETRY), x.get("detail") or x.get("status") or "") for x in results]
        if r.status_code >= 500 or r.status_code in (408, 429):
            raise Unreachable(f"{NAME} is busy or unavailable ({r.status_code})")
        return [Outcome(RETRY, f"{NAME} answered {r.status_code}: {r.text[:200]}")] * len(rows)


__all__ = ["HOLD", "SerenityDestination"]
