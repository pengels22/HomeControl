from importlib import import_module
import json
import time

import pytest

agent_mod = import_module('07_servises.common.agent')
infra = import_module('07_servises.common.module_infra')


def test_module_web_html_prompts_for_hcm_login_and_status_only():
    agent = agent_mod.ModuleAgent('RCM', {'web': {'enabled': True}})

    html = agent._module_web_html()

    assert 'Sign in with HCM account' in html
    assert '/api/module/login' in html
    assert '/api/module/status' in html
    assert '/api/module/config' in html
    assert '/device/command' not in html


@pytest.mark.asyncio
async def test_module_web_status_includes_identity_and_hcm_connection_flag():
    agent = agent_mod.ModuleAgent('LCM', {'web': {'enabled': True}, 'tls': {'key_file': '/secret/key.pem'}})
    agent.hcm_connected = True

    status = await agent.web_status()

    assert status['module_type'] == 'LCM'
    assert status['identity']['module_type'] == 'LCM'
    assert status['hcm_connected'] is True
    assert status['config']['web']['enabled'] is True
    assert status['config']['tls']['key_file'] == '<redacted>'
    assert status['component_health']['i2c']
    assert status['pending_hcm_log_delivery_count'] == 0
    assert status['hcm_heartbeat_health']['connected'] is True


@pytest.mark.asyncio
async def test_module_agent_persists_heartbeat_supervisor_config(tmp_path):
    identity_path = tmp_path / 'identity.json'
    agent = agent_mod.ModuleAgent('SIM', {'identity_path': str(identity_path)})
    payload = {
        'version': 4,
        'heartbeat_supervisor': {
            'enabled': True,
            'device_id': '3c53bbf7adb2',
            'host': '192.168.20.26',
            'port': 6004,
            'interval_seconds': 5,
            'timeout_seconds': 15,
            'protocol': 'hcm-heartbeat-v3',
        },
    }

    result = await agent.apply_config(payload)

    saved = json.loads(identity_path.read_text())
    assert result == {'ok': True, 'config_version': 4}
    assert saved['heartbeat_supervisor'] == payload['heartbeat_supervisor']


@pytest.mark.asyncio
async def test_module_web_status_tracks_valid_heartbeat_ack():
    agent = agent_mod.ModuleAgent('LCM', {'web': {'enabled': True}, 'heartbeat_seconds': 5})
    agent.last_valid_ack_ts = __import__('time').time()

    status = await agent.web_status()

    assert status['hcm_heartbeat_health']['ack_current'] is True
    assert status['led_state']['LINK'] is True


@pytest.mark.asyncio
async def test_module_rejects_stale_config_and_preserves_local_lockouts(tmp_path):
    agent = agent_mod.ModuleAgent('RCM', {'runtime_root': str(tmp_path)})
    agent.identity['hostname'] = 'RCM1'
    local = {
        'channels': [
            {'channel': channel, 'name': channel, 'on': False, 'lockout': channel == 'A1'}
            for channel in infra.RCM_RELAY_CHANNELS
        ]
    }
    agent.config_store.save_json({'config': local})
    agent.config_sync['current_local_revision'] = 'local-rev'
    package = infra.build_config_package('RCM', 'RCM1', {
        'channels': [
            {'channel': channel, 'name': channel, 'on': False, 'lockout': False}
            for channel in infra.RCM_RELAY_CHANNELS
        ]
    }, revision='hcm-rev')

    stale = await agent.apply_config({'package': package, 'base_revision': 'older-rev'})
    applied = await agent.apply_config({'package': package, 'base_revision': 'local-rev'})

    assert stale['ok'] is False
    assert stale['error'] == 'stale_configuration'
    assert applied['ok'] is True
    assert applied['config_sync']['state'] == 'conflict'
    saved_channels = agent.config_store.load_json()['config']['channels']
    assert next(item for item in saved_channels if item['channel'] == 'A1')['lockout'] is True


@pytest.mark.asyncio
async def test_offline_local_auth_and_config_edit_without_hcm(tmp_path):
    agent = agent_mod.ModuleAgent('LCM', {'runtime_root': str(tmp_path), 'web': {'enabled': True}})
    hashed = infra.LocalAuthStore.hash_password('offline-admin-password')
    await agent.apply_config({'version': 1, 'offline_admins': [{**hashed, 'username': 'local-admin', 'role': 'ADMIN'}]})
    session = agent.local_auth.authenticate('local-admin', 'offline-admin-password', now=time.time())

    result = await agent.apply_local_config_edit({'note': 'offline edit'}, actor=session['username'])
    health = await agent.web_status()

    assert session is not None
    assert result['ok'] is True
    assert result['config_sync']['state'] == 'local_changes_pending_hcm_reconciliation'
    assert health['pending_hcm_log_delivery_count'] >= 1
    assert 'password' not in json.dumps(health).lower()


def test_local_auth_blocks_invalid_credentials_and_expires_sessions(tmp_path):
    auth = infra.LocalAuthStore(tmp_path / 'auth.json', session_ttl_s=1, max_failures=2, lockout_s=60)
    hashed = infra.LocalAuthStore.hash_password('correct horse battery staple')
    auth.provision_hashes([{**hashed, 'username': 'admin'}])

    assert auth.authenticate('admin', 'bad', now=10) is None
    assert auth.authenticate('admin', 'bad', now=11) is None
    assert auth.authenticate('admin', 'correct horse battery staple', now=12) is None
    session = auth.authenticate('admin', 'correct horse battery staple', now=80)

    assert session is not None
    assert auth.session(session['token'], now=80.5) is not None
    assert auth.session(session['token'], now=82) is None
