from __future__ import annotations

import base64
import hashlib
import hmac
import time
from dataclasses import dataclass
from secrets import token_bytes
from zlib import crc32

SIZE = 17
CENTER = 8
RADIUS = 8.2
EYE_CENTERS = ((4, 4), (12, 4), (4, 12))
EYE_HALF_WIDTH = 1
SECURE_PREFIX = "HC2"


@dataclass(frozen=True)
class PairingGlyph:
    payload: str
    code: str
    size: int
    matrix: list[str]
    qr_size: int
    qr_matrix: list[str]


def _in_circle(x: int, y: int) -> bool:
    return ((x - CENTER) ** 2 + (y - CENTER) ** 2) ** 0.5 <= RADIUS


def _is_eye(x: int, y: int) -> bool:
    return any(abs(x - ex) <= EYE_HALF_WIDTH and abs(y - ey) <= EYE_HALF_WIDTH for ex, ey in EYE_CENTERS)


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


def build_secure_pairing_payload(
    hcm_id: str,
    pairing_code: str,
    secret: bytes | str,
    *,
    issued_at: int | None = None,
    nonce: bytes | None = None,
) -> str:
    key = _secret_bytes(secret)
    nonce = nonce or token_bytes(4)
    issued = int(issued_at if issued_at is not None else time.time())
    bucket = issued // 300
    tag = hmac.new(key, f"{hcm_id}|{pairing_code}|{bucket}".encode("ascii"), hashlib.sha256).digest()[:5]
    token = _b64url(nonce + tag)
    return f"{SECURE_PREFIX}:{token}"


def verify_secure_pairing_payload(
    payload: str,
    hcm_id: str,
    pairing_code: str,
    secret: bytes | str,
    *,
    now: int | None = None,
    max_age_s: int = 300,
) -> bool:
    try:
        prefix, token = payload.split(":", 1)
        if prefix != SECURE_PREFIX:
            return False
        raw = _b64url_decode(token)
        if len(raw) != 9:
            return False
        tag = raw[4:]
        key = _secret_bytes(secret)
        bucket = int(now if now is not None else time.time()) // 300
        allowed_skew = max(0, max_age_s // 300)
        for candidate_bucket in range(bucket - allowed_skew, bucket + allowed_skew + 1):
            expected_tag = hmac.new(
                key,
                f"{hcm_id}|{pairing_code}|{candidate_bucket}".encode("ascii"),
                hashlib.sha256,
            ).digest()[:5]
            if hmac.compare_digest(tag, expected_tag):
                return True
        return False
    except ValueError:
        return False


def encode_pairing_glyph(hcm_id: str, pairing_code: str, secret: bytes | str | None = None) -> PairingGlyph:
    payload = (
        build_secure_pairing_payload(hcm_id, pairing_code, secret)
        if secret is not None
        else build_pairing_payload(hcm_id, pairing_code)
    )
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
        qr_size=21,
        qr_matrix=encode_qr_v1_l(payload) if len(payload.encode("iso-8859-1")) <= 17 else [],
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


def _secret_bytes(secret: bytes | str) -> bytes:
    return secret if isinstance(secret, bytes) else secret.encode("utf-8")


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _xor_stream(data: bytes, key: bytes, nonce: bytes) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < len(data):
        block = hmac.new(key, b"HC2-STREAM" + nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        out.extend(block)
        counter += 1
    return bytes(value ^ mask for value, mask in zip(data, out, strict=False))


def encode_qr_v1_l(payload: str) -> list[str]:
    data = payload.encode("iso-8859-1")
    if len(data) > 17:
        raise ValueError("payload is too large for QR version 1-L byte mode")

    codewords = _qr_data_codewords(data)
    ecc = _rs_ecc(codewords, 7)
    bits = _bits(bytes(codewords + ecc))
    matrix, reserved = _blank_qr()
    _place_qr_data(matrix, reserved, bits)
    _place_format_bits(matrix, reserved, _qr_format_bits(error_correction=1, mask=0))
    return ["".join("1" if cell else "0" for cell in row) for row in matrix]


def _qr_data_codewords(data: bytes) -> list[int]:
    bits = [0, 1, 0, 0]
    bits.extend(_int_bits(len(data), 8))
    for byte in data:
        bits.extend(_int_bits(byte, 8))
    bits.extend([0] * min(4, 19 * 8 - len(bits)))
    while len(bits) % 8:
        bits.append(0)

    codewords = [
        sum(bit << (7 - i) for i, bit in enumerate(bits[offset:offset + 8]))
        for offset in range(0, len(bits), 8)
    ]
    pads = [0xEC, 0x11]
    while len(codewords) < 19:
        codewords.append(pads[len(codewords) % 2])
    return codewords


def _int_bits(value: int, count: int) -> list[int]:
    return [(value >> shift) & 1 for shift in range(count - 1, -1, -1)]


def _blank_qr() -> tuple[list[list[bool]], list[list[bool]]]:
    size = 21
    matrix = [[False for _ in range(size)] for _ in range(size)]
    reserved = [[False for _ in range(size)] for _ in range(size)]

    def set_module(x: int, y: int, value: bool) -> None:
        if 0 <= x < size and 0 <= y < size:
            matrix[y][x] = value
            reserved[y][x] = True

    def finder(left: int, top: int) -> None:
        for y in range(top - 1, top + 8):
            for x in range(left - 1, left + 8):
                if 0 <= x < size and 0 <= y < size:
                    matrix[y][x] = False
                    reserved[y][x] = True
        for y in range(7):
            for x in range(7):
                xx, yy = left + x, top + y
                dark = x in (0, 6) or y in (0, 6) or (2 <= x <= 4 and 2 <= y <= 4)
                set_module(xx, yy, dark)

    finder(0, 0)
    finder(size - 7, 0)
    finder(0, size - 7)

    for i in range(8, size - 8):
        set_module(i, 6, i % 2 == 0)
        set_module(6, i, i % 2 == 0)

    for i in range(9):
        reserved[8][i] = True
        reserved[i][8] = True
        reserved[8][size - 1 - i] = True
        reserved[size - 1 - i][8] = True
    set_module(8, size - 8, True)
    return matrix, reserved


def _place_qr_data(matrix: list[list[bool]], reserved: list[list[bool]], bits: list[int]) -> None:
    size = len(matrix)
    bit_index = 0
    upward = True
    x = size - 1
    while x > 0:
        if x == 6:
            x -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for y in rows:
            for xx in (x, x - 1):
                if reserved[y][xx]:
                    continue
                bit = bits[bit_index] if bit_index < len(bits) else 0
                matrix[y][xx] = bool(bit) ^ ((xx + y) % 2 == 0)
                bit_index += 1
        upward = not upward
        x -= 2


def _qr_format_bits(error_correction: int, mask: int) -> int:
    data = (error_correction << 3) | mask
    value = data << 10
    generator = 0x537
    for shift in range(14, 9, -1):
        if (value >> shift) & 1:
            value ^= generator << (shift - 10)
    return ((data << 10) | value) ^ 0x5412


def _place_format_bits(matrix: list[list[bool]], reserved: list[list[bool]], bits: int) -> None:
    size = len(matrix)

    def bit(i: int) -> bool:
        return ((bits >> i) & 1) != 0

    placements = [
        (8, 0), (8, 1), (8, 2), (8, 3), (8, 4), (8, 5),
        (8, 7), (8, 8), (7, 8), (5, 8), (4, 8), (3, 8), (2, 8), (1, 8), (0, 8),
    ]
    mirrors = [
        (size - 1, 8), (size - 2, 8), (size - 3, 8), (size - 4, 8), (size - 5, 8),
        (size - 6, 8), (size - 7, 8), (size - 8, 8), (8, size - 7), (8, size - 6),
        (8, size - 5), (8, size - 4), (8, size - 3), (8, size - 2), (8, size - 1),
    ]
    for i, (x, y) in enumerate(placements):
        matrix[y][x] = bit(i)
        reserved[y][x] = True
    for i, (x, y) in enumerate(mirrors):
        matrix[y][x] = bit(i)
        reserved[y][x] = True


def _rs_ecc(data: list[int], degree: int) -> list[int]:
    generator = [1]
    for i in range(degree):
        generator = _poly_mul(generator, [1, _gf_pow(2, i)])

    result = [0] * degree
    for byte in data:
        factor = byte ^ result.pop(0)
        result.append(0)
        for i, coeff in enumerate(generator[1:]):
            result[i] ^= _gf_mul(coeff, factor)
    return result


def _poly_mul(a: list[int], b: list[int]) -> list[int]:
    out = [0] * (len(a) + len(b) - 1)
    for i, av in enumerate(a):
        for j, bv in enumerate(b):
            out[i + j] ^= _gf_mul(av, bv)
    return out


def _gf_mul(a: int, b: int) -> int:
    result = 0
    while b:
        if b & 1:
            result ^= a
        a <<= 1
        if a & 0x100:
            a ^= 0x11D
        b >>= 1
    return result


def _gf_pow(value: int, power: int) -> int:
    result = 1
    for _ in range(power):
        result = _gf_mul(result, value)
    return result
