"""Framed-text protocols: generic capture, Beckman Coulter AU online, Siemens Dimension.

These instruments do not speak ASTM/HL7, so their layouts are configurable via
device options. Defaults follow the vendors' published host-interface layouts
for typical factory settings; because sites customise field widths and sample
ID lengths on the instrument, confirm them against a capture
(``labsync parse --profile <id> capture.bin``) during commissioning.
"""

from __future__ import annotations

import re
import time
from typing import Any

from ..models import LabMessage, Observation, Report
from .base import ProtocolHandler, SessionContext

STX, ETX, ACK, NAK, EOT, ENQ, FS, CR, LF = 0x02, 0x03, 0x06, 0x15, 0x04, 0x05, 0x1C, 0x0D, 0x0A


class FramedTextHandler(ProtocolHandler):
    """Splits a byte stream into text frames and hands them to ``decode_frame``.

    Options:
      framing: stx_etx (default) | line | idle
      trailer_bytes: bytes after ETX to swallow (e.g. 1 for a BCC, 2 for a hex checksum)
      ack_frames: reply ACK after every complete frame (default True for stx_etx)
      ack_enq: reply ACK to ENQ (default True)
      idle_seconds: gap that ends a message in idle framing
      result_regex: for the generic handler, a regex with named groups code/value/units/flags
      specimen_regex: regex with a named group id, searched in the whole message
    """

    protocol_name = "TEXT"

    def __init__(self, ctx: SessionContext):
        super().__init__(ctx)
        self.framing = str(ctx.opt("framing", "stx_etx"))
        self.trailer = int(ctx.opt("trailer_bytes", 0))
        self.ack_frames = bool(ctx.opt("ack_frames", self.framing == "stx_etx"))
        self.ack_enq = bool(ctx.opt("ack_enq", True))
        self.idle_seconds = float(ctx.opt("idle_seconds", 1.5))
        self.encoding = str(ctx.opt("encoding", "latin-1"))
        self.buf = bytearray()
        self.last_data = time.monotonic()
        self.pending: list[tuple[str, bytes]] = []  # frames of the current transmission

    async def data_received(self, data: bytes) -> None:
        self.buf.extend(data)
        self.last_data = time.monotonic()
        if self.framing == "line":
            while True:
                idx = min((i for i in (self.buf.find(b"\n"), self.buf.find(b"\r")) if i >= 0), default=-1)
                if idx < 0:
                    break
                raw = bytes(self.buf[: idx + 1])
                del self.buf[: idx + 1]
                line = raw.decode(self.encoding, errors="replace").strip()
                if line:
                    await self.frame_received(line, raw)
            return
        if self.framing == "idle":
            return  # flushed by tick()
        while self.buf:
            b = self.buf[0]
            if b == ENQ:
                del self.buf[0]
                if self.ack_enq:
                    await self.write(bytes([ACK]))
                continue
            if b == EOT:
                del self.buf[0]
                await self.transmission_ended()
                continue
            if b != STX:
                del self.buf[0]
                continue
            end = self.buf.find(bytes([ETX]), 1)
            if end < 0 or len(self.buf) < end + 1 + self.trailer:
                return
            raw = bytes(self.buf[: end + 1 + self.trailer])
            text = bytes(self.buf[1:end]).decode(self.encoding, errors="replace")
            del self.buf[: end + 1 + self.trailer]
            if not self.verify(raw, text):
                await self.write(bytes([NAK]))
                continue
            if self.ack_frames:
                await self.write(bytes([ACK]))
            await self.frame_received(text, raw)

    async def tick(self) -> None:
        if self.framing == "idle" and self.buf and time.monotonic() - self.last_data > self.idle_seconds:
            raw = bytes(self.buf)
            self.buf.clear()
            await self.frame_received(raw.decode(self.encoding, errors="replace"), raw)
            await self.transmission_ended()
        elif self.pending and time.monotonic() - self.last_data > max(self.idle_seconds, 5.0):
            await self.transmission_ended()

    def verify(self, raw: bytes, text: str) -> bool:
        return True

    async def frame_received(self, text: str, raw: bytes) -> None:
        self.pending.append((text, raw))
        end_rx = self.ctx.opt("line_message_end_regex")
        if self.framing == "line" and end_rx and re.search(str(end_rx), text):
            await self.transmission_ended()

    async def transmission_ended(self) -> None:
        if not self.pending:
            return
        frames, self.pending = self.pending, []
        msg = self.decode([t for t, _ in frames])
        msg.raw = b"".join(r for _, r in frames)
        await self.emit(msg)

    # -- generic decoding via regexes ------------------------------------
    def decode(self, frames: list[str]) -> LabMessage:
        msg = LabMessage(device_id=self.ctx.device_id, protocol=self.protocol_name)
        text = "\n".join(frames)
        rx = self.ctx.opt("result_regex")
        if not rx:
            msg.message_type = "unparsed"
            return msg
        report = Report()
        srx = self.ctx.opt("specimen_regex")
        if srx:
            m = re.search(srx, text, re.MULTILINE)
            if m:
                report.specimen.id = m.group("id").strip()
        for i, m in enumerate(re.finditer(rx, text, re.MULTILINE), start=1):
            g = m.groupdict()
            report.observations.append(Observation(
                code=(g.get("code") or "").strip(), value=(g.get("value") or "").strip(),
                units=(g.get("units") or "").strip(),
                flags=[f for f in [(g.get("flags") or "").strip()] if f], sequence=i))
        if report.observations:
            msg.reports.append(report)
        return msg


class BeckmanAuHandler(FramedTextHandler):
    """Beckman Coulter AU480/AU680/AU5800 online protocol (fixed-width text blocks).

    Distinction codes: ``DB``/``DE`` start/end of a result batch, ``D `` patient
    results, ``DQ`` QC results, ``R `` requisition (query), ``RB``/``RE``.
    Field widths come from the instrument's online settings; adjust
    ``au_header`` / ``au_test`` if your site differs.
    """

    protocol_name = "BECKMAN-AU"

    DEFAULT_HEADER: list[list[Any]] = [
        ["code", 2], ["rack", 4], ["position", 2], ["sample_type", 1], ["sample_no", 4], ["sample_id", 10],
        ["dummy", 4], ["block", 1],
    ]
    DEFAULT_TEST = {"code": 3, "value": 6, "flags": 2}

    def __init__(self, ctx: SessionContext):
        ctx.options.setdefault("trailer_bytes", 0)
        super().__init__(ctx)
        self.header = ctx.opt("au_header", self.DEFAULT_HEADER)
        self.test = {**self.DEFAULT_TEST, **(ctx.opt("au_test", {}) or {})}
        self.test_map: dict[str, str] = ctx.opt("test_map", {}) or {}

    async def frame_received(self, text: str, raw: bytes) -> None:
        code = text[:2]
        if code in ("DB", "RB"):
            self.pending = []
            return
        if code in ("DE", "RE"):
            await self.transmission_ended()
            return
        if code.startswith("R"):
            # Requisition: reply that no order information is available.
            await self.emit(LabMessage(device_id=self.ctx.device_id, protocol=self.protocol_name, raw=raw,
                                       message_type="query"))
            return
        self.pending.append((text, raw))

    def decode(self, frames: list[str]) -> LabMessage:
        msg = LabMessage(device_id=self.ctx.device_id, protocol=self.protocol_name)
        for text in frames:
            pos = 0
            fields: dict[str, str] = {}
            for name, width in self.header:
                fields[name] = text[pos : pos + int(width)]
                pos += int(width)
            report = Report(is_qc=fields.get("code", "").startswith("DQ"))
            s = report.specimen
            s.id = (fields.get("sample_id") or "").strip() or (fields.get("sample_no") or "").strip()
            s.rack, s.position = fields.get("rack", "").strip(), fields.get("position", "").strip()
            s.type = {"": "serum", " ": "serum", "U": "urine", "X": "other", "W": "whole blood"}.get(
                (fields.get("sample_type") or "").strip(), (fields.get("sample_type") or "").strip())
            cw, vw, fw = int(self.test["code"]), int(self.test["value"]), int(self.test["flags"])
            step = cw + vw + fw
            body = text[pos:]
            seq = 0
            for i in range(0, len(body) - cw + 1, step):
                chunk = body[i : i + step]
                tcode = chunk[:cw].strip()
                if not tcode:
                    continue
                seq += 1
                value = chunk[cw : cw + vw].strip()
                flags = chunk[cw + vw : cw + vw + fw].strip()
                report.observations.append(Observation(
                    code=self.test_map.get(tcode, tcode), raw_code=tcode, value=value,
                    flags=[flags] if flags else [], sequence=seq))
            if report.observations or s.id:
                msg.reports.append(report)
        return msg


class DimensionHandler(FramedTextHandler):
    """Siemens Dimension (RxL/EXL/Xpand) host interface.

    Messages are ``STX <fields separated by FS> <2-char checksum> ETX``. The
    instrument polls (``P``); the host answers ``N`` (no request) or a sample
    request. Results arrive as ``R`` messages and are accepted with ``M``.
    Result layout indexes are configurable via ``dimension_layout``.
    """

    protocol_name = "DIMENSION"

    DEFAULT_LAYOUT = {"patient_id": 2, "sample_id": 3, "sample_type": 4, "test_count": 10, "first_test": 11,
                      "test_stride": 4, "test_fields": ["code", "value", "units", "error"]}

    def __init__(self, ctx: SessionContext):
        ctx.options.setdefault("ack_frames", True)
        super().__init__(ctx)
        self.layout = {**self.DEFAULT_LAYOUT, **(ctx.opt("dimension_layout", {}) or {})}

    @staticmethod
    def _checksum(text: str) -> str:
        return f"{sum(text.encode('latin-1', errors='replace')) & 0xFF:02X}"

    def verify(self, raw: bytes, text: str) -> bool:
        if not self.ctx.opt("verify_checksum", True) or len(text) < 3:
            return True
        body, received = text[:-2], text[-2:].upper()
        ok = self._checksum(body) == received
        if not ok:
            self.log.warning("[%s] Dimension checksum mismatch", self.ctx.device_name)
        return ok or self.ctx.opt("checksum", "strict") != "strict"

    def _frame(self, fields: list[str]) -> bytes:
        body = chr(FS).join(fields) + chr(FS)
        return bytes([STX]) + (body + self._checksum(body)).encode("latin-1") + bytes([ETX])

    async def frame_received(self, text: str, raw: bytes) -> None:
        body = text[:-2] if len(text) > 2 else text
        fields = body.split(chr(FS))
        mtype = fields[0][:1].upper() if fields else ""
        if mtype == "P":
            await self.write(self._frame(["N"]))  # no request message
        elif mtype == "R":
            msg = self.decode([body])
            msg.raw = raw
            await self.emit(msg)
            await self.write(self._frame(["M", "A"]))  # result acceptance
        elif mtype == "Q":
            await self.emit(LabMessage(device_id=self.ctx.device_id, protocol=self.protocol_name, raw=raw,
                                       message_type="query"))
            await self.write(self._frame(["N"]))
        else:
            await self.emit(LabMessage(device_id=self.ctx.device_id, protocol=self.protocol_name, raw=raw,
                                       message_type="event", meta={"dimension_type": mtype}))

    def decode(self, frames: list[str]) -> LabMessage:
        msg = LabMessage(device_id=self.ctx.device_id, protocol=self.protocol_name)
        lay = self.layout
        for body in frames:
            f = body.split(chr(FS))

            def at(i: int, fields: list[str] = f) -> str:
                return fields[i].strip() if 0 <= i < len(fields) else ""

            report = Report()
            report.patient.id = at(int(lay["patient_id"]))
            report.specimen.id = at(int(lay["sample_id"]))
            report.specimen.type = at(int(lay["sample_type"]))
            try:
                count = int(at(int(lay["test_count"])) or 0)
            except ValueError:
                count = 0
            stride = int(lay["test_stride"])
            names = list(lay["test_fields"])
            start = int(lay["first_test"])
            n = count or max(0, (len(f) - start) // stride)
            for i in range(n):
                vals = {name: at(start + i * stride + j) for j, name in enumerate(names)}
                if not vals.get("code"):
                    continue
                o = Observation(code=vals["code"], value=vals.get("value", ""), units=vals.get("units", ""),
                                sequence=i + 1)
                if vals.get("error"):
                    o.flags.append(vals["error"])
                report.observations.append(o)
            if report.observations:
                msg.reports.append(report)
        return msg
