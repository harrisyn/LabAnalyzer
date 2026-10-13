"""Physical links: TCP server, TCP client and serial (RS-232/USB) ports.

Each configured device gets one ``DeviceRunner``. The runner owns the link,
creates a fresh protocol handler for every connection, feeds it bytes, drives
its timers and reports status changes to the engine.
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ..models import escape_control
from ..protocols.base import ProtocolHandler

log = logging.getLogger("labsync.transport")


@dataclass
class DeviceStatus:
    device_id: str
    state: str = "stopped"  # stopped | starting | listening | connecting | connected | error
    detail: str = ""
    peers: list[str] = field(default_factory=list)
    last_message_at: str = ""
    messages: int = 0
    errors: int = 0
    bytes_in: int = 0
    bytes_out: int = 0


class _Link:
    """Writable side handed to protocol handlers; optionally traces bytes."""

    def __init__(self, peer: str, writer: Callable[[bytes], Any], closer: Callable[[], None],
                 runner: DeviceRunner):
        self.peer = peer
        self._writer = writer
        self._closer = closer
        self._runner = runner

    async def write(self, data: bytes) -> None:
        self._runner.status.bytes_out += len(data)
        if self._runner.trace:
            self._runner.log.info("[%s] >> %s %s", self._runner.name, self.peer, escape_control(data))
        result = self._writer(data)
        if asyncio.iscoroutine(result):
            await result

    def close(self) -> None:
        self._closer()


class DeviceRunner:
    def __init__(self, device: dict[str, Any], handler_factory: Callable[[], ProtocolHandler],
                 on_status: Callable[[DeviceStatus], None]):
        self.device = device
        self.id = device["id"]
        self.name = device.get("name") or self.id
        self.transport = dict(device.get("transport") or {})
        self.trace = bool((device.get("options") or {}).get("trace", False))
        self.handler_factory = handler_factory
        self.on_status = on_status
        self.status = DeviceStatus(device_id=self.id)
        self.log = logging.getLogger(f"labsync.device.{self.id}")
        self._task: asyncio.Task | None = None
        self._server: asyncio.base_events.Server | None = None
        self._conns: set[asyncio.Task] = set()
        self._stopping = False
        allowed = self.transport.get("allowed_peers") or []
        self._allowed = [ipaddress.ip_network(a, strict=False) for a in allowed if str(a).strip()]

    # ------------------------------------------------------------------ status
    def _set(self, state: str, detail: str = "") -> None:
        self.status.state = state
        self.status.detail = detail
        self.on_status(self.status)

    def note_message(self) -> None:
        self.status.messages += 1
        self.status.last_message_at = datetime.now(UTC).isoformat(timespec="seconds")
        self.on_status(self.status)

    # ------------------------------------------------------------------ lifecycle
    async def start(self) -> None:
        self._stopping = False
        kind = self.transport.get("type", "tcp_server")
        self._set("starting")
        if kind == "tcp_server":
            await self._start_server()
        elif kind == "tcp_client":
            self._task = asyncio.create_task(self._client_loop(), name=f"client-{self.id}")
        elif kind == "serial":
            self._task = asyncio.create_task(self._serial_loop(), name=f"serial-{self.id}")
        else:
            self._set("error", f"unknown transport {kind!r}")

    async def stop(self) -> None:
        self._stopping = True
        if self._server is not None:
            self._server.close()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self._server.wait_closed(), 3)
            self._server = None
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None
        for t in list(self._conns):
            t.cancel()
        if self._conns:
            await asyncio.gather(*self._conns, return_exceptions=True)
        self._conns.clear()
        self.status.peers.clear()
        self._set("stopped")

    # ------------------------------------------------------------------ shared session loop
    async def _session(self, peer: str, read: Callable[[], Any], write: Callable[[bytes], Any],
                       close: Callable[[], None]) -> None:
        handler = self.handler_factory()
        link = _Link(peer, write, close, self)
        self.status.peers.append(peer)
        self._set("connected", peer)
        self.log.info("[%s] connected: %s", self.name, peer)
        await handler.connection_made(link)

        async def ticker() -> None:
            while True:
                await asyncio.sleep(1.0)
                try:
                    await handler.tick()
                except Exception:
                    self.log.exception("[%s] protocol timer error", self.name)

        tick_task = asyncio.create_task(ticker())
        try:
            while True:
                data = await read()
                if not data:
                    break
                self.status.bytes_in += len(data)
                if self.trace:
                    self.log.info("[%s] << %s %s", self.name, peer, escape_control(data))
                try:
                    await handler.data_received(data)
                except (ConnectionError, OSError):
                    raise
                except Exception:
                    self.status.errors += 1
                    self.log.exception("[%s] protocol error while handling data from %s", self.name, peer)
        except (ConnectionError, OSError) as exc:
            self.log.info("[%s] connection to %s ended: %s", self.name, peer, exc)
        finally:
            tick_task.cancel()
            with contextlib.suppress(Exception):
                await handler.connection_lost()
            with contextlib.suppress(Exception):
                close()
            if peer in self.status.peers:
                self.status.peers.remove(peer)
            self.log.info("[%s] disconnected: %s", self.name, peer)
            if not self._stopping:
                kind = self.transport.get("type")
                if kind == "tcp_server":
                    self._set("listening" if not self.status.peers else "connected", self._listen_detail())
                else:
                    self._set("connecting", "reconnecting")

    # ------------------------------------------------------------------ TCP server
    def _listen_detail(self) -> str:
        return f"{self.transport.get('host') or '0.0.0.0'}:{self.transport.get('port')}"

    async def _start_server(self) -> None:
        host = self.transport.get("host") or "0.0.0.0"
        port = int(self.transport.get("port", 5000))
        try:
            self._server = await asyncio.start_server(self._accept, host, port, reuse_address=True)
        except OSError as exc:
            self.status.errors += 1
            self._set("error", f"cannot listen on {host}:{port}: {exc.strerror or exc}")
            self.log.error("[%s] cannot listen on %s:%s: %s", self.name, host, port, exc)
            return
        self._set("listening", self._listen_detail())
        self.log.info("[%s] listening on %s:%s", self.name, host, port)

    async def _accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        addr = writer.get_extra_info("peername") or ("?", 0)
        peer = f"{addr[0]}:{addr[1]}"
        if self._allowed:
            try:
                ip = ipaddress.ip_address(addr[0])
                allowed = any(ip in net for net in self._allowed)
            except ValueError:
                allowed = False
            if not allowed:
                self.log.warning("[%s] rejected connection from %s (not in allowed_peers)", self.name, peer)
                writer.close()
                return
        max_conn = int(self.transport.get("max_connections", 8))
        if len(self.status.peers) >= max_conn:
            self.log.warning("[%s] rejected connection from %s (limit %d reached)", self.name, peer, max_conn)
            writer.close()
            return
        _enable_keepalive(writer)
        task = asyncio.current_task()
        if task is not None:
            self._conns.add(task)

        async def write(data: bytes) -> None:
            writer.write(data)
            await writer.drain()

        try:
            await self._session(peer, lambda: reader.read(65536), write, writer.close)
        finally:
            if task is not None:
                self._conns.discard(task)

    # ------------------------------------------------------------------ TCP client
    async def _client_loop(self) -> None:
        host = self.transport.get("host", "")
        port = int(self.transport.get("port", 0))
        delay = float(self.transport.get("reconnect_seconds", 5))
        backoff = delay
        while not self._stopping:
            self._set("connecting", f"{host}:{port}")
            try:
                reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), 15)
            except (TimeoutError, OSError) as exc:
                self._set("connecting", f"{host}:{port} unreachable ({exc.__class__.__name__}); retrying")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
                continue
            backoff = delay
            _enable_keepalive(writer)

            async def write(data: bytes, w: asyncio.StreamWriter = writer) -> None:
                w.write(data)
                await w.drain()

            await self._session(f"{host}:{port}", lambda r=reader: r.read(65536), write, writer.close)
            if not self._stopping:
                await asyncio.sleep(delay)

    # ------------------------------------------------------------------ serial
    async def _serial_loop(self) -> None:
        try:
            import serial  # pyserial
        except ImportError:
            self._set("error", "pyserial is not installed")
            return
        t = self.transport
        port = t.get("port", "")
        loop = asyncio.get_running_loop()
        backoff = 2.0
        while not self._stopping:
            self._set("connecting", f"opening {port}")
            try:
                ser = await loop.run_in_executor(None, lambda: serial.Serial(
                    port=port,
                    baudrate=int(t.get("baudrate", 9600)),
                    bytesize=int(t.get("bytesize", 8)),
                    parity=str(t.get("parity", "N"))[:1].upper(),
                    stopbits=float(t.get("stopbits", 1)),
                    rtscts=bool(t.get("rtscts", False)),
                    xonxoff=bool(t.get("xonxoff", False)),
                    dsrdtr=bool(t.get("dsrdtr", False)),
                    timeout=0.2,
                    write_timeout=10,
                ))
            except Exception as exc:
                self._set("error", f"cannot open {port}: {exc}")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)
                continue
            backoff = 2.0
            queue: asyncio.Queue[bytes] = asyncio.Queue()
            stop = threading.Event()

            def reader_thread(s=ser, q=queue, ev=stop) -> None:
                try:
                    while not ev.is_set():
                        chunk = s.read(s.in_waiting or 1)
                        if chunk:
                            loop.call_soon_threadsafe(q.put_nowait, chunk)
                except Exception as exc:  # port unplugged etc.
                    log.warning("serial read error on %s: %s", s.port, exc)
                finally:
                    loop.call_soon_threadsafe(q.put_nowait, b"")

            th = threading.Thread(target=reader_thread, name=f"serial-{self.id}", daemon=True)
            th.start()

            async def write(data: bytes, s=ser) -> None:
                await loop.run_in_executor(None, s.write, data)

            def close(s=ser, ev=stop) -> None:
                ev.set()
                with contextlib.suppress(Exception):
                    s.close()

            try:
                await self._session(port, queue.get, write, close)
            finally:
                close()
            if not self._stopping:
                await asyncio.sleep(2)


def _enable_keepalive(writer: asyncio.StreamWriter) -> None:
    import socket

    sock = writer.get_extra_info("socket")
    if sock is None:
        return
    with contextlib.suppress(OSError, AttributeError):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)


def list_serial_ports() -> list[tuple[str, str]]:
    try:
        from serial.tools import list_ports
    except ImportError:
        return []
    return [(p.device, p.description or "") for p in sorted(list_ports.comports(), key=lambda p: p.device)]
