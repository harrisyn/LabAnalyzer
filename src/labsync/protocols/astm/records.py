"""ASTM E1394 / CLSI LIS2-A2 record layer: parse records into the canonical model and build records.

Field numbering in comments follows the standard (1-based, record type is
field 1). In code, ``fields[n]`` is 0-based, so standard field ``k`` is
``fields[k - 1]``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ...models import LabMessage, Observation, OrderRequest, Patient, PersonName, Query, Report


@dataclass(slots=True)
class Delimiters:
    field: str = "|"
    repeat: str = "\\"
    component: str = "^"
    escape: str = "&"

    @classmethod
    def from_header(cls, record: str) -> Delimiters:
        # H|\^&|... : the 4 characters after "H" are field, repeat, component, escape.
        if len(record) >= 5 and record[0] == "H":
            return cls(field=record[1], repeat=record[2], component=record[3], escape=record[4])
        return cls()


def unescape(value: str, d: Delimiters) -> str:
    if d.escape not in value:
        return value
    e = re.escape(d.escape)
    mapping = {"F": d.field, "S": d.component, "R": d.repeat, "E": d.escape}

    def repl(m: re.Match[str]) -> str:
        code = m.group(1)
        if code in mapping:
            return mapping[code]
        if code.startswith("X"):
            try:
                return bytes.fromhex(code[1:]).decode("latin-1")
            except ValueError:
                return m.group(0)
        return m.group(0)

    return re.sub(f"{e}([FSRE]|X[0-9A-Fa-f]+){e}", repl, value)


def escape(value: str, d: Delimiters) -> str:
    out = value.replace(d.escape, f"{d.escape}E{d.escape}")
    out = out.replace(d.field, f"{d.escape}F{d.escape}")
    out = out.replace(d.component, f"{d.escape}S{d.escape}")
    return out.replace(d.repeat, f"{d.escape}R{d.escape}")


@dataclass
class Record:
    raw: str
    fields: list[str]
    d: Delimiters

    @property
    def type(self) -> str:
        return self.fields[0][-1:].upper() if self.fields and self.fields[0] else ""

    def get(self, std_field: int) -> str:
        """Return standard field ``std_field`` (1-based), unescaped, or ''."""
        idx = std_field - 1
        if 0 <= idx < len(self.fields):
            return self.fields[idx]
        return ""

    def components(self, std_field: int) -> list[str]:
        return [unescape(c, self.d) for c in self.get(std_field).split(self.d.component)]

    def repeats(self, std_field: int) -> list[list[str]]:
        raw = self.get(std_field)
        if not raw:
            return []
        return [[unescape(c, self.d) for c in rep.split(self.d.component)] for rep in raw.split(self.d.repeat)]

    def text(self, std_field: int) -> str:
        return unescape(self.get(std_field), self.d).strip()


def split_record(raw: str, d: Delimiters) -> Record:
    raw = raw.strip("\r\n")
    # A frame-number digit is sometimes left in front of the record by lenient senders.
    if len(raw) > 1 and raw[0].isdigit() and raw[1].isalpha():
        raw = raw[1:]
    if raw[:1] == "H" and len(raw) >= 5:
        d = Delimiters.from_header(raw)
        # "H|\^&|..." -> fields: ["H", "\^&", ...]; the delimiter field must not be split.
        rest = raw[5:]
        fields = ["H", raw[2:5]] + (rest[1:].split(d.field) if rest.startswith(d.field) else ([rest] if rest else []))
        return Record(raw=raw, fields=fields, d=d)
    return Record(raw=raw, fields=raw.split(d.field), d=d)


def parse_astm_datetime(value: str) -> str:
    """Convert YYYYMMDD[HHMM[SS]] into ISO 8601; return the input unchanged if it does not fit."""
    value = (value or "").strip()
    digits = re.sub(r"\D", "", value)
    for fmt, length in (("%Y%m%d%H%M%S", 14), ("%Y%m%d%H%M", 12), ("%Y%m%d", 8)):
        if len(digits) >= length:
            try:
                dt = datetime.strptime(digits[:length], fmt)
            except ValueError:
                continue
            return dt.date().isoformat() if length == 8 else dt.isoformat()
    return value


def _norm_sex(value: str) -> str:
    v = (value or "").strip().upper()[:1]
    return v if v in {"M", "F", "O", "U"} else ("U" if v else "")


@dataclass
class AstmOptions:
    """Per-instrument quirks. Defaults follow LIS2-A2."""

    patient_id_fields: list[int] = field(default_factory=lambda: [3, 4, 5])
    name_component_offset: int = 0  # Sysmex XN sends "^LAST^FIRST" (offset 1)
    specimen_id_field: int = 3  # O-3 specimen ID
    specimen_id_component: int = 0
    instrument_specimen_field: int = 4  # O-4 instrument specimen ID
    instrument_specimen_component: int = -1  # -1 = best non-empty component
    test_code_component: int = -1  # -1 = first non-empty component from index 3, then any
    strip_test_code_suffix: str = "/"  # Roche sends "^^^8710/" -> "8710"
    query_specimen_component: int = -1
    qc_specimen_prefixes: list[str] = field(default_factory=lambda: ["QC"])

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> AstmOptions:
        opts = cls()
        for key, value in (data or {}).items():
            if hasattr(opts, key) and value is not None:
                setattr(opts, key, value)
        return opts


def _best_component(parts: list[str], index: int) -> str:
    cleaned = [p.strip() for p in parts]
    if 0 <= index < len(cleaned) and cleaned[index]:
        return cleaned[index]
    if index >= 0:
        return ""
    # Prefer the longest component that is not a one-letter attribute such as "B" or "M".
    candidates = [p for p in cleaned if p and len(p) > 1] or [p for p in cleaned if p]
    return max(candidates, key=len) if candidates else ""


def test_code_from(parts: list[str], opts: AstmOptions) -> str:
    cleaned = [p.strip() for p in parts]
    code = ""
    if opts.test_code_component >= 0:
        if opts.test_code_component < len(cleaned):
            code = cleaned[opts.test_code_component]
    else:
        for p in cleaned[3:]:
            if p:
                code = p
                break
        if not code:
            code = next((p for p in cleaned if p), "")
    if opts.strip_test_code_suffix and opts.strip_test_code_suffix in code:
        head = code.split(opts.strip_test_code_suffix, 1)[0]
        code = head or code
    return code


class AstmMessageBuilder:
    """Accumulates parsed records of one or more H..L messages into LabMessages."""

    def __init__(self, device_id: str, protocol: str, opts: AstmOptions):
        self.device_id = device_id
        self.protocol = protocol
        self.opts = opts
        self.d = Delimiters()
        self.messages: list[LabMessage] = []
        self._msg: LabMessage | None = None
        self._patient: Patient | None = None
        self._report: Report | None = None
        self._last: Observation | Report | None = None

    # -- helpers -------------------------------------------------------
    def _ensure_message(self) -> LabMessage:
        if self._msg is None:
            self._msg = LabMessage(device_id=self.device_id, protocol=self.protocol)
        return self._msg

    def _new_report(self) -> Report:
        msg = self._ensure_message()
        report = Report(patient=self._patient or Patient())
        msg.reports.append(report)
        self._report = report
        self._last = report
        return report

    def _close(self) -> None:
        if self._msg is not None:
            msg = self._msg
            msg.reports = [r for r in msg.reports if r.observations or r.specimen.id or r.comments]
            if msg.queries and not msg.reports:
                msg.message_type = "query"
            elif not msg.reports and not msg.queries:
                msg.message_type = "status"
            self.messages.append(msg)
        self._msg = None
        self._patient = None
        self._report = None
        self._last = None

    # -- record handlers -------------------------------------------------
    def feed(self, raw_record: str) -> None:
        if not raw_record.strip():
            return
        rec = split_record(raw_record, self.d)
        rtype = rec.type
        if rtype == "H":
            if self._msg is not None:
                self._close()
            self.d = rec.d
            msg = self._ensure_message()
            sender = rec.components(5)
            msg.sender = "^".join(p for p in sender if p).strip()
            msg.control_id = rec.text(3)
            msg.meta["header"] = {
                "sender": sender,
                "processing_id": rec.text(12),
                "version": rec.text(13),
                "timestamp": parse_astm_datetime(rec.text(14)),
            }
            if rec.text(12).upper() == "Q":
                msg.meta["qc_processing"] = True
        elif rtype == "P":
            self._ensure_message()
            self._patient = self._parse_patient(rec)
            self._report = None
            self._last = None
        elif rtype == "O":
            report = self._new_report()
            self._parse_order(rec, report)
        elif rtype == "R":
            if self._report is None:
                self._new_report()
            assert self._report is not None
            obs = self._parse_result(rec, len(self._report.observations) + 1)
            self._report.observations.append(obs)
            self._last = obs
        elif rtype == "C":
            text = " ".join(p for p in rec.components(4) if p.strip()).strip()
            if text:
                target = self._last
                if isinstance(target, (Observation, Report)):
                    target.comments.append(text)
                else:
                    self._ensure_message().warnings.append(f"comment: {text}")
        elif rtype == "Q":
            msg = self._ensure_message()
            msg.queries.append(self._parse_query(rec))
        elif rtype == "M":
            msg = self._ensure_message()
            msg.meta.setdefault("manufacturer_records", []).append(rec.raw)
        elif rtype == "S":
            self._ensure_message().meta.setdefault("scientific_records", []).append(rec.raw)
        elif rtype == "L":
            msg = self._ensure_message()
            msg.meta["termination_code"] = rec.text(3)
            self._close()
        else:
            self._ensure_message().warnings.append(f"unknown record type {rtype!r}")

    def finish(self) -> list[LabMessage]:
        if self._msg is not None:
            self._msg.warnings.append("message ended without terminator (L) record")
            self._close()
        out, self.messages = self.messages, []
        return out

    # -- parsing ---------------------------------------------------------
    def _parse_patient(self, rec: Record) -> Patient:
        p = Patient()
        ids = []
        for f in self.opts.patient_id_fields:
            value = _best_component(rec.components(f), -1)
            if value:
                ids.append(value)
        if ids:
            p.id = ids[0]
            p.alternate_ids = [i for i in ids[1:] if i != p.id]
        name = [c.strip() for c in rec.components(6)]
        off = self.opts.name_component_offset
        if off and len(name) > off:
            name = name[off:]
        if any(name):
            p.name = PersonName(
                family=name[0] if len(name) > 0 else "",
                given=name[1] if len(name) > 1 else "",
                middle=name[2] if len(name) > 2 else "",
                suffix=name[3] if len(name) > 3 else "",
                prefix=name[4] if len(name) > 4 else "",
            )
        p.birth_date = parse_astm_datetime(rec.text(8))
        p.sex = _norm_sex(rec.text(9))
        p.physician = " ".join(c for c in rec.components(14) if c.strip()).strip()
        p.location = " ".join(c.strip() for c in rec.components(26) if c.strip())
        return p

    def _parse_order(self, rec: Record, report: Report) -> None:
        s = report.specimen
        o = self.opts
        spec_parts = rec.components(o.specimen_id_field)
        s.id = _best_component(spec_parts, o.specimen_id_component) if o.specimen_id_component >= 0 else _best_component(spec_parts, -1)
        inst_parts = rec.components(o.instrument_specimen_field)
        s.instrument_specimen_id = _best_component(inst_parts, o.instrument_specimen_component)
        if not s.id:
            s.id = s.instrument_specimen_id
        # Rack/position are commonly the first two components of the instrument specimen ID.
        if len(inst_parts) >= 2:
            s.rack, s.position = inst_parts[0].strip(), inst_parts[1].strip()
        s.requested_tests = [c for c in (test_code_from(r, o) for r in rec.repeats(5)) if c]
        s.priority = rec.text(6)[:1].upper()
        s.collected_at = parse_astm_datetime(rec.text(8))
        s.received_at = parse_astm_datetime(rec.text(15))
        s.type = rec.components(16)[0].strip() if rec.get(16) else ""
        report_type = rec.text(26).upper()
        action = rec.text(12).upper()
        prefixes = tuple(p.upper() for p in self.opts.qc_specimen_prefixes if p)
        if action == "Q" or (prefixes and s.id.upper().startswith(prefixes)):
            report.is_qc = True
        if self._msg is not None and self._msg.meta.get("qc_processing"):
            report.is_qc = True
        report.qc_info = {"action_code": action, "report_type": report_type} if report.is_qc else {}

    def _parse_result(self, rec: Record, seq: int) -> Observation:
        parts = rec.components(3)
        code = test_code_from(parts, self.opts)
        name = parts[1].strip() if len(parts) > 1 else ""
        value_parts = rec.components(4)
        value = value_parts[0].strip() if value_parts else ""
        # Some instruments put a qualitative interpretation in the second component.
        extra = [v.strip() for v in value_parts[1:] if v.strip()]
        flags = [f.strip() for f in re.split(r"[\\^]", rec.text(7)) if f.strip()]
        try:
            sequence = int(rec.text(2) or seq)
        except ValueError:
            sequence = seq
        obs = Observation(
            code=code,
            name=name,
            value=value,
            units=rec.text(5),
            reference_range=rec.text(6),
            flags=flags,
            status=rec.text(9),
            observed_at=parse_astm_datetime(rec.text(13) or rec.text(12)),
            sequence=sequence,
            instrument=rec.text(14),
            raw_code=rec.get(3),
        )
        if extra:
            obs.comments.append("interpretation: " + " ".join(extra))
        return obs

    def _parse_query(self, rec: Record) -> Query:
        q = Query(raw_fields={"starting_range": rec.get(3), "tests": rec.get(5), "status": rec.text(13)})
        for rep in rec.repeats(3) or [[]]:
            if not rep:
                continue
            idx = self.opts.query_specimen_component
            if idx >= 0:
                sid = rep[idx].strip() if idx < len(rep) else ""
            elif len(rep) == 1:
                sid = rep[0].strip()
            elif len(rep) == 2:
                # LIS2-A2: patient ID ^ specimen ID
                q.patient_id = q.patient_id or rep[0].strip()
                sid = rep[1].strip()
            else:
                # e.g. Sysmex "rack^pos^sample no^attr": take the most specific component.
                sid = _best_component(rep[1:], -1)
            if sid and sid.upper() != "ALL":
                q.specimen_ids.append(sid)
        return q


# ----------------------------------------------------------------------------
# Building records (host -> instrument)
# ----------------------------------------------------------------------------


def build_header(sender: str = "LabSync", receiver: str = "", processing_id: str = "P") -> str:
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"H|\\^&|||{sender}|||||{receiver}||{processing_id}|1|{ts}"


def build_order_records(
    orders: list[OrderRequest],
    *,
    test_prefix: str = "^^^",
    query: Query | None = None,
    echo_specimen_field: bool = False,
    sender: str = "LabSync",
) -> list[str]:
    """Build H/P/O.../L records answering a host query.

    ``echo_specimen_field`` copies the query's starting-range field into O-4 so
    instruments that match responses by rack/position (e.g. Sysmex) accept them.
    """
    d = Delimiters()
    records = [build_header(sender)]
    if not orders:
        records.append("L|1|I")  # I = no information available from last query
        return records
    for pi, order in enumerate(orders, start=1):
        p = order.patient
        name = ""
        if p.name:
            name = d.component.join([escape(p.name.family, d), escape(p.name.given, d), escape(p.name.middle, d)]).rstrip("^")
        dob = p.birth_date.replace("-", "")
        records.append(f"P|{pi}||{escape(p.id, d)}||{name}||{dob}|{p.sex}")
        tests = d.repeat.join(f"{test_prefix}{escape(t, d)}" for t in order.tests)
        inst = ""
        if echo_specimen_field and query is not None:
            inst = str(query.raw_fields.get("starting_range", ""))
        collected = order.collected_at.replace("-", "").replace(":", "").replace("T", "")
        fields = ["O", "1", escape(order.specimen_id, d), inst, tests, order.priority or "R", "", collected,
                  "", "", "", "N", "", "", "", order.specimen_type, "", "", "", "", "", "", "", "", "", "O"]
        records.append(d.field.join(fields))
    records.append("L|1|N")
    return records
