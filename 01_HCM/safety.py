from __future__ import annotations
import asyncio
import json
import logging
import time
from importlib import import_module
from . import db
from .devices import apply_active_intent, command_logical
from .notifications import notifications, Notification
from .priority import OutputSource, clear_source

log = logging.getLogger(__name__)
fire_input_mod = import_module('07_servises.common.fire_input')
arbiter_mod = import_module('07_servises.common.safety_arbiter')
global_config = import_module('07_servises.common.global_config')


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
    def __init__(self, hvac, emergency_lighting_logical_names: list[str] | None = None, heartbeat: SafetyHeartbeatReporter | None = None, safety_relays=None, globals_=None):
        self.globals = globals_ or global_config.load_global_config('HCM')
        self.hvac = hvac
        self.fire_active = False
        self.alarm_contact_active = False
        self.alarm_contact_fault = True
        self.ac_power_present: bool | None = None
        self.ac_power_fault = True
        self.maintenance_lockout_active = False
        self.fire_input = fire_input_mod.DebouncedFireInput(
            alarm_level=bool(self.globals.Fire_Input_Alarm_High),
            debounce_seconds=float(self.globals.Fire_Contact_Debounce) / 1000.0,
        )
        self.alarm_contact_input = fire_input_mod.DebouncedFireInput(
            alarm_level=bool(self.globals.Fire_Input_Alarm_High),
            debounce_seconds=float(self.globals.Alarm_Contact_Debounce) / 1000.0,
        )
        self.ac_power_input = fire_input_mod.DebouncedFireInput(
            alarm_level=True,
            debounce_seconds=float(self.globals.Fire_Contact_Debounce) / 1000.0,
        )
        self.emergency_lighting_logical_names = list(emergency_lighting_logical_names or [])
        self.heartbeat = heartbeat or SafetyHeartbeatReporter()
        self.safety_relays = safety_relays

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
            await self.heartbeat.status('fire_alarm_s', 'unknown')
            await self.heartbeat.fault('fire_input_fault', 'fire input unknown or disconnected')
        else:
            await self.heartbeat.fault('fire_input_fault', None)
        if sample.changed:
            await self.heartbeat.status('fire_alarm_s', 'active' if sample.fire_active else 'normal')
            await self.set_fire(sample.fire_active)
        return sample

    async def sample_alarm_contact(self, level: bool | None, now: float | None = None):
        sample = self.alarm_contact_input.sample(level, time.monotonic() if now is None else now)
        if sample.fault:
            if not self.alarm_contact_fault:
                async with db.acquire() as conn:
                    await conn.execute('INSERT INTO safety_events(event_type,active,details) VALUES($1,$2,$3::jsonb)', 'alarm_contact_fault', True, '{"reason":"unknown_or_invalid"}')
            self.alarm_contact_fault = True
            await self.heartbeat.status('alarm_contact', 'unknown')
            await self.heartbeat.fault('alarm_contact_fault', 'alarm contact unknown or disconnected')
            return sample

        if self.alarm_contact_fault:
            async with db.acquire() as conn:
                await conn.execute('INSERT INTO safety_events(event_type,active,details) VALUES($1,$2,$3::jsonb)', 'alarm_contact_fault', False, '{}')
        self.alarm_contact_fault = False
        await self.heartbeat.fault('alarm_contact_fault', None)
        if sample.changed:
            self.alarm_contact_active = sample.fire_active
            async with db.acquire() as conn:
                await conn.execute('INSERT INTO safety_events(event_type,active,details) VALUES($1,$2,$3::jsonb)', 'alarm_contact', self.alarm_contact_active, '{}')
            await self.heartbeat.status('alarm_contact', 'active' if self.alarm_contact_active else 'inactive')
        return sample

    async def sample_alarm_contact_from_backend(self, now: float | None = None):
        if self.safety_relays is None:
            return await self.sample_alarm_contact(None, now)
        try:
            level = self.safety_relays.read_input('alarm_contact')
        except Exception:
            level = None
        return await self.sample_alarm_contact(level, now)

    async def sample_fire_input_from_backend(self, now: float | None = None):
        if self.safety_relays is None:
            return await self.sample_fire_input(None, time.monotonic() if now is None else now)
        try:
            level = self.safety_relays.read_input('fire_alarm_s')
        except Exception:
            level = None
        return await self.sample_fire_input(level, time.monotonic() if now is None else now)

    async def sample_ac_power_from_backend(self, now: float | None = None):
        sample_time = time.monotonic() if now is None else now
        level = None
        if self.safety_relays is not None:
            try:
                level = self.safety_relays.read_input('fire_alarm_P')
            except Exception:
                level = None
        if level is None:
            self.ac_power_input.sample(None, sample_time)
            self.ac_power_present = None
            self.ac_power_fault = True
            await self.heartbeat.status('fire_alarm_P', 'unknown')
            await self.heartbeat.fault('fire_alarm_P_fault', 'AC-present input unavailable')
            return {'state': 'unknown', 'fault': True, 'changed': False, 'sampled_at': sample_time}
        sample = self.ac_power_input.sample(bool(level), sample_time)
        if sample.fault:
            self.ac_power_present = None
            self.ac_power_fault = True
            await self.heartbeat.status('fire_alarm_P', 'unknown')
            await self.heartbeat.fault('fire_alarm_P_fault', 'AC-present input is debouncing or unavailable')
            return {'state': 'unknown', 'fault': True, 'changed': False, 'sampled_at': sample_time}
        present = bool(sample.fire_active)
        changed = sample.changed or present != self.ac_power_present
        self.ac_power_present = present
        self.ac_power_fault = False
        await self.heartbeat.fault('fire_alarm_P_fault', None)
        if changed:
            await self.heartbeat.status('fire_alarm_P', 'present' if present else 'absent')
        return {'state': 'present' if present else 'absent', 'fault': False, 'changed': changed, 'sampled_at': sample_time}

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
