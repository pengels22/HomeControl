#!/usr/bin/env python3
"""Run the shared HomeControl browser renderer and FT6336U touch path."""

from __future__ import annotations

import argparse
import asyncio
import importlib
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def main() -> None:
    parser = argparse.ArgumentParser(description="HomeControl Chromium-to-ST7796U bridge")
    parser.add_argument("--role", choices=["RCM", "LCM", "SIM"], default="RCM")
    parser.add_argument("--mode", choices=["simulated", "orange_pi"], default="simulated")
    parser.add_argument("--url", default=None)
    args = parser.parse_args()

    hardware = importlib.import_module("10_scripts.touchscreen_hardware")
    renderer_module = importlib.import_module("10_scripts.touchscreen_hardware.browser_renderer")
    input_module = importlib.import_module("10_scripts.touchscreen_hardware.input_bridge")
    service = hardware.create_service(args.role, args.mode)
    if args.mode == "simulated":
        print("Simulated display bridge selected; no display, touch, or browser hardware opened.")
        return

    display = service.create_display()
    await display.initialize()
    url = args.url or f"http://127.0.0.1:8765/?role={args.role}"
    renderer = renderer_module.BrowserRenderer(
        display,
        renderer_module.BrowserRendererConfig(url=url, width=display.width, height=display.height),
    )
    stop = asyncio.Event()
    touch = service.create_touch()
    tasks = []
    try:
        await renderer.start()
        sink = input_module.CdpTouchSink(renderer.client)
        tasks = [
            asyncio.create_task(renderer.run(stop)),
            asyncio.create_task(input_module.run_touch_input(touch, sink, stop)),
        ]
        await asyncio.gather(
            *tasks,
        )
    except (KeyboardInterrupt, asyncio.CancelledError):
        stop.set()
    finally:
        stop.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        await renderer.stop()
        await display.close()


if __name__ == "__main__":
    asyncio.run(main())
