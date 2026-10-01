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

class FireStateIn(BaseModel):
    active: bool
