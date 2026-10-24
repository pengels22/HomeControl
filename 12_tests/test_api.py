from importlib import import_module
import base64

import pytest
from fastapi import HTTPException

api = import_module('02_HCM.api')
safety_relays_mod = import_module('02_HCM.safety_relays')


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
async def test_time_api_is_read_only_and_exposes_canonical_clock(monkeypatch):
    class Clock:
        def as_payload(self):
            return {'utc': '2026-07-01T03:30:00Z', 'local': '2026-06-30T23:30:00-04:00',
                    'timezone': 'America/Detroit', 'utc_offset_seconds': -14400,
                    'dst': True, 'sync_status': 'unknown', 'checked_at': '2026-07-01T03:30:00Z'}
    monkeypatch.setattr(api, 'time_service', Clock())
    payload = await api.system_time({'user': 'reader', 'role': 'READONLY'})
    assert payload['timezone'] == 'America/Detroit'
    assert payload['sync_status'] == 'unknown'


@pytest.mark.asyncio
async def test_fire_api_rejects_manual_changes_when_physical_input_is_authoritative(monkeypatch):
    class PhysicalSafety:
        fire_active = True
        def physical_fire_input_authoritative(self):
            return True

    monkeypatch.setattr(api, 'safety', PhysicalSafety())
    with pytest.raises(HTTPException) as exc:
        await api.fire(api.FireStateIn(active=False), {'user': 'admin', 'role': 'ADMIN'})
    assert exc.value.status_code == 409

async def test_safety_status_endpoint_returns_controller_source_and_state(monkeypatch):
    class Safety:
        def status_payload(self):
            return {
                'status': 'Normal',
                'system_state': 'normal',
                'fire_active': False,
                'maintenance_lockout_active': False,
                'physical_input_authoritative': True,
                'fire_alarm_s': {'state': 'normal', 'fresh': True, 'age_seconds': 0},
                'fire_alarm_P': {'state': 'present', 'fresh': True, 'age_seconds': 0},
            }

    monkeypatch.setattr(api, 'safety', Safety())
    result = await api.safety_status({'role': 'READONLY'})
    assert result['ok'] is True
    assert result['physical_input_authoritative'] is True
    assert result['fire_alarm_s']['state'] == 'normal'


@pytest.mark.asyncio
async def test_auth_session_returns_current_user():
    result = await api.auth_session({'user': 'patrick', 'role': 'ADMIN'})

    assert result == {'user': 'patrick', 'role': 'ADMIN'}


@pytest.mark.asyncio
async def test_touchscreen_viewer_cannot_use_device_command(monkeypatch):
    async def viewer_session(*args, **kwargs):
        return {'user': 'viewer', 'permission': 'VIEWER', 'device_id': 'screen-1', 'session_id': 1}

    monkeypatch.setattr(api, 'require_touchscreen_session', viewer_session)
    with pytest.raises(HTTPException) as exc:
        await api.device_command(
            api.DeviceCommand(logical_name='Entry Light', command={'op': 'set_relay', 'value': True}),
            authorization=None,
            x_homecontrol_touchscreen_id='screen-1',
            x_homecontrol_touchscreen_session='session',
        )
    assert exc.value.status_code == 403


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
