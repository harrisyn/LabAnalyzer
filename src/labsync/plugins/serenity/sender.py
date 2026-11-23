"""Lab results to Serenity's device gateway (POST {url}/device-gateway/lab-results)."""

from __future__ import annotations

from typing import Any

from ... import __version__
from ...models import Report
from ...outbound.senders import DeliveryError, HttpSender
from .link import NAME, is_configured


class SerenitySender(HttpSender):
    """Authenticated with this computer's device key from the plugin settings.

    The body is the LabSync 1.x shape the gateway reads; ``Idempotency-Key``
    (the report id) lets it drop repeats. A refused key keeps results queued
    instead of parking them: they go once a new setup code is entered.
    """

    def __init__(self, dest: dict[str, Any], settings: dict[str, Any]):
        base = (settings.get("url") or "").rstrip("/")
        super().__init__({
            **dest,
            "url": f"{base}/device-gateway/lab-results" if base else "",
            "method": "POST",
            "payload_format": "legacy",
            "verify_tls": True,
            "ca_bundle": settings.get("ca_bundle", ""),
            "headers": {},
            "auth": {"method": "api_key", "header": "X-Device-Key", "api_key": settings.get("device_key", "")},
        })
        self._ready = bool(settings.get("enabled", True) and is_configured(settings))

    async def send(self, report: Report, ctx: dict[str, Any]) -> tuple[int | None, str]:
        if not self._ready:
            raise DeliveryError(f"connection error: {NAME} is not paired yet (enter the setup code)")
        try:
            return await super().send(report, ctx)
        except DeliveryError as exc:
            if exc.status in (401, 403):
                raise DeliveryError(f"{NAME} did not accept the device key; results are kept until a new "
                                    "setup code is entered", retryable=True, status=exc.status) from exc
            raise

    async def test(self) -> str:
        if not self._ready:
            raise DeliveryError(f"{NAME} is not paired yet (Settings > Integrations, setup code)")
        session = await self._get_session()
        headers = await self._headers(session)
        url = self.dest["url"].rsplit("/lab-results", 1)[0] + "/heartbeat"
        try:
            async with session.post(url, json={"version": __version__, "report": {"test": True}}, headers=headers,
                                    ssl=self._ssl) as resp:
                if resp.status == 401:
                    raise DeliveryError(f"{NAME} did not accept the device key")
                if resp.status >= 400:
                    raise DeliveryError(f"{NAME} answered HTTP {resp.status}")
                data = await resp.json()
                return f"connected to {(data.get('organization') or {}).get('name', NAME)}"
        except DeliveryError:
            raise
        except Exception as exc:
            raise DeliveryError(f"{exc.__class__.__name__}: {exc}") from exc
