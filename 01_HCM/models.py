from __future__ import annotations
from pydantic import BaseModel, Field
from typing import Any, Literal

class RoomStateIn(BaseModel):
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

class ModuleRoleChangeIn(BaseModel):
    requested_role: Literal['UNASSIGNED','RCM','SIM','LCM']
    confirm: bool = False

class FireStateIn(BaseModel):
    active: bool

class MaintenanceLockoutIn(BaseModel):
    logical_name: str
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

class UserCreateIn(BaseModel):
    username: str
    password: str = Field(min_length=10)
    role: Literal['ADMIN','READONLY'] = 'READONLY'

class PairingKeyCreateIn(BaseModel):
    label: str
    target_type: Literal['HCM_SCREEN','PNL','RCM','LCM','SIM','RMC','OTHER']
    ttl_minutes: int = Field(default=30, ge=1, le=1440)
    metadata: dict[str, Any] = Field(default_factory=dict)

class PairingKeyVerifyIn(BaseModel):
    pairing_key: str
    used_by: str | None = None

class RmcFirmwareUpdateIn(BaseModel):
    target_rmc_id: str
    sim_hostname: str
    can_interface: str
    node_id: int = Field(ge=0, le=15)
    firmware_version: str
    firmware_image_b64: str
    hardware_revision: str = 'RMC-NANO-ATMEGA328P'
