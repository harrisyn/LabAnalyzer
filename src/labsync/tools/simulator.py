"""Analyzer simulator for commissioning and demos.

    labsync-sim astm  --port 5000 --count 3       Sysmex-style ASTM with full E1381 handshake
    labsync-sim hl7   --port 5001                 Mindray-style ORU^R01 over MLLP
    labsync-sim poct1a --port 5002                POCT1-A2 conversation (HEL, DST, OBS, EOT)
    labsync-sim astm --query S123                 send a host query and print the order response
    labsync-sim replay capture.bin --port 5000    replay raw bytes captured from a real analyzer
"""

from __future__ import annotations

import argparse
import asyncio
import random
from datetime import datetime

from ..protocols.astm.framing import ACK, ENQ, EOT, build_frames, try_parse_frame

CBC = [("WBC", "10*3/uL", 4.0, 10.0), ("RBC", "10*6/uL", 4.2, 5.9), ("HGB", "g/dL", 12.0, 17.5),
       ("HCT", "%", 36.0, 52.0), ("MCV", "fL", 80.0, 100.0), ("PLT", "10*3/uL", 150.0, 450.0)]
CHEM = [("GLU", "mmol/L", 3.9, 6.1), ("CREA", "umol/L", 53, 115), ("UREA", "mmol/L", 2.5, 7.8),
        ("ALT", "U/L", 0, 41), ("AST", "U/L", 0, 40), ("CHOL", "mmol/L", 0, 5.2)]


def _value(lo: float, hi: float) -> tuple[str, str]:
    v = random.uniform(lo * 0.8, hi * 1.2)
    flag = "H" if v > hi else "L" if v < lo else "N"
    return (f"{v:.1f}" if hi < 100 else f"{v:.0f}"), flag


def astm_records(sample: str, patient: str) -> list[str]:
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    tests = "\\".join("^^^^" + c for c, *_ in CBC)
    recs = ["H|\\^&|||XN-550^00-18^11001^^^^12345678||||||||E1394-97",
            f"P|1|||{patient}|^DOE^JANE||19800131|F",
            f"O|1||^^{sample:>22}^B|{tests}|||||||N||||||||||||||F"]
    for i, (code, unit, lo, hi) in enumerate(CBC, start=1):
        v, f = _value(lo, hi)
        recs.append(f"R|{i}|^^^^{code}^1|{v}|{unit}||{f}||||||{ts}")
    recs.append("L|1|N")
    return recs


async def _expect(reader: asyncio.StreamReader, want: int, timeout: float = 15) -> int:
    b = await asyncio.wait_for(reader.read(1), timeout)
    if not b:
        raise ConnectionError("connection closed")
    if b[0] != want:
        print(f"  expected {want:#04x}, got {b[0]:#04x}")
    return b[0]


async def send_astm(host: str, port: int, count: int, query: str | None) -> None:
    reader, writer = await asyncio.open_connection(host, port)
    for n in range(count):
        if query:
            recs = ["H|\\^&|||XN-550^00-18^11001||||||||E1394-97", f"Q|1|2^1^{query:>22}^B||^^^^ALL||||||||A", "L|1|N"]
        else:
            recs = astm_records(f"{random.randint(100000, 999999)}", f"P{random.randint(10000, 99999)}")
        writer.write(bytes([ENQ]))
        await writer.drain()
        await _expect(reader, ACK)
        for frame in build_frames(recs):
            writer.write(frame)
            await writer.drain()
            await _expect(reader, ACK)
        writer.write(bytes([EOT]))
        await writer.drain()
        print(f"sent ASTM message {n + 1}/{count} ({len(recs)} records)")
        if query:
            await _receive_astm(reader, writer)
        await asyncio.sleep(0.5)
    writer.close()


async def _receive_astm(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    buf = bytearray()
    while True:
        chunk = await asyncio.wait_for(reader.read(4096), 30)
        if not chunk:
            return
        buf.extend(chunk)
        while buf:
            if buf[0] == ENQ:
                del buf[0]
                writer.write(bytes([ACK]))
            elif buf[0] == 0x02:
                frame = try_parse_frame(buf)
                if frame is None:
                    break
                del buf[: frame.consumed]
                print("  host ->", frame.text.decode("latin-1").strip())
                writer.write(bytes([ACK]))
            elif buf[0] == EOT:
                print("  host finished")
                return
            else:
                del buf[0]
        await writer.drain()


async def send_hl7(host: str, port: int, count: int) -> None:
    reader, writer = await asyncio.open_connection(host, port)
    for n in range(count):
        ts = datetime.now().strftime("%Y%m%d%H%M%S")
        sample = f"{random.randint(100000, 999999)}"
        segs = [f"MSH|^~\\&|Mindray|BS-430|||{ts}||ORU^R01|{n + 1}|P|2.3.1||||0||ASCII|||",
                f"PID|1||P{random.randint(1000, 9999)}^^^^MR||DOE^JOHN||19750412|M",
                f"OBR|1|{sample}|{sample}|^|N|{ts}|{ts}|||||||{ts}|serum|||||||||||||||||||||||||||||||||"]
        for i, (code, unit, lo, hi) in enumerate(CHEM, start=1):
            v, f = _value(lo, hi)
            segs.append(f"OBX|{i}|NM|{code}^{code}^LN||{v}|{unit}|{lo}-{hi}|{f}|||F||{v}|{ts}||")
        writer.write(b"\x0b" + "\r".join(segs).encode() + b"\r\x1c\r")
        await writer.drain()
        ack = await asyncio.wait_for(reader.readuntil(b"\x1c\r"), 15)
        msa = next((s for s in ack.decode(errors="replace").split("\r") if s.startswith("MSA")), "?")
        print(f"sent HL7 message {n + 1}/{count}; {msa}")
        await asyncio.sleep(0.5)
    writer.close()


async def send_poct1a(host: str, port: int) -> None:
    reader, writer = await asyncio.open_connection(host, port)
    ts = datetime.now().astimezone().isoformat(timespec="seconds")

    def hdr(cid: int) -> str:
        return f'<HDR><HDR.control_id V="{cid}"/><HDR.version_id V="POCT1"/><HDR.creation_dttm V="{ts}"/></HDR>'

    docs = [
        f'<HEL.R01>{hdr(1)}<DEV><DEV.device_id V="ISTAT-01"/><DEV.vendor_id V="ABBOTT"/><DEV.model_id V="i-STAT"/></DEV></HEL.R01>',
        f'<DST.R01>{hdr(2)}<DST><DST.status_dttm V="{ts}"/><DST.new_observations_qty V="1"/></DST></DST.R01>',
        f'<OBS.R01>{hdr(3)}<SVC><SVC.role_cd V="OBS"/><SVC.observation_dttm V="{ts}"/>'
        f'<PT><PT.patient_id V="P12345"/><OBS><OBS.observation_id V="Na" SN="LOCAL"/><OBS.value V="140" U="mmol/L"/>'
        f'<OBS.normal_lo-hi_limit V="135-145"/></OBS><OBS><OBS.observation_id V="K"/><OBS.value V="5.9" U="mmol/L"/>'
        f'<OBS.interpretation_cd V="H"/></OBS></PT></SVC></OBS.R01>',
        f'<EOT.R01>{hdr(4)}<EOT><EOT.topic_cd V="OBS"/></EOT></EOT.R01>',
    ]
    for doc in docs:
        writer.write(b'<?xml version="1.0" encoding="UTF-8"?>' + doc.encode())
        await writer.drain()
        await asyncio.sleep(0.3)
        try:
            reply = await asyncio.wait_for(reader.read(65536), 3)
            print("  manager ->", reply[:120].decode(errors="replace"), "…")
        except TimeoutError:
            pass
    writer.close()


async def replay(host: str, port: int, path: str) -> None:
    with open(path, "rb") as fh:
        data = fh.read()
    reader, writer = await asyncio.open_connection(host, port)
    for i in range(0, len(data), 256):
        writer.write(data[i : i + 256])
        await writer.drain()
        await asyncio.sleep(0.01)
    await asyncio.sleep(2)
    writer.close()
    print(f"replayed {len(data)} bytes")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="labsync-sim", description="Simulate laboratory analyzers")
    p.add_argument("kind", choices=["astm", "hl7", "poct1a", "replay"])
    p.add_argument("file", nargs="?", help="capture file for replay")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=5000)
    p.add_argument("--count", type=int, default=1)
    p.add_argument("--query", help="ASTM: send a host query for this specimen ID")
    a = p.parse_args(argv)
    if a.kind == "astm":
        asyncio.run(send_astm(a.host, a.port, a.count, a.query))
    elif a.kind == "hl7":
        asyncio.run(send_hl7(a.host, a.port, a.count))
    elif a.kind == "poct1a":
        asyncio.run(send_poct1a(a.host, a.port))
    else:
        if not a.file:
            p.error("replay needs a capture file")
        asyncio.run(replay(a.host, a.port, a.file))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
