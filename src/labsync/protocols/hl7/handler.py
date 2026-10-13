"""HL7 v2 over MLLP (VT ... FS CR), with original-mode acknowledgements and host queries."""

from __future__ import annotations

import time

from ...models import LabMessage, Query
from ..base import ProtocolHandler, SessionContext
from . import message as hl7

VT, FS, CR = 0x0B, 0x1C, 0x0D
MAX_MESSAGE = 16 * 1024 * 1024


def mllp_wrap(text: str, encoding: str = "utf-8") -> bytes:
    return bytes([VT]) + text.encode(encoding, errors="replace") + bytes([FS, CR])


class Hl7Handler(ProtocolHandler):
    protocol_name = "HL7"

    def __init__(self, ctx: SessionContext):
        super().__init__(ctx)
        self.opts = hl7.Hl7Options.from_dict(ctx.options.get("hl7"))
        self.encoding = str(ctx.opt("encoding", "utf-8"))
        self.ack_mode = str(ctx.opt("ack", "always")).lower()  # always | never | msh15
        self.query_style = str(ctx.opt("query_style", "mindray")).lower()  # mindray | none
        self.idle_flush = float(ctx.opt("unframed_idle_seconds", 2.0))
        self.buf = bytearray()
        self.last_data = time.monotonic()

    async def data_received(self, data: bytes) -> None:
        self.buf.extend(data)
        self.last_data = time.monotonic()
        await self._drain()

    async def _drain(self) -> None:
        while True:
            start = self.buf.find(bytes([VT]))
            if start < 0:
                # No MLLP start byte: some devices send bare "MSH|..." over TCP/serial.
                if b"MSH" not in self.buf:
                    if len(self.buf) > MAX_MESSAGE:
                        self.buf.clear()
                    return
                start = self.buf.find(b"MSH")
                end = self.buf.find(bytes([FS]), start)
                if end < 0:
                    return  # wait for FS or the idle flush in tick()
                payload = bytes(self.buf[start:end])
                del self.buf[: end + 1]
            else:
                end = self.buf.find(bytes([FS]), start + 1)
                if end < 0:
                    if start > 0:
                        del self.buf[:start]
                    if len(self.buf) > MAX_MESSAGE:
                        self.log.error("[%s] HL7 message exceeds %d bytes; discarding", self.ctx.device_name, MAX_MESSAGE)
                        self.buf.clear()
                    return
                payload = bytes(self.buf[start + 1 : end])
                del self.buf[: end + 1]
            if self.buf[:1] == bytes([CR]):
                del self.buf[:1]
            await self._handle(payload)

    async def tick(self) -> None:
        # Flush a bare (unframed) HL7 message after a quiet period.
        if self.buf and time.monotonic() - self.last_data > self.idle_flush and b"MSH" in self.buf and bytes([VT]) not in self.buf:
            payload = bytes(self.buf[self.buf.find(b"MSH"):])
            self.buf.clear()
            await self._handle(payload)

    async def _handle(self, payload: bytes) -> None:
        text = payload.decode(self.encoding, errors="replace")
        try:
            parsed = hl7.parse(text)
        except ValueError as exc:
            self.log.warning("[%s] invalid HL7 message: %s", self.ctx.device_name, exc)
            msg = LabMessage(device_id=self.ctx.device_id, protocol=self.protocol_name, raw=payload,
                             message_type="unknown", warnings=[f"invalid HL7: {exc}"])
            await self.emit(msg)
            return

        try:
            lab = hl7.to_lab_message(parsed, self.ctx.device_id, self.opts)
            ack_code, ack_text = "AA", ""
        except Exception as exc:
            self.log.exception("[%s] failed to interpret HL7 %s", self.ctx.device_name, parsed.message_type)
            lab = LabMessage(device_id=self.ctx.device_id, protocol=self.protocol_name, message_type="unknown",
                             warnings=[f"interpretation failed: {exc}"])
            ack_code, ack_text = "AE", str(exc)
        lab.raw = payload
        mtype = parsed.msh.get(9, 1).upper()

        if mtype in ("QRY", "QBP"):
            lab.message_type = "query"
            lab.queries.append(self._query_from(parsed))
            await self.emit(lab)
            await self._answer_query(parsed, lab.queries[0])
            return

        await self.emit(lab)
        if mtype == "ACK":
            return
        if self.ack_mode == "never":
            return
        if self.ack_mode == "msh15" and parsed.msh.get(15).upper() in ("NE", "ER"):
            return
        ack = hl7.build_ack(parsed, ack_code, ack_text)
        await self.write(mllp_wrap(ack, self.encoding))

    def _query_from(self, parsed: hl7.Hl7Message) -> Query:
        q = Query()
        qrd = parsed.first("QRD")
        if qrd is not None:
            # QRD-8 "who subject filter" carries the sample barcode on Mindray analyzers.
            sid = qrd.get(8)
            if sid:
                q.specimen_ids.append(sid)
        qpd = parsed.first("QPD")
        if qpd is not None:
            for n in (3, 4):
                v = qpd.get(n)
                if v and v not in q.specimen_ids:
                    q.specimen_ids.append(v)
        q.raw_fields = {"message_type": parsed.message_type}
        return q

    async def _answer_query(self, parsed: hl7.Hl7Message, query: Query) -> None:
        orders = await self.lookup_orders(query)
        mtype = parsed.message_type.upper()
        responses: list[str] = []
        if mtype.startswith("QRY") and self.query_style == "mindray":
            responses.append(hl7.build_qck(parsed, bool(orders)))
            for order in orders:
                responses.append(hl7.build_mindray_dsr(parsed, order))
        else:
            responses.append(hl7.build_ack(parsed, "AA", "no orders" if not orders else ""))
        for text in responses:
            await self.write(mllp_wrap(text, self.encoding))
        out = LabMessage(device_id=self.ctx.device_id, protocol=self.protocol_name, message_type="order",
                         raw="\n".join(responses).encode(self.encoding, errors="replace"))
        out.meta["direction"] = "out"
        out.meta["orders"] = len(orders)
        await self.record_outbound(out)
