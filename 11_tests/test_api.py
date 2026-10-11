from importlib import import_module
import base64

import pytest
from fastapi import HTTPException

api = import_module('01_HCM.api')
safety_relays_mod = import_module('01_HCM.safety_relays')


class FakeModuleSession:
    device_id = '2ccf675d3414'
    connection_key = '2ccf675d3414'

    def __init__(self):
        self.commands = []

    async def command(self, payload, request_id=None, timeout=10.0):
        self.commands.append((payload, request_id, timeout))
        return {'ok': True, 'accepted': True}


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


@pytest.mark.asyncio
async def test_hcm_safety_relay_pulse_requires_admin(monkeypatch):
    controller = safety_relays_mod.HCMSafetyRelayController()
    monkeypatch.setattr(api, 'safety_relays', controller)

    with pytest.raises(HTTPException) as exc:
        await api.safety_hcm_relay_pulse(
            api.SafetyRelayPulseIn(relay='door_request'),
            {'user': 'viewer', 'role': 'READONLY'},
        )

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_hcm_safety_relay_pulse_uses_global_default(monkeypatch):
    controller = safety_relays_mod.HCMSafetyRelayController()
    monkeypatch.setattr(api, 'safety_relays', controller)

    result = await api.safety_hcm_relay_pulse(
        api.SafetyRelayPulseIn(relay='door_request'),
        {'user': 'patrick', 'role': 'ADMIN'},
    )
    await controller.shutdown()

    assert result['ok'] is True
    assert result['pulse_ms'] == 3000
    assert result['relay']['lockout_exempt'] is True


@pytest.mark.asyncio
async def test_module_role_change_requires_admin():
    with pytest.raises(HTTPException) as exc:
        await api.module_role_change(
            '2ccf675d3414',
            api.ModuleRoleChangeIn(requested_role='SIM', confirm=True),
            {'user': 'viewer', 'role': 'READONLY'},
        )

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_module_role_change_requires_explicit_confirmation():
    with pytest.raises(HTTPException) as exc:
        await api.module_role_change(
            '2ccf675d3414',
            api.ModuleRoleChangeIn(requested_role='SIM', confirm=False),
            {'user': 'patrick', 'role': 'ADMIN'},
        )

    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_module_role_change_sends_existing_control_session(monkeypatch):
    session = FakeModuleSession()
    monkeypatch.setattr(api.registry, 'connections', {'2ccf675d3414': session})
    monkeypatch.setattr(api.registry, '_connections_lock', __import__('asyncio').Lock())

    async def create_transition(**kwargs):
        assert kwargs['actor'] == 'patrick'
        assert kwargs['control_session_key'] == '2ccf675d3414'
        return {
            'operation_id': '11111111-2222-4333-8444-555555555555',
            'command_payload': {
                'op': 'set_module_role',
                'device_id': '2ccf675d3414',
                'requested_role': 'SIM',
                'simulation_required': True,
            },
        }

    async def mark_sent(operation_id):
        assert operation_id == '11111111-2222-4333-8444-555555555555'

    async def mark_acknowledged(operation_id, ack):
        assert ack == {'ok': True, 'accepted': True}
        return {'operation_id': operation_id, 'status': 'ACCEPTED'}

    monkeypatch.setattr(api.role_switching, 'create_transition', create_transition)
    monkeypatch.setattr(api.role_switching, 'mark_sent', mark_sent)
    monkeypatch.setattr(api.role_switching, 'mark_acknowledged', mark_acknowledged)

    result = await api.module_role_change(
        '2ccf675d3414',
        api.ModuleRoleChangeIn(requested_role='SIM', confirm=True),
        {'user': 'patrick', 'role': 'ADMIN'},
    )

    assert result['status'] == 'ACCEPTED'
    assert session.commands[0][0]['operation_id'] == '11111111-2222-4333-8444-555555555555'
    assert session.commands[0][1] == '11111111-2222-4333-8444-555555555555'


@pytest.mark.asyncio
async def test_module_role_change_rejects_offline_module(monkeypatch):
    monkeypatch.setattr(api.registry, 'connections', {})
    monkeypatch.setattr(api.registry, '_connections_lock', __import__('asyncio').Lock())

    with pytest.raises(HTTPException) as exc:
        await api.module_role_change(
            '2ccf675d3414',
            api.ModuleRoleChangeIn(requested_role='SIM', confirm=True),
            {'user': 'patrick', 'role': 'ADMIN'},
        )

    assert exc.value.status_code == 409
