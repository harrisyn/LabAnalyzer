from __future__ import annotations

import base64

from labsync.devices.catalog import MINDRAY_HL7
from labsync.models import OrderRequest, Patient, PersonName, Report
from labsync.protocols.hl7 import message as hl7
from labsync.protocols.hl7.handler import Hl7Handler, mllp_wrap
from labsync.protocols.poct1a import Poct1aHandler
from labsync.protocols.vendor import BeckmanAuHandler, DimensionHandler, FramedTextHandler

from conftest import connect

MINDRAY_ORU = "\r".join([
    "MSH|^~\\&|Mindray|BS-430|||20240301101010||ORU^R01|42|P|2.3.1||||0||ASCII|||",
    "PID|1||PAT77^^^^MR||OKAFOR^ADA^N||19850704|F",
    "PV1|1|O|WARD3^^BED2||||1234^HOUSE^GREG",
    "OBR|1|S100|S100|^|N|20240301100000|20240301100500|||||||20240301100000|serum",
    "OBX|1|NM|GLU^Glucose^LN||7.8|mmol/L|3.9-6.1|H|||F||7.8|20240301101000||",
    "NTE|1||fasting",
    "OBX|2|NM|CREA^Creatinine^LN||88|umol/L|53-115|N|||F||88|20240301101000||",
    "OBX|3|ST|COMMENT^Remark||Lipemic \\T\\ hemolysed||||||F",
]) + "\r"


async def test_mindray_oru_parsed_and_acked():
    h, link, msgs, _ = await connect(Hl7Handler, MINDRAY_HL7)
    data = mllp_wrap(MINDRAY_ORU)
    await h.data_received(data[:30])
    await h.data_received(data[30:])
    (msg,) = msgs
    assert msg.control_id == "42" and msg.message_type == "results"
    (rep,) = msg.reports
    assert rep.patient.id == "PAT77" and rep.patient.name.family == "OKAFOR"
    assert rep.patient.birth_date == "1985-07-04" and rep.patient.sex == "F"
    assert rep.patient.physician == "HOUSE GREG 1234"
    assert rep.specimen.id == "S100" and rep.specimen.type == "serum"
    glu, crea, comment = rep.observations
    assert glu.code == "GLU" and glu.name == "Glucose" and glu.flags == ["H"] and glu.comments == ["fasting"]
    assert crea.numeric_value == 88
    assert comment.value == "Lipemic & hemolysed"
    ack = link.take()
    assert ack.startswith(b"\x0b") and ack.endswith(b"\x1c\r")
    parsed = hl7.parse(ack.decode())
    assert parsed.msh.get(9, 1) == "ACK"
    assert parsed.first("MSA").get(1) == "AA" and parsed.first("MSA").get(2) == "42"
    assert parsed.msh.get(3) == "" or parsed.msh.get(5) == "Mindray"


async def test_two_messages_in_one_chunk_and_bare_msh():
    h, link, msgs, _ = await connect(Hl7Handler)
    await h.data_received(mllp_wrap(MINDRAY_ORU) + mllp_wrap(MINDRAY_ORU.replace("|42|", "|43|")))
    assert [m.control_id for m in msgs] == ["42", "43"]
    h2, _, msgs2, _ = await connect(Hl7Handler)
    await h2.data_received(MINDRAY_ORU.encode())
    h2.last_data = 0
    await h2.tick()
    assert len(msgs2) == 1


async def test_encapsulated_histogram_kept_as_attachment():
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 20
    oru = MINDRAY_ORU.replace("OBX|3|ST|COMMENT^Remark||Lipemic \\T\\ hemolysed||||||F",
                              f"OBX|3|ED|WBCHist^WBC Histogram||^Image^PNG^Base64^{base64.b64encode(png).decode()}||||||F")
    h, link, msgs, _ = await connect(Hl7Handler)
    await h.data_received(mllp_wrap(oru))
    rep = msgs[0].reports[0]
    assert len(rep.observations) == 2
    assert rep.attachments[0].data == png and rep.attachments[0].mime == "image/png"


async def test_invalid_message_is_kept():
    h, link, msgs, _ = await connect(Hl7Handler)
    await h.data_received(b"\x0bgarbage\x1c\r")
    assert msgs[0].message_type == "unknown" and msgs[0].raw == b"garbage"


class OneOrder:
    async def lookup(self, query, device_id):
        return [OrderRequest(specimen_id=query.specimen_ids[0], tests=["GLU", "CREA"],
                             patient=Patient(id="P1", name=PersonName(family="DOE", given="J")))]


async def test_mindray_query_gets_qck_and_dsr():
    qry = "\r".join(["MSH|^~\\&|Mindray|BS-430|||20240301||QRY^Q02|7|P|2.3.1||||||ASCII|||",
                     "QRD|20240301|R|D|1|||RD|BC123|OTH|||T", "QRF|BS-430|||||RCT|COR|ALL||"]) + "\r"
    h, link, msgs, outbound = await connect(Hl7Handler, MINDRAY_HL7, orders=OneOrder())
    await h.data_received(mllp_wrap(qry))
    assert msgs[0].message_type == "query" and msgs[0].queries[0].specimen_ids == ["BC123"]
    out = link.take().split(b"\x1c\r")
    qck = hl7.parse(out[0].decode())
    dsr = hl7.parse(out[1].decode())
    assert qck.message_type == "QCK^Q02" and qck.first("QAK").get(2) == "OK"
    assert dsr.message_type == "DSR^Q03"
    dsps = dsr.all("DSP")
    assert any(d.get(3) == "BC123" for d in dsps)
    assert any(d.get(3) == "GLU" for d in dsps)
    assert outbound[0].meta["orders"] == 1


async def test_mindray_query_no_orders_is_nf():
    qry = "MSH|^~\\&|Mindray|BS|||20240301||QRY^Q02|8|P|2.3.1\rQRD|20240301|R|D|1|||RD|X9|OTH\r"
    h, link, msgs, _ = await connect(Hl7Handler, MINDRAY_HL7)
    await h.data_received(mllp_wrap(qry))
    qck = hl7.parse(link.take().decode())
    assert qck.first("QAK").get(2) == "NF"


def test_oru_builder_round_trip():
    from labsync.protocols.hl7.message import Hl7Options, parse, report_to_oru, to_lab_message

    rep = Report()
    rep.patient = Patient(id="P|1", name=PersonName(family="O^NEIL", given="Ann"), birth_date="1990-01-02", sex="F")
    rep.specimen.id = "S-1"
    from labsync.models import Observation

    rep.observations = [Observation(code="K", value="5.9", units="mmol/L", flags=["H"], reference_range="3.5-5.1")]
    text = report_to_oru(rep, device_name="Analyzer")
    msg = to_lab_message(parse(text), "d", Hl7Options())
    back = msg.reports[0]
    assert back.patient.id == "P|1" and back.patient.name.family == "O^NEIL"
    assert back.specimen.id == "S-1"
    assert back.observations[0].value == "5.9" and back.observations[0].flags == ["H"]


# --------------------------------------------------------------------------- POCT1-A


def _doc(tag: str, cid: int, inner: str = "") -> bytes:
    return (f'<?xml version="1.0"?><{tag}><HDR><HDR.control_id V="{cid}"/><HDR.version_id V="POCT1"/></HDR>'
            f"{inner}</{tag}>").encode()


async def test_poct1a_conversation():
    h, link, msgs, _ = await connect(Poct1aHandler)
    hel = _doc("HEL.R01", 1, '<DEV><DEV.device_id V="ISTAT1"/><DEV.vendor_id V="ABBOTT"/></DEV>')
    await h.data_received(hel[:20])
    await h.data_received(hel[20:])
    assert b"<ACK.ack_control_id V=\"1\"/>" in link.take()
    await h.data_received(_doc("DST.R01", 2, '<DST><DST.new_observations_qty V="1"/></DST>'))
    out = link.take()
    assert b'ack_control_id V="2"' in out and b"<REQ.R01>" in out and b'V="ROBS"' in out
    obs = _doc("OBS.R01", 3, '<SVC><SVC.role_cd V="OBS"/><SVC.observation_dttm V="2024-03-01T10:00:00"/>'
                             '<PT><PT.patient_id V="P5"/><OBS><OBS.observation_id V="Glu"/>'
                             '<OBS.value V="9.1" U="mmol/L"/><OBS.interpretation_cd V="H"/></OBS></PT>'
                             '<OPR><OPR.operator_id V="nurse1"/></OPR></SVC>')
    await h.data_received(obs + _doc("EOT.R01", 4, '<EOT><EOT.topic_cd V="OBS"/></EOT>'))
    out = link.take()
    assert b'ack_control_id V="3"' in out and b'ack_control_id V="4"' in out and b"<END.R01>" in out
    results = [m for m in msgs if m.reports]
    (rep,) = results[0].reports
    assert rep.patient.id == "P5" and rep.specimen.id == "P5"
    assert rep.observations[0].code == "Glu" and rep.observations[0].units == "mmol/L"
    assert rep.observations[0].flags == ["H"] and rep.observations[0].comments == ["operator: nurse1"]
    assert msgs[0].meta["device"]["vendor"] == "ABBOTT"


async def test_poct1a_rejects_entities():
    h, link, msgs, _ = await connect(Poct1aHandler)
    evil = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY e "boom">]><HEL.R01><HDR>&e;</HDR></HEL.R01>'
    await h.data_received(evil)
    assert msgs[0].message_type == "unknown"


# --------------------------------------------------------------------------- vendor


async def test_beckman_au_fixed_width():
    h, link, msgs, _ = await connect(BeckmanAuHandler, {"test_map": {"001": "GLU"}})
    header = "D " + "0012" + "03" + " " + "0045" + "S000123456" + "    " + "E"
    tests = "001" + "  5.50" + "H " + "002" + " 120.0" + "  "
    await h.data_received(b"\x02DB\x03")
    assert link.take() == b"\x06"
    await h.data_received(b"\x02" + (header + tests).encode() + b"\x03")
    await h.data_received(b"\x02DE\x03")
    (msg,) = msgs
    (rep,) = msg.reports
    assert rep.specimen.id == "S000123456" and rep.specimen.rack == "0012" and rep.specimen.position == "03"
    assert [(o.code, o.value, o.flags) for o in rep.observations] == [("GLU", "5.50", ["H"]), ("002", "120.0", [])]


async def test_dimension_poll_and_result():
    h, link, msgs, _ = await connect(DimensionHandler)

    def frame(fields):
        body = "\x1c".join(fields) + "\x1c"
        return b"\x02" + (body + DimensionHandler._checksum(body)).encode("latin-1") + b"\x03"

    await h.data_received(frame(["P", "1", "DIM01"]))
    out = link.take()
    assert out.startswith(b"\x06\x02N\x1c")
    fields = ["R", "0", "PAT1", "SAMP9", "1", "", "", "", "", "", "2", "GLU", "5.4", "mmol/L", "", "CREA", "77", "umol/L", ""]
    await h.data_received(frame(fields))
    (msg,) = msgs
    rep = msg.reports[0]
    assert rep.specimen.id == "SAMP9" and rep.patient.id == "PAT1"
    assert [(o.code, o.value, o.units) for o in rep.observations] == [("GLU", "5.4", "mmol/L"), ("CREA", "77", "umol/L")]
    assert b"\x02M\x1cA\x1c" in link.take()


async def test_generic_text_capture_with_regex():
    opts = {"framing": "line", "result_regex": r"^(?P<code>[A-Z]{2,5})\s+(?P<value>[\d.]+)\s*(?P<units>\S+)?",
            "specimen_regex": r"ID:\s*(?P<id>\S+)", "line_message_end_regex": "^END"}
    h, link, msgs, _ = await connect(FramedTextHandler, opts)
    await h.data_received(b"ID: 777\r\nHGB 13.1 g/dL\r\nWBC 6.2 10^9/L\r\nEND\r\n")
    (msg,) = msgs
    rep = msg.reports[0]
    assert rep.specimen.id == "777"
    assert [(o.code, o.value, o.units) for o in rep.observations] == [("HGB", "13.1", "g/dL"), ("WBC", "6.2", "10^9/L")]
