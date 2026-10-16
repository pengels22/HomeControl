#!/usr/bin/env python3
"""Manual display/touch diagnostic; never runs automatically or controls outputs."""

from __future__ import annotations

import argparse
import asyncio

if __package__:
    from .service import create_service
else:
    from importlib import import_module
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

    create_service = import_module("10_scripts.touchscreen_hardware.service").create_service


async def main() -> None:
    parser = argparse.ArgumentParser(description="HomeControl touchscreen hardware diagnostic")
    parser.add_argument("--role", choices=["RCM", "LCM", "SIM"], default="RCM")
    parser.add_argument("--mode", choices=["simulated", "orange_pi"], default="simulated")
    args = parser.parse_args()
    service = create_service(args.role, args.mode)
    if args.mode == "simulated":
        print("Simulated touchscreen selected; no device nodes opened.")
        return
    display, touch = service.create_display(), service.create_touch()
    await display.initialize(); await touch.initialize()
    print("Touchscreen diagnostic running. Press Ctrl+C to stop.")
    try:
        while True:
            event = await touch.read_event()
            if event: print(event)
    finally:
        await touch.close(); await display.close()


if __name__ == "__main__":
    asyncio.run(main())
