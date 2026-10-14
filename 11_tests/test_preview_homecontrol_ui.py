from importlib import import_module
import inspect

import pytest
from fastapi.testclient import TestClient


preview = import_module("10_scripts.preview_homecontrol_ui")


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(preview, "state", preview.PreviewState())
    with TestClient(preview.app) as test_client:
        yield test_client


def headers():
    return {"Authorization": f"Bearer {preview.PREVIEW_TOKEN}"}


def test_preview_server_app_starts_and_reports_preview_mode(client):
    response = client.get("/api/v1/preview-mode", headers=headers())

    assert response.status_code == 200
    assert response.json() == {"preview": True, "production_connected": False}


def test_preview_assets_load_from_real_www_directory(client):
    html = client.get("/")
    css = client.get("/static/app.css")
    js = client.get("/static/app.js")

    assert html.status_code == 200
    assert "HomeControl" in html.text
    assert "preview-banner" in html.text
    assert css.status_code == 200
    assert ".preview-banner" in css.text
    assert ".toggle-control" in css.text
    assert ".toggle-thumb" in css.text
    assert ".dashboard-grid" in css.text
    assert ".thermostat-modal" in css.text
    assert js.status_code == 200
    assert "detectPreviewMode" in js.text
    assert "data-output-channel" in js.text
    assert "data-lock-channel" in js.text
    assert "data-open-hvac" in js.text


def test_browser_route_refresh_serves_spa_for_device_detail(client):
    response = client.get("/devices/RCM2")

    assert response.status_code == 200
    assert '<script src="/static/app.js"></script>' in response.text


def test_preview_devices_include_all_requested_fixtures(client):
    data = client.get("/api/v1/modules", headers=headers()).json()
    modules = {module["hostname"]: module for module in data["modules"]}

    assert set(modules) == {"LAB1", "RCM1", "RCM2", "LCM1", "LCM2", "SIM1", "SIM2", "RCM3"}
    assert modules["LAB1"]["last_state"]["state"]["lab_role"] == "UNASSIGNED"
    assert modules["LAB1"]["last_state"]["state"]["simulation"] is True
    assert modules["LAB1"]["last_state"]["state"]["physical_outputs_enabled"] is False
    assert modules["RCM3"]["online"] is False


def test_role_based_device_interface_selection_uses_fixture_role(client):
    lab = client.get("/api/v1/device-admin/LAB1", headers=headers()).json()
    rcm = client.get("/api/v1/device-admin/RCM2", headers=headers()).json()
    lcm = client.get("/api/v1/device-admin/LCM1", headers=headers()).json()
    sim = client.get("/api/v1/device-admin/SIM1", headers=headers()).json()

    assert lab["effective_role"] == "UNASSIGNED"
    assert rcm["effective_role"] == "RCM"
    assert lcm["effective_role"] == "LCM"
    assert sim["effective_role"] == "SIM"


def test_dashboard_frontend_uses_health_overview_and_effective_roles(client):
    js = client.get("/static/app.js").text

    assert "Attention Required" in js
    assert "moduleEffectiveRole" in js
    assert "module_type" in js
    assert "registered " in js
    assert "deviceTable(modules)" not in js[js.index("async function renderDashboard"):js.index("function settledValue")]
    assert "Conflict Supervisor" in js
    assert "Fire / Life Safety" in js


def test_preview_health_and_logical_devices_support_dashboard_metrics(client):
    health = client.get("/api/v1/health", headers=headers()).json()
    logical = client.get("/api/v1/logical-devices", headers=headers()).json()

    assert health["heartbeat_supervisor"]["status"] == "Online"
    assert health["fire_life_safety"]["status"] == "Unavailable"
    assert health["active_fault_count"] == 2
    assert any(device["maintenance_locked"] for device in logical["logical_devices"])


def test_hvac_preview_supports_modal_modes_and_threshold_contract(client):
    js = client.get("/static/app.js").text

    assert 'hvacModeOption("HEAT"' in js
    assert 'hvacModeOption("COOL"' in js
    assert 'hvacModeOption("HEAT_COOL"' in js
    assert 'hvacModeOption("FAN"' in js
    assert 'hvacModeOption("OFF"' in js
    assert "target - 3" in js
    assert "target + 2" in js
    assert "Heat/Cool is not supported by the current production HCM HVAC API" in js
    assert "Applying thermostat request" in js
    assert "HVAC command failed" in js


def test_hvac_preview_state_updates_only_through_authenticated_preview_api(client):
    unauthorized = client.put("/api/v1/hvac/mode", json={"mode": "FAN"})
    mode = client.put("/api/v1/hvac/mode", headers=headers(), json={"mode": "FAN"})
    setpoint = client.put("/api/v1/hvac/setpoint", headers=headers(), json={"setpoint_f": 73})
    invalid = client.put("/api/v1/hvac/mode", headers=headers(), json={"mode": "EMERGENCY_HEAT"})
    state = client.get("/api/v1/hvac", headers=headers()).json()

    assert unauthorized.status_code == 401
    assert mode.status_code == 200
    assert setpoint.status_code == 200
    assert invalid.status_code == 422
    assert state["mode"] == "FAN"
    assert state["fan"] is True
    assert state["setpoint_f"] == 73.0


def test_sim_preview_dashboard_reports_can_loops_room_groups_and_ai(client):
    data = client.get("/api/v1/device-admin/SIM1/sim-dashboard", headers=headers()).json()

    assert data["device"]["effective_role"] == "SIM"
    assert [loop["status"] for loop in data["can_loops"]] == ["Online", "Online", "Fault"]
    rooms = {group["room"]: group for group in data["room_clusters"]}
    assert "Living Room" in rooms
    assert len(rooms["Living Room"]["rmcs"]) == 2
    assert len(data["analog_inputs"]) == 10
    assert [item["channel"] for item in data["analog_inputs"]] == [f"AI-{index}" for index in range(1, 11)]


def test_sim_preview_unknown_status_when_diagnostics_are_missing(client):
    data = client.get("/api/v1/device-admin/SIM2/sim-dashboard", headers=headers()).json()

    assert [loop["status"] for loop in data["can_loops"]] == ["Unknown", "Unknown", "Unknown"]
    assert next(item for item in data["analog_inputs"] if item["channel"] == "AI-10")["status"] == "Unknown"


def test_sim_rmc_name_change_persists_without_altering_identity(client):
    before = client.get("/api/v1/device-admin/SIM1/sim-dashboard", headers=headers()).json()
    original = next(item for item in before["rmcs"] if item["id"] == "RMC:can0:1")

    response = client.patch(
        "/api/v1/device-admin/SIM1/sim-rmcs/RMC:can0:1/settings",
        headers=headers(),
        json={"name": "Living Room Primary"},
    )

    assert response.status_code == 200
    updated = next(item for item in response.json()["rmcs"] if item["id"] == "RMC:can0:1")
    assert updated["name"] == "Living Room Primary"
    assert updated["id"] == original["id"]
    assert updated["can_interface"] == original["can_interface"]
    assert updated["can_node_address"] == original["can_node_address"]
    assert updated["room"] == original["room"]


def test_sim_settings_require_authorization_and_bound_identity(client):
    unauthorized = client.patch(
        "/api/v1/device-admin/SIM1/sim-rmcs/RMC:can0:1/settings",
        json={"name": "Nope"},
    )
    unbound_rmc = client.patch(
        "/api/v1/device-admin/SIM1/sim-rmcs/RMC:can2:4/settings",
        headers=headers(),
        json={"name": "Should Not Save"},
    )
    unbound_ai = client.patch(
        "/api/v1/device-admin/SIM1/sim-analog-inputs/AI-10/settings",
        headers=headers(),
        json={"name": "Should Not Save"},
    )

    assert unauthorized.status_code == 401
    assert unbound_rmc.status_code == 404
    assert unbound_ai.status_code == 404


def test_sim_device_scoping_and_stale_missing_telemetry(client):
    sim1 = client.get("/api/v1/device-admin/SIM1/sim-dashboard", headers=headers()).json()
    sim2 = client.get("/api/v1/device-admin/SIM2/sim-dashboard", headers=headers()).json()

    assert sim1["rmcs"]
    assert sim2["rmcs"] == []
    stale = next(item for item in sim1["rmcs"] if item["status"] == "Stale")
    assert stale["readings"]["lux"]["status"] == "Unknown"
    assert stale["readings"]["temperature_f"]["status"] == "Stale"


def test_sim_frontend_uses_dashboard_and_no_output_controls(client):
    js = client.get("/static/app.js").text

    assert "renderSim" in js
    assert "/sim-dashboard" in js
    assert "Room Clusters" in js
    assert "Analog Inputs" in js
    assert "data-sim-rmc-settings" in js
    assert "rmc-grid" in js
    assert "rmc-details" not in js
    assert "set_hexa" not in js


def test_sim_frontend_rmc_cards_are_compact_and_dialog_contains_diagnostics(client):
    js = client.get("/static/app.js").text
    css = client.get("/static/app.css").text

    assert "cog-button" in js
    assert "Permanent ID" in js
    assert "Last heartbeat" in js
    assert "Health flags" in js
    assert "This RMC is not bound to a logical device" in js
    assert ".rmc-grid" in css
    assert "grid-template-columns: repeat(3, minmax(0, 1fr))" in css


def test_lcm_preview_loads_lights_and_dimmers(client):
    data = client.get("/api/v1/device-admin/LCM1/lcm-channels", headers=headers()).json()

    assert data["device"]["effective_role"] == "LCM"
    assert {channel["kind"] for channel in data["channels"]} == {"light", "dimmer"}
    assert [channel["channel"] for channel in data["channels"][:8]] == [f"A{i}" for i in range(1, 9)]
    assert [channel["channel"] for channel in data["channels"][8:18]] == [f"10-{i}" for i in range(1, 11)]
    assert [channel["channel"] for channel in data["channels"][18:]] == [f"HV-{i}" for i in range(1, 5)]
    assert len(data["channels"]) == 22
    assert len([channel for channel in data["channels"] if channel["kind"] == "light"]) == 8
    assert len([channel for channel in data["channels"] if channel["kind"] == "dimmer"]) == 14
    assert next(channel for channel in data["channels"] if channel["channel"] == "A8")["type_label"] == "Relay"
    assert next(channel for channel in data["channels"] if channel["channel"] == "10-10")["type_label"] == "0-10V"
    assert next(channel for channel in data["channels"] if channel["channel"] == "HV-4")["type_label"] == "110V"
    assert any(channel["emergency_lighting"] for channel in data["channels"])
    assert any(channel["maintenance_locked"] for channel in data["channels"])


def test_lcm_unbound_channels_are_visible_but_disabled(client):
    data = client.get("/api/v1/device-admin/LCM1/lcm-channels", headers=headers()).json()
    channel = next(item for item in data["channels"] if item["channel"] == "10-10")

    assert channel["bound"] is False
    assert channel["logical_name"] is None
    assert channel["control_enabled"] is False
    assert channel["disabled_reason"] == "No logical binding"

    command = client.post(
        "/api/v1/device/command",
        headers=headers(),
        json={"logical_name": "LCM1 10-10", "command": {"op": "set_dimmer", "percent": 50}},
    )
    settings = client.patch(
        "/api/v1/device-admin/LCM1/lcm-channels/10-10/settings",
        headers=headers(),
        json={"name": "Should Not Save", "emergency_lighting": False, "max_intensity": 50, "fade_seconds": 3},
    )

    assert command.status_code == 404
    assert settings.status_code == 404


def test_lcm_light_command_is_scoped_to_selected_module(client):
    result = client.post(
        "/api/v1/device/command",
        headers=headers(),
        json={"logical_name": "LCM1 A1", "command": {"op": "set_relay", "value": True}},
    )

    assert result.status_code == 200
    lcm1 = client.get("/api/v1/device-admin/LCM1/lcm-channels", headers=headers()).json()
    lcm2 = client.get("/api/v1/device-admin/LCM2/lcm-channels", headers=headers()).json()

    assert next(item for item in lcm1["channels"] if item["channel"] == "A1")["value"] is True
    assert next(item for item in lcm2["channels"] if item["channel"] == "A1")["value"] is False


def test_lcm_dimmer_clamps_to_max_without_error_and_preserves_requested_effective(client):
    result = client.post(
        "/api/v1/device/command",
        headers=headers(),
        json={"logical_name": "LCM1 10-2", "command": {"op": "set_dimmer", "percent": 100}},
    )

    assert result.status_code == 423

    client.post(
        "/api/v1/safety/maintenance-lockout",
        headers=headers(),
        json={"logical_name": "LCM1 10-2", "active": False},
    )
    result = client.post(
        "/api/v1/device/command",
        headers=headers(),
        json={"logical_name": "LCM1 10-2", "command": {"op": "set_dimmer", "percent": 100}},
    )

    assert result.status_code == 200
    assert result.json()["requested"]["percent"] == 100
    assert result.json()["effective"]["percent"] == 75.0


def test_lcm_off_and_restore_behavior_in_preview(client):
    client.post(
        "/api/v1/device/command",
        headers=headers(),
        json={"logical_name": "LCM1 HV-1", "command": {"op": "set_dimmer", "percent": 42}},
    )
    client.post(
        "/api/v1/device/command",
        headers=headers(),
        json={"logical_name": "LCM1 HV-1", "command": {"op": "set_dimmer", "percent": 0}},
    )
    off = client.get("/api/v1/device-admin/LCM1/lcm-channels", headers=headers()).json()
    hv = next(item for item in off["channels"] if item["channel"] == "HV-1")

    assert hv["percent"] == 0.0
    assert hv["last_nonzero_percent"] == 42.0


def test_lcm_maintenance_lockout_forces_off_and_prevents_activation(client):
    client.post(
        "/api/v1/device/command",
        headers=headers(),
        json={"logical_name": "LCM2 10-1", "command": {"op": "set_dimmer", "percent": 55}},
    )
    lock = client.post(
        "/api/v1/safety/maintenance-lockout",
        headers=headers(),
        json={"logical_name": "LCM2 10-1", "active": True},
    )
    rejected = client.post(
        "/api/v1/device/command",
        headers=headers(),
        json={"logical_name": "LCM2 10-1", "command": {"op": "set_dimmer", "percent": 20}},
    )
    data = client.get("/api/v1/device-admin/LCM2/lcm-channels", headers=headers()).json()
    channel = next(item for item in data["channels"] if item["channel"] == "10-1")

    assert lock.status_code == 200
    assert channel["maintenance_locked"] is True
    assert channel["percent"] == 0.0
    assert rejected.status_code == 423


def test_lcm_settings_validation_names_and_elight(client):
    invalid = client.patch(
        "/api/v1/device-admin/LCM1/lcm-channels/10-1/settings",
        headers=headers(),
        json={"name": "", "emergency_lighting": False, "max_intensity": 50, "fade_seconds": 3},
    )
    valid = client.patch(
        "/api/v1/device-admin/LCM1/lcm-channels/10-1/settings",
        headers=headers(),
        json={"name": "Island Pendant", "emergency_lighting": True, "max_intensity": 62, "fade_seconds": 1.5},
    )

    assert invalid.status_code == 400
    assert valid.status_code == 200
    channel = next(item for item in valid.json()["channels"] if item["channel"] == "10-1")
    assert channel["name"] == "Island Pendant"
    assert channel["emergency_lighting"] is True
    assert channel["max_intensity"] == 62
    assert channel["fade_seconds"] == 1.5


def test_lcm_frontend_slider_commits_on_change_not_input(client):
    js = client.get("/static/app.js").text

    assert 'document.addEventListener("input"' in js
    assert 'document.addEventListener("change"' in js
    assert "data-dimmer-slider" in js


def test_lcm_frontend_uses_compact_three_column_layout_and_unknown_telemetry(client):
    js = client.get("/static/app.js").text
    css = client.get("/static/app.css").text

    assert 'lcmColumn("Relays"' in js
    assert 'lcmColumn("0-10V Dimmers"' in js
    assert 'lcmColumn("110V Dimmers"' in js
    assert "Unknown" in js
    assert ".lcm-columns" in css
    assert "grid-template-columns: minmax(210px, 0.9fr) minmax(230px, 1fr) minmax(210px, 0.9fr)" in css


def test_rcm1_and_rcm2_state_is_isolated(client):
    rename = client.patch(
        "/api/v1/device-admin/RCM1/rcm-channels/A1/name",
        headers=headers(),
        json={"name": "RCM1 Pump"},
    )
    command = client.post(
        "/api/v1/device/command",
        headers=headers(),
        json={"logical_name": "RCM1 A1", "command": {"op": "set_relay", "value": True}},
    )

    assert rename.status_code == 200
    assert command.status_code == 200
    rcm1 = client.get("/api/v1/device-admin/RCM1/rcm-channels", headers=headers()).json()
    rcm2 = client.get("/api/v1/device-admin/RCM2/rcm-channels", headers=headers()).json()

    assert rcm1["channels"][0]["name"] == "RCM1 Pump"
    assert rcm1["channels"][0]["value"] is True
    assert rcm2["channels"][0]["name"] == "RCM2 Channel 1"
    assert rcm2["channels"][0]["value"] is False


def test_channel_rename_persists_in_preview_memory(client):
    client.patch(
        "/api/v1/device-admin/RCM2/rcm-channels/B2/name",
        headers=headers(),
        json={"name": "Exhaust Fan"},
    )

    data = client.get("/api/v1/device-admin/RCM2/rcm-channels", headers=headers()).json()
    channel = next(item for item in data["channels"] if item["channel"] == "B2")

    assert channel["name"] == "Exhaust Fan"


def test_maintenance_lockout_forces_off_and_unlock_leaves_off(client):
    client.post(
        "/api/v1/device/command",
        headers=headers(),
        json={"logical_name": "RCM2 A1", "command": {"op": "set_relay", "value": True}},
    )
    client.post(
        "/api/v1/safety/maintenance-lockout",
        headers=headers(),
        json={"logical_name": "RCM2 A1", "active": True},
    )
    locked = client.get("/api/v1/device-admin/RCM2/rcm-channels", headers=headers()).json()["channels"][0]
    client.post(
        "/api/v1/safety/maintenance-lockout",
        headers=headers(),
        json={"logical_name": "RCM2 A1", "active": False},
    )
    unlocked = client.get("/api/v1/device-admin/RCM2/rcm-channels", headers=headers()).json()["channels"][0]

    assert locked["maintenance_locked"] is True
    assert locked["value"] is False
    assert locked["control_enabled"] is False
    assert unlocked["maintenance_locked"] is False
    assert unlocked["value"] is False


def test_locked_output_rejects_energize_command(client):
    client.post(
        "/api/v1/safety/maintenance-lockout",
        headers=headers(),
        json={"logical_name": "RCM1 A1", "active": True},
    )

    response = client.post(
        "/api/v1/device/command",
        headers=headers(),
        json={"logical_name": "RCM1 A1", "command": {"op": "set_relay", "value": True}},
    )

    assert response.status_code == 423
    assert "maintenance lockout" in response.text


def test_preview_source_does_not_import_production_api_or_database():
    source = inspect.getsource(preview)

    assert "01_HCM.api" not in source
    assert "01_HCM.db" not in source
    assert "asyncpg" not in source
    assert "database_url" not in source
