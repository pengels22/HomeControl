from importlib import import_module

import pytest


pnl = import_module('05_PNL.main')


@pytest.mark.asyncio
async def test_pnl_reports_global_display_defaults():
    agent = pnl.PNLAgent({})

    state = await agent.collect_state()

    assert state['display']['auto_refresh_interval_ms'] == 5000
    assert state['display']['default_brightness'] == 100
    assert state['display']['require_authentication'] is True


@pytest.mark.asyncio
async def test_pnl_apply_config_updates_existing_display_settings(tmp_path):
    agent = pnl.PNLAgent({'identity_path': str(tmp_path / 'identity.json')})

    result = await agent.apply_config({
        'version': 2,
        'auto_refresh_interval_ms': 2500,
        'default_brightness': 45,
        'require_authentication': False,
    })
    state = await agent.collect_state()

    assert result['config_version'] == 2
    assert state['display']['auto_refresh_interval_ms'] == 2500
    assert state['display']['default_brightness'] == 45
    assert state['display']['require_authentication'] is False
