from importlib import import_module

import pytest

identity = import_module('homecontrol_identity')


def test_normalize_colon_mac_to_device_id():
    assert identity.normalize_device_id('48:b0:2d:87:db:16') == '48b02d87db16'


def test_normalize_plain_uppercase_mac_to_device_id():
    assert identity.normalize_device_id('48B02D87DB16') == '48b02d87db16'


@pytest.mark.parametrize('value', [
    '',
    '48:b0:2d:87:db',
    '48:b0:2d:87:db:zz',
    '000000000000',
    'ffffffffffff',
    '01:00:5e:00:00:fb',
    '550e8400-e29b-41d4-a716-446655440000',
])
def test_invalid_device_ids_rejected(value):
    with pytest.raises(identity.InvalidDeviceId):
        identity.normalize_device_id(value)
