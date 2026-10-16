"""Shared physical touchscreen hardware boundary for HomeControl modules.

The default HomeControl touchscreen remains browser-based and simulated.  This
package provides the validated Orange Pi display/touch adapters without
importing laser-control code or enabling physical outputs.
"""

from .interfaces import DisplayConfig, TouchConfig, TouchEvent, TouchPoint
from .input_bridge import TouchEventBridge, UInputTouchSink, run_touch_input
from .service import TouchscreenHardwareService, create_service

__all__ = [
    "DisplayConfig",
    "TouchConfig",
    "TouchEvent",
    "TouchPoint",
    "TouchscreenHardwareService",
    "TouchEventBridge",
    "UInputTouchSink",
    "create_service",
    "run_touch_input",
]
