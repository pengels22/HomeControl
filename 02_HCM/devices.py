from __future__ import annotations
import json
import asyncio
import logging
from typing import Any
from importlib import import_module
from . import db
from .priority import OutputSource, active_intent, coerce_source, record_intent
from .registry import registry

safety_arbiter_mod = import_module('08_servises.common.safety_arbiter')
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
    if binding_metadata.get('channel_enabled') is False and (command.get('value') or command.get('percent', 0)):
        raise PermissionError('Channel is disabled')
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
               d.maintenance_locked, b.channel,
               CASE WHEN c.id IS NULL THEN b.metadata ELSE b.metadata || jsonb_build_object(
                   'emergency_lighting', c.purpose='LIGHTING' AND c.emergency AND c.enabled,
                   'hvac_shutdown', c.purpose='HVAC' OR COALESCE((b.metadata->>'hvac_shutdown')::boolean,false), 'semantic_hvac', c.purpose='HVAC', 'hvac_control', c.hvac_control, 'metadata_channel_id', c.id, 'channel_enabled', c.enabled) END AS metadata
        FROM logical_devices d
        JOIN device_bindings b ON b.logical_device_id=d.id
        JOIN modules m ON m.id=b.module_id
        LEFT JOIN channel_metadata c ON c.module_id=b.module_id AND c.channel_id=b.channel
        WHERE {where} AND d.enabled=true AND b.enabled=true
        ORDER BY b.id
    ''', value)
    if not rows:
        raise KeyError(logical_name if logical_name is not None else logical_device_id)
    if len(rows) > 1:
        raise RuntimeError('ambiguous enabled bindings')
    return rows[0]


_semantic_hvac_lock = asyncio.Lock()
_hvac_command_states = {}


async def _dispatch_with_arbitration(row, command, source, extra_conditions=None):
    metadata = _metadata(row)
    if not metadata.get('semantic_hvac'):
        return await _dispatch_resolved(row, command, source, extra_conditions)
    from .channel_registry import channels, contract
    from .bridges import reported_state
    def state_key(channel):
        connection = registry.connections.get(channel['device_id'])
        return (id(connection), channel['id'])
    async with _semantic_hvac_lock:
        records = [c for c in await channels() if c['purpose'] == 'HVAC']
        on = bool(command.get('value') or command.get('percent', 0))
        role = metadata.get('hvac_control')
        opposite = contract.COOLING if role in contract.HEATING else contract.HEATING if role in contract.COOLING else set()
        if on:
            for channel in records:
                if channel['hvac_control'] not in opposite:
                    continue
                state = _hvac_command_states.get(state_key(channel))
                if state is None:
                    report = reported_state(channel)
                    state = None if report is None else report['state'] == 'ON'
                if state is not False:
                    raise PermissionError('HCM heating/cooling interlock: opposite output active or unknown')
        current = next((c for c in records if c['id'] == metadata['metadata_channel_id']), None)
        try:
            result = await _dispatch_resolved(row, command, source, extra_conditions)
        except Exception:
            if current:
                _hvac_command_states.pop(state_key(current), None)
            raise
        if current:
            if result.get('ok', True):
                _hvac_command_states[state_key(current)] = result['arbitration']['effective_state']['energized']
            else:
                _hvac_command_states.pop(state_key(current), None)
        return result


async def _dispatch_resolved(row, command: dict[str, Any], source: OutputSource, extra_conditions: set[str] | None = None) -> dict[str, Any]:
    from . import api
    extra_conditions = set(extra_conditions or set())
    if api.safety is not None:
        if api.safety.fire_active:
            extra_conditions.add('fire_active')
        if api.safety.maintenance_lockout_active:
            extra_conditions.add('maintenance_lockout')
    if _metadata(row).get('semantic_hvac') and (command.get('value') or command.get('percent', 0)):
        from .bridges import bridge
        if not await bridge.module_metadata_current(row['hostname']):
            raise PermissionError('HVAC metadata has not been acknowledged by the module')
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
