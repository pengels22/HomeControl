from __future__ import annotations
import json
from typing import Any
from . import db
from .priority import OutputSource, active_intent, coerce_source, record_intent
from .registry import registry

class MaintenanceLockedError(PermissionError):
    pass

async def command_logical(
    logical_name: str,
    command: dict[str, Any],
    source: str | OutputSource = OutputSource.USER,
) -> dict[str, Any]:
    src = coerce_source(source)
    async with db.acquire() as conn:
        row = await conn.fetchrow('''
            SELECT d.id AS logical_device_id, m.hostname, d.maintenance_locked, b.channel, b.binding_type, b.metadata
            FROM logical_devices d
            JOIN device_bindings b ON b.logical_device_id=d.id
            JOIN modules m ON m.id=b.module_id
            WHERE d.logical_name=$1 AND d.enabled=true AND b.enabled=true
            ORDER BY b.id
            LIMIT 1
        ''', logical_name)
    if not row:
        raise KeyError(f'no binding for {logical_name}')
    if row['maintenance_locked']:
        raise MaintenanceLockedError(f'{logical_name} is maintenance locked')
    logical_device_id = int(row['logical_device_id'])
    await record_intent(logical_device_id, src, command)
    intent = await active_intent(logical_device_id)
    if intent and intent.source != src:
        return {
            'ok': True,
            'suppressed': True,
            'logical_name': logical_name,
            'requested_source': src.value,
            'active_source': intent.source.value,
        }
    effective = intent.command if intent else command
    metadata = row['metadata'] or {}
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    payload = dict(metadata) if isinstance(metadata, dict) else {}
    payload.update(effective)
    if 'channel' not in payload and row['channel']:
        payload['channel'] = row['channel']
    result = await registry.command_by_hostname(row['hostname'], payload)
    return {**result, 'source': src.value}


async def apply_active_intent(logical_device_id: int) -> dict[str, Any]:
    async with db.acquire() as conn:
        row = await conn.fetchrow('''
            SELECT d.logical_name, m.hostname, d.maintenance_locked, b.channel, b.metadata
            FROM logical_devices d
            JOIN device_bindings b ON b.logical_device_id=d.id
            JOIN modules m ON m.id=b.module_id
            WHERE d.id=$1 AND d.enabled=true AND b.enabled=true
            ORDER BY b.id
            LIMIT 1
        ''', logical_device_id)
    if not row:
        raise KeyError(f'no binding for logical device id {logical_device_id}')
    if row['maintenance_locked']:
        raise MaintenanceLockedError(f"{row['logical_name']} is maintenance locked")
    intent = await active_intent(logical_device_id)
    if not intent:
        return {'ok': True, 'logical_name': row['logical_name'], 'idle': True}
    metadata = row['metadata'] or {}
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    payload = dict(metadata) if isinstance(metadata, dict) else {}
    payload.update(intent.command)
    if 'channel' not in payload and row['channel']:
        payload['channel'] = row['channel']
    result = await registry.command_by_hostname(row['hostname'], payload)
    return {**result, 'source': intent.source.value}
