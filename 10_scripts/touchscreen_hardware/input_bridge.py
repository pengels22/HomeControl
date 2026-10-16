"""Deliver FT6336U touch events to a Linux browser through a virtual device.

The bridge deliberately forwards raw single-contact lifecycle events. Chromium
then owns DOM hit-testing, scrolling, pointer capture, sliders, and gestures.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Protocol

from .interfaces import TouchEvent, TouchPoint


LOGGER = logging.getLogger(__name__)


class TouchSink(Protocol):
    def open(self) -> None: ...
    def press(self, point: TouchPoint) -> None: ...
    def move(self, point: TouchPoint) -> None: ...
    def release(self, point: TouchPoint | None = None) -> None: ...
    def close(self) -> None: ...


@dataclass
class TouchEventBridge:
    """Translate the validated FT6336U lifecycle to browser input events."""

    sink: TouchSink
    active_id: int | None = None
    active_point: TouchPoint | None = None

    def handle(self, event: TouchEvent) -> bool:
        LOGGER.info("touch bridge event kind=%s points=%s", event.kind, event.points)
        if event.kind == "down" and event.points:
            point = event.points[0]
            if self.active_id is not None:
                self.cancel()
            self.active_id = point.id
            self.active_point = point
            self.sink.press(point)
            return True

        if event.kind == "move" and event.points and self.active_id is not None:
            point = next((item for item in event.points if item.id == self.active_id), None)
            if point is None:
                return False
            self.active_point = point
            self.sink.move(point)
            return True

        if event.kind == "up" and self.active_id is not None:
            self.sink.release(self.active_point)
            self.active_id = None
            self.active_point = None
            return True

        return False

    def cancel(self) -> None:
        if self.active_id is None:
            return
        self.sink.release(self.active_point)
        self.active_id = None
        self.active_point = None


class UInputTouchSink:
    """Create a virtual single-touch device consumed by the kiosk compositor."""

    def __init__(self, width: int = 480, height: int = 320, name: str = "HomeControl FT6336U Touch") -> None:
        self.width = width
        self.height = height
        self.name = name
        self._device = None

    def open(self) -> None:
        try:
            from evdev import AbsInfo, UInput, ecodes
        except ImportError as exc:
            raise RuntimeError("Linux touchscreen bridge requires python-evdev") from exc

        self._device = UInput(
            {
                ecodes.EV_KEY: [ecodes.BTN_TOUCH, ecodes.BTN_TOOL_FINGER],
                ecodes.EV_ABS: [
                    (ecodes.ABS_X, AbsInfo(0, self.width - 1, 0, 0, 0)),
                    (ecodes.ABS_Y, AbsInfo(0, self.height - 1, 0, 0, 0)),
                    (ecodes.ABS_MT_SLOT, AbsInfo(0, 0, 0, 0, 0)),
                    (ecodes.ABS_MT_TRACKING_ID, AbsInfo(-1, 1, 0, 0, 0)),
                    (ecodes.ABS_MT_POSITION_X, AbsInfo(0, self.width - 1, 0, 0, 0)),
                    (ecodes.ABS_MT_POSITION_Y, AbsInfo(0, self.height - 1, 0, 0, 0)),
                ],
            },
            name=self.name,
        )

    def press(self, point: TouchPoint) -> None:
        self._write_position(point)
        self._write(self._code("BTN_TOUCH"), 1)
        self._write(self._code("BTN_TOOL_FINGER"), 1)
        self._write(self._code("ABS_MT_TRACKING_ID"), 1)
        self._syn()

    def move(self, point: TouchPoint) -> None:
        self._write_position(point)
        self._syn()

    def release(self, point: TouchPoint | None = None) -> None:
        if point is not None:
            self._write_position(point)
        self._write(self._code("ABS_MT_TRACKING_ID"), -1)
        self._write(self._code("BTN_TOUCH"), 0)
        self._write(self._code("BTN_TOOL_FINGER"), 0)
        self._syn()

    def close(self) -> None:
        if self._device is not None:
            self._device.close()
            self._device = None

    def _write_position(self, point: TouchPoint) -> None:
        self._write(self._code("ABS_X"), point.x)
        self._write(self._code("ABS_Y"), point.y)
        self._write(self._code("ABS_MT_SLOT"), 0)
        self._write(self._code("ABS_MT_POSITION_X"), point.x)
        self._write(self._code("ABS_MT_POSITION_Y"), point.y)

    def _write(self, code: int, value: int) -> None:
        if self._device is None:
            raise RuntimeError("touch sink is not open")
        from evdev import ecodes

        event_type = ecodes.EV_KEY if code in {ecodes.BTN_TOUCH, ecodes.BTN_TOOL_FINGER} else ecodes.EV_ABS
        self._device.write(event_type, code, value)

    def _syn(self) -> None:
        if self._device is None:
            raise RuntimeError("touch sink is not open")
        self._device.syn()

    @staticmethod
    def _code(name: str) -> int:
        from evdev import ecodes

        return getattr(ecodes, name)


class CdpTouchSink:
    """CDP equivalent for headless Chromium without a compositor."""

    def __init__(self, client, coordinate_scale: float = 1.0):
        self.client = client
        self.coordinate_scale = coordinate_scale
        self.dispatch_count = 0
        self.dispatch_seconds = 0.0

    def open(self) -> None:
        self.client.command("Input.setIgnoreInputEvents", {"ignore": False})

    def press(self, point: TouchPoint) -> None:
        LOGGER.info("CDP dispatch type=touchStart point=(%s,%s)", point.x, point.y)
        self._dispatch("touchStart", point)

    def move(self, point: TouchPoint) -> None:
        LOGGER.info("CDP dispatch type=touchMove point=(%s,%s)", point.x, point.y)
        self._dispatch("touchMove", point)

    def release(self, point: TouchPoint | None = None) -> None:
        LOGGER.info("CDP dispatch type=touchEnd point=%s", point)
        started = time.perf_counter()
        result = self.client.command("Input.dispatchTouchEvent", {
            "type": "touchEnd",
            "touchPoints": [],
            "timestamp": time.time(),
        })
        LOGGER.info("CDP acknowledgment type=touchEnd result=%s", result)
        self.dispatch_count += 1
        self.dispatch_seconds += time.perf_counter() - started

    def close(self) -> None:
        return None

    def _dispatch(self, action: str, point: TouchPoint) -> None:
        started = time.perf_counter()
        scaled = TouchPoint(
            point.id,
            round(point.x * self.coordinate_scale),
            round(point.y * self.coordinate_scale),
        )
        result = self.client.command("Input.dispatchTouchEvent", {
            "type": action,
            "touchPoints": [{
                "x": scaled.x,
                "y": scaled.y,
                "radiusX": 1,
                "radiusY": 1,
                "force": 1,
                "id": point.id,
            }],
            "timestamp": time.time(),
        })
        LOGGER.info("CDP acknowledgment type=%s result=%s", action, result)
        self.dispatch_count += 1
        self.dispatch_seconds += time.perf_counter() - started


async def run_touch_input(touch, sink: TouchSink, stop_event: asyncio.Event | None = None) -> None:
    """Run the FT6336U consumer until cancelled or ``stop_event`` is set."""

    bridge = TouchEventBridge(sink)
    sink.open()
    try:
        await touch.initialize()
        LOGGER.info("touch reader initialized")
        while stop_event is None or not stop_event.is_set():
            event = await touch.read_event()
            if event is not None:
                bridge.handle(event)
    finally:
        LOGGER.info("touch reader shutting down")
        bridge.cancel()
        await touch.close()
        sink.close()
