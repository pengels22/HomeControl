import asyncio
from types import SimpleNamespace
from importlib import import_module

import pytest

climate = import_module('01_HCM.climate')
importer = import_module('01_HCM.ha_importer')


class Controller:
    def __init__(self):
        self.state = SimpleNamespace(mode=SimpleNamespace(value='OFF'), setpoint_f=68.0)
        self.calls = []

    def average_temperature(self):
        return 67.5

    async def persist_state(self):
        self.calls.append('persist')

    async def evaluate(self):
        self.calls.append('evaluate')

    async def force_off(self):
        self.calls.append('force_off')
        return {'ok': True}


@pytest.mark.asyncio
async def test_climate_requests_delegate_and_publish_logical_state_only():
    controller = Controller()
    layer = climate.HVACSemanticLayer(controller)
    result = await layer.set_temperature(7, 70.0)
    assert result['status'] == 'accepted'
    assert controller.state.setpoint_f == 70.0
    assert controller.calls == ['persist', 'evaluate']
    result = await layer.set_hvac_mode(7, 'heat')
    assert result['mode'] == 'heat'
    assert controller.calls[-2:] == ['persist', 'evaluate']


@pytest.mark.asyncio
async def test_turn_off_is_allowed_during_fire_and_uses_authority():
    controller = Controller()
    safety = SimpleNamespace(fire_active=True, maintenance_lockout_active=False)
    layer = climate.HVACSemanticLayer(controller, policy=climate.HVACPolicy(safety))
    assert (await layer.set_hvac_mode(1, 'cool'))['status'] == 'blocked'
    assert (await layer.turn_off(1))['status'] == 'accepted'
    assert 'force_off' in controller.calls


@pytest.mark.asyncio
async def test_temperature_validation_and_dry_run():
    layer = climate.HVACSemanticLayer(Controller())
    with pytest.raises(climate.HVACRequestError):
        await layer.set_temperature(1, 70.25)
    with pytest.raises(climate.HVACRequestError):
        await layer.set_temperature(1, 100)
    result = await layer.set_hvac_mode(1, 'cool', dry_run=True)
    assert result['status'] == 'planned'


@pytest.mark.asyncio
async def test_unsupported_mode_is_rejected_without_controller_call():
    controller = Controller()
    layer = climate.HVACSemanticLayer(controller)
    with pytest.raises(climate.HVACRequestError):
        await layer.set_hvac_mode(1, 'auto')
    assert controller.calls == []


def test_ha_climate_services_have_semantic_mappings_but_turn_on_remains_unavailable():
    assert importer.SERVICE_MAPPINGS['climate.set_temperature']['service'] == 'set_temperature'
    assert importer.SERVICE_MAPPINGS['climate.set_hvac_mode']['service'] == 'set_hvac_mode'
    assert importer.SERVICE_MAPPINGS['climate.turn_off']['service'] == 'turn_off'
    assert 'climate.turn_on' not in importer.SERVICE_MAPPINGS
