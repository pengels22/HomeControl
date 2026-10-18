from __future__ import annotations
import json
import logging
from typing import Any
from importlib import import_module
from . import db
from .priority import OutputSource, active_intent, coerce_source, record_intent
from .registry import registry

safety_arbiter_mod = import_module('07_servises.common.safety_arbiter')
log = logging.getLogger(__name__)

class MaintenanceLockedError(PermissionError):
    pass


def _metadata(row) -> dict[str, Any]:
    metadata = row['metadata'] or {}
    if isinstance(metadata, str):
        metadata = json.loads(metadata)
    return metadata if isinstance(metadata, dict) else {}


def _payload(row, command: dict[str, Any]) -> dict[str, Any]:
    payload = dict(_metadata(row))
    payload.update(command)
    if 'channel' not in payload and row['channel']:
        payload['channel'] = row['channel']
    return payload


def _conditions(row, extra: set[str] | None = None) -> set[str]:
    conditions = set(extra or set())
    if row['maintenance_locked']:
        conditions.add(safety_arbiter_mod.SafetyCondition.MAINTENANCE_LOCKOUT.value)
    return conditions


def _arbiter_for(row):
    metadata = _metadata(row)
    channel = str(row['channel']).upper() if row['channel'] else ''
    emergency = {channel} if metadata.get('emergency_lighting') else set()
    hvac_shutdown = {channel} if metadata.get('hvac_shutdown') else set()
    return safety_arbiter_mod.SafetyArbiter(emergency_lighting_channels=emergency, hvac_shutdown_channels=hvac_shutdown)


async def _dispatch_with_arbitration(row, command: dict[str, Any], source: OutputSource, extra_conditions: set[str] | None = None) -> dict[str, Any]:
    payload = _payload(row, command)
    channel = str(payload.get('channel') or row['channel'] or row['logical_name'])
    decision = _arbiter_for(row).decide(
        safety_arbiter_mod.OutputRequest(
            device_id=None,
            channel_id=channel,
            command=payload,
            source=source.value,
        ),
        local_conditions=_conditions(row, extra_conditions),
    )
    result = await registry.command_by_hostname(row['hostname'], decision.final_command)
    try:
        async with db.acquire() as conn:
            await conn.execute(
                '''
                INSERT INTO output_arbitration_events(
                    logical_device_id, device_id, channel_id, control_source,
                    requested_state, effective_state, feedback_state,
                    active_safety_conditions, fault_state, inhibited
                )
                VALUES($1,$2,$3,$4,$5::jsonb,$6::jsonb,$7::jsonb,$8::text[],$9,$10)
                ''',
                int(row['logical_device_id']) if 'logical_device_id' in row else None,
                None,
                decision.channel_id,
                decision.control_source,
                json.dumps(decision.as_dict()['requested_state']),
                json.dumps(decision.as_dict()['effective_state']),
                json.dumps(decision.as_dict()['feedback_state']),
                decision.active_safety_conditions,
                decision.fault_state,
                decision.inhibited,
            )
    except Exception:
        # Audit persistence must never block a safety/output command, but a
        # silent failure makes arbitration history falsely look complete.
        log.exception('failed to persist output arbitration event')
    return {
        **result,
        'source': source.value,
        'arbitration': decision.as_dict(),
        'suppressed': decision.inhibited,
    }

async def command_logical(
    logical_name: str,
    command: dict[str, Any],
    source: str | OutputSource = OutputSource.USER,
    safety_conditions: set[str] | None = None,
) -> dict[str, Any]:
    src = coerce_source(source)
    async with db.acquire() as conn:
        rows = await conn.fetch('''
            SELECT d.id AS logical_device_id, m.hostname, d.maintenance_locked, b.channel, b.binding_type, b.metadata
            FROM logical_devices d
            JOIN device_bindings b ON b.logical_device_id=d.id
            JOIN modules m ON m.id=b.module_id
            WHERE d.logical_name=$1 AND d.enabled=true AND b.enabled=true
            ORDER BY b.id
        ''', logical_name)
    if not rows:
        raise KeyError(f'no binding for {logical_name}')
    if len(rows) > 1:
        raise RuntimeError(f'ambiguous enabled bindings for {logical_name}')
    row = rows[0]
    logical_device_id = int(row['logical_device_id'])
    if row['maintenance_locked']:
        return await _dispatch_with_arbitration(row, command, src, safety_conditions)
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
    effective_source = intent.source if intent else src
    return await _dispatch_with_arbitration(row, effective, effective_source, safety_conditions)


async def apply_active_intent(logical_device_id: int) -> dict[str, Any]:
    async with db.acquire() as conn:
        row = await conn.fetchrow('''
            SELECT d.id AS logical_device_id, d.logical_name, m.hostname, d.maintenance_locked, b.channel, b.metadata
            FROM logical_devices d
            JOIN device_bindings b ON b.logical_device_id=d.id
            JOIN modules m ON m.id=b.module_id
            WHERE d.id=$1 AND d.enabled=true AND b.enabled=true
            ORDER BY b.id
            LIMIT 1
        ''', logical_device_id)
    if not row:
        raise KeyError(f'no binding for logical device id {logical_device_id}')
    intent = await active_intent(logical_device_id)
    if not intent:
        if row['maintenance_locked']:
            return await _dispatch_with_arbitration(row, {'value': False, 'percent': 0}, OutputSource.USER)
        return {'ok': True, 'logical_name': row['logical_name'], 'idle': True}
    return await _dispatch_with_arbitration(row, intent.command, intent.source)


async def set_maintenance_lockout(logical_name: str, active: bool) -> dict[str, Any]:
    async with db.acquire() as conn:
        row = await conn.fetchrow('''
            UPDATE logical_devices d SET maintenance_locked=$2
            WHERE d.logical_name=$1 AND d.enabled=true
            RETURNING d.id AS logical_device_id
        ''', logical_name, active)
    if not row:
        raise KeyError(logical_name)
    if active:
        result = await apply_active_intent(int(row['logical_device_id']))
    else:
        result = {'ok': True, 'logical_name': logical_name, 'maintenance_locked': False}
    try:
        from . import management
        async with db.acquire() as conn:
            binding = await conn.fetchrow('''
                SELECT m.hostname, m.module_type
                FROM device_bindings b
                JOIN modules m ON m.id=b.module_id
                WHERE b.logical_device_id=$1 AND b.enabled=true
                ORDER BY b.id
                LIMIT 1
            ''', int(row['logical_device_id']))
        if binding and binding['module_type'] == 'RCM':
            snapshot = await management.get_rcm_channels(binding['hostname'])
            result['config_sync'] = await management.mirror_module_configuration('RCM', binding['hostname'], management.rcm_config_from_channels(snapshot['channels']))
        elif binding and binding['module_type'] == 'LCM':
            snapshot = await management.get_lcm_channels(binding['hostname'])
            result['config_sync'] = await management.mirror_module_configuration('LCM', binding['hostname'], management.lcm_config_from_channels(snapshot['channels']))
    except Exception:
        pass
    return result
