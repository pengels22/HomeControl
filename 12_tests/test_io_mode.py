from importlib import import_module

import pytest

io = import_module('08_servises.common.io')
hardware_factory = import_module('08_servises.common.hardware_factory')


def test_dev_mode_forces_simulated_io(monkeypatch):
    monkeypatch.setenv('HCM_DEV_MODE', 'true')

    assert io.io_mode({'io': {'mode': 'real'}}) == 'simulated'
    assert io.real_io_enabled({'io': {'mode': 'real'}}) is False


def test_auto_mode_requires_explicit_selection(monkeypatch):
    monkeypatch.delenv('HCM_DEV_MODE', raising=False)
    monkeypatch.delenv('HC_DEV_MODE', raising=False)
    monkeypatch.delenv('HC_IO_MODE', raising=False)
    monkeypatch.delenv('HCM_IO_MODE', raising=False)

    with pytest.raises(ValueError, match='choose real or simulated explicitly'):
        io.io_mode({'io': {'mode': 'auto'}})


def test_hardware_factory_rejects_auto_mode():
    with pytest.raises(ValueError, match='choose real or simulated explicitly'):
        hardware_factory.build_hardware_bundle('RCM', {'hardware_mode': 'auto'})


def test_io_mode_env_override(monkeypatch):
    monkeypatch.delenv('HCM_DEV_MODE', raising=False)
    monkeypatch.delenv('HC_DEV_MODE', raising=False)
    monkeypatch.setenv('HC_IO_MODE', 'simulated')

    assert io.io_mode({'io': {'mode': 'real'}}) == 'simulated'


def test_explicit_real_mode_is_real_outside_development(monkeypatch):
    monkeypatch.delenv('HCM_DEV_MODE', raising=False)
    monkeypatch.delenv('HC_DEV_MODE', raising=False)
    monkeypatch.delenv('HC_IO_MODE', raising=False)
    monkeypatch.delenv('HCM_IO_MODE', raising=False)

    assert io.io_mode({'io': {'mode': 'real'}}) == 'real'
    assert io.real_io_enabled({'io': {'mode': 'real'}}) is True
