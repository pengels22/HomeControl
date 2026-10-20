import importlib


heos = importlib.import_module('01_HCM.integrations.heos')


def test_heos_parses_json_player_discovery_envelope():
    transport = heos.HEOSTransport('192.0.2.1')
    parsed = transport.parse(
        '{"heos":{"command":"player/get_players","result":"success"},'
        '"payload":[{"pid":123,"name":"Living Room"}]}'
    )
    assert parsed['command'] == 'player/get_players'
    assert parsed['params']['players'][0]['pid'] == 123


def test_heos_preserves_legacy_url_parser():
    transport = heos.HEOSTransport('192.0.2.1')
    parsed = transport.parse('heos://player/get_now_playing_media?pid=123&state=play')
    assert parsed == {
        'command': 'player/get_now_playing_media',
        'params': {'pid': '123', 'state': 'play'},
    }
