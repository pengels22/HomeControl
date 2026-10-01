import asyncio
from importlib import import_module

import pytest

registry_mod = import_module('01_HCM.registry')
protocol = import_module('07_servises.common.protocol')


class FakeAcquire:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        return self.conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeRegistryConn:
    def __init__(self):
        self.modules = {}
        self.executed = []

    async def fetchrow(self, query, *args):
        if 'WHERE module_uuid=$1' in query:
            row = self.modules.get(args[0])
            if not row:
                return None
            return {'hostname': row['hostname'], 'ip_address': row['ip_address']}
        if 'WHERE hostname=$1' in query:
            for module_uuid, row in self.modules.items():
                if row['hostname'] == args[0]:
                    return {'module_uuid': module_uuid}
            return None
        raise AssertionError(f'unexpected fetchrow: {query}')

    async def fetch(self, query, *args):
        if 'SELECT ip_address FROM modules WHERE module_type=$1' in query:
            return [
                {'ip_address': row['ip_address']}
                for row in self.modules.values()
                if row['module_type'] == args[0]
            ]
        raise AssertionError(f'unexpected fetch: {query}')

    async def execute(self, query, *args):
        self.executed.append((query, args))
        if 'INSERT INTO modules' in query:
            module_uuid, module_type, hostname, ip_address, software_version = args
            self.modules[module_uuid] = {
                'module_type': module_type,
                'hostname': hostname,
                'ip_address': ip_address,
                'software_version': software_version,
                'online': True,
            }
        elif 'UPDATE modules SET online=true,last_seen=now(),last_state' in query:
            module_uuid = args[0]
            if module_uuid in self.modules:
                self.modules[module_uuid]['last_state'] = args[1]
                self.modules[module_uuid]['online'] = True
        elif 'UPDATE modules SET online=true' in query:
            module_uuid = args[0]
            if module_uuid in self.modules:
                self.modules[module_uuid]['online'] = True
        elif 'UPDATE modules SET online=false' in query:
            module_uuid = args[0]
            if module_uuid in self.modules:
                self.modules[module_uuid]['online'] = False
        else:
            raise AssertionError(f'unexpected execute: {query}')


@pytest.mark.asyncio
async def test_assign_uses_pinned_module_ranges(monkeypatch):
    conn = FakeRegistryConn()
    monkeypatch.setattr(registry_mod.db, 'acquire', lambda: FakeAcquire(conn))
    monkeypatch.setattr(registry_mod.settings, 'commissioning_enabled', True)
    reg = registry_mod.ModuleRegistry()

    first = await reg._assign({'module_type': 'RCM', 'module_uuid': 'rcm-a', 'software_version': '0.1'})
    second = await reg._assign({'module_type': 'RCM', 'module_uuid': 'rcm-b', 'software_version': '0.1'})
    lcm = await reg._assign({'module_type': 'LCM', 'module_uuid': 'lcm-a', 'software_version': '0.1'})

    assert first == {'hostname': 'RCM01', 'ip_address': '192.168.60.20', 'reboot_required': True}
    assert second == {'hostname': 'RCM02', 'ip_address': '192.168.60.21', 'reboot_required': True}
    assert lcm == {'hostname': 'LCM01', 'ip_address': '192.168.60.30', 'reboot_required': True}


@pytest.mark.asyncio
async def test_assign_existing_module_keeps_identity(monkeypatch):
    conn = FakeRegistryConn()
    conn.modules['rcm-a'] = {
        'module_type': 'RCM',
        'hostname': 'RCM01',
        'ip_address': '192.168.60.20',
        'online': False,
    }
    monkeypatch.setattr(registry_mod.db, 'acquire', lambda: FakeAcquire(conn))
    monkeypatch.setattr(registry_mod.settings, 'commissioning_enabled', False)
    reg = registry_mod.ModuleRegistry()

    assignment = await reg._assign({'module_type': 'RCM', 'module_uuid': 'rcm-a', 'software_version': '0.2'})

    assert assignment == {'hostname': 'RCM01', 'ip_address': '192.168.60.20', 'reboot_required': False}


@pytest.mark.asyncio
async def test_assign_rejects_unknown_module_when_commissioning_disabled(monkeypatch):
    conn = FakeRegistryConn()
    monkeypatch.setattr(registry_mod.db, 'acquire', lambda: FakeAcquire(conn))
    monkeypatch.setattr(registry_mod.settings, 'commissioning_enabled', False)
    reg = registry_mod.ModuleRegistry()

    with pytest.raises(PermissionError):
        await reg._assign({'module_type': 'RCM', 'module_uuid': 'rcm-new', 'software_version': '0.1'})


def test_mutual_tls_requires_ca(monkeypatch):
    monkeypatch.setattr(registry_mod.settings, 'tls_enabled', True)
    monkeypatch.setattr(registry_mod.settings, 'tls_cert', '/tmp/cert.pem')
    monkeypatch.setattr(registry_mod.settings, 'tls_key', '/tmp/key.pem')
    monkeypatch.setattr(registry_mod.settings, 'tls_ca', None)
    monkeypatch.setattr(registry_mod.settings, 'tls_require_client_cert', True)
    reg = registry_mod.ModuleRegistry()

    with pytest.raises(RuntimeError, match='HCM_TLS_CA'):
        reg._ssl_context()


@pytest.mark.asyncio
async def test_registered_module_receives_config_and_heartbeat_ack(monkeypatch):
    conn = FakeRegistryConn()
    conn.modules['rcm-a'] = {
        'module_type': 'RCM',
        'hostname': 'RCM01',
        'ip_address': '192.168.60.20',
        'online': False,
    }
    monkeypatch.setattr(registry_mod.db, 'acquire', lambda: FakeAcquire(conn))
    reg = registry_mod.ModuleRegistry()

    async def base_config(module_type):
        return {'version': 7, 'config': {'module_type': module_type}}

    monkeypatch.setattr(reg, '_base_config', base_config)
    server = await asyncio.start_server(reg.handle_client, '127.0.0.1', 0)
    port = server.sockets[0].getsockname()[1]

    reader, writer = await asyncio.open_connection('127.0.0.1', port)
    await protocol.write_frame(writer, {
        'type': 'identify',
        'payload': {
            'module_type': 'RCM',
            'module_uuid': 'rcm-a',
            'hostname': 'RCM01',
            'assigned_ip': '192.168.60.20',
            'software_version': '0.2',
        },
    })
    reply = await protocol.read_frame(reader)
    await protocol.write_frame(writer, {
        'type': 'heartbeat',
        'payload': {'module_uuid': 'rcm-a', 'state': {'relays': {}}},
    })
    ack = await protocol.read_frame(reader)

    writer.close()
    await writer.wait_closed()
    server.close()
    await server.wait_closed()

    assert reply == {'type': 'config', 'payload': {'version': 7, 'config': {'module_type': 'RCM'}}}
    assert ack['type'] == 'heartbeat_ack'
    assert conn.modules['rcm-a']['last_state'] == '{"module_uuid": "rcm-a", "state": {"relays": {}}}'
