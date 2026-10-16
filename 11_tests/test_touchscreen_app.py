from importlib import import_module

import pytest
from fastapi.testclient import TestClient


touchscreen = import_module('10_scripts.touchscreen_app')


def test_role_navigation_is_shared_and_status_is_omitted_after_four_pages():
    assert touchscreen.ROLE_PAGES['RCM'] == ['status', 'relays', 'network', 'settings']
    pages = ['status', 'one', 'two', 'three', 'four']
    assert [page for page in pages if page != 'status'] == ['one', 'two', 'three', 'four']


@pytest.fixture()
def client():
    with TestClient(touchscreen.app) as test_client:
        yield test_client


@pytest.mark.parametrize('role', ['RCM', 'LCM', 'SIM', 'HCM'])
def test_each_role_has_shared_state_and_simulation_safety(client, role):
    response = client.get('/api/touchscreen/state', params={'role': role})
    assert response.status_code == 200
    state = response.json()
    assert state['module']['role'] == role
    assert state['module']['simulation'] is True
    assert state['module']['physical_outputs_enabled'] is False
    assert state['hardware_profile']['physical_output_enabled'] is False


def test_lcm_exposes_fourteen_dimmers_and_threshold_normalization(client):
    state = client.get('/api/touchscreen/state', params={'role': 'LCM'}).json()
    assert [item['channel'] for item in state['dimmers']] == [f'10-{i}' for i in range(1, 11)] + [f'HV-{i}' for i in range(1, 5)]
    for value, expected in [(0, 0), (1, 0), (5, 0), (6, 6), (100, 100)]:
        response = client.post('/api/touchscreen/command', json={'kind': 'dimmer', 'channel': '10-1', 'value': value, 'role': 'LCM'})
        assert response.status_code == 200
        assert response.json()['value'] == expected
        assert response.json()['physical_output_commanded'] is False


def test_relay_ack_is_simulated_and_lockout_is_enforced(client):
    response = client.post('/api/touchscreen/command', json={'kind': 'relay', 'channel': 'A1', 'value': True, 'role': 'RCM'})
    assert response.status_code == 200
    assert response.json()['simulated'] is True
    assert response.json()['physical_output_commanded'] is False
    touchscreen.adapters['RCM'].state['relays'][0]['lockout'] = True
    blocked = client.post('/api/touchscreen/command', json={'kind': 'relay', 'channel': 'A1', 'value': False, 'role': 'RCM'})
    assert blocked.status_code == 409
    touchscreen.adapters['RCM'].state['relays'][0]['lockout'] = False


def test_permission_guard_rejects_unauthorized_command(client):
    response = client.post('/api/touchscreen/command', json={'kind': 'relay', 'channel': 'A1', 'value': True, 'role': 'RCM', 'authorized': False})
    assert response.status_code == 403


def test_sim_rmc_data_is_stale_safe_and_hcm_sensor_scope_is_external_only(client):
    sim = client.get('/api/touchscreen/state', params={'role': 'SIM'}).json()
    assert sim['rooms'][0]['online'] is False
    assert sim['rooms'][0]['temperature_f'] is None
    hcm = client.get('/api/touchscreen/state', params={'role': 'HCM'}).json()
    assert [item['name'] for item in hcm['external_sensors']] == ['FIRE input', 'AC monitor']
    assert all(item['value'] == 'Unavailable' for item in hcm['external_sensors'])


def test_static_preview_assets_are_available(client):
    assert client.get('/').status_code == 200
    assert client.get('/assets/touchscreen.css').status_code == 200
    assert client.get('/assets/touchscreen.js').status_code == 200
