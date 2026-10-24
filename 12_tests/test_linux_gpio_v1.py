import struct
from importlib import import_module
import pytest

transport = import_module('08_servises.common.linux_gpio_v1')
safety = import_module('02_HCM.safety_relays')


def test_v1_requests_only_input_and_reads_without_output_ioctl(monkeypatch):
    closed = []
    calls = []
    monkeypatch.setattr(transport.os, 'open', lambda path, flags: 10)
    monkeypatch.setattr(transport.os, 'close', closed.append)
    def ioctl(fd, command, data, mutate):
        calls.append(command)
        if command == transport.GET_LINEHANDLE:
            assert struct.unpack_from('=I', data, 0)[0] == 159
            assert struct.unpack_from('=I', data, 256)[0] == 1
            assert struct.unpack_from('=I', data, 356)[0] == 1
            struct.pack_into('=i', data, 360, 11)
        elif command == transport.GET_VALUES:
            data[0] = 1
    monkeypatch.setattr(transport.fcntl, 'ioctl', ioctl)
    reader = transport.LinuxGPIOV1InputTransport('/dev/gpiochip0', 159, 'test')
    assert reader.read() is True
    reader.close()
    reader.close()
    assert calls == [transport.GET_LINEINFO, transport.GET_LINEHANDLE, transport.GET_VALUES]
    assert closed == [10, 11]


@pytest.mark.parametrize('flags', [1, 2, 3])
def test_v1_refuses_owned_or_output_line(monkeypatch, flags):
    closed = []
    monkeypatch.setattr(transport.os, 'open', lambda path, mode: 10)
    monkeypatch.setattr(transport.os, 'close', closed.append)
    def ioctl(fd, command, data, mutate):
        assert command == transport.GET_LINEINFO
        struct.pack_into('=I', data, 4, flags)
    monkeypatch.setattr(transport.fcntl, 'ioctl', ioctl)
    with pytest.raises(OSError, match='refusing'):
        transport.LinuxGPIOV1InputTransport('/dev/gpiochip0', 159, 'test')
    assert closed == [10]


def test_unconfirmed_contacts_never_open_or_report_normal(monkeypatch):
    def prohibited(*args):
        raise AssertionError('unconfirmed wiring must not be sampled')
    monkeypatch.setattr(transport, 'LinuxGPIOV1InputTransport', prohibited)
    backend = safety.LinuxSafetyInputBackend({'fire_alarm_s': {}, 'fire_alarm_P': {}}, abi='v1', connected_inputs=[])
    assert backend.physical_input_authoritative
    for name in ('fire_alarm_s', 'fire_alarm_P'):
        assert backend.read(safety.SafetyRelay(name, None, None, 'input', True)) is None
