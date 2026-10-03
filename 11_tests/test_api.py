from importlib import import_module
import base64

import pytest
from fastapi import HTTPException

api = import_module('01_HCM.api')


@pytest.mark.asyncio
async def test_dev_session_hidden_when_dev_mode_disabled(monkeypatch):
    monkeypatch.setattr(api.settings, 'dev_mode', False)

    with pytest.raises(HTTPException) as exc:
        await api.dev_session()

    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_dev_session_available_when_dev_mode_enabled(monkeypatch):
    monkeypatch.setattr(api.settings, 'dev_mode', True)

    result = await api.dev_session()

    assert 'token' in result
    assert result['token']


@pytest.mark.asyncio
async def test_auth_session_returns_current_user():
    result = await api.auth_session({'user': 'patrick', 'role': 'ADMIN'})

    assert result == {'user': 'patrick', 'role': 'ADMIN'}


@pytest.mark.asyncio
async def test_passkey_challenge_endpoint_uses_auth_service(monkeypatch):
    async def create_login_challenge(username):
        return {'rp_id': 'homecontrol.local', 'username': username, 'challenge': 'abc'}

    monkeypatch.setattr(api, 'create_login_challenge', create_login_challenge)

    result = await api.auth_challenge(api.AuthChallengeIn(username='patrick'))

    assert result == {'rp_id': 'homecontrol.local', 'username': 'patrick', 'challenge': 'abc'}


@pytest.mark.asyncio
async def test_passkey_verify_endpoint_returns_session_token(monkeypatch):
    async def verify_login_challenge(username, challenge, assertion):
        assert username == 'patrick'
        assert challenge == 'abc'
        assert assertion == {'client': 'data'}
        return 'session-token'

    monkeypatch.setattr(api, 'verify_login_challenge', verify_login_challenge)

    result = await api.auth_verify(
        api.AuthVerifyIn(username='patrick', challenge='abc', assertion={'client': 'data'})
    )

    assert result == {'token': 'session-token'}


@pytest.mark.asyncio
async def test_rmc_firmware_update_endpoint_routes_through_updater(monkeypatch):
    async def update_rmc_via_sim(**kwargs):
        assert kwargs['target_rmc_id'] == 'RMC-07'
        assert kwargs['sim_hostname'] == 'SIM01'
        assert kwargs['can_interface'] == 'can0'
        assert kwargs['node_id'] == 7
        assert kwargs['firmware_image'] == b'firmware'
        assert kwargs['firmware_version'] == '1.4.0'
        return {'ok': True, 'state': 'COMPLETE'}

    monkeypatch.setattr(api.updater, 'update_rmc_via_sim', update_rmc_via_sim)

    result = await api.rmc_firmware_update(
        api.RmcFirmwareUpdateIn(
            target_rmc_id='RMC-07',
            sim_hostname='SIM01',
            can_interface='can0',
            node_id=7,
            firmware_version='1.4.0',
            firmware_image_b64=base64.b64encode(b'firmware').decode('ascii'),
        ),
        {'user': 'patrick', 'role': 'ADMIN'},
    )

    assert result == {'ok': True, 'state': 'COMPLETE'}
