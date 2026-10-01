from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any

@dataclass
class DigitalBank:
    names: list[str]
    values: dict[str, bool] = field(default_factory=dict)

    def __post_init__(self):
        for n in self.names:
            self.values.setdefault(n, False)

    def set(self, channel: str, value: bool) -> None:
        if channel not in self.values:
            raise KeyError(channel)
        self.values[channel] = bool(value)

    def get(self, channel: str) -> bool:
        return self.values[channel]

    def snapshot(self) -> dict[str, bool]:
        return dict(self.values)

@dataclass
class AnalogOutputs:
    names: list[str]
    values: dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        for n in self.names:
            self.values.setdefault(n, 0.0)

    def set_percent(self, channel: str, percent: float) -> None:
        if channel not in self.values:
            raise KeyError(channel)
        self.values[channel] = max(0.0, min(100.0, float(percent)))

    def volts(self, channel: str) -> float:
        return self.values[channel] / 10.0

    def snapshot(self) -> dict[str, Any]:
        return {n: {'percent': p, 'volts': p / 10.0} for n, p in self.values.items()}
