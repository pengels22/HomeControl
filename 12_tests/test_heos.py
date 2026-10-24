import importlib
import asyncio
from pydantic import BaseModel


heos = importlib.import_module('02_HCM.integrations.heos')


def test_heos_parses_json_player_discovery_envelope():
    transport = heos.HEOSTransport('192.0.2.1')
    parsed = transport.parse(
        '{"heos":{"command":"player/get_players","result":"success"},'
        '"payload":[{"pid":123,"name":"Living Room"}]}'
    )
    assert parsed['command'] == 'player/get_players'
    assert parsed['params']['players'][0]['pid'] == 123


def test_heos_parses_json_group_discovery_envelope():
    transport = heos.HEOSTransport('192.0.2.1')
    parsed = transport.parse(
        '{"heos":{"command":"group/get_groups","result":"success"},'
        '"payload":[{"gid":7,"leader":123,"players":[{"pid":123}]}]}'
    )
    assert parsed['params']['groups'][0]['gid'] == 7


def test_heos_preserves_legacy_url_parser():
    transport = heos.HEOSTransport('192.0.2.1')
    parsed = transport.parse('heos://player/get_now_playing_media?pid=123&state=play')
    assert parsed == {
        'command': 'player/get_now_playing_media',
        'params': {'pid': '123', 'state': 'play'},
    }


class FakeTransport:
    def __init__(self, groups):
        self.groups = groups
        self.commands = []

    async def command(self, path, params=None):
        self.commands.append((path, params or {}))
        if path == 'group/get_groups':
            return {'params': {'groups': self.groups}}
        return {'params': {}}


class FakeContext:
    def __init__(self):
        self.config = {'host': '192.0.2.1'}
        self.services = []

    async def service(self, domain, name, arguments, callback, **kwargs):
        assert issubclass(arguments, BaseModel)
        self.services.append((domain, name, callback, kwargs))


def test_heos_group_volume_resolves_current_group_and_dry_runs_without_mutation():
    provider = heos.HEOSProvider(FakeTransport([{'gid': 7, 'leader': 123, 'players': [{'pid': 123}, {'pid': 456}]}]))
    provider.entities = {'123': 'media_player.living'}
    result = asyncio.run(provider.group_volume_up(heos.GroupVolumeArgs(step=3, dry_run=True), 'media_player.living'))
    assert result == {'status': 'dry_run', 'entity_id': 'media_player.living', 'group_id': '7', 'direction': 'up', 'step': 3}
    assert provider.transport.commands == [('group/get_groups', {})]


def test_heos_group_volume_handles_ungrouped_and_executes_only_mock_command():
    provider = heos.HEOSProvider(FakeTransport([]))
    provider.entities = {'123': 'media_player.living'}
    result = asyncio.run(provider.group_volume_down(heos.GroupVolumeArgs(), 'media_player.living'))
    assert result['status'] == 'not_grouped'
    assert provider.transport.commands == [('group/get_groups', {})]

    provider = heos.HEOSProvider(FakeTransport([{'gid': 9, 'leader': 123, 'players': [{'pid': 123}]}]))
    provider.entities = {'123': 'media_player.living'}
    result = asyncio.run(provider.group_volume_down(heos.GroupVolumeArgs(step=2), 'media_player.living'))
    assert result['status'] == 'success'
    assert provider.transport.commands[-1] == ('group/volume_down', {'gid': 9, 'step': 2})


def test_heos_registers_native_group_volume_services():
    provider = heos.HEOSProvider(FakeTransport([]))
    context = FakeContext()
    asyncio.run(provider.setup(context))
    names = {name for domain, name, _callback, _kwargs in context.services if domain == 'media_player'}
    assert {'group_volume_up', 'group_volume_down'} <= names
