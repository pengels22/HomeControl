from importlib import import_module

io = import_module('07_servises.common.io')


def test_dev_mode_forces_simulated_io(monkeypatch):
    monkeypatch.setenv('HCM_DEV_MODE', 'true')

    assert io.io_mode({'io': {'mode': 'real'}}) == 'simulated'
    assert io.real_io_enabled({'io': {'mode': 'real'}}) is False


def test_auto_mode_resolves_to_real_when_not_dev(monkeypatch):
    monkeypatch.delenv('HCM_DEV_MODE', raising=False)
    monkeypatch.delenv('HC_DEV_MODE', raising=False)
    monkeypatch.delenv('HC_IO_MODE', raising=False)
    monkeypatch.delenv('HCM_IO_MODE', raising=False)

    assert io.io_mode({'io': {'mode': 'auto'}}) == 'real'


def test_io_mode_env_override(monkeypatch):
    monkeypatch.delenv('HCM_DEV_MODE', raising=False)
    monkeypatch.delenv('HC_DEV_MODE', raising=False)
    monkeypatch.setenv('HC_IO_MODE', 'simulated')

    assert io.io_mode({'io': {'mode': 'real'}}) == 'simulated'
