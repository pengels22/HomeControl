from __future__ import annotations
import json
from typing import Any
from . import db
from .registry import registry

async def command_logical(logical_name: str, command: dict[str, Any]) -> dict[str, Any]:
    async with db.acquire() as conn:
        row = await conn.fetchrow('''
            SELECT m.hostname, b.channel, b.binding_type, b.metadata
            FROM logical_devices d
            JOIN device_bindings b ON b.logical_device_id=d.id
            JOIN modules m ON m.id=b.module_id
            WHERE d.logical_name=$1 AND b.enabled=true
            ORDER BY b.id
            LIMIT 1
        ''', logical_name)
    if not row:
        raise KeyError(f'no binding for {logical_name}')
    payload = dict(command)
    if 'channel' not in payload and row['channel']:
        payload['channel'] = row['channel']
    return await registry.command_by_hostname(row['hostname'], payload)
