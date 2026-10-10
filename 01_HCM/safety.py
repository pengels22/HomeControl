from __future__ import annotations
import asyncio
import json
import logging
from importlib import import_module
from . import db
from .devices import apply_active_intent, command_logical
from .notifications import notifications, Notification
from .priority import OutputSource, clear_source

log = logging.getLogger(__name__)
fire_input_mod = import_module('07_servises.common.fire_input')
arbiter_mod = import_module('07_servises.common.safety_arbiter')


class SafetyHeartbeatReporter:
    def __init__(self, socket_path: str = '/run/hcm-heartbeat/control.sock'):
        self.socket_path = socket_path

    async def _send(self, payload: dict):
        try:
            reader, writer = await asyncio.open_unix_connection(self.socket_path)
            writer.write((json.dumps(payload) + '\n').encode('utf-8'))
            await writer.drain()
            await asyncio.wait_for(reader.readline(), timeout=1.0)
            writer.close()
            try:
                await writer.wait_closed()
            except AttributeError:
                pass
        except Exception:
            log.debug('safety heartbeat reporting unavailable', exc_info=True)

    async def status(self, name: str, value: str):
        await self._send({'action': 'status_set', 'name': name, 'value': value})

    async def fault(self, name: str, detail: str | None):
        action = 'fault_set' if detail else 'fault_clear'
        payload = {'action': action, 'name': name}
        if detail:
            payload['value'] = detail
        await self._send(payload)

class SafetyController:
    def __init__(self, hvac, emergency_lighting_logical_names: list[str] | None = None, heartbeat: SafetyHeartbeatReporter | None = None):
        self.hvac = hvac
        self.fire_active = False
        self.maintenance_lockout_active = False
        self.fire_input = fire_input_mod.DebouncedFireInput(alarm_level=True, debounce_seconds=0.25)
        self.emergency_lighting_logical_names = list(emergency_lighting_logical_names or [])
        self.heartbeat = heartbeat or SafetyHeartbeatReporter()

    def state(self) -> str:
        if self.fire_active and self.maintenance_lockout_active:
            return 'fire_active_with_maintenance_lockout'
        if self.fire_active:
            return 'fire_active'
        if self.maintenance_lockout_active:
            return 'maintenance_lockout'
        return 'normal'

    async def sample_fire_input(self, level: bool | None, now: float):
        sample = self.fire_input.sample(level, now)
        if sample.fault:
            await self.heartbeat.fault('fire_input_fault', 'fire input unknown or disconnected')
        else:
            await self.heartbeat.fault('fire_input_fault', None)
        if sample.changed:
            await self.set_fire(sample.fire_active)
        return sample

    async def set_maintenance_lockout(self, active: bool):
        self.maintenance_lockout_active = bool(active)
        await self.heartbeat.status('maintenance_lockout', 'active' if active else 'inactive')

    async def set_fire(self, active: bool):
        if active == self.fire_active:
            return
        self.fire_active = active
        async with db.acquire() as conn:
            await conn.execute('INSERT INTO safety_events(event_type,active,details) VALUES($1,$2,$3::jsonb)', 'fire', active, '{}')
        await self.heartbeat.status('fire_alarm', 'active' if active else 'inactive')
        await self.heartbeat.fault('fire_alarm_active', 'fire alarm active' if active else None)
        if active:
            await self.hvac.force_off()
            await notifications.send(Notification(title='Fire alarm', body='Fire alarm active. HVAC shut down and available lights commanded on.', priority='critical', category='life_safety'))
            if self.maintenance_lockout_active:
                rows = []
                await self.heartbeat.fault('output_command_inhibited', 'fire emergency lighting inhibited by maintenance lockout')
            else:
                async with db.acquire() as conn:
                    if self.emergency_lighting_logical_names:
                        rows = [{'logical_name': name} for name in self.emergency_lighting_logical_names]
                    else:
                        rows = await conn.fetch("""
                            SELECT logical_name
                            FROM logical_devices
                            WHERE device_class='light'
                              AND enabled=true
                              AND COALESCE((metadata->>'emergency_lighting')::boolean,false)=true
                        """)
            for r in rows:
                try:
                    await command_logical(
                        r['logical_name'],
                        {'op':'light','percent':100,'value':True},
                        source=OutputSource.LIFE_SAFETY,
                        safety_conditions={arbiter_mod.SafetyCondition.FIRE_ACTIVE.value},
                    )
                except Exception:
                    log.exception('failed life-safety light command: %s', r['logical_name'])
        else:
            for logical_device_id in await clear_source(OutputSource.LIFE_SAFETY):
                try:
                    await apply_active_intent(logical_device_id)
                except Exception:
                    log.exception('failed restoring output after life-safety clear: %s', logical_device_id)
