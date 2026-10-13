"""Minimal, dependency-free HL7 v2 parser and builder."""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from datetime import datetime
from itertools import count

from ...models import Attachment, LabMessage, Observation, OrderRequest, Patient, PersonName, Report

_control = count(1)


@dataclass(slots=True)
class Encoding:
    field: str = "|"
    component: str = "^"
    repeat: str = "~"
    escape: str = "\\"
    subcomponent: str = "&"

    @property
    def msh2(self) -> str:
        return f"{self.component}{self.repeat}{self.escape}{self.subcomponent}"


def unescape(value: str, enc: Encoding) -> str:
    if enc.escape not in value:
        return value
    e = re.escape(enc.escape)
    mapping = {"F": enc.field, "S": enc.component, "R": enc.repeat, "E": enc.escape, "T": enc.subcomponent,
               ".br": "\n"}

    def repl(m: re.Match[str]) -> str:
        code = m.group(1)
        if code in mapping:
            return mapping[code]
        if code.startswith("X"):
            try:
                return bytes.fromhex(code[1:]).decode("latin-1")
            except ValueError:
                return ""
        return ""

    return re.sub(f"{e}(.*?){e}", repl, value)


def escape(value: str, enc: Encoding = Encoding()) -> str:
    value = value or ""
    out = value.replace(enc.escape, f"{enc.escape}E{enc.escape}")
    for ch, code in ((enc.field, "F"), (enc.component, "S"), (enc.repeat, "R"), (enc.subcomponent, "T")):
        out = out.replace(ch, f"{enc.escape}{code}{enc.escape}")
    return out.replace("\r", f"{enc.escape}.br{enc.escape}").replace("\n", f"{enc.escape}.br{enc.escape}")


@dataclass
class Segment:
    id: str
    fields: list[str]
    enc: Encoding

    def raw(self, n: int) -> str:
        """Raw field ``n`` using HL7 numbering (MSH-1 is the field separator)."""
        if self.id == "MSH":
            if n == 1:
                return self.enc.field
            idx = n - 1
        else:
            idx = n
        return self.fields[idx] if 0 <= idx < len(self.fields) else ""

    def get(self, n: int, comp: int = 1, rep: int = 0) -> str:
        value = self.raw(n)
        if not value:
            return ""
        reps = value.split(self.enc.repeat) if self.id != "MSH" or n != 2 else [value]
        if rep >= len(reps):
            return ""
        comps = reps[rep].split(self.enc.component) if not (self.id == "MSH" and n == 2) else [reps[rep]]
        if comp - 1 >= len(comps):
            return ""
        return unescape(comps[comp - 1].split(self.enc.subcomponent)[0] if comp else comps[0], self.enc).strip()

    def components(self, n: int, rep: int = 0) -> list[str]:
        value = self.raw(n)
        if not value:
            return []
        reps = value.split(self.enc.repeat)
        if rep >= len(reps):
            return []
        return [unescape(c, self.enc).strip() for c in reps[rep].split(self.enc.component)]

    def repetitions(self, n: int) -> int:
        value = self.raw(n)
        return len(value.split(self.enc.repeat)) if value else 0


@dataclass
class Hl7Message:
    segments: list[Segment]
    enc: Encoding
    text: str

    def first(self, seg_id: str) -> Segment | None:
        return next((s for s in self.segments if s.id == seg_id), None)

    def all(self, seg_id: str) -> list[Segment]:
        return [s for s in self.segments if s.id == seg_id]

    @property
    def msh(self) -> Segment:
        seg = self.first("MSH")
        if seg is None:
            raise ValueError("message has no MSH segment")
        return seg

    @property
    def message_type(self) -> str:
        msh = self.msh
        return f"{msh.get(9, 1)}^{msh.get(9, 2)}".rstrip("^")

    @property
    def control_id(self) -> str:
        return self.msh.get(10)

    @property
    def version(self) -> str:
        return self.msh.get(12) or "2.3.1"


def parse(text: str) -> Hl7Message:
    text = text.replace("\r\n", "\r").replace("\n", "\r").strip("\r\x0b\x1c ")
    start = text.find("MSH")
    if start < 0:
        raise ValueError("no MSH segment found")
    text = text[start:]
    if len(text) < 8:
        raise ValueError("MSH segment too short")
    enc = Encoding(field=text[3])
    chars = text[4:8]
    if len(chars) >= 1:
        enc.component = chars[0]
    if len(chars) >= 2:
        enc.repeat = chars[1]
    if len(chars) >= 3:
        enc.escape = chars[2]
    if len(chars) >= 4 and chars[3] != enc.field:
        enc.subcomponent = chars[3]
    segments = []
    for line in text.split("\r"):
        line = line.strip("\x0b\x1c")
        if len(line) < 3:
            continue
        parts = line.split(enc.field)
        segments.append(Segment(id=parts[0][:3].upper(), fields=parts, enc=enc))
    return Hl7Message(segments=segments, enc=enc, text=text)


def hl7_datetime(value: str) -> str:
    value = (value or "").strip()
    digits = re.match(r"\d+", value)
    if not digits:
        return value
    d = digits.group(0)
    for fmt, length in (("%Y%m%d%H%M%S", 14), ("%Y%m%d%H%M", 12), ("%Y%m%d", 8)):
        if len(d) >= length:
            try:
                dt = datetime.strptime(d[:length], fmt)
            except ValueError:
                continue
            return dt.date().isoformat() if length == 8 else dt.isoformat()
    return value


def now_ts() -> str:
    return datetime.now().strftime("%Y%m%d%H%M%S")


def next_control_id(prefix: str = "LS") -> str:
    return f"{prefix}{datetime.now().strftime('%Y%m%d%H%M%S')}{next(_control) % 10000:04d}"


# ---------------------------------------------------------------------------
# HL7 -> canonical
# ---------------------------------------------------------------------------


@dataclass
class Hl7Options:
    specimen_id_sources: list[str] = field(default_factory=lambda: ["SPM-2", "OBR-3", "OBR-2", "ORC-3", "ORC-2"])
    patient_id_sources: list[str] = field(default_factory=lambda: ["PID-3", "PID-2", "PID-4"])
    test_code_component: int = 1  # OBX-3.1 is the identifier; some devices use .2 (text)
    include_encapsulated: bool = True
    qc_processing_ids: list[str] = field(default_factory=lambda: ["Q"])

    @classmethod
    def from_dict(cls, data: dict | None) -> Hl7Options:
        opts = cls()
        for k, v in (data or {}).items():
            if hasattr(opts, k) and v is not None:
                setattr(opts, k, v)
        return opts


def _lookup(msg: Hl7Message, ref: str, scope: list[Segment] | None = None) -> str:
    seg_id, _, num = ref.partition("-")
    comp = 1
    if "." in num:
        num, c = num.split(".", 1)
        comp = int(c)
    segs = [s for s in (scope or msg.segments) if s.id == seg_id]
    for s in segs:
        v = s.get(int(num), comp)
        if v:
            return v
    return ""


def _patient(pid: Segment | None, msg: Hl7Message, opts: Hl7Options) -> Patient:
    p = Patient()
    if pid is None:
        return p
    ids = []
    for ref in opts.patient_id_sources:
        seg_id, _, num = ref.partition("-")
        if seg_id != "PID":
            continue
        n = int(num.split(".")[0])
        for r in range(max(1, pid.repetitions(n))):
            v = pid.get(n, 1, r)
            if v and v not in ids:
                ids.append(v)
    if ids:
        p.id, p.alternate_ids = ids[0], ids[1:]
    name = pid.components(5)
    if name:
        p.name = PersonName(
            family=name[0] if len(name) > 0 else "",
            given=name[1] if len(name) > 1 else "",
            middle=name[2] if len(name) > 2 else "",
            suffix=name[3] if len(name) > 3 else "",
            prefix=name[4] if len(name) > 4 else "",
        )
    p.birth_date = hl7_datetime(pid.get(7))
    sex = pid.get(8).upper()[:1]
    p.sex = sex if sex in {"M", "F", "O", "U"} else ("U" if sex else "")
    pv1 = msg.first("PV1")
    if pv1 is not None:
        p.location = " ".join(c for c in pv1.components(3) if c)
        doc = pv1.components(7)
        if doc:
            p.physician = " ".join(c for c in doc[1:3] + doc[:1] if c)
    return p


def _observation(obx: Segment, opts: Hl7Options, seq: int) -> Observation | Attachment:
    vtype = obx.get(2).upper()
    ident = obx.components(3)
    code = ident[opts.test_code_component - 1] if len(ident) >= opts.test_code_component else ""
    code = code or next((c for c in ident if c), "")
    name = ident[1] if len(ident) > 1 else ""
    if vtype in ("ED", "RP") and opts.include_encapsulated:
        comps = obx.components(5)
        # ED: source ^ type ^ subtype ^ encoding ^ data
        data = comps[4] if len(comps) >= 5 else (comps[-1] if comps else "")
        subtype = (comps[2] if len(comps) >= 3 else "").lower() or "octet-stream"
        enc = (comps[3] if len(comps) >= 4 else "").lower()
        payload = data.encode("latin-1", errors="replace")
        if enc in ("base64", "b64", ""):
            try:
                payload = base64.b64decode(data, validate=False)
            except (ValueError, TypeError):
                pass
        mime = f"image/{subtype}" if subtype in ("png", "bmp", "jpeg", "jpg", "gif", "tiff") else f"application/{subtype}"
        return Attachment(name=code or name or f"obx{seq}", mime=mime, data=payload)
    value_reps = [obx.get(5, 1, r) for r in range(max(1, obx.repetitions(5)))]
    value = " ".join(v for v in value_reps if v)
    if vtype in ("CE", "CWE") and not value:
        value = obx.get(5, 2)
    flags = [obx.get(8, 1, r) for r in range(max(1, obx.repetitions(8)))]
    try:
        sequence = int(obx.get(1) or seq)
    except ValueError:
        sequence = seq
    return Observation(
        code=code,
        name=name,
        value=value,
        units=obx.get(6),
        reference_range=obx.get(7),
        flags=[f for f in flags if f],
        status=obx.get(11),
        observed_at=hl7_datetime(obx.get(14)),
        sequence=sequence,
        instrument=obx.get(18),
        value_type=vtype,
        raw_code=obx.raw(3),
    )


def to_lab_message(msg: Hl7Message, device_id: str, opts: Hl7Options) -> LabMessage:
    out = LabMessage(device_id=device_id, protocol="HL7")
    msh = msg.msh
    out.sender = " ".join(v for v in (msh.get(3), msh.get(4)) if v)
    out.control_id = msg.control_id
    out.meta.update({"message_type": msg.message_type, "version": msg.version, "processing_id": msh.get(11)})
    mtype = msh.get(9, 1).upper()
    is_qc = msh.get(11).upper()[:1] in [q.upper() for q in opts.qc_processing_ids]

    if mtype in ("QRY", "QBP"):
        out.message_type = "query"
        return out

    # Group: PID starts a patient; OBR/SPM starts a report; OBX/NTE attach to the current report.
    patient = Patient()
    report: Report | None = None
    group: list[Segment] = []

    def close() -> None:
        nonlocal report, group
        if report is not None:
            spec = report.specimen
            for ref in opts.specimen_id_sources:
                v = _lookup(msg, ref, group)
                if v:
                    spec.id = v
                    break
            if report.observations or report.attachments or spec.id:
                out.reports.append(report)
        report, group = None, []

    pid_seg: Segment | None = None
    for seg in msg.segments:
        if seg.id == "PID":
            close()
            pid_seg = seg
            patient = _patient(seg, msg, opts)
        elif seg.id == "OBR":
            if report is not None and (report.observations or any(g.id == "OBR" for g in group)):
                close()
            if report is None:
                report = Report(patient=patient, is_qc=is_qc)
            group.append(seg)
            s = report.specimen
            s.requested_tests = [c for c in [seg.get(4, 1)] if c]
            s.collected_at = hl7_datetime(seg.get(7))
            s.priority = seg.get(5)[:1]
            s.type = seg.get(15, 1)
            doc = seg.components(16)
            if doc and not patient.physician:
                patient.physician = " ".join(c for c in doc[1:3] + doc[:1] if c)
        elif seg.id in ("ORC", "SPM", "SAC", "TQ1", "INV"):
            if report is None:
                report = Report(patient=patient, is_qc=is_qc)
            group.append(seg)
            if seg.id == "SPM":
                report.specimen.type = report.specimen.type or seg.get(4, 1)
                report.specimen.collected_at = report.specimen.collected_at or hl7_datetime(seg.get(17))
        elif seg.id == "OBX":
            if report is None:
                report = Report(patient=patient, is_qc=is_qc)
            group.append(seg)
            item = _observation(seg, opts, len(report.observations) + 1)
            if isinstance(item, Attachment):
                report.attachments.append(item)
            else:
                report.observations.append(item)
        elif seg.id == "NTE":
            text = seg.get(3)
            if text:
                if report is not None and report.observations:
                    report.observations[-1].comments.append(text)
                elif report is not None:
                    report.comments.append(text)
                else:
                    out.warnings.append(f"note: {text}")
    close()
    if pid_seg is None and not out.reports:
        out.message_type = "status" if mtype not in ("ORU", "OUL") else "results"
    if mtype not in ("ORU", "OUL", "ORM", "OML", "MDM") and not out.reports:
        out.message_type = "event"
    return out


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def build_msh(msg_type: str, *, sending_app: str = "LabSync", sending_facility: str = "",
              receiving_app: str = "", receiving_facility: str = "", version: str = "2.5.1",
              control_id: str | None = None, processing_id: str = "P", enc: Encoding = Encoding()) -> str:
    f = enc.field
    return f.join([
        "MSH", enc.msh2, escape(sending_app), escape(sending_facility), escape(receiving_app),
        escape(receiving_facility), now_ts(), "", msg_type, control_id or next_control_id(), processing_id, version,
    ])


def build_ack(original: Hl7Message, code: str = "AA", text: str = "", msg_type: str | None = None) -> str:
    msh = original.msh
    trigger = msh.get(9, 2)
    mtype = msg_type or (f"ACK^{trigger}^ACK" if trigger else "ACK")
    header = build_msh(
        mtype,
        sending_app=msh.get(5) or "LabSync",
        sending_facility=msh.get(6),
        receiving_app=msh.get(3),
        receiving_facility=msh.get(4),
        version=original.version,
        processing_id=msh.get(11) or "P",
        enc=original.enc,
    )
    msa = original.enc.field.join(["MSA", code, original.control_id, escape(text)[:80]])
    return "\r".join([header, msa]) + "\r"


def report_to_oru(report: Report, *, device_name: str = "", sending_app: str = "LabSync",
                  sending_facility: str = "", receiving_app: str = "", receiving_facility: str = "",
                  version: str = "2.5.1") -> str:
    """Build an ORU^R01 for one report (for forwarding results to a LIS/HIS)."""
    p, s = report.patient, report.specimen
    segs = [build_msh("ORU^R01^ORU_R01", sending_app=sending_app, sending_facility=sending_facility,
                      receiving_app=receiving_app, receiving_facility=receiving_facility, version=version,
                      processing_id="Q" if report.is_qc else "P")]
    name = "^".join([escape(p.name.family), escape(p.name.given), escape(p.name.middle)]).rstrip("^")
    ids = "~".join(f"{escape(i)}^^^LAB^MR" for i in ([p.id] if p.id else []) + p.alternate_ids)
    segs.append("|".join(["PID", "1", "", ids, "", name, "", p.birth_date.replace("-", ""), p.sex]))
    segs.append("|".join(["ORC", "RE", escape(s.id), escape(s.id)]))
    test = s.requested_tests[0] if s.requested_tests else (report.observations[0].code if report.observations else "")
    segs.append("|".join(["OBR", "1", escape(s.id), escape(s.id), f"{escape(test)}^^L", s.priority,
                          "", s.collected_at.replace("-", "").replace(":", "").replace("T", "")[:14],
                          "", "", "", "", "", "", "", s.type, "", "", "", "", "", "", "", "", "", "F"]))
    for i, o in enumerate(report.observations, start=1):
        vtype = "NM" if o.numeric_value is not None and not o.value.strip().startswith(("<", ">")) else "ST"
        obs_ts = o.observed_at.replace("-", "").replace(":", "").replace("T", "")[:14]
        segs.append("|".join([
            "OBX", str(i), vtype, f"{escape(o.code)}^{escape(o.name)}^L", "", escape(o.value), escape(o.units),
            escape(o.reference_range), "~".join(escape(f) for f in o.flags), "", "", o.status or "F", "", "",
            obs_ts, "", "", escape(o.instrument or device_name),
        ]))
        for c in o.comments:
            segs.append(f"NTE|1|L|{escape(c)}")
    for c in report.comments:
        segs.append(f"NTE|1|L|{escape(c)}")
    return "\r".join(segs) + "\r"


def build_qck(query: Hl7Message, found: bool) -> str:
    """QCK^Q02 response used by Mindray and other HL7 2.3.1 analyzers."""
    header = build_msh("QCK^Q02", sending_app=query.msh.get(5) or "LabSync", receiving_app=query.msh.get(3),
                       receiving_facility=query.msh.get(4), version=query.version, enc=query.enc)
    return "\r".join([header, f"MSA|AA|{query.control_id}|Message accepted|||0", "ERR|0",
                      f"QAK|SR|{'OK' if found else 'NF'}"]) + "\r"


def build_mindray_dsr(query: Hl7Message, order: OrderRequest) -> str:
    """DSR^Q03 order download in the layout documented by Mindray BS/CL series host interfaces."""
    qrd = query.first("QRD")
    qrf = query.first("QRF")
    p = order.patient
    header = build_msh("DSR^Q03", sending_app=query.msh.get(5) or "LabSync", receiving_app=query.msh.get(3),
                       version=query.version, enc=query.enc)
    segs = [header, f"MSA|AA|{query.control_id}|Message accepted|||0", "ERR|0", "QAK|SR|OK"]
    if qrd is not None:
        segs.append("|".join(qrd.fields))
    if qrf is not None:
        segs.append("|".join(qrf.fields))
    dsp = [
        p.id, "", p.name.full, p.birth_date.replace("-", ""), p.sex, "", "", "", "", "", "", "", "", "", "", "",
        "", "", "", "", order.specimen_id, "", order.collected_at.replace("-", "").replace(":", "").replace("T", ""),
        "Y" if order.priority.upper() == "S" else "N", "", order.specimen_type or "serum", "", "",
    ]
    for i, v in enumerate(dsp, start=1):
        segs.append(f"DSP|{i}||{escape(v)}|||")
    n = len(dsp)
    for j, t in enumerate(order.tests, start=1):
        segs.append(f"DSP|{n + j}||{escape(t)}^^^|||")
    segs.append("DSC||")
    return "\r".join(segs) + "\r"
