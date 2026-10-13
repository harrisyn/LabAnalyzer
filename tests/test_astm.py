from __future__ import annotations

import asyncio

import pytest

from labsync.devices.catalog import ROCHE_ASTM, SYSMEX_ASTM
from labsync.models import OrderRequest, Patient, PersonName
from labsync.protocols.astm.framing import (
    ACK,
    ENQ,
    EOT,
    NAK,
    build_frame,
    build_frames,
    checksum,
    try_parse_frame,
)
from labsync.protocols.astm.handler import AstmHandler
from labsync.protocols.astm.records import AstmMessageBuilder, AstmOptions, Delimiters, split_record, unescape

from conftest import connect

SYSMEX = [
    "H|\\^&|||XN-550^00-18^11001^^^^12345678||||||||E1394-97",
    "P|1|||1418626|^FAABAR^AHITOPHEL||19830101|M|||||^||||||||||||^^^",
    "O|1||^^                475371^M|^^^^WBC\\^^^^RBC\\^^^^HGB|||||||N||||||||||||||F",
    "R|1|^^^^WBC^1|7.43|10*3/uL||N||||||20240101101010",
    "R|2|^^^^RBC^1|4.69|10*6/uL||L||||||20240101101010",
    "C|1||Sample clotted?|G",
    "R|3|^^^^HGB^1|13.2|g/dL||H||||||20240101101010",
    "L|1|N",
]


def transmission(records: list[str]) -> bytes:
    return bytes([ENQ]) + b"".join(build_frames(records)) + bytes([EOT])


# --------------------------------------------------------------------------- framing


def test_checksum_excludes_stx_and_includes_etx():
    body = b"1H|\\^&\r\x03"
    assert checksum(body) == f"{sum(body) % 256:02X}"
    frame = build_frame(1, b"H|\\^&\r", final=True)
    assert frame[0] == 0x02 and frame.endswith(b"\r\n")
    parsed = try_parse_frame(frame)
    assert parsed is not None and parsed.checksum_ok and parsed.final and parsed.number == 1


def test_long_records_are_split_with_etb():
    long = "R|1|^^^X|" + "9" * 600
    frames = build_frames([long])
    assert len(frames) == 3
    assert all(len(f) <= 247 for f in frames)
    parsed = [try_parse_frame(f) for f in frames]
    assert [p.final for p in parsed] == [False, False, True]
    assert [p.number for p in parsed] == [1, 2, 3]


def test_frame_numbers_wrap_modulo_8():
    frames = build_frames([f"R|{i}|^^^T|1" for i in range(10)])
    assert [try_parse_frame(f).number for f in frames] == [1, 2, 3, 4, 5, 6, 7, 0, 1, 2]


def test_incomplete_frame_needs_more_data():
    frame = build_frame(1, b"H|\\^&\r", final=True)
    assert try_parse_frame(frame[:-4]) is None


# --------------------------------------------------------------------------- link layer


async def test_full_transmission_byte_by_byte():
    h, link, msgs, _ = await connect(AstmHandler, SYSMEX_ASTM)
    for b in transmission(SYSMEX):
        await h.data_received(bytes([b]))
    assert link.take() == bytes([ACK]) * (1 + len(SYSMEX))
    assert len(msgs) == 1
    msg = msgs[0]
    assert msg.sender.startswith("XN-550")
    assert msg.raw.startswith(bytes([ENQ])) and msg.raw.endswith(bytes([EOT]))
    (report,) = msg.reports
    assert report.patient.id == "1418626"
    assert report.patient.name.family == "FAABAR" and report.patient.name.given == "AHITOPHEL"
    assert report.patient.birth_date == "1983-01-01"
    assert report.specimen.id == "475371"
    assert [o.code for o in report.observations] == ["WBC", "RBC", "HGB"]
    assert report.observations[1].flags == ["L"]
    assert report.observations[1].comments == ["Sample clotted?"]
    assert report.observations[0].observed_at == "2024-01-01T10:10:10"
    assert report.observations[0].numeric_value == pytest.approx(7.43)


async def test_coalesced_chunks():
    h, link, msgs, _ = await connect(AstmHandler, SYSMEX_ASTM)
    data = transmission(SYSMEX) + transmission(SYSMEX)
    await h.data_received(data)
    assert len(msgs) == 2


async def test_bad_checksum_is_nakked_then_retransmission_accepted():
    h, link, msgs, _ = await connect(AstmHandler)
    frames = build_frames(SYSMEX)
    await h.data_received(bytes([ENQ]))
    await h.data_received(frames[0])
    corrupted = bytearray(frames[1])
    corrupted[5] ^= 0x01
    await h.data_received(bytes(corrupted))
    assert link.take() == bytes([ACK, ACK, NAK])
    for f in frames[1:]:
        await h.data_received(f)
    await h.data_received(bytes([EOT]))
    assert len(msgs) == 1 and len(msgs[0].reports[0].observations) == 3


async def test_duplicate_frame_is_acked_but_not_duplicated():
    h, link, msgs, _ = await connect(AstmHandler)
    frames = build_frames(SYSMEX)
    await h.data_received(bytes([ENQ]) + frames[0] + frames[1] + frames[1])
    for f in frames[2:]:
        await h.data_received(f)
    await h.data_received(bytes([EOT]))
    assert len(msgs[0].reports[0].observations) == 3


async def test_lenient_checksum_accepts():
    h, link, msgs, _ = await connect(AstmHandler, {"checksum": "lenient"})
    frames = [bytearray(f) for f in build_frames(SYSMEX)]
    frames[3][-4] = ord("0")  # damage checksum digit
    frames[3][-3] = ord("0")
    await h.data_received(bytes([ENQ]) + b"".join(frames) + bytes([EOT]))
    assert NAK not in link.take()
    assert len(msgs) == 1


async def test_frames_without_crlf_trailer():
    h, link, msgs, _ = await connect(AstmHandler)
    frames = [f[:-2] for f in build_frames(SYSMEX)]
    await h.data_received(bytes([ENQ]) + b"".join(frames) + bytes([EOT]))
    assert len(msgs) == 1


async def test_unframed_records_over_tcp():
    h, link, msgs, _ = await connect(AstmHandler, SYSMEX_ASTM)
    data = ("\r".join(SYSMEX) + "\r").encode()
    await h.data_received(data[:50])
    assert not msgs
    await h.data_received(data[50:] + data)
    assert len(msgs) == 2
    assert msgs[0].reports[0].specimen.id == "475371"


async def test_connection_lost_mid_transmission_keeps_records():
    h, link, msgs, _ = await connect(AstmHandler)
    frames = build_frames(SYSMEX)
    await h.data_received(bytes([ENQ]) + b"".join(frames[:5]))
    await h.connection_lost()
    assert len(msgs) == 1
    assert len(msgs[0].reports[0].observations) == 2
    assert any("terminator" in w for w in msgs[0].warnings)


async def test_multiple_records_in_one_frame():
    h, link, msgs, _ = await connect(AstmHandler)
    text = ("\r".join(SYSMEX) + "\r").encode()
    await h.data_received(bytes([ENQ]) + build_frame(1, text[:200], False) + build_frame(2, text[200:], True) + bytes([EOT]))
    assert len(msgs) == 1 and len(msgs[0].reports[0].observations) == 3


# --------------------------------------------------------------------------- records


def test_custom_delimiters_and_escapes():
    rec = split_record("H!@#$!!!SENDER", Delimiters())
    assert rec.d.field == "!" and rec.d.repeat == "@" and rec.d.component == "#" and rec.d.escape == "$"
    assert rec.text(5) == "SENDER"
    assert unescape("a&F&b&S&c&R&d&E&e", Delimiters()) == "a|b^c\\d&e"


def test_roche_cobas_test_codes_and_query():
    records = [
        "H|\\^&|||H7600^1||||||||1",
        "P|1|||||||U",
        "O|1|SAMPLE01|0^50001^001^^S1^SC|^^^8710/\\^^^8510/|R||||||N||||1||||||||||F",
        "R|1|^^^8710/|135|mmol/L||N||F||||20240501101010",
        "R|2|^^^8510/|4.1|mmol/L||N||F||||20240501101010",
        "L|1|N",
    ]
    b = AstmMessageBuilder("d", "ASTM", AstmOptions.from_dict(ROCHE_ASTM["astm"]))
    for r in records:
        b.feed(r)
    (msg,) = b.finish()
    rep = msg.reports[0]
    assert rep.specimen.id == "SAMPLE01"
    assert [o.code for o in rep.observations] == ["8710", "8510"]
    assert rep.specimen.requested_tests == ["8710", "8510"]

    q = AstmMessageBuilder("d", "ASTM", AstmOptions.from_dict(ROCHE_ASTM["astm"]))
    for r in ["H|\\^&|||H7600^1", "Q|1|^^SAMPLE01^0^50001^001^^S1^SC||ALL||||||||O", "L|1|N"]:
        q.feed(r)
    (qmsg,) = q.finish()
    assert qmsg.message_type == "query"
    assert qmsg.queries[0].specimen_ids == ["SAMPLE01"]


def test_standard_lis2a2_message_with_two_patients():
    records = [
        "H|\\^&|||Analyzer|||||||P|LIS2-A2|20240101120000",
        "P|1||PAT1||SMITH^JOHN^Q||19700101|M",
        "O|1|SPEC1||^^^GLU|R",
        "R|1|^^^GLU|5.5|mmol/L|3.9-6.1|N||F",
        "P|2||PAT2||DOE^JANE||19800202|F",
        "O|1|SPEC2||^^^K|S",
        "R|1|^^^K|6.1|mmol/L|3.5-5.1|H||F",
        "L|1|N",
    ]
    b = AstmMessageBuilder("d", "ASTM", AstmOptions())
    for r in records:
        b.feed(r)
    (msg,) = b.finish()
    assert [r.patient.id for r in msg.reports] == ["PAT1", "PAT2"]
    assert [r.specimen.id for r in msg.reports] == ["SPEC1", "SPEC2"]
    assert msg.reports[0].patient.name.middle == "Q"
    assert msg.reports[1].observations[0].abnormal
    assert msg.reports[1].observations[0].reference_range == "3.5-5.1"
    assert msg.reports[1].specimen.priority == "S"


def test_qc_detection():
    b = AstmMessageBuilder("d", "ASTM", AstmOptions())
    for r in ["H|\\^&|||A", "P|1", "O|1|QC-LOT1||^^^GLU|R||||||Q", "R|1|^^^GLU|5.0|mmol/L", "L|1|N"]:
        b.feed(r)
    (msg,) = b.finish()
    assert msg.reports[0].is_qc


# --------------------------------------------------------------------------- host query -> order download


class Orders:
    def __init__(self, orders):
        self.orders = orders
        self.queries = []

    async def lookup(self, query, device_id):
        self.queries.append(query)
        return self.orders


async def _play_instrument(h, link, timeout=5.0) -> list[str]:
    """Act as the instrument receiving the host's transmission; return received record texts."""
    records: list[str] = []
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    buf = bytearray()
    while loop.time() < end:
        await asyncio.sleep(0.01)
        buf.extend(link.take())
        while buf:
            if buf[0] == ENQ:
                del buf[0]
                await h.data_received(bytes([ACK]))
            elif buf[0] == 0x02:
                frame = try_parse_frame(buf)
                if frame is None:
                    break
                del buf[: frame.consumed]
                assert frame.checksum_ok
                records.append(frame.text.decode().strip("\r"))
                await h.data_received(bytes([ACK]))
            elif buf[0] == EOT:
                return records
            else:
                del buf[0]
    raise AssertionError("host did not finish its transmission")


async def test_query_answered_with_orders_sysmex():
    order = OrderRequest(specimen_id="1000000001", tests=["WBC", "RBC"],
                         patient=Patient(id="P9", name=PersonName(family="DOE", given="JANE"), birth_date="1990-05-06", sex="F"))
    src = Orders([order])
    h, link, msgs, outbound = await connect(AstmHandler, SYSMEX_ASTM, orders=src)
    query = ["H|\\^&|||XN-550^00-18^11001||||||||E1394-97", "Q|1|2^1^          1000000001^B||^^^^ALL||||||||A", "L|1|N"]
    await h.data_received(transmission(query))
    link.take()
    records = await _play_instrument(h, link)
    assert src.queries[0].specimen_ids == ["1000000001"]
    assert records[0].startswith("H|\\^&")
    assert any(r.startswith("P|1||P9||DOE^JANE||19900506|F") for r in records)
    o = next(r for r in records if r.startswith("O|"))
    assert "2^1^          1000000001^B" in o  # echoed for Sysmex
    assert "^^^^WBC\\^^^^RBC" in o
    assert records[-1].startswith("L|1|N")
    assert outbound and outbound[0].meta["delivered"] is True


async def test_query_without_orders_sends_no_information():
    h, link, msgs, _ = await connect(AstmHandler, orders=Orders([]))
    await h.data_received(transmission(["H|\\^&|||A", "Q|1|^S1||^^^ALL", "L|1|N"]))
    link.take()
    records = await _play_instrument(h, link)
    assert records[-1] == "L|1|I"
