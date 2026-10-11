from importlib import import_module
import json

import pytest

agent_mod = import_module('07_servises.common.agent')


def test_module_web_html_prompts_for_hcm_login_and_status_only():
    agent = agent_mod.ModuleAgent('RCM', {'web': {'enabled': True}})

    html = agent._module_web_html()

    assert 'Sign in with HCM account' in html
    assert '/api/module/login' in html
    assert '/api/module/status' in html
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
