from importlib import import_module

import pytest
from fastapi import HTTPException


api = import_module('01_HCM.pnl_production_api')


def test_production_router_exposes_separate_admin_and_panel_contracts():
    paths = {route.path for route in api.router.routes}
    assert '/api/v1/pnl-production/admin/devices' in paths
    assert '/api/v1/pnl-production/admin/dashboard-assignments' in paths
    assert '/api/v1/pnl-production/panel/config' in paths
    assert '/api/v1/pnl-production/panel/state' in paths
    assert '/api/v1/pnl-production/panel/events' in paths
    assert '/api/v1/pnl-production/panel/commands' in paths
    assert '/api/v1/pnl-production/panel/sonic-ack' in paths


def test_panel_auth_headers_normalize_mac_and_fail_closed():
    assert api._panel_headers('Bearer token', '02:00:00:00:00:10') == ('020000000010', 'token')
    with pytest.raises(HTTPException) as missing:
        api._panel_headers(None, '02:00:00:00:00:10')
    assert missing.value.status_code == 401
    with pytest.raises(HTTPException):
        api._panel_headers('Bearer token', 'not-a-mac')


def test_command_and_occupancy_contracts_bound_payloads():
    command = api.CommandIn(request_id='x', card_type='slider', entity='light.main', value=55)
    assert command.ttl_seconds == 30
    event = api.OccupancyIn(sequence=1, event_key='motion-1', occupied=True, occurred_at='2026-10-24T12:00:00Z')
    assert event.occupied is True
    with pytest.raises(ValueError):
        api.CommandIn(request_id='', card_type='button', entity='light.main', value=True)
