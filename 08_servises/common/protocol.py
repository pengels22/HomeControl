from __future__ import annotations

import asyncio
import json
import struct
from dataclasses import dataclass
from typing import Any

MAX_FRAME = 1024 * 1024

class ProtocolError(Exception):
    pass

async def read_frame(reader: asyncio.StreamReader) -> dict[str, Any]:
    header = await reader.readexactly(4)
    (length,) = struct.unpack('!I', header)
    if length <= 0 or length > MAX_FRAME:
        raise ProtocolError(f'invalid frame length: {length}')
    raw = await reader.readexactly(length)
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ProtocolError('invalid JSON frame') from exc
    if not isinstance(obj, dict):
        raise ProtocolError('frame must be a JSON object')
    return obj

async def write_frame(writer: asyncio.StreamWriter, message: dict[str, Any]) -> None:
    raw = json.dumps(message, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    if len(raw) > MAX_FRAME:
        raise ProtocolError('frame too large')
    writer.write(struct.pack('!I', len(raw)) + raw)
    await writer.drain()

@dataclass(slots=True)
class Envelope:
    type: str
    payload: dict[str, Any]
    request_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {'type': self.type, 'payload': self.payload}
        if self.request_id is not None:
            d['request_id'] = self.request_id
        return d
