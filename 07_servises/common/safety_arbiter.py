from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SafetyCondition(str, Enum):
    MAINTENANCE_LOCKOUT = "maintenance_lockout"
    FIRE_ACTIVE = "fire_active"
    FIRE_INPUT_FAULT = "fire_input_fault"
    COMMUNICATION_LOSS = "communication_loss"
    ARBITER_FAULT = "arbiter_fault"


class ControlSource(str, Enum):
    MAINTENANCE = "maintenance"
    LIFE_SAFETY = "life_safety"
    LOCAL_OVERRIDE = "local_override"
    USER = "user"
    RULES = "rules"
    SCHEDULE = "schedule"
    SCENE = "scene"
    MODULE_API = "module_api"


@dataclass
class OutputState:
    energized: bool = False
    percent: float = 0.0

    def to_command(self, original: dict[str, Any] | None = None) -> dict[str, Any]:
        command = dict(original or {})
        if "percent" in command or command.get("op") in ("light", "set_dimmer") or self.percent not in (0.0, 100.0):
            command["percent"] = 0.0 if not self.energized else self.percent
        command["value"] = bool(self.energized)
        return command


@dataclass
class OutputRequest:
    device_id: str | None
    channel_id: str
    command: dict[str, Any]
    source: str | ControlSource
    requested_at: float = field(default_factory=time.time)


@dataclass
class OutputDecision:
    device_id: str | None
    channel_id: str
    requested_state: OutputState
    effective_state: OutputState
    feedback_state: OutputState | None
    control_source: str
    active_safety_conditions: list[str]
    inhibited: bool
    reason: str | None
    final_command: dict[str, Any]
    last_transition: float
    fault_state: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "channel_id": self.channel_id,
            "requested_state": {
                "energized": self.requested_state.energized,
                "percent": self.requested_state.percent,
            },
            "effective_state": {
                "energized": self.effective_state.energized,
                "percent": self.effective_state.percent,
            },
            "feedback_state": None if self.feedback_state is None else {
                "energized": self.feedback_state.energized,
                "percent": self.feedback_state.percent,
            },
            "control_source": self.control_source,
            "active_safety_conditions": list(self.active_safety_conditions),
            "inhibited": self.inhibited,
            "reason": self.reason,
            "final_command": dict(self.final_command),
            "last_transition": self.last_transition,
            "fault_state": self.fault_state,
        }


def coerce_output_state(command: dict[str, Any] | None) -> OutputState:
    command = command or {}
    raw_percent = command.get("percent")
    raw_value = command.get("value")
    if raw_percent is not None:
        percent = max(0.0, min(100.0, float(raw_percent)))
        return OutputState(energized=percent > 0.0, percent=percent)
    if isinstance(raw_value, bool):
        return OutputState(energized=raw_value, percent=100.0 if raw_value else 0.0)
    if raw_value is None:
        return OutputState(False, 0.0)
    try:
        percent = max(0.0, min(100.0, float(raw_value)))
        return OutputState(energized=percent > 0.0, percent=percent)
    except (TypeError, ValueError):
        return OutputState(energized=bool(raw_value), percent=100.0 if raw_value else 0.0)


def deenergized_state() -> OutputState:
    return OutputState(False, 0.0)


class SafetyArbiter:
    def __init__(
        self,
        emergency_lighting_channels: set[str] | None = None,
        hvac_shutdown_channels: set[str] | None = None,
        default_to_safe_on_unknown: bool = True,
    ):
        self.emergency_lighting_channels = {str(ch).upper() for ch in (emergency_lighting_channels or set())}
        self.hvac_shutdown_channels = {str(ch).upper() for ch in (hvac_shutdown_channels or set())}
        self.default_to_safe_on_unknown = bool(default_to_safe_on_unknown)
        self.conditions: set[SafetyCondition] = set()
        self.decisions: dict[str, OutputDecision] = {}

    def set_condition(self, condition: str | SafetyCondition, active: bool) -> None:
        cond = condition if isinstance(condition, SafetyCondition) else SafetyCondition(str(condition))
        if active:
            self.conditions.add(cond)
        else:
            self.conditions.discard(cond)

    def update_conditions(self, conditions: dict[str, bool] | None) -> None:
        for name, active in (conditions or {}).items():
            try:
                self.set_condition(name, bool(active))
            except ValueError:
                continue

    def snapshot(self) -> dict[str, Any]:
        return {
            "conditions": sorted(c.value for c in self.conditions),
            "outputs": {key: decision.as_dict() for key, decision in self.decisions.items()},
        }

    def decide(
        self,
        request: OutputRequest,
        local_conditions: set[str | SafetyCondition] | None = None,
        feedback_state: OutputState | None = None,
    ) -> OutputDecision:
        conditions = set(self.conditions)
        for condition in local_conditions or set():
            conditions.add(condition if isinstance(condition, SafetyCondition) else SafetyCondition(str(condition)))
        requested = coerce_output_state(request.command)
        channel = str(request.channel_id).upper()
        effective = requested
        inhibited = False
        reason = None
        fault_state = None

        if SafetyCondition.ARBITER_FAULT in conditions:
            effective = deenergized_state()
            inhibited = requested.energized
            reason = SafetyCondition.ARBITER_FAULT.value
            fault_state = "arbiter_fault"
        elif SafetyCondition.MAINTENANCE_LOCKOUT in conditions:
            effective = deenergized_state()
            inhibited = requested.energized
            reason = SafetyCondition.MAINTENANCE_LOCKOUT.value
        elif SafetyCondition.FIRE_INPUT_FAULT in conditions and self.default_to_safe_on_unknown:
            effective = deenergized_state()
            inhibited = requested.energized
            reason = SafetyCondition.FIRE_INPUT_FAULT.value
            fault_state = "fire_input_fault"
        elif SafetyCondition.COMMUNICATION_LOSS in conditions and self.default_to_safe_on_unknown:
            effective = deenergized_state()
            inhibited = requested.energized
            reason = SafetyCondition.COMMUNICATION_LOSS.value
            fault_state = "communication_loss"
        elif SafetyCondition.FIRE_ACTIVE in conditions:
            if channel in self.emergency_lighting_channels:
                effective = OutputState(True, 100.0)
                inhibited = requested.percent != 100.0 or not requested.energized
                reason = SafetyCondition.FIRE_ACTIVE.value
            elif channel in self.hvac_shutdown_channels:
                effective = deenergized_state()
                inhibited = requested.energized
                reason = SafetyCondition.FIRE_ACTIVE.value

        if feedback_state is not None and feedback_state.energized != effective.energized:
            fault_state = "feedback_mismatch"

        decision = OutputDecision(
            device_id=request.device_id,
            channel_id=channel,
            requested_state=requested,
            effective_state=effective,
            feedback_state=feedback_state,
            control_source=str(request.source.value if isinstance(request.source, ControlSource) else request.source),
            active_safety_conditions=sorted(c.value for c in conditions),
            inhibited=inhibited,
            reason=reason,
            final_command=effective.to_command(request.command),
            last_transition=time.time(),
            fault_state=fault_state,
        )
        self.decisions[channel] = decision
        return decision

    def deenergize_all(self, channels: list[str], source: str = ControlSource.MAINTENANCE.value) -> list[OutputDecision]:
        return [
            self.decide(OutputRequest(None, channel, {"value": False, "percent": 0}, source))
            for channel in channels
        ]
