"""Protocol handler registry."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from ..models import LabMessage
from .astm.handler import AstmHandler
from .base import ProtocolHandler, SessionContext
from .hl7.handler import Hl7Handler
from .poct1a import Poct1aHandler
from .vendor import BeckmanAuHandler, DimensionHandler, FramedTextHandler

HANDLERS: dict[str, type[ProtocolHandler]] = {
    "astm": AstmHandler,
    "hl7": Hl7Handler,
    "poct1a": Poct1aHandler,
    "beckman_au": BeckmanAuHandler,
    "dimension": DimensionHandler,
    "text": FramedTextHandler,
}

PROTOCOL_LABELS = {
    "astm": "ASTM E1381/E1394 (LIS01/LIS2-A2)",
    "hl7": "HL7 v2.x over MLLP",
    "poct1a": "POCT1-A2 (XML)",
    "beckman_au": "Beckman Coulter AU online",
    "dimension": "Siemens Dimension host interface",
    "text": "Generic text capture",
}


def handler_for(protocol: str) -> type[ProtocolHandler]:
    try:
        return HANDLERS[protocol.lower()]
    except KeyError as exc:
        raise ValueError(f"unknown protocol {protocol!r}; expected one of {', '.join(HANDLERS)}") from exc


class _CaptureLink:
    peer = "capture"

    def __init__(self) -> None:
        self.written = bytearray()

    async def write(self, data: bytes) -> None:
        self.written.extend(data)

    def close(self) -> None:
        pass


async def _parse(protocol: str, options: dict[str, Any], data: bytes, chunk: int) -> tuple[list[LabMessage], bytes]:
    out: list[LabMessage] = []

    async def collect(msg: LabMessage) -> None:
        out.append(msg)

    ctx = SessionContext(device_id="capture", device_name="capture", profile_id="", options=options,
                         on_message=collect, logger=logging.getLogger("labsync.capture"))
    handler = handler_for(protocol)(ctx)
    link = _CaptureLink()
    await handler.connection_made(link)
    for i in range(0, len(data), chunk):
        await handler.data_received(data[i : i + chunk])
    # Flush idle-based framings.
    for attr in ("last_data", "last_activity"):
        if hasattr(handler, attr):
            setattr(handler, attr, 0.0)
    await handler.tick()
    await handler.connection_lost()
    return out, bytes(link.written)


def parse_capture(protocol: str, data: bytes, options: dict[str, Any] | None = None,
                  chunk: int = 4096) -> tuple[list[LabMessage], bytes]:
    """Run a captured byte stream through a protocol handler. Returns (messages, bytes we replied)."""
    return asyncio.run(_parse(protocol, dict(options or {}), data, chunk))


__all__ = ["HANDLERS", "PROTOCOL_LABELS", "ProtocolHandler", "SessionContext", "handler_for", "parse_capture"]
