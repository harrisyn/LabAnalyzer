"""Destination senders: HTTP/REST, FHIR R4, HL7 v2 over MLLP, and file export.

A sender raises ``DeliveryError`` for failures; ``retryable`` decides whether
the outbox schedules another attempt or parks the item as failed.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import ssl
import tempfile
import time
from pathlib import Path
from typing import Any

import aiohttp

from .. import __version__
from ..models import Report
from ..protocols.hl7 import message as hl7
from . import formats


class DeliveryError(Exception):
    def __init__(self, message: str, retryable: bool = True, status: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status = status


class Sender:
    def __init__(self, dest: dict[str, Any]):
        self.dest = dest
        self.name = dest.get("name") or dest.get("id")

    async def send(self, report: Report, ctx: dict[str, Any]) -> tuple[int | None, str]:
        raise NotImplementedError

    async def close(self) -> None:
        pass

    async def test(self) -> str:
        """Connectivity check used by the GUI 'Test' button."""
        return "ok"


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


def _ssl_context(dest: dict[str, Any]) -> ssl.SSLContext | bool:
    """Verify TLS against the operating system trust store (hospital CAs work out of the box)."""
    if not dest.get("verify_tls", True):
        return False
    try:
        import truststore

        ctx: ssl.SSLContext = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    except ImportError:  # pragma: no cover - truststore is a declared dependency
        ctx = ssl.create_default_context()
    if dest.get("ca_bundle"):
        ctx.load_verify_locations(dest["ca_bundle"])
    return ctx


def _basic(user: str, password: str) -> str:
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode("ascii")


class _OAuth2:
    def __init__(self, auth: dict[str, Any]):
        self.auth = auth
        self.token = ""
        self.expires = 0.0
        self._lock = asyncio.Lock()

    async def get(self, session: aiohttp.ClientSession, ssl_ctx: Any) -> str:
        async with self._lock:
            if self.token and time.monotonic() < self.expires:
                return self.token
            data = {"grant_type": "client_credentials"}
            if self.auth.get("scope"):
                data["scope"] = self.auth["scope"]
            if self.auth.get("audience"):
                data["audience"] = self.auth["audience"]
            headers = {"Accept": "application/json"}
            if self.auth.get("credentials_in_body"):
                data.update(client_id=self.auth.get("client_id", ""), client_secret=self.auth.get("client_secret", ""))
            else:
                headers["Authorization"] = _basic(self.auth.get("client_id", ""), self.auth.get("client_secret", ""))
            async with session.post(self.auth["token_url"], data=data, ssl=ssl_ctx, headers=headers) as resp:
                body = await resp.text()
                if resp.status != 200:
                    raise DeliveryError(f"OAuth2 token request failed: HTTP {resp.status}: {body[:200]}",
                                        retryable=resp.status >= 500 or resp.status == 429, status=resp.status)
                payload = json.loads(body)
            self.token = payload["access_token"]
            self.expires = time.monotonic() + max(30, int(payload.get("expires_in", 3600)) * 0.9)
            return self.token

    def invalidate(self) -> None:
        self.token = ""


class HttpSender(Sender):
    def __init__(self, dest: dict[str, Any]):
        super().__init__(dest)
        self._session: aiohttp.ClientSession | None = None
        self._ssl = _ssl_context(dest)
        auth = dest.get("auth") or {}
        self._oauth = _OAuth2(auth) if auth.get("method") == "oauth2" else None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=float(self.dest.get("timeout", 30)))
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def _headers(self, session: aiohttp.ClientSession, extra: dict[str, str] | None = None) -> dict[str, str]:
        headers = {"User-Agent": f"LabSync/{__version__}", "Accept": "application/json"}
        headers.update({str(k): str(v) for k, v in (self.dest.get("headers") or {}).items()})
        headers.update(extra or {})
        auth = self.dest.get("auth") or {}
        method = auth.get("method", "none")
        if method == "api_key" and auth.get("api_key"):
            headers[auth.get("header") or "X-API-Key"] = auth["api_key"]
        elif method == "bearer" and auth.get("token"):
            headers["Authorization"] = f"Bearer {auth['token']}"
        elif method == "basic":
            headers["Authorization"] = _basic(auth.get("username", ""), auth.get("password", ""))
        elif method == "oauth2" and self._oauth is not None:
            headers["Authorization"] = f"Bearer {await self._oauth.get(session, self._ssl)}"
        return headers

    def body_for(self, report: Report, ctx: dict[str, Any]) -> tuple[Any, str]:
        fmt = self.dest.get("payload_format", "labsync")
        if fmt == "legacy":
            return formats.legacy_json(report, ctx), "application/json"
        if fmt == "fhir":
            return formats.fhir_bundle(report, ctx), "application/fhir+json"
        return formats.labsync_json(report, ctx, bool(self.dest.get("include_attachments"))), "application/json"

    def url_for(self, report: Report, ctx: dict[str, Any]) -> str:
        return self.dest.get("url", "")

    async def send(self, report: Report, ctx: dict[str, Any]) -> tuple[int | None, str]:
        session = await self._get_session()
        body, ctype = self.body_for(report, ctx)
        url = self.url_for(report, ctx)
        method = str(self.dest.get("method", "POST")).upper()
        for attempt in range(2):
            headers = await self._headers(session, {"Content-Type": ctype, "Idempotency-Key": report.id,
                                                           "X-LabSync-Report-Id": report.id})
            try:
                async with session.request(method, url, data=json.dumps(body, default=str), headers=headers,
                                           ssl=self._ssl) as resp:
                    text = await resp.text()
                    if 200 <= resp.status < 300:
                        return resp.status, text[:500]
                    if resp.status == 401 and self._oauth is not None and attempt == 0:
                        self._oauth.invalidate()
                        continue
                    retryable = resp.status >= 500 or resp.status in (408, 409, 423, 425, 429)
                    raise DeliveryError(f"HTTP {resp.status}: {text[:500]}", retryable=retryable, status=resp.status)
            except aiohttp.ClientSSLError as exc:
                raise DeliveryError(f"TLS error: {exc}", retryable=True) from exc
            except (TimeoutError, aiohttp.ClientError) as exc:
                raise DeliveryError(f"connection error: {exc.__class__.__name__}: {exc}", retryable=True) from exc
        raise DeliveryError("unauthorised after refreshing the OAuth2 token", retryable=False, status=401)

    async def test(self) -> str:
        session = await self._get_session()
        headers = await self._headers(session)
        try:
            async with session.request("OPTIONS", self.dest.get("url", ""), headers=headers, ssl=self._ssl) as resp:
                return f"reachable (HTTP {resp.status})"
        except Exception as exc:
            raise DeliveryError(f"{exc.__class__.__name__}: {exc}") from exc

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()


class FhirSender(HttpSender):
    def body_for(self, report: Report, ctx: dict[str, Any]) -> tuple[Any, str]:
        return formats.fhir_bundle(report, {**ctx, **{k: self.dest.get(k) for k in
                                                       ("identifier_system", "specimen_system", "code_system")
                                                       if self.dest.get(k)}}), "application/fhir+json"

    def url_for(self, report: Report, ctx: dict[str, Any]) -> str:
        return self.dest.get("url", "").rstrip("/")  # transaction bundles post to the server base

    async def test(self) -> str:
        session = await self._get_session()
        headers = await self._headers(session)
        async with session.get(self.dest.get("url", "").rstrip("/") + "/metadata", headers=headers, ssl=self._ssl) as resp:
            if resp.status != 200:
                raise DeliveryError(f"/metadata returned HTTP {resp.status}")
            data = await resp.json(content_type=None)
            return f"FHIR {data.get('fhirVersion', '?')} server: {data.get('software', {}).get('name', 'unknown')}"


# ---------------------------------------------------------------------------
# HL7 MLLP
# ---------------------------------------------------------------------------


class MllpSender(Sender):
    def __init__(self, dest: dict[str, Any]):
        super().__init__(dest)
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._lock = asyncio.Lock()

    async def _connect(self) -> None:
        if self._writer is not None and not self._writer.is_closing():
            return
        timeout = float(self.dest.get("timeout", 30))
        try:
            ssl_ctx = ssl.create_default_context() if self.dest.get("tls") else None
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self.dest["host"], int(self.dest.get("port", 2575)), ssl=ssl_ctx), timeout)
        except (TimeoutError, OSError) as exc:
            raise DeliveryError(f"cannot connect to {self.dest.get('host')}:{self.dest.get('port')}: {exc}") from exc

    async def _drop(self) -> None:
        if self._writer is not None:
            self._writer.close()
        self._reader = self._writer = None

    async def send(self, report: Report, ctx: dict[str, Any]) -> tuple[int | None, str]:
        text = hl7.report_to_oru(
            report, device_name=ctx.get("device_name", ""), sending_facility=self.dest.get("sending_facility", ""),
            receiving_app=self.dest.get("receiving_app", ""), receiving_facility=self.dest.get("receiving_facility", ""),
            version=self.dest.get("hl7_version", "2.5.1"))
        async with self._lock:
            await self._connect()
            assert self._writer is not None and self._reader is not None
            try:
                self._writer.write(b"\x0b" + text.encode("utf-8") + b"\x1c\r")
                await self._writer.drain()
                raw = await asyncio.wait_for(self._reader.readuntil(b"\x1c"), float(self.dest.get("timeout", 30)))
            except (TimeoutError, OSError, asyncio.IncompleteReadError, asyncio.LimitOverrunError) as exc:
                await self._drop()
                raise DeliveryError(f"no acknowledgement: {exc.__class__.__name__}") from exc
        ack = hl7.parse(raw.decode("utf-8", errors="replace"))
        msa = ack.first("MSA")
        code = msa.get(1).upper() if msa else ""
        if code in ("AA", "CA"):
            return None, f"ACK {code}"
        detail = msa.get(3) if msa else "no MSA segment"
        raise DeliveryError(f"rejected by receiver ({code or '?'}): {detail}", retryable=code in ("AE", "CE", ""))

    async def test(self) -> str:
        async with self._lock:
            await self._connect()
            await self._drop()
        return "connected"

    async def close(self) -> None:
        await self._drop()


# ---------------------------------------------------------------------------
# File export
# ---------------------------------------------------------------------------


_unsafe = re.compile(r"[^A-Za-z0-9._-]+")


class FileSender(Sender):
    async def send(self, report: Report, ctx: dict[str, Any]) -> tuple[int | None, str]:
        folder = Path(self.dest.get("folder", "")).expanduser()
        fmt = self.dest.get("format", "json")
        stem = _unsafe.sub("_", f"{ctx.get('device_name', 'device')}_{report.specimen.id or 'nospecimen'}_{report.id[:8]}")
        if fmt == "hl7":
            content, ext = hl7.report_to_oru(report, device_name=ctx.get("device_name", "")), "hl7"
        elif fmt == "csv":
            content, ext = formats.csv_rows(report, ctx), "csv"
        elif fmt == "fhir":
            content, ext = json.dumps(formats.fhir_bundle(report, ctx), indent=2), "json"
        else:
            content, ext = json.dumps(formats.labsync_json(report, ctx), indent=2), "json"

        def write() -> str:
            folder.mkdir(parents=True, exist_ok=True)
            final = folder / f"{stem}.{ext}"
            fd, tmp = tempfile.mkstemp(dir=str(folder), prefix=".tmp-", suffix=f".{ext}")
            with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
                fh.write(content)
            os.replace(tmp, final)  # atomic: pollers never see a half-written file
            return str(final)

        try:
            path = await asyncio.get_running_loop().run_in_executor(None, write)
        except OSError as exc:
            raise DeliveryError(f"cannot write to {folder}: {exc}") from exc
        return None, path

    async def test(self) -> str:
        folder = Path(self.dest.get("folder", "")).expanduser()
        folder.mkdir(parents=True, exist_ok=True)
        probe = folder / ".labsync-write-test"
        probe.write_text("ok")
        probe.unlink()
        return f"writable: {folder}"


SENDERS: dict[str, type[Sender]] = {"http": HttpSender, "fhir": FhirSender, "hl7_mllp": MllpSender, "file": FileSender}


def make_sender(dest: dict[str, Any]) -> Sender:
    return SENDERS[dest.get("type", "http")](dest)
