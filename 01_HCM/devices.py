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
    binding_metadata = _metadata(row)
    payload = dict(binding_metadata)
    payload.update(command)
    if 'channel' not in payload and row['channel']:
        payload['channel'] = row['channel']
    # Binding metadata is durable HCM authority. A request payload cannot
    # upgrade a simulated binding to physical execution.
    configured_mode = binding_metadata.get('execution_mode')
    mode = str(configured_mode or 'simulated').lower()
    if mode not in {'simulated', 'physical'}:
        raise ValueError('execution_mode must be simulated or physical')
    if configured_mode is not None:
        payload['execution_mode'] = mode
        payload['physical_write_requested'] = mode == 'physical'
    else:
        # Preserve the established simulated wire shape. Physical execution
        # is only requested when durable binding metadata explicitly selects it.
        payload.pop('physical_write_requested', None)
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


async def _resolve_single_binding(conn, *, logical_name: str | None = None, logical_device_id: int | None = None):
    if logical_name is not None:
        where, value = 'd.logical_name=$1', logical_name
    else:
        where, value = 'd.id=$1', int(logical_device_id)
    rows = await conn.fetch(f'''
        SELECT d.id AS logical_device_id, d.logical_name, m.hostname, m.module_type,
               d.maintenance_locked, b.channel, b.metadata
        FROM logical_devices d
        JOIN device_bindings b ON b.logical_device_id=d.id
        JOIN modules m ON m.id=b.module_id
        WHERE {where} AND d.enabled=true AND b.enabled=true
        ORDER BY b.id
    ''', value)
    if not rows:
        raise KeyError(logical_name if logical_name is not None else logical_device_id)
    if len(rows) > 1:
        raise RuntimeError('ambiguous enabled bindings')
    return rows[0]


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
        row = await _resolve_single_binding(conn, logical_name=logical_name)
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
        row = await _resolve_single_binding(conn, logical_device_id=logical_device_id)
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
            binding = await _resolve_single_binding(conn, logical_device_id=int(row['logical_device_id']))
        if binding and binding['module_type'] == 'RCM':
            snapshot = await management.get_rcm_channels(binding['hostname'])
            result['config_sync'] = await management.mirror_module_configuration('RCM', binding['hostname'], management.rcm_config_from_channels(snapshot['channels']))
        elif binding and binding['module_type'] == 'LCM':
            snapshot = await management.get_lcm_channels(binding['hostname'])
            result['config_sync'] = await management.mirror_module_configuration('LCM', binding['hostname'], management.lcm_config_from_channels(snapshot['channels']))
    except Exception:
        pass
    return result
