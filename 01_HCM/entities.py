"""Canonical HCM view of physical output channels, independent of bridges."""
import json

from . import channel_registry


def reported_state(row):
    state = row.get('last_state') or {}
    if isinstance(state, str):
        state = json.loads(state)
    if not isinstance(state, dict):
        return None
    state = state.get('state', state)
    if not isinstance(state, dict):
        return None
    key = {'relay': 'relays', 'lv_dimmer': 'lv_dimmers', 'hv_dimmer': 'hv_dimmers'}.get(row['channel_kind'])
    if key is None:
        return None
    value = state.get(key, {}).get(row['channel_id'])
    if value is None:
        return None
    if row['channel_kind'] == 'relay':
        if not isinstance(value, bool):
            return None
        return {'state': 'ON' if value else 'OFF'}
    level = value.get('percent') if isinstance(value, dict) else value
    if not isinstance(level, (float, int)) or not 0 <= level <= 100:
        return None
    return {'state': 'ON' if level > 0 else 'OFF', 'brightness': level}


def channel_entity(row):
    kind = row['channel_kind']
    actuator = bool(row.get('writable', kind in {'relay', 'lv_dimmer', 'hv_dimmer'}))
    capability = row.get('capability') or (
        'dimmable_light' if kind in {'lv_dimmer', 'hv_dimmer'} else
        'light' if kind == 'relay' and row['purpose'] == 'LIGHTING' else
        'relay' if kind == 'relay' else 'unknown'
    )
    state = reported_state(row)
    report = row.get('last_state') or {}
    if isinstance(report, str):
        report = json.loads(report)
    faults = report.get('faults') if isinstance(report, dict) else None
    return {
        'entity_id': f"channel_{row['id']}",
        'logical_device_id': row.get('logical_device_id'),
        'logical_name': row.get('logical_name'),
        'name': row['display_name'] or row.get('logical_name') or f"{row['hostname']} {row['channel_id']}",
        'module_id': row.get('module_id'),
        'module_type': row.get('module_type'),
        'device_id': row.get('device_id'),
        'channel': row['channel_id'],
        'channel_id': row['channel_id'],
        'room_id': row.get('room_id'),
        'room': row.get('room_name'),
        'area_id': row.get('area_id'),
        'area': row.get('area_name'),
        'capability': capability,
        'state': state,
        'current_state': state,
        'available': bool(row['enabled'] and row.get('control_session_online')
                          and (not actuator or row.get('logical_enabled'))
                          and not row.get('maintenance_locked')),
        'state_known': state is not None,
        'fault_state': faults,
        'writable': bool(actuator and row.get('logical_device_id') and row.get('logical_enabled')),
        'matter_exposed': bool(row.get('matter_enabled')),
    }


async def list_channel_entities(identifier=None):
    return [channel_entity(row) for row in await channel_registry.channels(identifier)]
