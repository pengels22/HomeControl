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
fire_input_mod = import_module('08_servises.common.fire_input')
arbiter_mod = import_module('08_servises.common.safety_arbiter')
global_config = import_module('08_servises.common.global_config')


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
        self._fire_hvac_complete = False
        self._fire_metadata_complete = False
        self._fire_lights_complete: set[str] = set()
        self._fire_lighting_complete = False
        self._fire_event_recorded = False
        self.alarm_contact_active = False
        self.alarm_contact_fault = True
        self.ac_power_present: bool | None = None
        self.ac_power_fault = True
        self.fire_input_fault = True
        self.last_input_sample_wall: float | None = None
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

    def status_payload(self) -> dict:
        age = None if self.last_input_sample_wall is None else max(0.0, time.time() - self.last_input_sample_wall)
        fresh = age is not None and age <= 2.0
        fire = 'unknown' if self.fire_input_fault or not fresh else ('active' if self.fire_active else 'normal')
        ac = 'unknown' if self.ac_power_fault or not fresh else ('present' if self.ac_power_present else 'absent')
        return {
            'status': 'Active' if fire == 'active' else 'Normal' if fire == 'normal' else 'Unknown',
            'maintenance_lockout_active': self.maintenance_lockout_active,
            'system_state': self.state(),
            'fire_active': self.fire_active,
            'physical_input_authoritative': self.physical_fire_input_authoritative(),
            'fire_alarm_s': {'state': fire, 'fault': fire == 'unknown', 'fresh': fresh, 'age_seconds': age},
            'fire_alarm_P': {'state': ac, 'fault': ac == 'unknown', 'fresh': fresh, 'age_seconds': age},
            'source': 'Physical input' if self.physical_fire_input_authoritative() else 'Simulation',
        }

    async def sample_fire_input(self, level: bool | None, now: float):
        self.last_input_sample_wall = time.time()
        sample = self.fire_input.sample(level, now)
        self.fire_input_fault = bool(sample.fault)
        if sample.fault:
            for report in (self.heartbeat.status('fire_alarm_s', 'unknown'), self.heartbeat.fault('fire_input_fault', 'fire input unknown or disconnected')):
                try:
                    await report
                except Exception:
                    log.exception('fire input heartbeat reporting failed')
        else:
            try:
                await self.heartbeat.fault('fire_input_fault', None)
            except Exception:
                log.exception('fire input heartbeat reporting failed')
        if not sample.fault:
            if self.fire_active != sample.fire_active:
                try:
                    await self.heartbeat.status('fire_alarm_s', 'active' if sample.fire_active else 'normal')
                except Exception:
                    log.exception('fire input heartbeat reporting failed')
            if self.fire_active != sample.fire_active or (self.fire_active and not (self._fire_hvac_complete and self._fire_metadata_complete and self._fire_lighting_complete and self._fire_event_recorded)):
                await self.set_fire(sample.fire_active, source='physical')
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
        self.last_input_sample_wall = time.time()
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
        await self.heartbeat.fault(
            'fire_alarm_P_power_loss',
            'smoke alarm AC supply absent' if not present else None,
        )
        if changed:
            await self.heartbeat.status('fire_alarm_P', 'present' if present else 'absent')
        return {'state': 'present' if present else 'absent', 'fault': False, 'changed': changed, 'sampled_at': sample_time}

    async def set_maintenance_lockout(self, active: bool):
        was_active = self.maintenance_lockout_active
        self.maintenance_lockout_active = bool(active)
        try:
            await self.heartbeat.status('maintenance_lockout', 'active' if active else 'inactive')
        except Exception:
            log.exception('maintenance lockout heartbeat reporting failed')
        if was_active and not active and self.fire_active:
            self._fire_lighting_complete = False
            await self.set_fire(True, source='physical' if self.physical_fire_input_authoritative() else 'software')

    def physical_fire_input_authoritative(self) -> bool:
        return bool(getattr(self.safety_relays and self.safety_relays.backend, 'physical_input_authoritative', False))

    async def set_fire(self, active: bool, *, source: str = 'software'):
        if self.physical_fire_input_authoritative() and source != 'physical':
            raise PermissionError('physical fire input is authoritative')
        changed = active != self.fire_active
        if not changed and not active:
            return
        self.fire_active = active
        if changed:
            self._fire_event_recorded = False
        if active:
            if changed:
                self._fire_hvac_complete = False
                self._fire_metadata_complete = False
                self._fire_lights_complete.clear()
                self._fire_lighting_complete = False
            if not self._fire_hvac_complete:
                try:
                    hvac_result = await self.hvac.force_off()
                    self._fire_hvac_complete = not isinstance(hvac_result, dict) or hvac_result.get('ok', True)
                    if not self._fire_hvac_complete:
                        log.error('life-safety HVAC shutdown had output failures: %s', hvac_result.get('failures'))
                except Exception:
                    log.exception('life-safety HVAC shutdown failed')
            from .channel_registry import fire_shutdown
            if not self._fire_metadata_complete:
                try:
                    metadata_failures = await fire_shutdown()
                    self._fire_metadata_complete = not metadata_failures
                    if metadata_failures:
                        log.error('Metadata HVAC safety shutdown failures: %s', metadata_failures)
                except Exception:
                    log.exception('Metadata HVAC safety shutdown failed')
            if self.maintenance_lockout_active:
                rows = []
                self._fire_lighting_complete = True
                try:
                    await self.heartbeat.fault('output_command_inhibited', 'fire emergency lighting inhibited by maintenance lockout')
                except Exception:
                    log.exception('fire lockout heartbeat reporting failed')
            else:
                if self.emergency_lighting_logical_names:
                    rows = [{'logical_name': name} for name in self.emergency_lighting_logical_names]
                    self._fire_lighting_complete = True
                else:
                    try:
                        async with db.acquire() as conn:
                            rows = await conn.fetch("""
                            SELECT DISTINCT d.logical_name
                            FROM logical_devices d
                            LEFT JOIN device_bindings b ON b.logical_device_id=d.id AND b.enabled
                            LEFT JOIN channel_metadata c ON c.module_id=b.module_id AND c.channel_id=b.channel
                            WHERE d.enabled AND (
                                (c.id IS NOT NULL AND c.enabled AND c.purpose='LIGHTING' AND c.emergency)
                                OR (c.id IS NULL AND d.device_class='light' AND COALESCE((d.metadata->>'emergency_lighting')::boolean,false)))
                        """)
                        self._fire_lighting_complete = True
                    except Exception:
                        rows = []
                        self._fire_lighting_complete = False
                        log.exception('fire emergency-light lookup failed')
            for r in rows:
                if r['logical_name'] in self._fire_lights_complete:
                    continue
                try:
                    result = await command_logical(
                        r['logical_name'],
                        {'op':'light','percent':100,'value':True},
                        source=OutputSource.LIFE_SAFETY,
                        safety_conditions={arbiter_mod.SafetyCondition.FIRE_ACTIVE.value},
                    )
                    if not isinstance(result, dict) or result.get('ok', True):
                        self._fire_lights_complete.add(r['logical_name'])
                    else:
                        self._fire_lighting_complete = False
                        log.error('life-safety light command rejected: %s: %s', r['logical_name'], result)
                except Exception:
                    self._fire_lighting_complete = False
                    log.exception('failed life-safety light command: %s', r['logical_name'])
            if changed:
                try:
                    await notifications.send(Notification(title='Fire alarm', body='Fire alarm active. HVAC shutdown initiated. Emergency lighting actions initiated where permitted.', priority='critical', category='life_safety'))
                except Exception:
                    log.exception('fire notification failed')
        else:
            self._fire_hvac_complete = False
            self._fire_metadata_complete = False
            self._fire_lights_complete.clear()
            self._fire_lighting_complete = False
            for logical_device_id in await clear_source(OutputSource.LIFE_SAFETY):
                try:
                    await apply_active_intent(logical_device_id)
                except Exception:
                    log.exception('failed restoring output after life-safety clear: %s', logical_device_id)
        if changed or not self._fire_event_recorded:
            try:
                async with db.acquire() as conn:
                    await conn.execute('INSERT INTO safety_events(event_type,active,details) VALUES($1,$2,$3::jsonb)', 'fire', active, '{}')
                self._fire_event_recorded = True
            except Exception:
                log.exception('fire safety event persistence failed')
        if changed:
            for report in (
                self.heartbeat.status('fire_alarm', 'active' if active else 'inactive'),
                self.heartbeat.fault('fire_alarm_active', 'fire alarm active' if active else None),
            ):
                try:
                    await report
                except Exception:
                    log.exception('fire heartbeat reporting failed')
