"""Provider-neutral alarm/security semantics.

This module is deliberately separate from the fire/life-safety authority.  It
contains request validation and controller ownership only; providers decide the
authoritative state transition and publish it through the normal entity path.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict


class AlarmMode(str, Enum):
    HOME = "home"
    AWAY = "away"
    VACATION = "vacation"


VALID_STATES = {"disarmed", "arming", "armed_home", "armed_away",
                "armed_vacation", "pending", "triggered", "unavailable"}


class AlarmRequestError(ValueError):
    pass


class AlarmServiceArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    credential_ref: str | None = None


@dataclass(frozen=True)
class AlarmCapabilities:
    arm_modes: frozenset[AlarmMode] = frozenset({AlarmMode.HOME, AlarmMode.AWAY})
    arm_requires_credential: bool = False
    disarm_requires_credential: bool = True
    automation_disarm_allowed: bool = False


@dataclass(frozen=True)
class AlarmControlRequest:
    entity_ref: int
    operation: str
    mode: AlarmMode | None = None
    source: str = "service"
    caller: str | None = None
    credential_ref: str | None = None
    credential_configured: bool = False
    dry_run: bool = False


class AlarmController(Protocol):
    capabilities: AlarmCapabilities
    state: str

    async def request_arm(self, mode: AlarmMode, request: AlarmControlRequest) -> dict[str, Any]: ...
    async def request_disarm(self, request: AlarmControlRequest) -> dict[str, Any]: ...


@dataclass
class AlarmPolicy:
    """Conservative policy boundary applied before a controller request."""

    def check(self, request: AlarmControlRequest, capabilities: AlarmCapabilities) -> str | None:
        if request.operation not in {"arm", "disarm"}:
            return "invalid_operation"
        if request.operation == "arm":
            if request.mode not in capabilities.arm_modes:
                return "unsupported_mode"
            if capabilities.arm_requires_credential and not request.credential_configured:
                return "credential_required"
        else:
            if request.source == "automation" and not capabilities.automation_disarm_allowed:
                return "automation_disarm_denied"
            if capabilities.disarm_requires_credential and not request.credential_configured:
                return "credential_required"
        return None


class SecurityAlarmLayer:
    """Serialize semantic requests and publish controller-owned state."""

    def __init__(self, controller: AlarmController, *, entity_ref: int,
                 context: Any = None, policy: AlarmPolicy | None = None):
        self.controller = controller
        self.entity_ref = int(entity_ref)
        self.context = context
        self.policy = policy or AlarmPolicy()
        self._lock = asyncio.Lock()

    @property
    def state(self) -> str:
        if hasattr(self.controller, "available") and not bool(self.controller.available):
            return "unavailable"
        value = str(self.controller.state)
        return value if value in VALID_STATES else "unavailable"

    async def _publish(self):
        if self.context is not None:
            await self.context.state(self.entity_ref, self.state, attributes={
                "supported_arm_modes": sorted(mode.value for mode in self.controller.capabilities.arm_modes),
                "arm_requires_credential": self.controller.capabilities.arm_requires_credential,
                "disarm_requires_credential": self.controller.capabilities.disarm_requires_credential,
            }, available=self.state != "unavailable")

    async def _request(self, request: AlarmControlRequest) -> dict[str, Any]:
        async with self._lock:
            if self.state == "unavailable":
                return {"status": "controller_unavailable", "entity_ref": self.entity_ref}
            reason = self.policy.check(request, self.controller.capabilities)
            if reason:
                return {"status": "policy_rejected" if reason != "credential_required" else "credential_required",
                        "reason": reason, "entity_ref": self.entity_ref,
                        "credential_present": bool(request.credential_configured)}
            if request.dry_run:
                return {"status": "dry_run", "operation": request.operation,
                        "mode": request.mode.value if request.mode else None,
                        "entity_ref": self.entity_ref,
                        "credential_present": bool(request.credential_configured)}
            if request.operation == "arm" and self.state == f"armed_{request.mode.value}":
                return {"status": "no_change", "entity_ref": self.entity_ref, "state": self.state}
            if request.operation == "disarm" and self.state == "disarmed":
                return {"status": "no_change", "entity_ref": self.entity_ref, "state": self.state}
            result = await (self.controller.request_arm(request.mode, request) if request.operation == "arm"
                            else self.controller.request_disarm(request))
            await self._publish()
            return {"entity_ref": self.entity_ref, "credential_present": bool(request.credential_configured), **result}

    async def arm(self, mode: str, *, source="service", caller=None, credential_ref=None,
                  credential_configured=False, dry_run=False):
        try:
            selected = AlarmMode(str(mode).lower())
        except ValueError:
            return {"status": "invalid_mode", "entity_ref": self.entity_ref}
        return await self._request(AlarmControlRequest(self.entity_ref, "arm", selected, source, caller,
                                                        credential_ref, credential_configured, dry_run))

    async def disarm(self, *, source="service", caller=None, credential_ref=None,
                     credential_configured=False, dry_run=False):
        return await self._request(AlarmControlRequest(self.entity_ref, "disarm", None, source, caller,
                                                        credential_ref, credential_configured, dry_run))


@dataclass
class MockAlarmController:
    """Deterministic test controller; it performs no external security action."""

    capabilities: AlarmCapabilities = field(default_factory=lambda: AlarmCapabilities(
        arm_modes=frozenset({AlarmMode.HOME, AlarmMode.AWAY, AlarmMode.VACATION}),
        arm_requires_credential=False, disarm_requires_credential=True,
        automation_disarm_allowed=False))
    state: str = "disarmed"
    available: bool = True

    async def request_arm(self, mode: AlarmMode, request: AlarmControlRequest) -> dict[str, Any]:
        if not self.available:
            self.state = "unavailable"
            return {"status": "controller_unavailable"}
        self.state = "arming"
        self.state = f"armed_{mode.value}"
        return {"status": "accepted", "state": self.state}

    async def request_disarm(self, request: AlarmControlRequest) -> dict[str, Any]:
        if not self.available:
            self.state = "unavailable"
            return {"status": "controller_unavailable"}
        self.state = "disarmed"
        return {"status": "accepted", "state": self.state}

    def trigger(self):
        self.state = "triggered"
