import asyncio
from importlib import import_module

import pytest


safety_relays = import_module('01_HCM.safety_relays')


@pytest.mark.asyncio
async def test_hcm_safety_relays_are_simulated_and_lockout_exempt():
    controller = safety_relays.HCMSafetyRelayController()

    status = controller.status()

    assert status['mode'] == 'simulated_gpio'
    assert status['maintenance_lockout_exempt'] is True
    assert status['relays']['alarm_contact']['direction'] == 'input'
    assert status['relays']['door_request']['lockout_exempt'] is True
    assert status['relays']['auxiliary']['lockout_exempt'] is True


@pytest.mark.asyncio
async def test_hcm_door_request_pulse_uses_configured_bounds_and_releases():
    controller = safety_relays.HCMSafetyRelayController()

    result = await controller.pulse('door_request', duration_ms=250)

    assert result['ok'] is True
    assert result['pulse_ms'] == 250
    assert controller.relays['door_request'].active is True
    await asyncio.sleep(0.26)
    assert controller.relays['door_request'].active is False


@pytest.mark.asyncio
async def test_hcm_relay_input_cannot_be_written_as_output():
    controller = safety_relays.HCMSafetyRelayController()

    with pytest.raises(ValueError):
        await controller.set_output('alarm_contact', True)


@pytest.mark.asyncio
async def test_hcm_auxiliary_relay_can_be_set_and_shutdown_without_lockout_arbitration():
    controller = safety_relays.HCMSafetyRelayController()

    result = await controller.set_output('auxiliary', True)
    await controller.shutdown()

    assert result['relay']['active'] is True
    assert controller.relays['auxiliary'].active is False
