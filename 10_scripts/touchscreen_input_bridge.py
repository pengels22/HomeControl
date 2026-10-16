#!/usr/bin/env python3
"""Manual Orange Pi FT6336U-to-kiosk input bridge."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _modules():
    bridge = importlib.import_module("10_scripts.touchscreen_hardware.input_bridge")
    service = importlib.import_module("10_scripts.touchscreen_hardware.service")
    return bridge, service


async def main() -> None:
    parser = argparse.ArgumentParser(description="HomeControl Orange Pi touchscreen input bridge")
    parser.add_argument("--role", choices=["RCM", "LCM", "SIM"], default="RCM")
    parser.add_argument("--mode", choices=["simulated", "orange_pi"], default="simulated")
    args = parser.parse_args()
    bridge_module, service_module = _modules()
    service = service_module.create_service(args.role, args.mode)
    if args.mode == "simulated":
        print("Simulated touchscreen selected; no input device opened.")
        return
    touch = service.create_touch()
    sink = bridge_module.UInputTouchSink(
        width=service.touch_config.width,
        height=service.touch_config.height,
    )
    print("Starting FT6336U input bridge; Ctrl+C stops it.")
    try:
        await bridge_module.run_touch_input(touch, sink)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    asyncio.run(main())
