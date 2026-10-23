"""Canonical HCM view of module channels and reported sensor state.

This module only normalizes rows already owned by the module registry and
channel metadata tables. It never stores live values and never sends commands.
"""
import json
import re

from . import channel_registry, db

CAPABILITIES = frozenset({
    'binary_switch', 'relay', 'light', 'dimmable_light',
    'temperature_sensor', 'humidity_sensor', 'illuminance_sensor',
    'occupancy_sensor', 'motion_sensor', 'contact_sensor', 'thermostat',
    'analog_value', 'fault_state',
})


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
    fault_state = faults if faults else None
    availability = 'available' if row.get('control_session_online') else 'unavailable'
    if fault_state:
        availability = 'faulted'
    elif state is None and availability == 'available':
        availability = 'unknown'
    capabilities = ['relay'] if kind == 'relay' else ['dimmable_light'] if kind in {'lv_dimmer', 'hv_dimmer'} else [capability]
    if kind == 'relay':
        capabilities.append('binary_switch')
        if row['purpose'] == 'LIGHTING':
            capabilities.append('light')
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
        'capabilities': capabilities,
        'state': state,
        'current_state': state,
        'available': bool(row['enabled'] and row.get('control_session_online')
                          and (not actuator or row.get('logical_enabled'))
                          and not row.get('maintenance_locked')),
        'state_known': state is not None,
        'availability': availability,
        'fault_state': fault_state,
        'writable': bool(actuator and row.get('logical_device_id') and row.get('logical_enabled')),
        'matter_exposed': bool(row.get('matter_enabled')),
        'metadata': {'source': 'module_channel', 'channel_kind': kind},
    }


async def list_channel_entities(identifier=None):
    channels = [channel_entity(row) for row in await channel_registry.channels(identifier)]
    async with db.acquire() as conn:
        modules = await conn.fetch('''SELECT id,device_id,hostname,module_type,control_session_online,
            online,last_state,last_health FROM modules
            WHERE ($1::text IS NULL OR id::text=$1 OR hostname=$1 OR device_id=$1)
            ORDER BY id''', identifier)
    sensors = []
    for module in modules:
        sensors.extend(_sensor_entities(dict(module)))
    return channels + sensors


def _json(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return {}
    return value if isinstance(value, dict) else {}


def _sensor_entity(module, source, suffix, name, capability, value, *, unit=None,
                   room_id=None, room=None, area_id=None, area=None, stale=False,
                   fault_state=None, metadata=None):
    safe_source = re.sub(r'[^a-z0-9]+', '_', str(source).lower()).strip('_')
    safe_suffix = re.sub(r'[^a-z0-9]+', '_', str(suffix).lower()).strip('_')
    state = {'value': value, 'unit': unit} if value is not None else None
    availability = 'unavailable' if not module.get('control_session_online') else 'stale' if stale else 'available'
    if fault_state:
        availability = 'faulted'
    elif state is None and availability == 'available':
        availability = 'unknown'
    return {
        'entity_id': f"module_{module['id']}_{safe_source}_{safe_suffix}",
        'logical_device_id': None,
        'logical_name': None,
        'name': name,
        'module_id': module['id'],
        'module_type': module.get('module_type'),
        'device_id': module.get('device_id'),
        'channel': source,
        'channel_id': source,
        'room_id': room_id,
        'room': room,
        'area_id': area_id,
        'area': area,
        'capability': capability,
        'capabilities': [capability],
        'state': state,
        'current_state': state,
        'available': availability == 'available',
        'availability': availability,
        'state_known': state is not None,
        'fault_state': fault_state,
        'writable': False,
        'matter_exposed': False,
        'metadata': {'source': source, **(metadata or {})},
    }


def _sensor_entities(module):
    """Normalize only sensor keys with established SIM/RMC semantics."""
    state = _json(module.get('last_state'))
    nested = _json(state.get('state', state))
    entities = []
    nodes = nested.get('rmc_nodes') if isinstance(nested.get('rmc_nodes'), dict) else {}
    for node_id, raw in nodes.items():
        node = _json(raw)
        stale = bool(node.get('stale') or not node.get('online', True))
        faults = node.get('faults') or node.get('sensor_faults')
        base = f"rmc:{node_id}"
        mappings = (
            ('temperature_f', 'temperature_sensor', 'Temperature', '°F'),
            ('humidity_pct', 'humidity_sensor', 'Humidity', '%'),
            ('lux', 'illuminance_sensor', 'Illuminance', 'lux'),
            ('presence', 'occupancy_sensor', 'Presence', None),
            ('motion', 'motion_sensor', 'Motion', None),
            ('contact', 'contact_sensor', 'Contact', None),
        )
        for key, capability, label, unit in mappings:
            if key not in node:
                continue
            entities.append(_sensor_entity(module, base, key, f"{node_id} {label}", capability,
                                           node.get(key), unit=unit, stale=stale,
                                           fault_state=faults, metadata={'node_id': str(node_id)}))
    hexa = _json(nested.get('hexa_board'))
    aio = _json(hexa.get('aio'))
    analog = aio.get('analog_inputs') if isinstance(aio.get('analog_inputs'), dict) else {}
    for source, raw in analog.items():
        item = _json(raw)
        if 'value' not in item:
            continue
        entities.append(_sensor_entity(module, f"analog:{source}", 'value', item.get('label') or str(source),
                                       'analog_value', item.get('value'), unit=item.get('unit'),
                                       fault_state=None if item.get('ok', True) else item.get('status'),
                                       metadata={'input': source, 'source_detail': item.get('source')}))
    return entities


def filter_entities(entities, *, module=None, room=None, area=None, capability=None, availability=None):
    def match(item):
        checks = ((module, lambda v: str(item.get('module_id')) == str(v) or item.get('device_id') == v or item.get('module_type') == v),
                  (room, lambda v: str(item.get('room_id')) == str(v) or item.get('room') == v),
                  (area, lambda v: str(item.get('area_id')) == str(v) or item.get('area') == v),
                  (capability, lambda v: item.get('capability') == v),
                  (availability, lambda v: item.get('availability') == v))
        return all(value is None or predicate(value) for value, predicate in checks)
    return [item for item in entities if match(item)]
