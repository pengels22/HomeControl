#!/usr/bin/env python3
"""Run the browser renderer and FT6336U touch path for a long-lived bench."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import logging
import os
from pathlib import Path
import resource
import signal
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

LOGGER = logging.getLogger("homecontrol.touchscreen")
MAX_RESTARTS = 3
RESTART_WINDOW_SECONDS = 60.0
RESTART_DELAY_SECONDS = 1.0


def _configure_logging() -> None:
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    stream = logging.StreamHandler()
    stream.setFormatter(formatter)
    root.addHandler(stream)
    log_path = os.getenv("HOMECONTROL_TOUCH_LOG", "/tmp/homecontrol-touchscreen-events.log")
    try:
        file_handler = logging.FileHandler(log_path)
    except OSError:
        return
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)


def _task_result(task: asyncio.Task, name: str) -> str:
    if task.cancelled():
        LOGGER.warning("task=%s lifecycle=cancelled", name)
        return "cancelled"
    exception = task.exception()
    if exception is not None:
        LOGGER.error("task=%s lifecycle=exception type=%s error=%s", name, type(exception).__name__, exception, exc_info=exception)
        return "exception"
    LOGGER.error("task=%s lifecycle=returned unexpectedly", name)
    return "returned"


async def _run_attempt(service, renderer_module, input_module, role: str, url: str, stop: asyncio.Event) -> tuple[bool, dict]:
    display = service.create_display()
    renderer = None
    sink = None
    touch_client = None
    tasks: list[asyncio.Task] = []
    started = time.monotonic()
    reason = "unknown"
    try:
        LOGGER.info("attempt lifecycle=starting role=%s", role)
        await display.initialize()
        renderer = renderer_module.BrowserRenderer(
            display,
            renderer_module.BrowserRendererConfig(url=url, width=display.width, height=display.height),
        )
        await renderer.start()
        # Keep touch traffic on a separate CDP session. Screenshot capture can
        # be slow on the Orange Pi and must never delay an active touch.
        touch_client = renderer_module.CdpClient(renderer.client.websocket_url)
        await asyncio.to_thread(touch_client.connect)
        sink = input_module.CdpTouchSink(touch_client, coordinate_scale=1 / renderer.config.output_scale)
        tasks = [
            asyncio.create_task(renderer.run(stop), name="renderer"),
            asyncio.create_task(input_module.run_touch_input(service.create_touch(), sink, stop), name="touch-reader"),
        ]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        if stop.is_set():
            reason = "intentional-shutdown"
            LOGGER.info("attempt lifecycle=stopping reason=%s", reason)
        else:
            reasons = [_task_result(task, task.get_name()) for task in done]
            reason = ",".join(reasons)
            LOGGER.error("attempt lifecycle=failed reason=%s", reason)
        for task in pending:
            task.cancel()
        await asyncio.gather(*done, *pending, return_exceptions=True)
    except asyncio.CancelledError:
        reason = "cancelled"
        LOGGER.info("attempt lifecycle=cancelled")
        raise
    except Exception as exc:
        reason = f"startup-{type(exc).__name__}"
        LOGGER.error("attempt lifecycle=exception type=%s error=%s", type(exc).__name__, exc, exc_info=True)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if renderer is not None:
            await renderer.stop()
        if touch_client is not None:
            touch_client.close()
        await display.close()
        metrics = {
            "reason": reason,
            "seconds": round(time.monotonic() - started, 3),
            "render": {
                "frames_captured": renderer.metrics.frames_captured if renderer else 0,
                "updates_sent": renderer.metrics.updates_sent if renderer else 0,
                "full_updates": renderer.metrics.full_updates if renderer else 0,
                "changed_pixels": renderer.metrics.changed_pixels if renderer else 0,
                "capture_fps": renderer.metrics.capture_fps if renderer else 0.0,
                "capture_seconds": renderer.metrics.capture_seconds if renderer else 0.0,
                "update_seconds": renderer.metrics.update_seconds if renderer else 0.0,
            },
            "touch": {
                "dispatch_count": getattr(sink, "dispatch_count", 0),
                "dispatch_seconds": getattr(sink, "dispatch_seconds", 0.0),
            },
        }
        LOGGER.info("attempt lifecycle=cleaned reason=%s metrics=%s", reason, metrics)
    return reason == "intentional-shutdown", metrics


async def run_physical_bridge(role: str, url: str | None = None) -> list[dict]:
    hardware = importlib.import_module("11_scripts.touchscreen_hardware")
    renderer_module = importlib.import_module("11_scripts.touchscreen_hardware.browser_renderer")
    input_module = importlib.import_module("11_scripts.touchscreen_hardware.input_bridge")
    service = hardware.create_service(role, "orange_pi")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stop.set)
        except NotImplementedError:
            pass
    attempts: list[dict] = []
    failures: list[float] = []
    while not stop.is_set():
        intentional, metrics = await _run_attempt(service, renderer_module, input_module, role, url or f"http://127.0.0.1:8765/?role={role}", stop)
        attempts.append(metrics)
        if intentional or stop.is_set():
            break
        now = time.monotonic()
        failures = [timestamp for timestamp in failures if now - timestamp < RESTART_WINDOW_SECONDS]
        failures.append(now)
        if len(failures) > MAX_RESTARTS:
            LOGGER.critical("bridge lifecycle=nonrecoverable failures=%s window_seconds=%s", len(failures), RESTART_WINDOW_SECONDS)
            break
        LOGGER.warning("bridge lifecycle=restarting attempt=%s delay_seconds=%s", len(failures), RESTART_DELAY_SECONDS)
        try:
            await asyncio.wait_for(stop.wait(), timeout=RESTART_DELAY_SECONDS)
        except asyncio.TimeoutError:
            pass
    return attempts


async def main() -> None:
    _configure_logging()
    parser = argparse.ArgumentParser(description="HomeControl Chromium-to-ST7796U bridge")
    parser.add_argument("--role", choices=["RCM", "LCM", "SIM"], default="RCM")
    parser.add_argument("--mode", choices=["simulated", "orange_pi"], default="simulated")
    parser.add_argument("--url", default=None)
    args = parser.parse_args()
    if args.mode == "simulated":
        print("Simulated display bridge selected; no display, touch, or browser hardware opened.")
        return
    attempts = await run_physical_bridge(args.role, args.url)
    print(json.dumps({
        "attempts": attempts,
        "process": {
            "user_cpu_seconds": resource.getrusage(resource.RUSAGE_SELF).ru_utime,
            "system_cpu_seconds": resource.getrusage(resource.RUSAGE_SELF).ru_stime,
            "max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        },
    }, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
