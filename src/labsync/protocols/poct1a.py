"""CLSI POCT1-A2 device messaging layer (observation reviewer / data manager side).

Conversation implemented (device -> manager):

    HEL.R01  -> ACK.R01
    DST.R01  -> ACK.R01, then REQ.R01 (ROBS: send pending observations) when enabled
    OBS.R01 / OBS.R02  -> ACK.R01 (patient / non-patient observations)
    EOT.R01  -> ACK.R01, then END.R01 to close the conversation
    KPA.R01  -> keep-alive, no ACK required (ACKed anyway when the device asks)

Messages are XML documents sent back-to-back over TCP. Used by Abbott i-STAT,
Radiometer ABL/AQT, Siemens RAPIDPoint, Roche cobas b 101/b 221/Accu-Chek
Inform II, Nova StatStrip and many other point-of-care devices.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from itertools import count
from xml.etree.ElementTree import Element

from defusedxml import ElementTree as SafeET

from ..models import LabMessage, Observation, Patient, Report
from .base import ProtocolHandler, SessionContext

_ROOT = re.compile(rb"<([A-Z]{3}\.R\d{2})\b")
_ids = count(1)


def _v(el: Element | None, path: str, attr: str = "V") -> str:
    if el is None:
        return ""
    node = el.find(path)
    return (node.get(attr) or "").strip() if node is not None else ""


def _ts() -> str:
    return datetime.now(UTC).astimezone().isoformat(timespec="seconds")


def _hdr(control_id: str) -> str:
    return (f"<HDR><HDR.control_id V=\"{control_id}\"/><HDR.version_id V=\"POCT1\"/>"
            f"<HDR.creation_dttm V=\"{_ts()}\"/></HDR>")


def build_ack(ack_control_id: str, ok: bool = True, note: str = "") -> bytes:
    cid = f"LS{next(_ids)}"
    note_xml = f"<ACK.note_txt V=\"{note}\"/>" if note else ""
    return (f"<?xml version=\"1.0\" encoding=\"UTF-8\"?><ACK.R01>{_hdr(cid)}<ACK><ACK.type_cd V=\"{'AA' if ok else 'AE'}\"/>"
            f"<ACK.ack_control_id V=\"{ack_control_id}\"/>{note_xml}</ACK></ACK.R01>").encode()


def build_req(request_cd: str = "ROBS") -> bytes:
    cid = f"LS{next(_ids)}"
    return (f"<?xml version=\"1.0\" encoding=\"UTF-8\"?><REQ.R01>{_hdr(cid)}<REQ><REQ.request_cd V=\"{request_cd}\"/>"
            f"</REQ></REQ.R01>").encode()


def build_end() -> bytes:
    cid = f"LS{next(_ids)}"
    return (f"<?xml version=\"1.0\" encoding=\"UTF-8\"?><END.R01>{_hdr(cid)}<TRM><TRM.reason_cd V=\"NML\"/></TRM>"
            f"</END.R01>").encode()


def parse_observations(root: Element, device_id: str) -> LabMessage:
    msg = LabMessage(device_id=device_id, protocol="POCT1-A", message_type="results")
    msg.control_id = _v(root, "HDR/HDR.control_id")
    non_patient = root.tag == "OBS.R02"
    for svc in root.iter("SVC"):
        report = Report(is_qc=non_patient)
        pt = svc.find("PT")
        if pt is not None:
            p = Patient(id=_v(pt, "PT.patient_id"))
            name = pt.find("PT.name")
            if name is not None:
                p.name.family = _v(name, "NM.family")
                p.name.given = _v(name, "NM.given")
            p.birth_date = _v(pt, "PT.birth_date")[:10]
            p.sex = _v(pt, "PT.gender_cd")[:1].upper()
            report.patient = p
        report.specimen.id = _v(svc, "SVC.specimen_id") or _v(svc, "SVC.sample_id") or _v(svc, "PT/PT.patient_id")
        report.specimen.type = _v(svc, "SVC.specimen_type_cd") or _v(svc, "SPC/SPC.type_cd")
        observed = _v(svc, "SVC.observation_dttm")
        report.specimen.collected_at = observed
        role = _v(svc, "SVC.role_cd")
        if role and role.upper() not in ("OBS", "PAT"):
            report.is_qc = True
            report.qc_info = {"role": role}
        operator = _v(svc, "OPR/OPR.operator_id")
        obs_nodes = list(svc.iter("OBS"))
        for i, obs in enumerate(obs_nodes, start=1):
            value = obs.find("OBS.value")
            o = Observation(
                code=_v(obs, "OBS.observation_id"),
                name=_v(obs, "OBS.observation_id", "DN") or _v(obs, "OBS.observation_id", "SN"),
                value=(value.get("V") or "") if value is not None else "",
                units=(value.get("U") or "") if value is not None else "",
                reference_range=_v(obs, "OBS.normal_lo-hi_limit") or _v(obs, "OBS.reference_range_txt"),
                flags=[f for f in (_v(obs, "OBS.interpretation_cd"),) if f],
                status=_v(obs, "OBS.status_cd") or "F",
                observed_at=observed,
                sequence=i,
                instrument=_v(root, "DEV/DEV.device_id"),
            )
            if operator:
                o.comments.append(f"operator: {operator}")
            report.observations.append(o)
        for nte in svc.iter("NTE"):
            text = _v(nte, "NTE.text")
            if text:
                report.comments.append(text)
        if report.observations:
            msg.reports.append(report)
    return msg


class Poct1aHandler(ProtocolHandler):
    protocol_name = "POCT1-A"

    def __init__(self, ctx: SessionContext):
        super().__init__(ctx)
        self.request_observations = bool(ctx.opt("request_observations", True))
        self.send_end = bool(ctx.opt("send_end", True))
        self.buf = bytearray()

    def _next_document(self) -> bytes | None:
        m = _ROOT.search(self.buf)
        if m is None:
            if len(self.buf) > 8 * 1024 * 1024:
                self.buf.clear()
            return None
        tag = m.group(1)
        close = self.buf.find(b"</" + tag + b">", m.end())
        if close < 0:
            return None
        start = self.buf.rfind(b"<?xml", 0, m.start())
        start = start if start >= 0 else m.start()
        end = close + len(tag) + 3
        doc = bytes(self.buf[start:end])
        del self.buf[:end]
        return doc

    async def data_received(self, data: bytes) -> None:
        self.buf.extend(data)
        while True:
            doc = self._next_document()
            if doc is None:
                return
            await self._handle(doc)

    async def _handle(self, doc: bytes) -> None:
        try:
            root = SafeET.fromstring(doc)
        except Exception as exc:
            self.log.warning("[%s] invalid POCT1-A XML: %s", self.ctx.device_name, exc)
            await self.emit(LabMessage(device_id=self.ctx.device_id, protocol=self.protocol_name, raw=doc,
                                       message_type="unknown", warnings=[f"invalid XML: {exc}"]))
            return
        tag = root.tag
        control_id = _v(root, "HDR/HDR.control_id")
        if tag == "ACK.R01":
            return
        if tag in ("OBS.R01", "OBS.R02"):
            msg = parse_observations(root, self.ctx.device_id)
            msg.raw = doc
            await self.emit(msg)
        else:
            msg = LabMessage(device_id=self.ctx.device_id, protocol=self.protocol_name, raw=doc,
                             message_type="event", control_id=control_id)
            msg.meta["poct1a_type"] = tag
            if tag == "HEL.R01":
                msg.sender = _v(root, "DEV/DEV.device_id") or _v(root, "DEV/DEV.vendor_id")
                msg.meta["device"] = {
                    "vendor": _v(root, "DEV/DEV.vendor_id"), "model": _v(root, "DEV/DEV.model_id"),
                    "serial": _v(root, "DEV/DEV.serial_id"), "software": _v(root, "DEV/DEV.sw_version"),
                }
            elif tag == "DST.R01":
                msg.message_type = "status"
                msg.meta["new_observations"] = _v(root, "DST/DST.new_observations_qty")
            await self.emit(msg)
        if tag != "KPA.R01" and control_id:
            await self.write(build_ack(control_id))
        if tag == "DST.R01" and self.request_observations:
            pending = _v(root, "DST/DST.new_observations_qty")
            if pending in ("", None) or pending != "0":
                await self.write(build_req("ROBS"))
        elif tag == "EOT.R01" and self.send_end:
            await self.write(build_end())
