"""Explicit per-channel physical-output commissioning gate.

Environment variables and UI payloads are intentionally ignored. An empty
allowlist is the safe default, including in PHYSICAL_BENCH mode.
"""

from __future__ import annotations

from typing import Any


def _output_section(profile: dict[str, Any], channel: str) -> dict[str, Any] | None:
    outputs = profile.get("outputs") or {}
    channel = str(channel)
    for section in outputs.values():
        if not isinstance(section, dict):
            continue
        channels = section.get("channels") or []
        mappings = section.get("mappings") or {}
        if channel in channels or channel in mappings:
            return section
    return None


def physical_write_allowed(profile: dict[str, Any], channel: str) -> bool:
    """Return true only for an explicitly commissioned channel."""
    section = _output_section(profile, channel)
    if not profile.get("physical_output_enabled") or not section:
        return False
    if not section.get("real_output_enabled"):
        return False
    return str(channel) in {str(item) for item in section.get("commissioned_channels", [])}


def commissioning_status(profile: dict[str, Any], channels: list[str]) -> dict[str, Any]:
    return {
        "mode": "PHYSICAL_BENCH" if profile.get("physical_output_enabled") else "SIMULATED",
        "physical_output_enabled": bool(profile.get("physical_output_enabled", False)),
        "commissioned_channels": [ch for ch in channels if physical_write_allowed(profile, ch)],
        "writes_allowed": any(physical_write_allowed(profile, ch) for ch in channels),
    }
