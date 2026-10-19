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


def physical_write_denial_reason(profile: dict[str, Any], channel: str) -> str:
    section = _output_section(profile, channel)
    if not section:
        return "unknown_physical_channel"
    if not profile.get("physical_output_enabled"):
        return "physical_outputs_disabled"
    status = str((profile.get("verification") or {}).get("status", "UNVERIFIED")).upper()
    if status != "COMMISSIONED":
        return "module_not_commissioned"
    if not section.get("real_output_enabled"):
        return "output_section_disabled"
    return "physical_output_not_authorized"


def bench_test_write_allowed(profile: dict[str, Any], channel: str, hardware_tests_enabled: bool, selected_target: str | None, selected_channel: str | None) -> bool:
    """Allow one exact BENCH_TESTING target for the opt-in hardware harness only."""
    section = _output_section(profile, channel)
    target = str(selected_target or "").upper()
    selected = str(selected_channel or "").upper()
    module = str(profile.get("module_type") or profile.get("device_type") or "").upper()
    return bool(
        hardware_tests_enabled
        and str((profile.get("verification") or {}).get("status", "UNVERIFIED")).upper() == "BENCH_TESTING"
        and target and target not in {"*", "ALL"}
        and selected and selected not in {"*", "ALL"}
        and target == module and selected == str(channel).upper() and section is not None
    )


def commissioning_status(profile: dict[str, Any], channels: list[str]) -> dict[str, Any]:
    status = str((profile.get("verification") or {}).get("status", "UNVERIFIED")).upper()
    return {
        "mode": status,
        "physical_output_enabled": bool(profile.get("physical_output_enabled", False)),
        "verification_status": status,
        "known_channels": [ch for ch in channels if _output_section(profile, ch)],
        "writes_allowed": any(physical_write_allowed(profile, ch) for ch in channels),
    }
