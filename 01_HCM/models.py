from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Any, Literal

class RoomStateIn(BaseModel):
    room_id: int | None = Field(default=None, gt=0)
    room: str
    temperature_f: float
    occupied: bool = False
    actuated_damper: bool = True
    damper_logical_device: str | None = None
    sensor_ok: bool = True

class HvacSetpointIn(BaseModel):
    setpoint_f: float = Field(ge=45, le=90)

class HvacModeIn(BaseModel):
    mode: Literal['OFF','HEAT','COOL','FAN']

class DeviceCommand(BaseModel):
    logical_name: str
    command: dict[str, Any]

class CommandIn(BaseModel):
    text: str = Field(min_length=1, max_length=256)
    source: str = Field(default='authenticated_command', min_length=1, max_length=64)
    source_event_id: str | None = Field(default=None, max_length=128)
    language: str | None = Field(default=None, max_length=32)

class LogicalDeviceCreateIn(BaseModel):
    logical_name: str = Field(min_length=1, max_length=120)
    device_class: str = Field(min_length=1, max_length=80)
    room_id: int | None = None
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

class LogicalDeviceUpdateIn(BaseModel):
    logical_name: str | None = Field(default=None, min_length=1, max_length=120)
    device_class: str | None = Field(default=None, min_length=1, max_length=80)
    room_id: int | None = None
    enabled: bool | None = None
    maintenance_locked: bool | None = None
    metadata: dict[str, Any] | None = None

class DeviceBindingCreateIn(BaseModel):
    logical_name: str = Field(min_length=1, max_length=120)
    module_identifier: str = Field(min_length=1, max_length=120)
    channel: str | None = Field(default=None, max_length=80)
    binding_type: str = Field(default='primary', min_length=1, max_length=40)
    enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

class DeviceBindingUpdateIn(BaseModel):
    channel: str | None = Field(default=None, max_length=80)
    binding_type: str | None = Field(default=None, min_length=1, max_length=40)
    enabled: bool | None = None
    metadata: dict[str, Any] | None = None

class RcmChannelNameIn(BaseModel):
    name: str = Field(max_length=120)

class RcmSimulationIn(BaseModel):
    action: Literal['set_relay', 'set_lockout']
    value: bool

class LcmChannelSettingsIn(BaseModel):
    name: str = Field(max_length=120)
    emergency_lighting: bool = False
    max_intensity: int | None = Field(default=None, ge=0, le=100)
    fade_seconds: float | None = Field(default=None, ge=0, le=60)

class ModuleRoleChangeIn(BaseModel):
    requested_role: Literal['UNASSIGNED','RCM','LCM','PNL']
    confirm: bool = False

class FireStateIn(BaseModel):
    active: bool

class MaintenanceLockoutIn(BaseModel):
    logical_name: str
    active: bool

class SystemMaintenanceLockoutIn(BaseModel):
    active: bool

class SafetyRelayPulseIn(BaseModel):
    relay: Literal['door_request', 'auxiliary'] = 'door_request'
    duration_ms: int | None = None

class SafetyRelayStateIn(BaseModel):
    relay: Literal['door_request', 'auxiliary']
    active: bool

class AuthChallengeIn(BaseModel):
    username: str

class AuthVerifyIn(BaseModel):
    username: str
    challenge: str
    assertion: dict[str, Any]

class PasswordLoginIn(BaseModel):
    username: str
    password: str

class TouchscreenPinIn(BaseModel):
    pin: str = Field(min_length=6, max_length=6)
    permission: Literal['VIEWER','CONTROL','ADMIN'] = 'VIEWER'

class TouchscreenPermissionIn(BaseModel):
    permission: Literal['VIEWER','CONTROL','ADMIN']

class UserCreateIn(BaseModel):
    username: str
    password: str = Field(min_length=10)
    role: Literal['ADMIN','READONLY'] = 'READONLY'

class UserRoleUpdateIn(BaseModel):
    role: Literal['ADMIN','READONLY']

class UserPasswordResetIn(BaseModel):
    password: str = Field(min_length=10)

class UserPasswordChangeIn(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10)

class PairingKeyCreateIn(BaseModel):
    label: str
    target_type: Literal['HCM_SCREEN','PNL','RCM','LCM','RMC','OTHER']
    ttl_minutes: int = Field(default=30, ge=1, le=1440)
    metadata: dict[str, Any] = Field(default_factory=dict)

class PairingKeyVerifyIn(BaseModel):
    pairing_key: str
    used_by: str | None = None
