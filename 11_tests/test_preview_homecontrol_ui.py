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
    assert js.status_code == 200
    assert "detectPreviewMode" in js.text
    assert "data-output-channel" in js.text
    assert "data-lock-channel" in js.text


def test_browser_route_refresh_serves_spa_for_device_detail(client):
    response = client.get("/devices/RCM2")

    assert response.status_code == 200
    assert '<script src="/static/app.js"></script>' in response.text


def test_preview_devices_include_all_requested_fixtures(client):
    data = client.get("/api/v1/modules", headers=headers()).json()
    modules = {module["hostname"]: module for module in data["modules"]}

    assert set(modules) == {"LAB1", "RCM1", "RCM2", "LCM1", "SIM1", "RCM3"}
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
