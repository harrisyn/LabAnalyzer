"""ASTM E1381 / CLSI LIS01-A2 low-level framing helpers."""

from __future__ import annotations

from dataclasses import dataclass

STX, ETX, EOT, ENQ, ACK, NAK, ETB, LF, CR = 0x02, 0x03, 0x04, 0x05, 0x06, 0x15, 0x17, 0x0A, 0x0D

MAX_FRAME_TEXT = 240  # LIS01-A2: at most 247 characters per frame including framing


def checksum(body: bytes) -> str:
    """Modulo-256 sum of every byte from the frame number through ETX/ETB, as two hex digits."""
    return f"{sum(body) & 0xFF:02X}"


def build_frame(frame_number: int, text: bytes, final: bool) -> bytes:
    body = bytes([0x30 + frame_number % 8]) + text + bytes([ETX if final else ETB])
    return bytes([STX]) + body + checksum(body).encode("ascii") + bytes([CR, LF])


def build_frames(records: list[str], encoding: str = "latin-1", max_text: int = MAX_FRAME_TEXT) -> list[bytes]:
    """Frame records one per message, splitting long records with ETB as the standard requires."""
    frames: list[bytes] = []
    fn = 1
    for record in records:
        data = record.encode(encoding, errors="replace") + b"\r"
        chunks = [data[i : i + max_text] for i in range(0, len(data), max_text)] or [b"\r"]
        for i, chunk in enumerate(chunks):
            frames.append(build_frame(fn, chunk, final=i == len(chunks) - 1))
            fn = (fn + 1) % 8
    return frames


@dataclass(slots=True)
class Frame:
    number: int
    text: bytes
    final: bool
    checksum_ok: bool
    received_checksum: str
    expected_checksum: str
    consumed: int


def try_parse_frame(buf: bytes | bytearray, start: int = 0) -> Frame | None:
    """Parse one frame beginning at ``buf[start] == STX``.

    Returns ``None`` when more bytes are needed. Tolerates a missing CR/LF
    trailer (common with TCP-converted serial devices).
    """
    if start >= len(buf) or buf[start] != STX:
        raise ValueError("frame must start with STX")
    end = -1
    for i in range(start + 1, len(buf)):
        b = buf[i]
        if b in (ETX, ETB):
            end = i
            break
        if b == STX:
            # A new STX before the terminator: the previous frame was truncated.
            return Frame(number=-1, text=bytes(buf[start + 1 : i]), final=False, checksum_ok=False,
                         received_checksum="", expected_checksum="", consumed=i - start)
    if end < 0 or len(buf) < end + 3:
        return None
    body = bytes(buf[start + 1 : end + 1])
    received = bytes(buf[end + 1 : end + 3]).decode("ascii", errors="replace").upper()
    expected = checksum(body)
    consumed = end + 3 - start
    for trailer in (CR, LF):
        if start + consumed < len(buf) and buf[start + consumed] == trailer:
            consumed += 1
    fn_char = body[0] if body else 0
    number = fn_char - 0x30 if 0x30 <= fn_char <= 0x37 else -1
    text = body[1:-1] if number >= 0 else body[:-1]
    return Frame(
        number=number,
        text=text,
        final=buf[end] == ETX,
        checksum_ok=received == expected,
        received_checksum=received,
        expected_checksum=expected,
        consumed=consumed,
    )
