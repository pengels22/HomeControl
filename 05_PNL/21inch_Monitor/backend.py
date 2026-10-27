"""HomeControl 21-inch kiosk backend. Localhost-only HA bridge; no secrets served."""
import os
import re
import time
from pathlib import Path
from urllib.parse import quote

import requests
from flask import Flask, jsonify, request, send_from_directory

ROOT = Path(__file__).resolve().parent
HA_URL = os.getenv("HA_URL", "http://192.168.1.8:8123").rstrip("/")
TOKEN = os.getenv("HA_TOKEN", "").strip()
app = Flask(__name__, static_folder=None)
ENTITY_RE = re.compile(r"^(?:light|switch|sensor|binary_sensor|climate|weather|calendar|media_player|timer|select)\.[a-z0-9_]+$")
# Explicit controls approved by the supplied Lovelace YAML.
LIGHTS = {
    "light.cabinets_lights_light","light.tv_leds_light","light.desk_leds_light",
    "light.living_room_glow","light.living_room_records","light.living_room_glow_all",
    "light.hubby_glow_light","light.wifey_glow_light","light.bed_underglow_light",
    "light.bedroom_lamp_light","light.headboard_white_light","light.office_desk_lights",
    "light.bathroom_toe",
}
SWITCHES = {
    "switch.lamp_switch","switch.office_lights_switch","switch.seasonal_switches",
    "switch.laundry_room","switch.bedroom_fan_switch","switch.barbecue_lights_switch",
    "switch.bedroom_vines_switch","switch.bedroom_light","switch.bedroom_tv_switch",
    "switch.modem_power_switch","switch.office_lights_switch_2",
    "switch.printer_lights_switch","switch.workbench_switch",
}
# Hold back compressor, laser and uncertain scenic circuitry pending physical verification.
AUTOMATIONS = {
    "automation.dvd_player","automation.fire_stick","automation.xbox",
    "automation.game_cube","automation.ps2","automation.listen_to_music",
    "automation.retropie",
}
TIMERS = {"timer.3_min_timer","timer.5_min_timer","timer.10_min_timer","timer.kitchen_timer"}
SELECTS = {"select.bedroom_curtain_bedroom_curtain_position_preset"}
CURTAIN_OPTIONS = {"Closed","1/4 Open","1/2 Open","3/4 Open","Open"}
ALLOWED_FILES = {"index.html","approved_trace.svg","apartment_render.svg",
                 "static_apartment_config.js","static_apartment.js","live_ha.js"}
ALLOWED_READ_DOMAINS = {"light","switch","sensor","binary_sensor","climate",
                        "weather","calendar","media_player","timer","select",
                        "alarm_control_panel","automation","input_datetime"}

def ha(method, path, payload=None):
    if not TOKEN:
        raise ValueError("HA_TOKEN missing")
    response = requests.request(
        method, HA_URL + path,
        headers={"Authorization": "Bearer " + TOKEN,
                 "Content-Type":"application/json"},
        json=payload, timeout=8)
    response.raise_for_status()
    return response.json() if response.content else {}

def error_response(exc):
    if isinstance(exc, ValueError):
        return jsonify(error=str(exc)), 503
    if isinstance(exc, requests.HTTPError):
        return jsonify(error="Home Assistant HTTP error",
                       status=exc.response.status_code), 502
    return jsonify(error="Home Assistant unavailable"), 503

@app.get("/api/health")
def health():
    try:
        ha("GET","/api/")
        return jsonify(backend="online",home_assistant="connected")
    except Exception as exc:
        return error_response(exc)

@app.get("/api/entities")
def entities():
    try:
        states = ha("GET","/api/states")
        return jsonify([
            {"entity_id":s["entity_id"], "state":s["state"],
             "attributes":s.get("attributes",{}),
             "last_updated":s.get("last_updated")}
            for s in states
            if s.get("entity_id","").split(".")[0] in ALLOWED_READ_DOMAINS
        ])
    except Exception as exc:
        return error_response(exc)

@app.get("/api/entities/<entity_id>")
def entity(entity_id):
    if not ENTITY_RE.fullmatch(entity_id):
        return jsonify(error="Invalid entity"), 400
    try:
        return jsonify(ha("GET","/api/states/"+quote(entity_id,safe=".")))
    except Exception as exc:
        return error_response(exc)

@app.post("/api/action")
def action():
    if request.content_length is None or request.content_length > 1024:
        return jsonify(error="Invalid payload size"), 413
    if request.mimetype != "application/json":
        return jsonify(error="JSON required"), 415
    # The kiosk is loopback-only. Keep all writes same-origin and disallow cross-origin posts.
    origin = request.headers.get("Origin")
    if origin and origin not in {"http://127.0.0.1:"+str(PORT),
                                  "http://localhost:"+str(PORT)}:
        return jsonify(error="Origin denied"), 403
    body = request.get_json(silent=True)
    if not isinstance(body,dict):
        return jsonify(error="Invalid payload"), 400
    entity_id = body.get("entity_id")
    command = body.get("command")
    if not isinstance(entity_id,str) or not ENTITY_RE.fullmatch(entity_id):
        return jsonify(error="Invalid entity"), 400
    domain, _, _ = entity_id.partition(".")
    if domain == "light" and entity_id in LIGHTS and command in {"turn_on","turn_off"}:
        service, data = command, {"entity_id":entity_id}
    elif domain == "switch" and entity_id in SWITCHES and command in {"turn_on","turn_off"}:
        service, data = command, {"entity_id":entity_id}
    elif domain == "timer" and entity_id in TIMERS and command in {"start","cancel"}:
        service, data = command, {"entity_id":entity_id}
    elif domain == "select" and entity_id in SELECTS and command == "select_option" and body.get("option") in CURTAIN_OPTIONS:
        service, data = command, {"entity_id":entity_id,"option":body["option"]}
    elif domain == "automation" and entity_id in AUTOMATIONS and command == "trigger":
        service, data = command, {"entity_id":entity_id,"skip_condition":False}
    elif domain == "media_player" and entity_id == "media_player.living_room" and command in {"volume_up","volume_down","media_play_pause","media_stop"}:
        service, data = command, {"entity_id":entity_id}
    else:
        return jsonify(error="Command not allowlisted"), 403
    try:
        previous = ha("GET","/api/states/"+quote(entity_id,safe="."))
        if previous.get("state") in {"unknown","unavailable"}:
            return jsonify(error="Entity unavailable"), 409
        ha("POST", "/api/services/"+domain+"/"+service, data)
        # Return authoritative readback; commands may take time to propagate.
        time.sleep(.2)
        updated = ha("GET","/api/states/"+quote(entity_id,safe="."))
        return jsonify(accepted=True, entity=updated)
    except Exception as exc:
        return error_response(exc)

@app.after_request
def headers(response):
    response.headers["Cache-Control"] = "no-store" if request.path.startswith("/api/") else "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Content-Security-Policy"] = "default-src 'self' 'unsafe-inline' data:; connect-src 'self'; img-src 'self' data:"
    return response

@app.get("/")
def index():
    return send_from_directory(ROOT,"index.html")

@app.get("/<path:filename>")
def files(filename):
    if filename not in ALLOWED_FILES:
        return jsonify(error="Not found"),404
    return send_from_directory(ROOT,filename)

PORT = int(os.getenv("MONITOR_PORT","8766"))
if __name__ == "__main__":
    app.run(host="127.0.0.1",port=PORT,threaded=True)
