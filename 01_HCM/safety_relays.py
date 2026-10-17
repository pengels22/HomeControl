from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from importlib import import_module
from typing import Any

common_global_config = import_module('07_servises.common.global_config')
physical_drivers = import_module('07_servises.common.physical_drivers')


@dataclass
class SafetyRelay:
    name: str
    gpio: int | str | None
    board_pin: int | None
    direction: str
    lockout_exempt: bool
    active: bool = False
    last_changed: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            'name': self.name,
            'gpio': self.gpio,
            'board_pin': self.board_pin,
            'direction': self.direction,
            'lockout_exempt': self.lockout_exempt,
            'active': self.active,
            'last_changed': self.last_changed,
        }


class SimulatedSafetyRelayBackend:
    def __init__(self):
        self.states: dict[str, bool] = {}
        self.input_states: dict[str, bool | None] = {
            'fire_alarm_s': False,
            'fire_alarm_P': True,
            # Compatibility name for older authenticated status consumers.
            'alarm_contact': False,
        }

    async def write(self, relay: SafetyRelay, active: bool) -> None:
        if relay.direction != 'output':
            raise ValueError('%s is not an output relay' % relay.name)
        self.states[relay.name] = bool(active)

    def read(self, relay: SafetyRelay) -> bool | None:
        if relay.direction != 'input':
            raise ValueError('%s is not an input relay' % relay.name)
        value = self.input_states.get(relay.name)
        if value is None:
            return None
        return bool(value)

    def set_input(self, name: str, value: bool | None) -> None:
        value = None if value is None else bool(value)
        self.input_states[name] = value
        if name == 'alarm_contact':
            self.input_states['fire_alarm_s'] = value
        elif name == 'fire_alarm_s':
            self.input_states['alarm_contact'] = value


class LinuxSafetyInputBackend:
    """Explicit read-only Jetson GPIO backend for the two safety inputs."""

    def __init__(self):
        self.inputs = {
            'fire_alarm_s': physical_drivers.LinuxGPIOInputTransport('/dev/gpiochip0', 159, 'homecontrol-fire-alarm-s'),
            'fire_alarm_P': physical_drivers.LinuxGPIOInputTransport('/dev/gpiochip0', 158, 'homecontrol-fire-alarm-P'),
        }

    def read(self, relay: SafetyRelay) -> bool:
        if relay.name not in self.inputs:
            raise ValueError('%s is not a Linux safety input' % relay.name)
        return self.inputs[relay.name].read()

    async def write(self, relay: SafetyRelay, active: bool) -> None:
        raise ValueError('safety GPIO inputs are read-only')

    def close(self) -> None:
        for input_ in self.inputs.values():
            input_.close()


class HCMSafetyRelayController:
    @classmethod
    def from_linux(cls, globals_=None):
        return cls(backend=LinuxSafetyInputBackend(), globals_=globals_)

    def __init__(self, backend: SimulatedSafetyRelayBackend | None = None, globals_=None):
        self.globals = globals_ or common_global_config.load_global_config('HCM')
        self.backend = backend or SimulatedSafetyRelayBackend()
        fire_s = SafetyRelay('fire_alarm_s', gpio='/dev/gpiochip0:159', board_pin=38, direction='input', lockout_exempt=True)
        fire_p = SafetyRelay('fire_alarm_P', gpio='/dev/gpiochip0:158', board_pin=40, direction='input', lockout_exempt=True)
        self.relays = {
            'fire_alarm_s': fire_s,
            'fire_alarm_P': fire_p,
            # Compatibility name for the legacy alarm-contact API.
            'alarm_contact': fire_s,
            'door_request': SafetyRelay('door_request', gpio='UNVERIFIED', board_pin=None, direction='output', lockout_exempt=True),
            'auxiliary': SafetyRelay('auxiliary', gpio='UNVERIFIED', board_pin=None, direction='output', lockout_exempt=True),
        }
        self._pulse_tasks: dict[str, asyncio.Task] = {}

    def status(self) -> dict[str, Any]:
        return {
            'mode': 'simulated_gpio',
            'maintenance_lockout_exempt': True,
            'fire_alarm_s': self.read_input('fire_alarm_s'),
            'fire_alarm_P': self.read_input('fire_alarm_P'),
            'alarm_contact': self.read_input('alarm_contact'),
            'relays': {name: relay.as_dict() for name, relay in self.relays.items()},
        }

    def _validate_output(self, name: str) -> SafetyRelay:
        if name not in self.relays:
            raise KeyError(name)
        relay = self.relays[name]
        if relay.direction != 'output':
            raise ValueError('%s is an input, not a relay output' % name)
        return relay

    def _validate_input(self, name: str) -> SafetyRelay:
        if name not in self.relays:
            raise KeyError(name)
        relay = self.relays[name]
        if relay.direction != 'input':
            raise ValueError('%s is an output, not an input' % name)
        return relay

    def read_input(self, name: str) -> bool | None:
        return self.backend.read(self._validate_input(name))

    def set_simulated_input(self, name: str, value: bool | None) -> dict[str, Any]:
        self._validate_input(name)
        self.backend.set_input(name, value)
        return {'ok': True, 'name': name, 'value': self.read_input(name)}

    def _validate_pulse_ms(self, duration_ms: int | None) -> int:
        value = int(self.globals.Door_Open_Pulse if duration_ms is None else duration_ms)
        if value < int(self.globals.Door_Open_Pulse_Min) or value > int(self.globals.Door_Open_Pulse_Max):
            raise ValueError('pulse duration must be between %s and %s ms' % (
                self.globals.Door_Open_Pulse_Min,
                self.globals.Door_Open_Pulse_Max,
            ))
        return value

    async def set_output(self, name: str, active: bool) -> dict[str, Any]:
        relay = self._validate_output(name)
        relay.active = bool(active)
        relay.last_changed = time.time()
        await self.backend.write(relay, relay.active)
        return {'ok': True, 'relay': relay.as_dict()}

    async def cancel_pulse(self, name: str, deenergize: bool = True) -> bool:
        task = self._pulse_tasks.pop(name, None)
        cancelled = bool(task and not task.done())
        if cancelled:
            task.cancel()
        if deenergize and name in self.relays and self.relays[name].direction == 'output':
            await self.set_output(name, False)
        return cancelled

    async def pulse(self, name: str = 'door_request', duration_ms: int | None = None) -> dict[str, Any]:
        relay = self._validate_output(name)
        pulse_ms = self._validate_pulse_ms(duration_ms)
        await self.cancel_pulse(name, deenergize=False)
        await self.set_output(name, True)
        task = asyncio.ensure_future(self._complete_pulse(relay, pulse_ms / 1000.0))
        self._pulse_tasks[name] = task
        return {'ok': True, 'relay': relay.as_dict(), 'pulse_ms': pulse_ms, 'policy': 'restart_existing_pulse'}

    async def _complete_pulse(self, relay: SafetyRelay, delay_s: float) -> None:
        try:
            await asyncio.sleep(delay_s)
            await self.set_output(relay.name, False)
        finally:
            if self._pulse_tasks.get(relay.name) is asyncio.current_task():
                self._pulse_tasks.pop(relay.name, None)

    async def shutdown(self) -> None:
        for name in list(self._pulse_tasks):
            await self.cancel_pulse(name)
        for relay in self.relays.values():
            if relay.direction == 'output':
                await self.set_output(relay.name, False)
        close = getattr(self.backend, 'close', None)
        if close is not None:
            close()
