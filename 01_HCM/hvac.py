from __future__ import annotations
import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from typing import Awaitable, Callable

class Mode(str, Enum):
    OFF='OFF'; HEAT='HEAT'; COOL='COOL'; FAN='FAN'

@dataclass
class RoomReading:
    room: str
    temperature_f: float
    occupied: bool
    actuated_damper: bool = True
    damper_logical_device: str | None = None
    sensor_ok: bool = True

@dataclass
class HVACState:
    mode: Mode = Mode.OFF
    setpoint_f: float = 70.0
    fan: bool = False
    heat: bool = False
    cool: bool = False
    call_started_at: float | None = None
    last_heat_off: float = 0.0
    last_cool_off: float = 0.0
    postrun_until: float = 0.0

class HVACController:
    DEADBAND_F = 1.0
    DAMPER_LEAD_S = 0.5
    FAN_LEAD_S = 0.5
    FAN_POSTRUN_S = 60.0
    COOL_MIN_RUN_S = 120.0
    HEAT_MIN_RUN_S = 60.0
    RESTART_LOCKOUT_S = 300.0

    def __init__(self, output: Callable[[str,bool], Awaitable[None]], damper: Callable[[RoomReading,bool], Awaitable[None]]):
        self.state = HVACState()
        self.rooms: dict[str, RoomReading] = {}
        self.output = output
        self.damper = damper
        self._lock = asyncio.Lock()

    def control_rooms(self) -> list[RoomReading]:
        # Permanently-open rooms are always part of the house average. Actuated rooms matter only while occupied.
        return [r for r in self.rooms.values() if r.sensor_ok and (not r.actuated_damper or r.occupied)]

    def average_temperature(self) -> float | None:
        rs = self.control_rooms()
        return None if not rs else sum(r.temperature_f for r in rs)/len(rs)

    async def _set_output(self, name: str, value: bool):
        await self.output(name, value)
        setattr(self.state, name.lower(), value)

    async def _open_needed_dampers(self, heating: bool):
        for r in self.rooms.values():
            if not r.actuated_damper:
                continue
            if not r.sensor_ok:
                await self.damper(r, True)  # fail open
                continue
            if not r.occupied:
                await self.damper(r, False)
                continue
            needs = r.temperature_f < self.state.setpoint_f if heating else r.temperature_f > self.state.setpoint_f
            await self.damper(r, needs)

    async def force_off(self):
        async with self._lock:
            now = time.monotonic()
            if self.state.cool:
                await self._set_output('COOL', False); self.state.last_cool_off = now
            if self.state.heat:
                await self._set_output('HEAT', False); self.state.last_heat_off = now
            if self.state.fan:
                await self._set_output('FAN', False)
            self.state.postrun_until = 0
            self.state.call_started_at = None

    async def evaluate(self):
        async with self._lock:
            now = time.monotonic()
            mode = self.state.mode
            avg = self.average_temperature()

            if mode == Mode.OFF or (not any(r.occupied for r in self.rooms.values())):
                await self._stop_conditioning(now, immediate_fan_off=True)
                return

            if mode == Mode.FAN:
                if self.state.heat: await self._set_output('HEAT', False); self.state.last_heat_off = now
                if self.state.cool: await self._set_output('COOL', False); self.state.last_cool_off = now
                if not self.state.fan: await self._set_output('FAN', True)
                return

            if avg is None:
                await self._stop_conditioning(now, immediate_fan_off=False)
                return

            if mode == Mode.COOL:
                if self.state.cool:
                    if avg <= self.state.setpoint_f and now - (self.state.call_started_at or now) >= self.COOL_MIN_RUN_S:
                        await self._stop_conditioning(now, immediate_fan_off=False)
                elif avg >= self.state.setpoint_f + self.DEADBAND_F and now - self.state.last_cool_off >= self.RESTART_LOCKOUT_S:
                    await self._start_conditioning(cooling=True)

            elif mode == Mode.HEAT:
                if self.state.heat:
                    if avg >= self.state.setpoint_f and now - (self.state.call_started_at or now) >= self.HEAT_MIN_RUN_S:
                        await self._stop_conditioning(now, immediate_fan_off=False)
                elif avg <= self.state.setpoint_f - self.DEADBAND_F and now - self.state.last_heat_off >= self.RESTART_LOCKOUT_S:
                    await self._start_conditioning(cooling=False)

            if not self.state.heat and not self.state.cool and self.state.fan and mode != Mode.FAN and now >= self.state.postrun_until:
                await self._set_output('FAN', False)

    async def _start_conditioning(self, cooling: bool):
        await self._open_needed_dampers(heating=not cooling)
        await asyncio.sleep(self.DAMPER_LEAD_S)
        if not self.state.fan: await self._set_output('FAN', True)
        await asyncio.sleep(self.FAN_LEAD_S)
        await self._set_output('COOL' if cooling else 'HEAT', True)
        self.state.call_started_at = time.monotonic()

    async def _stop_conditioning(self, now: float, immediate_fan_off: bool):
        changed = False
        if self.state.cool:
            await self._set_output('COOL', False); self.state.last_cool_off = now; changed=True
        if self.state.heat:
            await self._set_output('HEAT', False); self.state.last_heat_off = now; changed=True
        self.state.call_started_at = None
        if immediate_fan_off:
            if self.state.fan: await self._set_output('FAN', False)
            self.state.postrun_until = 0
        elif changed:
            self.state.postrun_until = now + self.FAN_POSTRUN_S
