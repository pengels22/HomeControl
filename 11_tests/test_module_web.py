from importlib import import_module

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
