"""Native climate semantics and the non-physical HVAC request boundary."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable


class HVACRequestError(ValueError):
    """A climate request was invalid or blocked by policy."""


class HVACMode(str, Enum):
    OFF = "off"
    HEAT = "heat"
    COOL = "cool"
    FAN = "fan"


@dataclass(frozen=True)
class HVACControlRequest:
    operation: str
    entity_ref: int
    source: str = "service"
    temperature_f: float | None = None
    mode: HVACMode | None = None
    dry_run: bool = False


class HVACPolicy:
    """Safety gate for logical HVAC requests; it never commands outputs."""

    def __init__(self, safety: Any = None, *, commissioning: Callable[[], bool] | None = None):
        self.safety = safety
        self.commissioning = commissioning or (lambda: False)

    def check(self, request: HVACControlRequest) -> str | None:
        # Turning HVAC off remains permitted during a safety condition so the
        # request can reinforce the existing life-safety shutdown.
        if request.operation == "turn_off":
            return None
        if self.safety is not None and getattr(self.safety, "fire_active", False):
            return "fire_active"
        if self.safety is not None and getattr(self.safety, "maintenance_lockout_active", False):
            return "maintenance_lockout"
        if self.commissioning():
            return "commissioning_active"
        return None


class HVACSemanticLayer:
    """Validate requests and delegate them to the existing HVAC authority."""

    MIN_F = 45.0
    MAX_F = 95.0
    STEP_F = 0.5
    MODES = tuple(mode.value for mode in HVACMode)

    def __init__(self, controller: Any, *, policy: HVACPolicy | None = None,
                 context: Any = None):
        self.controller = controller
        self.policy = policy or HVACPolicy()
        self.context = context
        self.entity_ref: int | None = None

    async def start(self) -> int | None:
        if self.context is None:
            return None
        device = await self.context.device("hcm_hvac", "HCM HVAC", available=True)
        self.entity_ref = await self.context.entity(
            "hcm_hvac", "climate.hcm_hvac", device, "HCM HVAC", unit="°F", device_class="temperature"
        )
        await self.publish_state()
        return self.entity_ref

    async def publish_state(self):
        if self.context is None or self.entity_ref is None:
            return
        state = self.controller.state
        await self.context.state(
            self.entity_ref,
            state.mode.value.lower(),
            attributes={
                "temperature": float(state.setpoint_f),
                "current_temperature": self.controller.average_temperature(),
                "hvac_modes": list(self.MODES),
                "requested_mode": state.mode.value.lower(),
                "requested_temperature": float(state.setpoint_f),
                "effective_mode": state.mode.value.lower(),
                "effective_temperature": float(state.setpoint_f),
                "unit_of_measurement": "°F",
            },
            available=True,
        )

    def _validate_temperature(self, value: float) -> float:
        value = float(value)
        if not self.MIN_F <= value <= self.MAX_F:
            raise HVACRequestError("Temperature is outside the supported range")
        if abs((value / self.STEP_F) - round(value / self.STEP_F)) > 1e-9:
            raise HVACRequestError("Temperature does not match the supported step")
        return value

    async def _apply(self, request: HVACControlRequest) -> dict[str, Any]:
        blocked = self.policy.check(request)
        if blocked:
            return {"status": "blocked", "reason": blocked, "entity_ref": request.entity_ref}
        if request.dry_run:
            return {"status": "planned", "operation": request.operation, "entity_ref": request.entity_ref}
        if request.operation == "set_temperature":
            self.controller.state.setpoint_f = request.temperature_f
            await self.controller.persist_state()
            await self.controller.evaluate()
        elif request.operation == "set_hvac_mode":
            self.controller.state.mode = request.mode
            await self.controller.persist_state()
            if request.mode == HVACMode.OFF:
                await self.controller.force_off()
            else:
                await self.controller.evaluate()
        elif request.operation == "turn_off":
            self.controller.state.mode = HVACMode.OFF
            await self.controller.persist_state()
            await self.controller.force_off()
        else:
            raise HVACRequestError("Unsupported HVAC operation")
        await self.publish_state()
        return {"status": "accepted", "entity_ref": request.entity_ref,
                "mode": self.controller.state.mode.value.lower(),
                "temperature": float(self.controller.state.setpoint_f)}

    async def set_temperature(self, entity_ref: int, temperature: float, *, source="service", dry_run=False):
        return await self._apply(HVACControlRequest("set_temperature", int(entity_ref), source,
            temperature_f=self._validate_temperature(temperature), dry_run=dry_run))

    async def set_hvac_mode(self, entity_ref: int, mode: str, *, source="service", dry_run=False):
        try:
            selected = HVACMode(str(mode).lower())
        except ValueError:
            raise HVACRequestError("Unsupported HVAC mode") from None
        return await self._apply(HVACControlRequest("set_hvac_mode", int(entity_ref), source,
            mode=selected, dry_run=dry_run))

    async def turn_off(self, entity_ref: int, *, source="service", dry_run=False):
        return await self._apply(HVACControlRequest("turn_off", int(entity_ref), source, mode=HVACMode.OFF, dry_run=dry_run))
