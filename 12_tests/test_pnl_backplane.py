from datetime import datetime, timezone
from importlib import import_module

import pytest


pnl = import_module('01_HCM.pnl_backplane')


def payload(sequence=1, device_id='aabbccddeeff'):
    return {'device_id': device_id, 'sequence': sequence,
            'timestamp': '2026-10-24T12:00:00Z',
            'local': {'lux': 10.5, 'occupancy': True, 'temp': 21.5, 'humidity': 45}}


def test_pnl_telemetry_accepts_identity_and_local_values():
    result = pnl.validate_telemetry(payload(), device_id='aabbccddeeff', last_sequence=0,
                                    now=datetime(2026, 10, 24, 12, 0, 10, tzinfo=timezone.utc).timestamp())
    assert result['sequence'] == 1
    assert pnl.local_aliases('aabbccddeeff', result['local'])[0]['entity_id'].startswith('pnl_aabbccddeeff_')


@pytest.mark.parametrize('bad', [
    {'device_id': '001122334455'},
    {'sequence': 0},
    {'local': {'lux': -1, 'occupancy': False, 'temp': 20, 'humidity': 40}},
    {'local': {'lux': 1, 'occupancy': False, 'temp': 20, 'humidity': 101}},
])
def test_pnl_telemetry_rejects_spoof_replay_and_invalid_values(bad):
    item = payload(); item.update(bad)
    with pytest.raises(pnl.PNLTelemetryError):
        pnl.validate_telemetry(item, device_id='aabbccddeeff', last_sequence=1,
                               now=datetime(2026, 10, 24, 12, 0, 10, tzinfo=timezone.utc).timestamp())


def test_panel_tokens_are_hashed_and_scoped():
    assert pnl.verify_token('secret', pnl.token_hash('secret'))
    assert not pnl.verify_token('other', pnl.token_hash('secret'))
    aliases_a = pnl.local_aliases('aabbccddeeff', payload()['local'])
    aliases_b = pnl.local_aliases('112233445566', payload()['local'])
    assert aliases_a[0]['entity_id'] != aliases_b[0]['entity_id']
