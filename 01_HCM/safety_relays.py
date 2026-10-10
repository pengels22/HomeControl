from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from importlib import import_module
from typing import Any

common_global_config = import_module('07_servises.common.global_config')


@dataclass
class SafetyRelay:
    name: str
    gpio: int
    board_pin: int
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

    async def write(self, relay: SafetyRelay, active: bool) -> None:
        if relay.direction != 'output':
            raise ValueError('%s is not an output relay' % relay.name)
        self.states[relay.name] = bool(active)


class HCMSafetyRelayController:
    def __init__(self, backend: SimulatedSafetyRelayBackend | None = None, globals_=None):
        self.globals = globals_ or common_global_config.load_global_config('HCM')
        self.backend = backend or SimulatedSafetyRelayBackend()
        self.relays = {
            'alarm_contact': SafetyRelay('alarm_contact', gpio=393, board_pin=15, direction='input', lockout_exempt=True),
            'door_request': SafetyRelay('door_request', gpio=256, board_pin=16, direction='output', lockout_exempt=True),
            'auxiliary': SafetyRelay('auxiliary', gpio=344, board_pin=18, direction='output', lockout_exempt=True),
        }
        self._pulse_tasks: dict[str, asyncio.Task] = {}

    def status(self) -> dict[str, Any]:
        return {
            'mode': 'simulated_gpio',
            'maintenance_lockout_exempt': True,
            'relays': {name: relay.as_dict() for name, relay in self.relays.items()},
        }

    def _validate_output(self, name: str) -> SafetyRelay:
        if name not in self.relays:
            raise KeyError(name)
        relay = self.relays[name]
        if relay.direction != 'output':
            raise ValueError('%s is an input, not a relay output' % name)
        return relay

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

    def cancel_pulse(self, name: str) -> bool:
        task = self._pulse_tasks.pop(name, None)
        if task and not task.done():
            task.cancel()
            return True
        return False

    async def pulse(self, name: str = 'door_request', duration_ms: int | None = None) -> dict[str, Any]:
        relay = self._validate_output(name)
        pulse_ms = self._validate_pulse_ms(duration_ms)
        self.cancel_pulse(name)
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
            self.cancel_pulse(name)
        for relay in self.relays.values():
            if relay.direction == 'output':
                await self.set_output(relay.name, False)
