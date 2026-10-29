"""Authenticated, allowlisted Home Assistant panel API for Sonic Fire 7.

This module is intentionally separate from the existing voice-command flow. It
is imported by the bridge only for /panel/* routes and has no microphone-policy
dependency: touchscreen controls remain usable while the global microphone is
muted.
"""
from __future__ import annotations

import datetime as _dt
import hmac
import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

HA_URL = os.environ.get("SONIC_HA_URL", "http://192.168.1.8:8123").rstrip("/")
HA_TOKEN_PATH = Path(os.environ.get("SONIC_HA_TOKEN_PATH", "/etc/sonic-ha/ha-token"))
PANEL_CONFIG_PATH = Path(os.environ.get("SONIC_PANEL_CONFIG_PATH", "/etc/sonic-ha/panel_config_living_room.json"))
FIRE7_TOKEN = os.environ.get("SONIC_FIRE7_TOKEN", "")
MAX_ACTION_BODY = 8192
MAX_HA_RESPONSE = 1024 * 1024
ACTION_WINDOW_SECONDS = 2.0
MAX_ACTIONS_PER_WINDOW = 8

_rate_lock = threading.Lock()
_recent_actions: dict[str, list[float]] = {}


class PanelError(Exception):
    def __init__(self, status: int, code: str):
        super().__init__(code)
        self.status = status
        self.code = code


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _read_config() -> dict:
    try:
        config = json.loads(PANEL_CONFIG_PATH.read_text())
    except (OSError, ValueError):
        raise PanelError(503, "panel_configuration_unavailable")
    controls = config.get("controls")
    if not isinstance(controls, list) or len(controls) < 5:
        raise PanelError(503, "panel_configuration_invalid")
    expected = {
        "light.living_room_glow_all": "light",
        "switch.lamp_switch": "switch",
        "switch.office_lights_switch": "switch",
        "switch.bedroom_camera_power": "switch",
        "climate.nest_thermostat": "climate",
    }
    seen = set()
    for control in controls:
        if not isinstance(control, dict):
            raise PanelError(503, "panel_configuration_invalid")
        entity_id = control.get("entity_id")
        if (entity_id in expected and control.get("type") != expected[entity_id]) or entity_id in seen:
            raise PanelError(503, "panel_configuration_invalid")
        if not isinstance(entity_id, str) or not entity_id.startswith(("light.", "switch.", "climate.", "media_player.", "select.")):
            raise PanelError(503, "panel_configuration_invalid")
        if control.get("type") not in ("light", "switch", "climate", "media_player", "select"):
            raise PanelError(503, "panel_configuration_invalid")
        seen.add(entity_id)
    if not set(expected).issubset(seen):
        raise PanelError(503, "panel_configuration_invalid")
    sources = config.get("media_sources", [])
    if not isinstance(sources, list) or len(sources) > 8:
        raise PanelError(503, "panel_configuration_invalid")
    controls_by_id = {c["entity_id"]: c for c in controls}
    for source in sources:
        if not isinstance(source, dict):
            raise PanelError(503, "panel_configuration_invalid")
        entity_id = source.get("entity_id")
        if (not isinstance(entity_id, str) or not entity_id.startswith("media_player.")
                or controls_by_id.get(entity_id, {}).get("type") != "media_player"
                or not isinstance(source.get("source"), str) or not source["source"]
                or not isinstance(source.get("label"), str) or not source["label"]):
            raise PanelError(503, "panel_configuration_invalid")
    return config


def _controls(config: dict) -> dict[str, dict]:
    return {c["entity_id"]: c for c in config["controls"]}


def _ha_token() -> str:
    try:
        token = HA_TOKEN_PATH.read_text().strip()
    except OSError:
        token = ""
    if not token:
        raise PanelError(503, "ha_credentials_unavailable")
    return token


def _ha_request(path: str, method: str = "GET", payload: dict | None = None) -> tuple[int, object]:
    data = None if payload is None else json.dumps(payload, separators=(",", ":")).encode()
    headers = {"Authorization": "Bearer " + _ha_token(), "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(HA_URL + path, method=method, headers=headers, data=data)
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            raw = response.read(MAX_HA_RESPONSE + 1)
            if len(raw) > MAX_HA_RESPONSE:
                raise PanelError(502, "ha_response_too_large")
            try:
                return response.status, json.loads(raw or b"{}")
            except ValueError:
                raise PanelError(502, "ha_invalid_response")
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            raise PanelError(502, "ha_authentication_failed")
        raise PanelError(503, "ha_unavailable")
    except (OSError, TimeoutError):
        raise PanelError(503, "ha_unavailable")


def _state_snapshot(config: dict) -> dict:
    _, raw = _ha_request("/api/states")
    if not isinstance(raw, list):
        raise PanelError(502, "ha_invalid_states")
    allowed = _controls(config)
    by_id = {item.get("entity_id"): item for item in raw if isinstance(item, dict)}
    states = []
    for entity_id in [c["entity_id"] for c in config["controls"]]:
        item = by_id.get(entity_id)
        if item is None:
            states.append({"entity_id": entity_id, "state": "unavailable", "available": False, "attributes": {}, "last_changed": None, "last_updated": None})
            continue
        state = item.get("state", "unknown")
        states.append({
            "entity_id": entity_id,
            "state": state,
            "available": state not in ("unknown", "unavailable"),
            "attributes": item.get("attributes") if isinstance(item.get("attributes"), dict) else {},
            "last_changed": item.get("last_changed"),
            "last_updated": item.get("last_updated"),
        })
    return {"snapshot_at": _now(), "states": states}


def _state_map(config: dict) -> dict[str, dict]:
    return {s["entity_id"]: s for s in _state_snapshot(config)["states"]}


def _number(body: dict, name: str) -> float:
    value = body.get(name)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise PanelError(400, "invalid_" + name)
    return float(value)


def _enum(body: dict, name: str) -> str:
    value = body.get(name)
    if not isinstance(value, str) or not value or len(value) > 64:
        raise PanelError(400, "invalid_" + name)
    return value


def _check_rate(client_key: str) -> None:
    now = time.monotonic()
    with _rate_lock:
        values = [t for t in _recent_actions.get(client_key, []) if now - t < ACTION_WINDOW_SECONDS]
        if len(values) >= MAX_ACTIONS_PER_WINDOW:
            raise PanelError(429, "action_rate_limited")
        values.append(now)
        _recent_actions[client_key] = values


def panel_authorized(header: str | None) -> bool:
    token = FIRE7_TOKEN
    return bool(token and header and hmac.compare_digest(header, "Bearer " + token))


def get_panel(path: str) -> tuple[int, dict]:
    config = _read_config()
    if path == "/panel/config":
        return 200, {
            "panel_id": config.get("panel_id", "fire7-living-room"),
            "revision": config.get("revision", 1),
            "updated_at": config.get("updated_at", ""),
            "controls": config["controls"],
            "media_sources": config.get("media_sources", []),
        }
    if path == "/panel/states":
        return 200, _state_snapshot(config)
    if path == "/panel/health":
        _ha_request("/api/")
        return 200, {"ok": True, "ha": "reachable", "config_revision": config.get("revision", 1)}
    raise PanelError(404, "not_found")


def post_panel(path: str, body: bytes, client_key: str = "unknown") -> tuple[int, dict]:
    if path != "/panel/action":
        raise PanelError(404, "not_found")
    if len(body) > MAX_ACTION_BODY or not body:
        raise PanelError(413, "action_body_too_large")
    try:
        request = json.loads(body)
    except (ValueError, TypeError):
        raise PanelError(400, "malformed_json")
    if not isinstance(request, dict):
        raise PanelError(400, "json_object_required")
    allowed_fields = {"entity_id", "action", "brightness_pct", "temperature", "hvac_mode", "fan_mode", "volume_level", "source", "option"}
    if set(request) - allowed_fields or not isinstance(request.get("entity_id"), str) or not isinstance(request.get("action"), str):
        raise PanelError(400, "invalid_action_request")
    _check_rate(client_key)
    config = _read_config()
    controls = _controls(config)
    entity_id = request["entity_id"]
    action = request["action"]
    control = controls.get(entity_id)
    if control is None or action not in control.get("actions", []):
        raise PanelError(403, "action_not_authorized")
    states = _state_map(config)
    state = states.get(entity_id, {})
    if not state.get("available"):
        raise PanelError(409, "entity_unavailable")
    attributes = state.get("attributes", {})
    domain = control["type"]
    service = None
    data: dict = {"entity_id": entity_id}
    if domain == "light" and action in ("turn_on", "turn_off"):
        service = action
    elif domain == "light" and action == "set_brightness":
        brightness = _number(request, "brightness_pct")
        if not 0 <= brightness <= 100 or not (attributes.get("supported_color_modes") or attributes.get("supported_features", 0)):
            raise PanelError(409, "brightness_unsupported")
        service = "turn_on"
        data["brightness_pct"] = int(round(brightness))
    elif domain == "switch" and action in ("turn_on", "turn_off"):
        service = action
    elif domain == "climate" and action == "set_temperature":
        temperature = _number(request, "temperature")
        minimum, maximum = attributes.get("min_temp"), attributes.get("max_temp")
        step = attributes.get("target_temp_step", 1)
        if not isinstance(minimum, (int, float)) or not isinstance(maximum, (int, float)) or not minimum <= temperature <= maximum:
            raise PanelError(422, "temperature_out_of_range")
        if not isinstance(step, (int, float)) or step <= 0:
            raise PanelError(409, "temperature_step_invalid")
        origin = minimum
        if abs(((temperature - origin) / step) - round((temperature - origin) / step)) > 1e-6:
            raise PanelError(422, "temperature_step_invalid")
        service = "set_temperature"
        data["temperature"] = temperature
    elif domain == "climate" and action == "set_hvac_mode":
        mode = _enum(request, "hvac_mode")
        if mode not in attributes.get("hvac_modes", []):
            raise PanelError(422, "unsupported_hvac_mode")
        service = action
        data["hvac_mode"] = mode
    elif domain == "climate" and action == "set_fan_mode":
        mode = _enum(request, "fan_mode")
        if mode not in attributes.get("fan_modes", []):
            raise PanelError(422, "unsupported_fan_mode")
        service = action
        data["fan_mode"] = mode
    elif domain == "media_player" and action in ("media_play_pause", "media_next_track", "media_previous_track", "turn_on", "turn_off"):
        service = action
    elif domain == "media_player" and action == "volume_set":
        volume = _number(request, "volume_level")
        if not 0 <= volume <= 1:
            raise PanelError(422, "volume_out_of_range")
        service = action
        data["volume_level"] = volume
    elif domain == "media_player" and action == "select_media_source":
        source = _enum(request, "source")
        if not any(item.get("entity_id") == entity_id and item.get("source") == source for item in config.get("media_sources", [])):
            raise PanelError(422, "unsupported_media_source")
        service = "select_source"
        data["source"] = source
    elif domain == "select" and action == "select_option":
        option = _enum(request, "option")
        if option not in attributes.get("options", []):
            raise PanelError(422, "unsupported_select_option")
        service = "select_option"
        data["option"] = option
    else:
        raise PanelError(422, "unsupported_action")
    status, _ = _ha_request(f"/api/services/{domain}/{service}", method="POST", payload=data)
    return 200, {"accepted": True, "entity_id": entity_id, "action": action, "ha_status": status}
