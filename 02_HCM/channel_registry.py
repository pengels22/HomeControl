"""PostgreSQL authority for channel semantics and room-based projections."""
from importlib import import_module
from . import db

contract = import_module('08_servises.common.channel_metadata')
FIELDS = tuple(contract.ChannelMetadata.model_fields)
SELECT = '''
SELECT c.*, m.device_id, m.hostname, m.module_type, m.control_session_online, m.last_state,
       r.name AS room_name, r.enabled AS room_enabled, r.area_id,
       a.name AS area_name,
       d.id AS logical_device_id, d.logical_name,
       d.enabled AS logical_enabled, d.maintenance_locked,
       e.endpoint
FROM channel_metadata c JOIN modules m ON m.id=c.module_id
LEFT JOIN rooms r ON r.id=c.room_id
LEFT JOIN hcm_areas a ON a.id=r.area_id
LEFT JOIN device_bindings b ON b.module_id=c.module_id AND b.channel=c.channel_id AND b.enabled
LEFT JOIN logical_devices d ON d.id=b.logical_device_id
LEFT JOIN matter_endpoints e ON e.channel_id=c.id
'''


async def channels(identifier=None):
    async with db.acquire() as conn:
        rows = await conn.fetch(SELECT + (" WHERE m.device_id=$1 OR m.hostname=$1" if identifier else '') + ' ORDER BY c.id', *([identifier] if identifier else []))
    return [dict(row) for row in rows]


async def update_channel(channel_id, values, actor):
    async with db.acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow('SELECT c.*,m.module_type FROM channel_metadata c JOIN modules m ON m.id=c.module_id WHERE c.id=$1 FOR UPDATE OF c', channel_id)
            if not row:
                raise KeyError(channel_id)
            current = {key: row[key] for key in FIELDS}
            current.update(values)
            validated = contract.validate_metadata(row['module_type'], row['channel_kind'], current).model_dump(mode='json')
            fields = list(validated)
            updated = await conn.fetchrow('UPDATE channel_metadata SET ' + ','.join(f'{key}=${i+2}' for i, key in enumerate(fields)) + ' WHERE id=$1 RETURNING *', channel_id, *[validated[key] for key in fields])
            await conn.execute("INSERT INTO device_management_events(actor,action,target_type,target_id) VALUES($1,'channel_metadata_updated','channel',$2)", actor, str(channel_id))
    from .bridges import bridge
    bridge.module_revisions.clear()
    bridge.changed.set()
    return dict(updated)


async def room_list():
    async with db.acquire() as conn:
        return [dict(r) for r in await conn.fetch('''SELECT r.*,a.name AS area_name
            FROM rooms r LEFT JOIN hcm_areas a ON a.id=r.area_id ORDER BY r.name,r.id''')]


async def area_list():
    async with db.acquire() as conn:
        return [dict(r) for r in await conn.fetch('SELECT * FROM hcm_areas ORDER BY name,id')]


async def pnl_controls(identifier):
    async with db.acquire() as conn:
        rows = await conn.fetch(SELECT + '''
            JOIN pnl_rooms p ON p.room_id=c.room_id
            JOIN modules panel ON panel.id=p.module_id
            WHERE (panel.device_id=$1 OR panel.hostname=$1) AND panel.module_type='PNL'
              AND c.enabled AND c.purpose='LIGHTING' AND r.enabled
            ORDER BY c.id''', identifier)
    return [dict(row) for row in rows]


async def allocate_endpoints():
    async with db.acquire() as conn:
        await conn.execute('''INSERT INTO matter_endpoints(channel_id)
            SELECT c.id FROM channel_metadata c WHERE c.matter_enabled AND c.enabled
              AND c.purpose='LIGHTING'
              AND NOT EXISTS(SELECT 1 FROM matter_endpoints e WHERE e.channel_id=c.id)
            ON CONFLICT(channel_id) DO NOTHING''')


def semantic_roles(rows):
    return {row['channel_id']: row['hvac_control'] for row in rows if row['purpose'] == 'HVAC'}


async def thermostat_output(name, value, command):
    """Single-stage thermostat; stage/aux/reversing calls are OFF-only here."""
    rows = [r for r in await channels() if r['purpose'] == 'HVAC' and r['enabled']]
    if not rows:
        # Explicit compatibility path until semantic HVAC configuration exists.
        logical = {'FAN': 'HVAC Fan Call', 'COOL': 'HVAC Cool Call', 'HEAT': 'HVAC Heat Call'}[name]
        result = await command(logical, {'op': 'set_relay', 'value': value})
        if result and (not result.get('ok', True) or result.get('suppressed')):
            raise RuntimeError('HVAC output was not accepted')
        return
    roles = {'FAN': {'G', 'O/B', 'OTHER_HVAC'}, 'COOL': contract.COOLING, 'HEAT': contract.HEATING}
    primary = {'FAN': 'G', 'COOL': 'Y1', 'HEAT': 'W1'}[name]
    # Always drop opposite family before energizing; errors abort the ON step.
    opposite = contract.HEATING if name == 'COOL' else contract.COOLING if name == 'HEAT' else set()
    selected = [(r, False) for r in rows if value and r['hvac_control'] in opposite]
    selected += [(r, value and r['hvac_control'] == primary) for r in rows if r['hvac_control'] in roles[name]]
    if value and not any(r['hvac_control'] == primary and r['logical_enabled'] for r in rows):
        raise RuntimeError(f'No enabled logical binding for HVAC {primary}')
    failures = []
    for row, on in selected:
        try:
            if not row['logical_name']:
                raise RuntimeError('HVAC channel has no logical binding')
            result = await command(row['logical_name'], {'op': 'set_relay', 'value': on})
            if result and (not result.get('ok', True) or result.get('suppressed')):
                raise RuntimeError('HVAC output was inhibited or rejected')
        except Exception as exc:
            failures.append(str(exc))
            if value:
                break
    if failures:
        raise RuntimeError('; '.join(failures))


async def fire_shutdown():
    """Safety OFF reaches classified outputs even when no logical binding exists."""
    from .registry import registry as modules
    failures = []
    rows = await channels()
    for hostname in {r['hostname'] for r in rows if r['purpose'] == 'HVAC'}:
        try:
            result = await modules.command_by_hostname(hostname, {'op': 'metadata_hvac_off'})
            if not result.get('ok'):
                failures.append({'hostname': hostname, 'error': result.get('error', result.get('failures'))})
        except Exception as exc:
            failures.append({'hostname': hostname, 'error': str(exc)})
    return failures


async def import_legacy_configuration(conn):
    """Called deliberately inside migration 008, never during normal startup."""
    import json
    from . import storage
    rows = await conn.fetch('''SELECT c.*,m.hostname,m.module_type FROM channel_metadata c
        JOIN modules m ON m.id=c.module_id''')
    files = {}
    for row in rows:
        key = (row['module_type'], row['hostname'])
        if key not in files:
            path = storage.storage_root() / 'config' / key[0] / f'{key[1]}.json'
            if path.exists():
                package = json.loads(path.read_text())
                config = package.get('config', {})
                files[key] = {c['channel']: c for c in config.get('channels', [])}
            else:
                files[key] = {}
        old = files[key].get(row['channel_id'], {})
        if not old:
            continue
        name = row['display_name'] or str(old.get('name') or '')
        emergency = row['emergency'] or old.get('emergency_lighting') is True
        purpose = 'LIGHTING' if emergency else row['purpose']
        # Refuse conflicting imported semantics; an operator must reconcile them.
        if emergency and row['hvac_control'] is not None:
            raise ValueError('Legacy emergency designation conflicts with HVAC role')
        await conn.execute('''UPDATE channel_metadata SET display_name=$2,purpose=$3,emergency=$4,
            mqtt_enabled=$5,matter_enabled=$6 WHERE id=$1''',row['id'],name,purpose,emergency,
            old.get('mqtt_enabled') is True or row['mqtt_enabled'], old.get('matter_enabled') is True or row['matter_enabled'])
