"""Canonical, protocol-independent data model.

Every protocol handler converts what the instrument sent into these types, and
every outbound destination formats them. Nothing downstream of a parser needs
to know whether a result arrived as ASTM, HL7, POCT1-A or a vendor format.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return uuid.uuid4().hex


# Abnormal flags that mean "outside the reference interval or otherwise notable".
ABNORMAL_FLAGS = {"L", "H", "LL", "HH", "<", ">", "A", "AA", "U", "D", "B", "W", "S", "R", "I", "*", "+", "-"}


@dataclass(slots=True)
class PersonName:
    family: str = ""
    given: str = ""
    middle: str = ""
    suffix: str = ""
    prefix: str = ""

    @property
    def full(self) -> str:
        return " ".join(p for p in (self.prefix, self.given, self.middle, self.family, self.suffix) if p).strip()

    def __bool__(self) -> bool:
        return bool(self.family or self.given or self.middle)


@dataclass(slots=True)
class Patient:
    id: str = ""
    alternate_ids: list[str] = field(default_factory=list)
    name: PersonName = field(default_factory=PersonName)
    birth_date: str = ""  # ISO yyyy-mm-dd when parseable, otherwise as sent
    sex: str = ""  # M, F, O, U
    physician: str = ""
    location: str = ""

    def __bool__(self) -> bool:
        return bool(self.id or self.alternate_ids or self.name)


@dataclass(slots=True)
class Specimen:
    id: str = ""  # sample / accession / barcode ID used to match the order
    instrument_specimen_id: str = ""
    type: str = ""
    collected_at: str = ""
    received_at: str = ""
    priority: str = ""  # R routine, S stat, A asap
    rack: str = ""
    position: str = ""
    requested_tests: list[str] = field(default_factory=list)


@dataclass(slots=True)
class Observation:
    code: str
    value: str = ""
    name: str = ""
    units: str = ""
    reference_range: str = ""
    flags: list[str] = field(default_factory=list)
    status: str = ""  # F final, P preliminary, C corrected, X cannot be done...
    observed_at: str = ""
    sequence: int = 0
    instrument: str = ""
    value_type: str = ""  # NM, ST, CE... when the protocol says
    comments: list[str] = field(default_factory=list)
    raw_code: str = ""

    @property
    def numeric_value(self) -> float | None:
        text = (self.value or "").strip().lstrip("<>=~").strip()
        if not text:
            return None
        try:
            return float(text.replace(",", ".")) if text.count(",") == 1 and "." not in text else float(text)
        except ValueError:
            return None

    @property
    def abnormal(self) -> bool:
        return any(f.upper() in ABNORMAL_FLAGS for f in self.flags if f and f.upper() != "N")


@dataclass(slots=True)
class Attachment:
    name: str
    mime: str
    data: bytes


@dataclass(slots=True)
class Report:
    """Results for one specimen (and patient, when known) from one message."""

    id: str = field(default_factory=new_id)
    patient: Patient = field(default_factory=Patient)
    specimen: Specimen = field(default_factory=Specimen)
    observations: list[Observation] = field(default_factory=list)
    comments: list[str] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    is_qc: bool = False
    qc_info: dict[str, Any] = field(default_factory=dict)

    @property
    def abnormal_count(self) -> int:
        return sum(1 for o in self.observations if o.abnormal)


@dataclass(slots=True)
class Query:
    """An instrument asking the host for orders (host query / worklist request)."""

    specimen_ids: list[str] = field(default_factory=list)
    patient_id: str = ""
    raw_fields: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class OrderRequest:
    """An order the host sends down to an instrument."""

    specimen_id: str
    tests: list[str]
    patient: Patient = field(default_factory=Patient)
    priority: str = "R"
    specimen_type: str = ""
    collected_at: str = ""


@dataclass(slots=True)
class LabMessage:
    """One logical message received from (or sent to) an instrument."""

    device_id: str
    protocol: str
    raw: bytes = b""
    received_at: datetime = field(default_factory=utcnow)
    message_type: str = "results"  # results, query, status, event, unknown
    sender: str = ""
    control_id: str = ""
    peer: str = ""
    reports: list[Report] = field(default_factory=list)
    queries: list[Query] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def raw_text(self) -> str:
        return self.raw.decode("latin-1", errors="replace")


def report_to_dict(report: Report) -> dict[str, Any]:
    data = asdict(report)
    data.pop("attachments", None)
    return data


def escape_control(data: bytes | str) -> str:
    """Render bytes with control characters shown as <STX>, <ETX>... for logs and the GUI."""
    names = {
        0x02: "<STX>", 0x03: "<ETX>", 0x04: "<EOT>", 0x05: "<ENQ>", 0x06: "<ACK>",
        0x15: "<NAK>", 0x17: "<ETB>", 0x0B: "<VT>", 0x1C: "<FS>", 0x0D: "<CR>\n",
        0x0A: "<LF>", 0x01: "<SOH>", 0x1D: "<GS>", 0x1E: "<RS>", 0x1F: "<US>",
    }
    if isinstance(data, str):
        data = data.encode("latin-1", errors="replace")
    out = []
    for b in data:
        if b in names:
            out.append(names[b])
        elif b < 0x20 or b == 0x7F:
            out.append(f"<{b:02X}>")
        else:
            out.append(chr(b))
    return "".join(out)
