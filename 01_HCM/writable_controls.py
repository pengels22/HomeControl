"""Provider-neutral writable number and select service contracts."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class NumberSetValueArgs(BaseModel):
    model_config = ConfigDict(extra='forbid')
    value: float
    dry_run: bool = False


class SelectOptionArgs(BaseModel):
    model_config = ConfigDict(extra='forbid')
    option: str = Field(min_length=1, max_length=256)
    dry_run: bool = False


@dataclass(frozen=True)
class NumberCapability:
    writable: bool = True
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None
    unit: str | None = None


@dataclass(frozen=True)
class SelectCapability:
    writable: bool = True
    options: tuple[str, ...] = ()


def validate_number(value: Any, capability: NumberCapability) -> float:
    if not capability.writable:
        raise ValueError('TARGET_DOES_NOT_SUPPORT')
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError('INVALID_ARGUMENT') from None
    if capability.minimum is not None and number < capability.minimum:
        raise ValueError('INVALID_ARGUMENT')
    if capability.maximum is not None and number > capability.maximum:
        raise ValueError('INVALID_ARGUMENT')
    if capability.step is not None and capability.step > 0 and capability.minimum is not None:
        quotient = (number - capability.minimum) / capability.step
        if abs(quotient - round(quotient)) > 1e-9:
            raise ValueError('INVALID_ARGUMENT')
    return number


def validate_option(option: str, capability: SelectCapability) -> str:
    if not capability.writable:
        raise ValueError('TARGET_DOES_NOT_SUPPORT')
    if option not in capability.options:
        raise ValueError('INVALID_ARGUMENT')
    return option
