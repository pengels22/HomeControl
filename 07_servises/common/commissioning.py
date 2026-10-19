"""Module-level physical-output commissioning gate.

The authoritative hardware profile defines the physical channel inventory.
There is deliberately no second per-channel commissioning allowlist.
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
    """Return true only for a known output on a commissioned module."""
    section = _output_section(profile, channel)
    if not profile.get("physical_output_enabled") or not section:
        return False
    if str((profile.get("verification") or {}).get("status", "UNVERIFIED")).upper() != "COMMISSIONED":
        return False
    if not section.get("real_output_enabled"):
        return False
    return True


def commissioning_status(profile: dict[str, Any], channels: list[str]) -> dict[str, Any]:
    status = str((profile.get("verification") or {}).get("status", "UNVERIFIED")).upper()
    return {
        "mode": status,
        "physical_output_enabled": bool(profile.get("physical_output_enabled", False)),
        "verification_status": status,
        "known_channels": [ch for ch in channels if _output_section(profile, ch)],
        "writes_allowed": any(physical_write_allowed(profile, ch) for ch in channels),
    }
