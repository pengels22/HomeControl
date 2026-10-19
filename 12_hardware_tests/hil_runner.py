"""Explicit RCM/LCM bench HIL runner.

This module is deliberately inert when imported.  Running it requires the
operator to provide an explicit hardware-test gate, target, scope, and Linux
I2C bus.  It uses the production driver classes and commissioning profile
logic, but BENCH_TESTING is an isolated HIL authorization rather than normal
HCM/module API authorization.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from importlib import import_module

config = import_module("07_servises.common.config")
commissioning = import_module("07_servises.common.commissioning")
factory = import_module("07_servises.common.hardware_factory")
profiles = import_module("07_servises.common.hardware_profiles")
infra = import_module("07_servises.common.module_infra")


RCM_CHANNELS = list(infra.RCM_RELAY_CHANNELS)
LCM_RELAY_CHANNELS = list(infra.LCM_RELAY_CHANNELS)
LCM_ANALOG_CHANNELS = list(infra.LCM_ANALOG_DIMMER_CHANNELS)


class HILConfigurationError(RuntimeError):
    pass


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name, default)
    return value.strip() if isinstance(value, str) else value


def require_gate(target: str, scope: str, channel: str | None) -> None:
    if _env("HCM_HARDWARE_TESTS") != "1":
        raise HILConfigurationError("set HCM_HARDWARE_TESTS=1 to authorize HIL")
    selected_target = (_env("HCM_HARDWARE_TARGET") or "").upper()
    if selected_target != target:
        raise HILConfigurationError(f"HCM_HARDWARE_TARGET must be {target}")
    if scope not in {"channel", "module"}:
        raise HILConfigurationError("scope must be channel or module")
    if scope == "channel" and not channel:
        raise HILConfigurationError("HCM_HARDWARE_CHANNEL is required for channel scope")
    if scope == "module" and channel:
        raise HILConfigurationError("module scope cannot be combined with HCM_HARDWARE_CHANNEL")


def load_bench_profile(target: str) -> tuple[dict[str, Any], dict[str, Any]]:
    directory = {"RCM": "04_RCM", "LCM": "03_LCM"}[target]
    cfg = config.load_yaml(ROOT / "06_config" / directory / ("rcm.yaml" if target == "RCM" else "lcm.yaml"))
    profile = profiles.load_profile(ROOT / "06_config" / directory / "hardware_pins.yaml", target).data
    runtime_profile = copy.deepcopy(profile)
    runtime_profile["module_type"] = target
    # Repository profiles remain DESIGN_APPROVED.  HIL receives an in-memory
    # BENCH_TESTING view and never writes this status back to the manifest.
    runtime_profile.setdefault("verification", {})["status"] = "BENCH_TESTING"
    return cfg, runtime_profile


def selected_channels(target: str, scope: str, channel: str | None) -> list[str]:
    if scope == "channel":
        channels = RCM_CHANNELS if target == "RCM" else LCM_RELAY_CHANNELS + LCM_ANALOG_CHANNELS
        normalized = str(channel).upper()
        if normalized not in channels:
            raise HILConfigurationError(f"unsupported {target} channel: {channel}")
        return [normalized]
    if target == "RCM":
        return list(RCM_CHANNELS)
    # Shelly endpoints are intentionally excluded until permanent identities
    # and endpoints are configured.  The LCM module scope covers safe local
    # relay and PCA9685 outputs only.
    return list(LCM_RELAY_CHANNELS) + list(LCM_ANALOG_CHANNELS)


def _bench_allowed(profile: dict[str, Any], target: str, channel: str) -> None:
    if not commissioning.bench_test_write_allowed(
        profile,
        channel,
        hardware_tests_enabled=True,
        selected_target=target,
        selected_channel=channel,
    ):
        raise HILConfigurationError(f"BENCH_TESTING gate rejected {target} {channel}")


def cycle_outputs(
    target: str,
    profile: dict[str, Any],
    drivers: Any,
    channels: list[str],
    dwell_s: float = 0.25,
    sleep: Callable[[float], None] = time.sleep,
) -> list[dict[str, Any]]:
    """Run OFF/ON/OFF and capture latch evidence for local RCM/LCM outputs."""
    results: list[dict[str, Any]] = []
    relay_driver = drivers.rcm_relays if target == "RCM" else drivers.lcm_relays
    for channel in channels:
        _bench_allowed(profile, target, channel)
        if target == "RCM":
            index = RCM_CHANNELS.index(channel)
            off = relay_driver.set_channel(index, False)
            on = relay_driver.set_channel(index, True)
            sleep(dwell_s)
            final = relay_driver.set_channel(index, False)
            results.append({"channel": channel, "kind": "relay", "off": off, "on": on, "final": final, "pass": final["readback"] is False})
        elif channel in LCM_RELAY_CHANNELS:
            index = LCM_RELAY_CHANNELS.index(channel)
            off = relay_driver.set_channel(index, False)
            on = relay_driver.set_channel(index, True)
            sleep(dwell_s)
            final = relay_driver.set_channel(index, False)
            results.append({"channel": channel, "kind": "relay", "off": off, "on": on, "final": final, "pass": final["readback"] is False})
        else:
            index = LCM_ANALOG_CHANNELS.index(channel)
            pwm = drivers.lcm_pwm
            steps = []
            for percent in (0, 25, 50, 75, 100, 0):
                step = pwm.set_percent(index, percent)
                steps.append({"requested_percent": percent, "raw": step["raw"], "readback": step["readback"]})
                sleep(dwell_s)
            results.append({"channel": channel, "kind": "pwm", "steps": steps, "pass": steps[-1]["readback"] == 0})
    return results


def all_off(target: str, drivers: Any) -> list[dict[str, Any]]:
    results = []
    if target == "RCM":
        for index, channel in enumerate(RCM_CHANNELS):
            try:
                result = drivers.rcm_relays.set_channel(index, False)
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}
            results.append({"channel": channel, **result})
    else:
        for index, channel in enumerate(LCM_RELAY_CHANNELS):
            try:
                result = drivers.lcm_relays.set_channel(index, False)
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}
            results.append({"channel": channel, **result})
        for index, channel in enumerate(LCM_ANALOG_CHANNELS):
            try:
                result = drivers.lcm_pwm.set_percent(index, 0)
            except Exception as exc:
                result = {"ok": False, "error": str(exc)}
            results.append({"channel": channel, **result})
    return results


def run(target: str, scope: str, channel: str | None, dwell_s: float) -> dict[str, Any]:
    if not target or not scope:
        raise HILConfigurationError("target and scope are required")
    target = target.upper()
    require_gate(target, scope, channel)
    if target not in {"RCM", "LCM"}:
        raise HILConfigurationError("HIL supports RCM and LCM only")
    bus = _env("HCM_HARDWARE_I2C_BUS")
    if not bus or not bus.isdigit():
        raise HILConfigurationError("set an explicit HCM_HARDWARE_I2C_BUS; no bus is guessed")
    cfg, profile = load_bench_profile(target)
    cfg["hardware_mode"] = "real"
    cfg["i2c"] = {**(cfg.get("i2c") or {}), "bus": int(bus)}
    bundle = factory.build_hardware_bundle(target, cfg, profile)
    channels = selected_channels(target, scope, channel)
    pattern = (_env("HCM_HARDWARE_PATTERN") or "").lower()
    if pattern == "all" and (target != "RCM" or scope != "module"):
        raise HILConfigurationError("HCM_HARDWARE_PATTERN=all requires RCM module scope")
    cleanup_done = False
    try:
        if target == "RCM":
            bundle.rcm_relays.initialize()
        else:
            bundle.lcm_relays.initialize()
            bundle.lcm_pwm.initialize()
        results = cycle_outputs(target, profile, bundle, channels, dwell_s=dwell_s)
        group = []
        if target == "RCM" and pattern == "all":
            for index in range(32):
                _bench_allowed(profile, target, RCM_CHANNELS[index])
                bundle.rcm_relays.set_channel(index, True)
            group = all_off(target, bundle)
        cleanup = all_off(target, bundle)
        cleanup_done = True
        return {"ok": all(item["pass"] for item in results), "target": target, "scope": scope, "results": results, "group_cleanup": group, "cleanup": cleanup}
    finally:
        # Cleanup is unconditional, including driver exceptions during a test.
        try:
            if not cleanup_done:
                all_off(target, bundle)
        finally:
            bundle.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Explicit HomeControl RCM/LCM bench HIL")
    parser.add_argument("--target", default=_env("HCM_HARDWARE_TARGET"), choices=("RCM", "LCM"))
    parser.add_argument("--scope", default=_env("HCM_HARDWARE_SCOPE"), choices=("channel", "module"))
    parser.add_argument("--channel", default=_env("HCM_HARDWARE_CHANNEL"))
    parser.add_argument("--dwell", type=float, default=float(_env("HCM_HARDWARE_DWELL_S", "0.25")))
    args = parser.parse_args(argv)
    print(json.dumps(run(args.target, args.scope, args.channel, max(0.0, args.dwell)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
