from __future__ import annotations

import os
from typing import Any
from .commissioning import physical_write_allowed


TRUE_VALUES = {"1", "true", "yes", "on"}


def env_true(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in TRUE_VALUES


def dev_mode_enabled(config: dict[str, Any] | None = None) -> bool:
    cfg = config or {}
    return (
        env_true("HCM_DEV_MODE")
        or env_true("HC_DEV_MODE")
        or bool(cfg.get("dev_mode", False))
    )


def io_mode(config: dict[str, Any] | None = None) -> str:
    cfg = config or {}
    forced = os.getenv("HC_IO_MODE") or os.getenv("HCM_IO_MODE")
    if forced:
        return forced.strip().lower()
    if dev_mode_enabled(cfg):
        return "simulated"
    io_cfg = cfg.get("io", {})
    mode = io_cfg.get("mode", cfg.get("io_mode", "simulated"))
    if str(mode).lower() == "auto":
        return "real"
    return str(mode).lower()


def real_io_enabled(config: dict[str, Any] | None = None) -> bool:
    return io_mode(config) == "real"


def physical_channel_write_allowed(config: dict[str, Any] | None, channel: str) -> bool:
    """Require both the configured real mode and explicit channel commissioning."""
    cfg = config or {}
    profile = cfg.get("hardware_profile") or {}
    return real_io_enabled(cfg) and physical_write_allowed(profile, channel)
