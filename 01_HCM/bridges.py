"""Registry projections. Every external command is reauthorized against HCM."""
import asyncio
import json
import logging
import os
import ssl
import time
from pathlib import Path
from . import db, channel_registry
from .entities import channel_entity, reported_state

log = logging.getLogger(__name__)


def stable_id(row):
    # A configured binding wins; rename never changes either durable ID.
    return f"logical_{row['logical_device_id']}" if row.get('logical_device_id') else f"channel_{row['id']}"


def representation(row, bridge):
    if not row['enabled'] or not row[f'{bridge}_enabled']:
        return None, 'Exposure disabled'
    entity = channel_entity(row)
    capability = entity['capability']
    # This registry is the single semantic boundary used by adapters.  A
    # relay remains a light only when HCM explicitly classified it as lighting.
    if capability == 'light' and row['purpose'] == 'LIGHTING':
        return 'light', None
    if capability == 'dimmable_light':
        return 'dimmer', None
    if bridge == 'mqtt' and row['channel_kind'] == 'relay' and row['purpose'] in {'GENERAL', 'LANDSCAPE', 'OTHER', 'SECURITY'}:
        return 'switch', None
    return None, 'No supported semantic device type'


MATTER_CAPABILITY_MAPPERS = {
    'light': 'on_off_light',
    'dimmable_light': 'dimmable_light',
    'temperature_sensor': 'temperature_sensor',
    'humidity_sensor': 'humidity_sensor',
    'illuminance_sensor': 'illuminance_sensor',
    'occupancy_sensor': 'occupancy_sensor',
    'motion_sensor': 'occupancy_sensor',
    'contact_sensor': 'contact_sensor',
}


def matter_mapper(entity):
    """Return the Matter device mapping for a canonical entity.

    Unsupported capabilities stay internal.  The bridge never guesses a
    device type for generic relays, analog values, faults, or future types.
    """
    if not entity.get('matter_exposed') or not entity.get('writable', True) and entity.get('capability') in {'analog_value', 'fault_state'}:
        return None
    return MATTER_CAPABILITY_MAPPERS.get(entity.get('capability'))


def projection(rows, bridge):
    result = []
    for row in rows:
        kind, reason = representation(row, bridge)
        entity = channel_entity(row)
        if bridge == 'matter' and matter_mapper(entity) is None:
            kind, reason = None, reason or 'No supported canonical Matter mapping'
        result.append({
            'channel_id': row['id'], 'stable_id': stable_id(row),
            'entity_id': entity['entity_id'], 'capability': entity['capability'],
            'name': entity['name'], 'room': entity['room'], 'area': entity['area'],
            'kind': kind, 'reason': reason, 'endpoint': row.get('endpoint'),
            'reported_state': entity['state'], 'current_state': entity['current_state'],
            'availability': entity['availability'], 'available': entity['available'],
        })
    return result


async def external_command(bridge, channel_id, value, percent=None):
    from .devices import command_logical
    from . import api
    rows = await channel_registry.channels()
    row = next((r for r in rows if r['id'] == channel_id), None)
    if row is None or representation(row, bridge)[0] is None:
        raise PermissionError('Channel is not exported')
    if not row.get('logical_enabled') or not row.get('logical_name'):
        raise PermissionError('Enabled logical binding required')
    if api.safety and (api.safety.fire_active or api.safety.maintenance_lockout_active):
        raise PermissionError('Safety control is active')
    if not isinstance(value, bool):
        raise ValueError('Boolean state required')
    command = {'op': 'set_relay', 'value': value}
    if row['channel_kind'] != 'relay':
        level = float(percent if percent is not None else 100 if value else 0)
        if not 0 <= level <= 100:
            raise ValueError('Brightness must be 0..100')
        command = {'op': 'light', 'value': value, 'percent': level if value else 0}
    result = await command_logical(row['logical_name'], command)
    if not result.get('ok', True) or result.get('suppressed'):
        raise RuntimeError('HCM rejected or inhibited command')
    return result


class RegistryBridge:
    def __init__(self):
        self.changed = asyncio.Event()
        self.task = None
        self.mqtt_task = None
        self.client = None
        self.matter = None
        self.matter_reader = None
        self.module_revisions = {}
        self.mqtt_state = 'disabled'
        self.matter_state = 'disabled'
        self.matter_failures = 0
        self.matter_next_retry = 0.0
        self.matter_stopping = False
        self.matter_started_at = 0.0
        self.sync_error = None
        self.rows = []
        self.settings = {}

    async def module_metadata_current(self, hostname):
        from .registry import registry
        for key, connection in registry.connections.items():
            if connection.hostname != hostname:
                continue
            rows = await channel_registry.channels(connection.device_id or hostname)
            payload = {'channel_metadata': [{'channel_id': r['channel_id'], 'metadata': {f: r[f] for f in channel_registry.FIELDS}} for r in rows]}
            return self.module_revisions.get(key) == (id(connection), json.dumps(payload, sort_keys=True))
        return False

    async def start(self):
        self.task = asyncio.create_task(self.run())


    async def stop(self):
        self.matter_stopping = True
        if self.client:
            try:
                await self.client.publish('homecontrol/status', 'offline', qos=1, retain=True)
            except Exception:
                pass
        tasks = [t for t in (self.task, self.mqtt_task, self.matter_reader) if t]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if self.matter and self.matter.returncode is None:
            self.matter.terminate()
            await self.matter.wait()
        self.matter_state = 'stopped intentionally'

    async def status(self):
        rows = await channel_registry.channels()
        from .registry import registry as modules
        delivery = [{'hostname': c.hostname, 'status': 'acknowledged' if self.module_revisions.get(key, (None,))[0] == id(c) else 'pending: agent metadata contract required'} for key, c in modules.connections.items() if c.module_type in {'RCM', 'LCM', 'PNL'}]
        return {'module_delivery': delivery, 'mqtt': {'status': self.mqtt_state, 'channels': projection(rows, 'mqtt')},
                'matter': {'status': self.matter_state, 'channels': projection(rows, 'matter')},
                'registry_sync_error': self.sync_error,
                'settings': await self.load_settings()}


    async def load_settings(self):
        configured = {
            'mqtt': {'enabled': bool(os.getenv('HCM_MQTT_HOST')), 'host': os.getenv('HCM_MQTT_HOST', ''),
                     'port': int(os.getenv('HCM_MQTT_PORT', '8883')), 'tls': os.getenv('HCM_MQTT_TLS', 'true').lower() == 'true'},
            'matter': {'enabled': os.getenv('HCM_MATTER_ENABLED', '').lower() == 'true'},
        }
        async with db.acquire() as conn:
            for row in await conn.fetch('SELECT bridge,settings FROM bridge_settings'):
                settings = json.loads(row['settings']) if isinstance(row['settings'], str) else row['settings']
                configured[row['bridge']].update(settings)
        return configured

    async def configure(self):
        configured = await self.load_settings()
        if configured.get('mqtt') != self.settings.get('mqtt'):
            if self.client:
                await self.client.publish('homecontrol/status', 'offline', qos=1, retain=True)
            if self.mqtt_task:
                self.mqtt_task.cancel()
                await asyncio.gather(self.mqtt_task, return_exceptions=True)
                self.mqtt_task = None
            self.mqtt_state = 'disabled'
            if configured['mqtt']['enabled']:
                self.mqtt_task = asyncio.create_task(self.run_mqtt(configured['mqtt']))
        matter_changed = configured.get('matter') != self.settings.get('matter')
        if matter_changed:
            self.matter_stopping = True
            if self.matter and self.matter.returncode is None:
                self.matter.terminate()
                await self.matter.wait()
            if self.matter_reader:
                await asyncio.gather(self.matter_reader, return_exceptions=True)
                self.matter_reader = None
            self.matter = None
            self.matter_stopping = False
            self.matter_failures = 0
            self.matter_next_retry = 0.0
            self.matter_state = 'disabled'
        if configured['matter']['enabled'] and (not os.getenv('HCM_MATTER_STORAGE') or not os.getenv('HCM_MATTER_PASSCODE')):
            self.matter_state = 'not configured: persistent storage and pairing code are required'
        elif configured['matter']['enabled']:
            if self.matter and self.matter_reader and self.matter_reader.done() and self.matter.returncode is None:
                self.matter.terminate()
                await self.matter.wait()
                if not self.matter_next_retry:
                    self._matter_failure('adapter reader stopped')
            if self.matter and self.matter.returncode is None and self.matter_state.startswith('running') and time.monotonic() - self.matter_started_at >= 60:
                self.matter_failures = 0
                self.matter_next_retry = 0.0
            if self.matter is None or self.matter.returncode is not None:
                # Wait for the reader to record an unexpected exit and its backoff.
                if self.matter_reader:
                    await asyncio.gather(self.matter_reader, return_exceptions=True)
                    self.matter_reader = None
                self.matter = None
                if time.monotonic() >= self.matter_next_retry:
                    await self.start_matter()
        self.settings = configured

    async def run(self):
        while True:
            try:
                async with db.acquire() as conn:
                    def dirty(*_args):
                        self.changed.set()
                    await conn.add_listener('hcm_registry_changed', dirty)
                    try:
                        while True:
                            self.changed.clear()
                            await self.refresh()
                            self.sync_error = None
                            try:
                                await asyncio.wait_for(self.changed.wait(), timeout=30)
                            except TimeoutError:
                                pass  # Reconcile reconnects and delivery failures too.
                            await asyncio.sleep(0.1)
                    finally:
                        await conn.remove_listener('hcm_registry_changed', dirty)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.sync_error = 'Registry synchronization failed; see HCM logs'
                log.exception('Registry synchronization failed')
                await asyncio.sleep(5)

    async def refresh(self):
        await self.configure()
        await channel_registry.allocate_endpoints()
        self.rows = await channel_registry.channels()
        await self.sync_modules()
        if self.client:
            await self.sync_mqtt()
        if self.matter and self.matter.returncode is None:
            await self.send_matter({'type': 'registry', 'channels': [r for r in projection(self.rows, 'matter') if r['kind']]})

    async def sync_modules(self):
        from .registry import registry
        # A connection-specific cache forces replay after every authenticated reconnect.
        for key, connection in list(registry.connections.items()):
            if connection.module_type in {'RCM', 'LCM'}:
                rows = [r for r in self.rows if r['device_id'] == connection.device_id]
                if not rows:
                    continue
                payload = {'channel_metadata': [{'channel_id': r['channel_id'], 'metadata': {f: r[f] for f in channel_registry.FIELDS}} for r in rows]}
            elif connection.module_type == 'PNL':
                controls = await channel_registry.pnl_controls(connection.device_id or connection.hostname)
                payload = {'room_controls': [{'id': r['id'], 'logical_device_id': r['logical_device_id'], 'logical_name': r['logical_name'], 'name': r['display_name'], 'room_id': r['room_id'], 'kind': r['channel_kind']} for r in controls]}
            else:
                continue
            revision = json.dumps(payload, sort_keys=True)
            if self.module_revisions.get(key) == (id(connection), revision):
                continue
            try:
                result = await connection.config(payload)
                if result.get('ok') and (result.get('room_controls_contract') == 1 if connection.module_type == 'PNL' else result.get('metadata_contract') == 1):
                    self.module_revisions[key] = (id(connection), revision)
            except Exception:
                log.warning('Metadata sync pending for %s', connection.hostname)

    async def run_mqtt(self, config):
        import aiomqtt
        while True:
            try:
                self.mqtt_state = 'connecting'
                tls = ssl.create_default_context() if config['tls'] else None
                async with aiomqtt.Client(config['host'], port=config['port'],
                        username=os.getenv('HCM_MQTT_USERNAME'), password=os.getenv('HCM_MQTT_PASSWORD'), tls_context=tls,
                        identifier='homecontrol-hcm', will=aiomqtt.Will('homecontrol/status', 'offline', qos=1, retain=True)) as client:
                    self.client = client
                    self.mqtt_state = 'connected'
                    await client.subscribe('homecontrol/+/set')
                    await client.publish('homecontrol/status', 'online', qos=1, retain=True)
                    self.changed.set()
                    async for message in client.messages:
                        # Retained actuator commands must never replay after reconnect.
                        if message.retain:
                            continue
                        try:
                            ident = str(message.topic).split('/')[1]
                            row = next(r for r in await channel_registry.channels() if stable_id(r) == ident)
                            body = json.loads(message.payload)
                            if body.get('state') not in {'ON', 'OFF'}:
                                raise ValueError('state must be ON or OFF')
                            await external_command('mqtt', row['id'], body['state'] == 'ON', body.get('brightness'))
                        except Exception:
                            log.warning('MQTT command rejected')
            except asyncio.CancelledError:
                raise
            except Exception:
                self.mqtt_state = 'unavailable'
                log.warning('MQTT connection unavailable')
            finally:
                self.client = None
            await asyncio.sleep(5)

    async def sync_mqtt(self):
        current = {}
        for row in projection(self.rows, 'mqtt'):
            if not row['kind']:
                continue
            component = 'light' if row['kind'] in {'light', 'dimmer'} else 'switch'
            topic = f"homeassistant/{component}/{row['stable_id']}/config"
            base = f"homecontrol/{row['stable_id']}"
            body = {'name': row['name'], 'unique_id': row['stable_id'], 'command_topic': base + '/set', 'state_topic': base + '/state',
                    'availability': [{'topic': 'homecontrol/status'}, {'topic': base + '/availability'}], 'availability_mode': 'all',
                    'device': {'identifiers': [row['stable_id']], 'name': row['name'], 'suggested_area': row['room'] or ''}}
            if component == 'light':
                body.update({'schema': 'json', 'brightness': row['kind'] == 'dimmer', 'brightness_scale': 100})
            else:
                body.update({'value_template': '{{ value_json.state }}', 'state_on': 'ON', 'state_off': 'OFF', 'payload_on': '{"state":"ON"}', 'payload_off': '{"state":"OFF"}'})
            current[topic] = body
            if row['reported_state'] is not None and row['available']:
                await self.client.publish(base + '/state', json.dumps(row['reported_state']), retain=True, qos=1)
            await self.client.publish(base + '/availability', 'online' if row['available'] else 'offline', retain=True, qos=1)
        async with db.acquire() as conn:
            old = {r['topic'] for r in await conn.fetch("SELECT topic FROM bridge_publications WHERE bridge='mqtt'")}
            for topic in old - current.keys():
                await self.client.publish(topic, '', retain=True, qos=1)
                await conn.execute("DELETE FROM bridge_publications WHERE bridge='mqtt' AND topic=$1", topic)
            for topic, body in current.items():
                # Persist before publication so a crash can still clean up retained discovery.
                await conn.execute("INSERT INTO bridge_publications(bridge,topic) VALUES('mqtt',$1) ON CONFLICT DO NOTHING", topic)
                await self.client.publish(topic, json.dumps(body), retain=True, qos=1)

    async def start_matter(self):
        path = Path(__file__).resolve().parents[1] / '08_servises/matter_bridge/bridge.mjs'
        try:
            self.matter_state = 'starting'
            self.matter = await asyncio.create_subprocess_exec('node', str(path), stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE)
            self.matter_started_at = time.monotonic()
            self.matter_reader = asyncio.create_task(self.read_matter())
        except OSError:
            self._matter_failure('Node runtime missing')

    def _matter_failure(self, reason):
        self.matter_failures += 1
        self.matter_next_retry = time.monotonic() + min(300, 5 * 2 ** min(self.matter_failures - 1, 6))
        self.matter_state = ('failed repeatedly' if self.matter_failures >= 3 else 'exited unexpectedly') + f': {reason}'

    async def send_matter(self, message):
        self.matter.stdin.write((json.dumps(message) + '\n').encode())
        await self.matter.stdin.drain()

    async def read_matter(self):
        async for line in self.matter.stdout:
            try:
                message = json.loads(line)
                if message.get('type') == 'ready':
                    self.matter_state = 'running (fabric commissioning not verified)'
                    self.changed.set()
                elif message.get('type') == 'error':
                    self.matter_state = 'unavailable: registry synchronization failed'
                elif message.get('type') == 'command':
                    try:
                        await external_command('matter', message['channel_id'], message['value'], message.get('percent'))
                        reply = {'type': 'result', 'id': message['id'], 'ok': True}
                    except Exception:
                        reply = {'type': 'result', 'id': message['id'], 'ok': False}
                    await self.send_matter(reply)
            except (ValueError, KeyError):
                log.warning('Invalid Matter adapter response')
        if not self.matter_stopping:
            self._matter_failure('adapter exited')


bridge = RegistryBridge()
