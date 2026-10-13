"""Protocol handler contract shared by every instrument protocol.

A transport (TCP server, TCP client, serial port) owns the wire. For every
connection it creates a fresh handler instance, so state such as partially
received frames never leaks between instruments or reconnects.

Handlers are written for a single asyncio event loop: ``data_received`` is
awaited sequentially by the transport reader, while a handler may run its own
tasks (for example to transmit orders) that wait for replies routed through
``data_received``.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..models import LabMessage, OrderRequest, Query


class Link(Protocol):
    """The writable side of a connection, as seen by a protocol handler."""

    peer: str

    async def write(self, data: bytes) -> None: ...

    def close(self) -> None: ...


class OrderSource(Protocol):
    async def lookup(self, query: Query, device_id: str) -> list[OrderRequest]: ...


@dataclass
class SessionContext:
    device_id: str
    device_name: str
    profile_id: str
    options: dict[str, Any]
    on_message: Callable[[LabMessage], Awaitable[None]]
    on_outbound: Callable[[LabMessage], Awaitable[None]] | None = None
    orders: OrderSource | None = None
    logger: logging.Logger = field(default_factory=lambda: logging.getLogger("labsync.protocol"))

    def opt(self, key: str, default: Any = None) -> Any:
        value = self.options.get(key, default)
        return default if value is None else value


class ProtocolHandler(ABC):
    """Base class for all protocol implementations."""

    protocol_name = "base"

    def __init__(self, ctx: SessionContext):
        self.ctx = ctx
        self.log = ctx.logger
        self.link: Link | None = None
        self.peer = ""

    async def connection_made(self, link: Link) -> None:
        self.link = link
        self.peer = getattr(link, "peer", "")

    @abstractmethod
    async def data_received(self, data: bytes) -> None: ...

    async def connection_lost(self) -> None:
        self.link = None

    async def tick(self) -> None:  # noqa: B027 - optional hook
        """Called about once per second by the transport for protocol timers."""

    async def write(self, data: bytes) -> None:
        if self.link is None:
            raise ConnectionError("not connected")
        await self.link.write(data)

    async def emit(self, message: LabMessage) -> None:
        message.peer = message.peer or self.peer
        await self.ctx.on_message(message)

    async def record_outbound(self, message: LabMessage) -> None:
        if self.ctx.on_outbound is not None:
            message.peer = message.peer or self.peer
            await self.ctx.on_outbound(message)

    async def lookup_orders(self, query: Query) -> list[OrderRequest]:
        if self.ctx.orders is None:
            return []
        try:
            return await self.ctx.orders.lookup(query, self.ctx.device_id)
        except Exception:
            self.log.exception("[%s] order lookup failed", self.ctx.device_name)
            return []
