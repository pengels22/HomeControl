from __future__ import annotations

from dataclasses import dataclass
from zlib import crc32

SIZE = 17
EYE_CENTERS = ((4, 4), (12, 4), (4, 12))


@dataclass(frozen=True)
class PairingGlyph:
    payload: str
    code: str
    size: int
    matrix: list[str]


def _in_circle(x: int, y: int) -> bool:
    return ((x - 8) ** 2 + (y - 8) ** 2) ** 0.5 <= 8.2


def _is_eye(x: int, y: int) -> bool:
    return any(abs(x - ex) <= 1 and abs(y - ey) <= 1 for ex, ey in EYE_CENTERS)


def _data_cells() -> list[tuple[int, int]]:
    return [
        (x, y)
        for y in range(SIZE)
        for x in range(SIZE)
        if _in_circle(x, y) and not _is_eye(x, y)
    ]


def _bits(data: bytes) -> list[int]:
    return [(byte >> shift) & 1 for byte in data for shift in range(7, -1, -1)]


def _bytes(bits: list[int]) -> bytes:
    out = bytearray()
    for i in range(0, len(bits), 8):
        chunk = bits[i:i + 8]
        if len(chunk) < 8:
            break
        value = 0
        for bit in chunk:
            value = (value << 1) | bit
        out.append(value)
    return bytes(out)


def build_pairing_payload(hcm_id: str, pairing_code: str) -> str:
    return f"HC1:{hcm_id}:{pairing_code}"


def encode_pairing_glyph(hcm_id: str, pairing_code: str) -> PairingGlyph:
    payload = build_pairing_payload(hcm_id, pairing_code)
    body = payload.encode("ascii")
    packet = len(body).to_bytes(1, "big") + body + crc32(body).to_bytes(4, "big")
    cells = _data_cells()
    packet_bits = _bits(packet)
    if len(packet_bits) > len(cells):
        raise ValueError("pairing payload is too large for the 17x17 circular glyph")

    grid = [["." for _ in range(SIZE)] for _ in range(SIZE)]
    for y in range(SIZE):
        for x in range(SIZE):
            if _is_eye(x, y):
                grid[y][x] = "E"
            elif not _in_circle(x, y):
                grid[y][x] = " "

    for (x, y), bit in zip(cells, packet_bits, strict=False):
        grid[y][x] = "1" if bit else "0"

    return PairingGlyph(
        payload=payload,
        code=pairing_code,
        size=SIZE,
        matrix=["".join(row) for row in grid],
    )


def decode_pairing_glyph(matrix: list[str]) -> str:
    if len(matrix) != SIZE or any(len(row) != SIZE for row in matrix):
        raise ValueError("invalid pairing glyph matrix size")

    cells = _data_cells()
    bits = [1 if matrix[y][x] in ("1", "E") else 0 for x, y in cells]
    raw = _bytes(bits)
    if not raw:
        raise ValueError("empty pairing glyph")

    length = raw[0]
    end = 1 + length
    body = raw[1:end]
    checksum = raw[end:end + 4]
    if len(body) != length or len(checksum) != 4:
        raise ValueError("incomplete pairing glyph payload")
    if crc32(body).to_bytes(4, "big") != checksum:
        raise ValueError("pairing glyph checksum mismatch")

    return body.decode("ascii")
