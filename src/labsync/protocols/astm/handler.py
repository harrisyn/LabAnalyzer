"""ASTM E1381 (LIS01-A2) link layer + E1394 (LIS2-A2) records, both directions.

Receiving: ENQ -> ACK, frames validated (frame number, checksum) and ACKed or
NAKed, ETB continuation frames reassembled, EOT completes the transmission and
the records are parsed into canonical messages.

Sending (answers to host queries): establishment with ENQ, contention handling
(the instrument wins), per-frame retransmission on NAK (max 6), timeouts, EOT.

Also accepts "unframed" ASTM (records sent as plain CR-terminated lines with no
ENQ/STX), which many TCP-native analyzers use.
"""

from __future__ import annotations

import asyncio
import re
import time

from ...models import LabMessage, Query
from ..base import ProtocolHandler, SessionContext
from .framing import ACK, CR, ENQ, EOT, ETB, ETX, LF, NAK, STX, build_frames, try_parse_frame
from .records import AstmMessageBuilder, AstmOptions, build_order_records

UNFRAMED_END = re.compile(rb"(?:^|[\r\n])[0-7]?L(?:\|[^\r\n]*)?[\r\n]")

RECEIVE_TIMEOUT = 30.0  # LIS01-A2 receiver timer
REPLY_TIMEOUT = 15.0  # LIS01-A2 sender timer
CONTENTION_BACKOFF = 20.0
BUSY_RETRY = 10.0
MAX_RETRANSMIT = 6


class AstmHandler(ProtocolHandler):
    protocol_name = "ASTM"

    def __init__(self, ctx: SessionContext):
        super().__init__(ctx)
        self.opts = AstmOptions.from_dict(ctx.options.get("astm"))
        self.framing = str(ctx.opt("framing", "auto")).lower()  # auto | e1381 | none
        self.checksum_mode = str(ctx.opt("checksum", "strict")).lower()  # strict | lenient | ignore
        self.check_frame_numbers = bool(ctx.opt("check_frame_numbers", True))
        self.encoding = str(ctx.opt("encoding", "latin-1"))
        self.answer_queries = bool(ctx.opt("answer_queries", True))
        self.echo_query_specimen = bool(ctx.opt("echo_query_specimen", False))
        self.test_prefix = str(ctx.opt("order_test_prefix", "^^^"))

        self.buf = bytearray()
        self.state = "idle"  # idle | receiving | sending
        self.expected_fn = 1
        self.last_fn = 0
        self.partial = bytearray()  # ETB-continued record text
        self.records: list[str] = []
        self.wire = bytearray()
        self.last_activity = time.monotonic()
        self.unframed = bytearray()

        self._replies: asyncio.Queue[int] = asyncio.Queue()
        self._send_lock = asyncio.Lock()
        self._proc_lock = asyncio.Lock()
        self._pending_queries: list[Query] = []
        self._tasks: set[asyncio.Task] = set()

    # ------------------------------------------------------------------ receive
    async def data_received(self, data: bytes) -> None:
        self.last_activity = time.monotonic()
        self.buf.extend(data)
        await self._process()

    async def _process(self) -> None:
        async with self._proc_lock:
            await self._process_locked()

    async def _process_locked(self) -> None:
        while self.buf:
            b = self.buf[0]
            if self.state == "sending":
                # While we transmit, the instrument only answers ACK/NAK/EOT (or ENQ in contention).
                del self.buf[0]
                if b in (ACK, NAK, EOT, ENQ):
                    self._replies.put_nowait(b)
                continue

            if self.unframed:
                if not await self._consume_unframed():
                    return
                continue

            if b == ENQ:
                del self.buf[0]
                if self.state == "receiving" and self.records:
                    self.log.warning("[%s] ENQ during an open transmission; previous data discarded", self.ctx.device_name)
                self._begin_receive()
                await self.write(bytes([ACK]))
            elif b == STX:
                if self.state != "receiving":
                    if self.framing == "none":
                        del self.buf[0]
                        continue
                    # Lenient: some instruments skip the establishment phase.
                    self.log.debug("[%s] frame without ENQ; accepting", self.ctx.device_name)
                    self._begin_receive(send_ack=False)
                frame = try_parse_frame(self.buf)
                if frame is None:
                    return  # wait for the rest of the frame
                raw = bytes(self.buf[: frame.consumed])
                del self.buf[: frame.consumed]
                self.wire.extend(raw)
                await self._handle_frame(frame)
            elif b == EOT:
                del self.buf[0]
                if self.state == "receiving":
                    self.wire.append(EOT)
                    await self._end_receive()
            elif b in (CR, LF, ACK, NAK, 0x00):
                del self.buf[0]
            elif self.state == "idle" and self.framing in ("auto", "none") and b == ord("H"):
                # Unframed ASTM: plain records beginning with the header.
                self.unframed.extend(self.buf)
                self.buf.clear()
                if not await self._consume_unframed():
                    return
            else:
                if self.state == "receiving":
                    self.wire.append(b)
                del self.buf[0]

    def _begin_receive(self, send_ack: bool = True) -> None:
        self.state = "receiving"
        self.expected_fn = 1
        self.last_fn = 0
        self.partial.clear()
        self.records = []
        self.wire = bytearray([ENQ]) if send_ack else bytearray()

    async def _handle_frame(self, frame) -> None:
        if frame.number < 0:
            self.log.warning("[%s] malformed frame (%r); NAK", self.ctx.device_name, bytes(frame.text[:40]))
            await self.write(bytes([NAK]))
            return
        if not frame.checksum_ok and self.checksum_mode != "ignore":
            msg = (f"[{self.ctx.device_name}] checksum mismatch on frame {frame.number}: "
                   f"got {frame.received_checksum}, expected {frame.expected_checksum}")
            if self.checksum_mode == "strict":
                self.log.warning(msg + "; NAK")
                await self.write(bytes([NAK]))
                return
            self.log.warning(msg + "; accepted (lenient mode)")
        if self.check_frame_numbers and frame.number != self.expected_fn:
            if frame.number == self.last_fn:
                # Retransmission of a frame we already accepted (our ACK was lost).
                await self.write(bytes([ACK]))
                return
            self.log.warning("[%s] frame number %d, expected %d", self.ctx.device_name, frame.number, self.expected_fn)
            if self.checksum_mode == "strict":
                await self.write(bytes([NAK]))
                return
        self.last_fn = frame.number
        self.expected_fn = (frame.number + 1) % 8
        self.partial.extend(frame.text)
        if frame.final:
            text = self.partial.decode(self.encoding, errors="replace")
            self.partial.clear()
            # One record per frame by the standard, but several CR-separated records are common.
            self.records.extend(r for r in text.replace("\n", "\r").split("\r") if r.strip())
        await self.write(bytes([ACK]))

    async def _end_receive(self) -> None:
        if self.partial:
            self.records.append(self.partial.decode(self.encoding, errors="replace"))
            self.partial.clear()
        records, wire = self.records, bytes(self.wire)
        self.state = "idle"
        self.records = []
        self.wire = bytearray()
        await self._deliver(records, wire)

    async def _consume_unframed(self) -> bool:
        """Unframed mode: collect lines until an L record. Returns False when more data is needed."""
        if self.buf:
            self.unframed.extend(self.buf)
            self.buf.clear()
        match = UNFRAMED_END.search(self.unframed)
        if match is None:
            if len(self.unframed) > 4 * 1024 * 1024:
                self.log.error("[%s] unframed data exceeded 4 MB without a terminator record; discarding",
                               self.ctx.device_name)
                self.unframed.clear()
            return False
        chunk = bytes(self.unframed[: match.end()])
        rest = bytes(self.unframed[match.end():]).lstrip(b"\r\n")
        self.unframed = bytearray()
        await self._flush_unframed(chunk)
        if rest:
            self.buf[:0] = rest
        return True

    async def _flush_unframed(self, chunk: bytes) -> None:
        text = chunk.decode(self.encoding, errors="replace").replace("\n", "\r")
        records = [r for r in text.split("\r") if r.strip()]
        await self._deliver(records, chunk)
        if self.ctx.opt("unframed_ack", False):
            await self.write(bytes([ACK]))

    async def _deliver(self, records: list[str], wire: bytes) -> None:
        if not records:
            return
        builder = AstmMessageBuilder(self.ctx.device_id, self.protocol_name, self.opts)
        for record in records:
            try:
                builder.feed(record)
            except Exception as exc:  # keep going; one bad record must not lose the rest
                self.log.exception("[%s] could not parse record %r", self.ctx.device_name, record[:80])
                builder._ensure_message().warnings.append(f"unparseable record: {exc}")
        messages = builder.finish()
        for i, msg in enumerate(messages):
            msg.raw = wire if i == 0 else b""
            msg.meta["records"] = len(records)
            if i > 0:
                msg.meta["same_transmission_as_previous"] = True
            await self.emit(msg)
            if msg.queries and self.answer_queries:
                self._pending_queries.extend(msg.queries)
        if self._pending_queries:
            queries, self._pending_queries = self._pending_queries, []
            task = asyncio.create_task(self._answer_queries(queries))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def tick(self) -> None:
        idle_for = time.monotonic() - self.last_activity
        if self.unframed and idle_for > RECEIVE_TIMEOUT:
            self.log.warning("[%s] unframed message without terminator; storing what was received",
                             self.ctx.device_name)
            chunk, self.unframed = bytes(self.unframed), bytearray()
            await self._flush_unframed(chunk)
        if self.state == "receiving" and time.monotonic() - self.last_activity > RECEIVE_TIMEOUT:
            self.log.warning("[%s] receive timeout; discarding incomplete transmission", self.ctx.device_name)
            if self.records:
                # Keep what we have: the data is real even if the sender went away.
                await self._end_receive()
            self.state = "idle"
            self.partial.clear()
            self.buf.clear()

    async def connection_lost(self) -> None:
        if self.state == "receiving" and self.records:
            self.log.warning("[%s] connection lost mid-transmission; storing %d records received",
                             self.ctx.device_name, len(self.records))
            await self._end_receive()
        for task in list(self._tasks):
            task.cancel()
        await super().connection_lost()

    # ------------------------------------------------------------------ send
    async def _answer_queries(self, queries: list[Query]) -> None:
        for query in queries:
            orders = await self.lookup_orders(query)
            records = build_order_records(
                orders,
                test_prefix=self.test_prefix,
                query=query,
                echo_specimen_field=self.echo_query_specimen,
            )
            self.log.info("[%s] answering query for %s with %d order(s)", self.ctx.device_name,
                          ",".join(query.specimen_ids) or "?", len(orders))
            ok = await self.send_records(records)
            out = LabMessage(device_id=self.ctx.device_id, protocol=self.protocol_name, message_type="order",
                             raw="\r".join(records).encode(self.encoding, errors="replace"))
            out.meta["direction"] = "out"
            out.meta["delivered"] = ok
            await self.record_outbound(out)

    async def _wait_reply(self, timeout: float) -> int | None:
        try:
            return await asyncio.wait_for(self._replies.get(), timeout)
        except TimeoutError:
            return None

    async def send_records(self, records: list[str]) -> bool:
        """Transmit records to the instrument. Returns True when every frame was acknowledged."""
        frames = build_frames(records, self.encoding)
        async with self._send_lock:
            for _ in range(6):
                # Wait for the line to be neutral: never interrupt an instrument transmission.
                while self.state == "receiving":
                    await asyncio.sleep(0.2)
                while not self._replies.empty():
                    self._replies.get_nowait()
                self.state = "sending"
                await self.write(bytes([ENQ]))
                reply = await self._wait_reply(REPLY_TIMEOUT)
                if reply == ACK:
                    break
                self.state = "idle"
                if reply == ENQ:
                    # Contention: the instrument has priority. Let it send, then retry.
                    self.log.info("[%s] line contention; yielding to instrument", self.ctx.device_name)
                    self.buf[:0] = bytes([ENQ])
                    await self._process()
                    await asyncio.sleep(CONTENTION_BACKOFF / 20)
                    continue
                if reply == NAK:
                    await asyncio.sleep(BUSY_RETRY)
                    continue
                self.log.warning("[%s] no reply to ENQ; aborting send", self.ctx.device_name)
                await self.write(bytes([EOT]))
                return False
            else:
                self.state = "idle"
                return False

            try:
                for frame in frames:
                    for attempt in range(MAX_RETRANSMIT + 1):
                        await self.write(frame)
                        reply = await self._wait_reply(REPLY_TIMEOUT)
                        if reply in (ACK, EOT):
                            break  # EOT here is a receiver interrupt request; treat as ACK
                        if reply is None:
                            self.log.warning("[%s] timeout waiting for frame ACK", self.ctx.device_name)
                            await self.write(bytes([EOT]))
                            return False
                        self.log.debug("[%s] frame NAKed (attempt %d)", self.ctx.device_name, attempt + 1)
                    else:
                        self.log.warning("[%s] frame rejected %d times; aborting", self.ctx.device_name, MAX_RETRANSMIT)
                        await self.write(bytes([EOT]))
                        return False
                await self.write(bytes([EOT]))
                return True
            finally:
                self.state = "idle"
                if self.buf:
                    await self._process()


__all__ = ["AstmHandler", "STX", "ETX", "ETB"]
