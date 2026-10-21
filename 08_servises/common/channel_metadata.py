"""Shared semantic contract. Physical identity and commissioning are separate."""
from enum import Enum
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Purpose(str, Enum):
    LIGHTING = 'LIGHTING'
    HVAC = 'HVAC'
    LANDSCAPE = 'LANDSCAPE'
    GENERAL = 'GENERAL'
    SECURITY = 'SECURITY'
    OTHER = 'OTHER'


class HVACControl(str, Enum):
    G = 'G'
    Y1 = 'Y1'
    Y2 = 'Y2'
    W1 = 'W1'
    W2 = 'W2'
    OB = 'O/B'
    AUX = 'AUX'
    E = 'E'
    OTHER = 'OTHER_HVAC'


HEATING = frozenset({'W1', 'W2', 'AUX', 'E'})
COOLING = frozenset({'Y1', 'Y2'})


class ChannelMetadata(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    display_name: str = Field(default='', max_length=120)
    room_id: int | None = Field(default=None, gt=0)
    purpose: Purpose = Purpose.GENERAL
    mqtt_enabled: bool = False
    matter_enabled: bool = False
    enabled: bool = True
    emergency: bool = False
    hvac_control: HVACControl | None = None
    hvac_description: str | None = Field(default=None, max_length=120)
    security_endpoint_label: str | None = Field(default=None, max_length=120)
    other_function: str | None = Field(default=None, max_length=120)

    @model_validator(mode='after')
    def purpose_fields(self):
        if self.emergency and self.purpose != Purpose.LIGHTING:
            raise ValueError('emergency requires LIGHTING')
        if self.purpose == Purpose.HVAC:
            if self.hvac_control is None:
                raise ValueError('HVAC requires hvac_control')
        elif self.hvac_control is not None:
            raise ValueError('hvac_control requires HVAC')
        if self.hvac_description and self.hvac_control != HVACControl.OTHER:
            raise ValueError('hvac_description requires OTHER_HVAC')
        if self.security_endpoint_label and self.purpose != Purpose.SECURITY:
            raise ValueError('security_endpoint_label requires SECURITY')
        if self.other_function and self.purpose != Purpose.OTHER:
            raise ValueError('other_function requires OTHER')
        return self


def validate_metadata(module_type, channel_kind, values):
    metadata = ChannelMetadata.model_validate(values)
    if channel_kind != 'relay' and (module_type != 'LCM' or metadata.purpose != Purpose.LIGHTING):
        raise ValueError('dimmer purpose is locked to LIGHTING')
    return metadata


def hvac_conflict(roles, states):
    active = {roles[ch] for ch, on in states.items() if on and ch in roles}
    return bool(active & HEATING and active & COOLING)
