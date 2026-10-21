"""Read-only discovery and mocked hardware adapters.

These adapters provide deterministic test seams. They do not open buses or
perform output writes; real adapters must be added only after commissioning.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MockOutputAdapter:
    channels: list[str]
    values: dict[str, Any] = field(default_factory=dict)
    writes: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.values.update({channel: self.values.get(channel, False) for channel in self.channels})

    def discover(self) -> dict[str, Any]:
        return {"ok": True, "mode": "mock", "channels": list(self.channels), "write_count": len(self.writes)}

    def set(self, channel: str, value: Any) -> None:
        if channel not in self.values:
            raise KeyError(channel)
        self.values[channel] = value
        self.writes.append({"channel": channel, "value": value})


@dataclass
class DiscoveryOnlyI2C:
    addresses: tuple[int, ...]

    def scan(self) -> dict[str, Any]:
        return {"ok": True, "mode": "discovery_only", "addresses": [f"0x{x:02X}" for x in self.addresses]}
