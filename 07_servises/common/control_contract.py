"""Shared command and acknowledgement shapes for all HomeControl clients.

The contract deliberately carries logical identity separately from the physical
channel. Physical addressing is resolved by HCM/module configuration, never by
the touchscreen client.
"""

from __future__ import annotations

from typing import Any


def normalize_touch_command(payload: dict[str, Any]) -> dict[str, Any]:
    """Convert a touchscreen command into an HCM module command payload."""
    kind = str(payload.get("kind", "")).lower()
    channel = payload.get("channel")
    if kind == "relay":
        return {
            "op": "set_relay",
            "channel": channel,
            "value": bool(payload.get("value")),
            "source": "touchscreen",
        }
    if kind == "dimmer":
        raw = payload.get("value", payload.get("percent", 0))
        percent = max(0.0, min(100.0, float(raw)))
        return {
            "op": "set_dimmer",
            "channel": channel,
            "percent": percent,
            "value": percent >= 5,
            "source": "touchscreen",
        }
    raise ValueError(f"unsupported touchscreen command kind: {kind}")


def command_ack(*, result: dict[str, Any], logical_name: str, channel: str) -> dict[str, Any]:
    """Return a stable acknowledgement without exposing client authority."""
    return {
        "ok": bool(result.get("ok")),
        "logical_name": logical_name,
        "channel": channel,
        "state": result,
        "physical_output_commanded": bool(result.get("physical_output_commanded", False)),
        "source": "hcm_logical_command",
    }
