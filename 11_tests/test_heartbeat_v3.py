import importlib.util
import hmac
import hashlib
import json
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('hcm_heartbeat_v3', ROOT / '00_Heartbeat/hcm_heartbeat.py')
hcm = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hcm)


def cfg(tmp_path, role='conflict'):
    return {
        'role': role,
        'bind_address': '127.0.0.1',
        'advertise_ip': '127.0.0.1',
        'port': 6004,
        'identity_interface': 'eth0',
        'state_file': str(tmp_path / f'{role}-state.json'),
        'registry_db': str(tmp_path / 'registry.sqlite3'),
        'socket_path': str(tmp_path / f'{role}.sock'),
        'services': [],
        'watchdogs': {},
        'min_available_memory_percent': 0,
        'root_disk_percent_fail': 101,
        'thermal_celsius_fail': 999,
        'interval_seconds': 5,
        'peer_timeout_seconds': 15,
        'startup_grace_seconds': 45,
        'request_timeout_seconds': 4,
        'conflict_address': '127.0.0.1',
        'conflict_hostname': 'conflict',
        'allowed_device_ids': ['48b02d87db16'],
        'maintenance_lockout': False,
    }


def patch_host(monkeypatch):
    monkeypatch.setattr(hcm, 'mac_address', lambda iface: '48b02d87db16' if iface == 'eth0' else '3c53bbf7adb2')
    monkeypatch.setattr(hcm, 'free_mem_percent', lambda: 50)
    monkeypatch.setattr(hcm, 'temps', lambda: None)
    monkeypatch.setattr(hcm, 'uptime', lambda: 100)


def heartbeat(device_id='48b02d87db16', hostname='RCM01', ip='192.168.20.31', seq=1, boot='boot-a', faults=None):
    return {
        'protocol': 'hcm-heartbeat',
        'version': 3,
        'hostname': hostname,
        'ip_address': ip,
        'device_id': device_id,
        'identity_interface': 'eth0',
        'boot_id': boot,
        'sequence': seq,
        'timestamp': int(time.time()),
        'health': {'state': 'healthy' if not faults else 'fault', 'faults': faults or [], 'system': {}, 'services': {}},
        'status': {'state': 'operational', 'modules': {'relay': {'state': 'ok'}}},
    }


def write_secret(tmp_path):
    secret_path = tmp_path / 'heartbeat.secret'
    secret_path.write_bytes(b'shared-development-test-secret')
    return secret_path


def sign_body(secret_path, body):
    return hmac.new(secret_path.read_bytes(), body, hashlib.sha256).hexdigest()


def test_conflict_registry_persists_but_restarts_offline(tmp_path, monkeypatch):
    patch_host(monkeypatch)
    state = hcm.State(cfg(tmp_path))
    state.store.record_heartbeat('48b02d87db16', heartbeat(), '192.168.20.31', 15)
    assert state.snapshot()['status']['registry']['48b02d87db16']['online'] is True
    state.store.close()

    restarted = hcm.State(cfg(tmp_path))
    registry = restarted.snapshot()['status']['registry']

    assert registry['48b02d87db16']['hostname'] == 'RCM01'
    assert registry['48b02d87db16']['online'] is False
    assert registry['48b02d87db16']['last_known_online'] is False
    restarted.store.close()


def test_hostname_and_ip_can_change_for_same_device_id(tmp_path, monkeypatch):
    patch_host(monkeypatch)
    state = hcm.State(cfg(tmp_path))
    state.store.record_heartbeat('48b02d87db16', heartbeat(hostname='RCM01', ip='192.168.20.31'), '192.168.20.31', 15)
    state.store.record_heartbeat('48b02d87db16', heartbeat(hostname='RCM02', ip='192.168.20.32', seq=2), '192.168.20.32', 15)

    entry = state.snapshot()['status']['registry']['48b02d87db16']
    assert entry['hostname'] == 'RCM02'
    assert entry['ip_address'] == '192.168.20.32'
    state.store.close()


def test_duplicate_device_id_from_different_reachable_source_rejected(tmp_path, monkeypatch):
    patch_host(monkeypatch)
    state = hcm.State(cfg(tmp_path))
    state.store.record_heartbeat('48b02d87db16', heartbeat(boot='boot-a'), '192.168.20.31', 15)

    with pytest.raises(ValueError, match='duplicate device_id'):
        state.store.record_heartbeat('48b02d87db16', heartbeat(boot='boot-b'), '192.168.20.32', 15)

    rows = state.store.conn.execute("SELECT event_type FROM heartbeat_events WHERE event_type='duplicate_device_id'").fetchall()
    assert len(rows) == 1
    state.store.close()


def test_fault_creation_clearing_and_persistence(tmp_path, monkeypatch):
    patch_host(monkeypatch)
    state = hcm.State(cfg(tmp_path, role='device'))
    state.control({'action': 'fault_set', 'name': 'sensors', 'value': 'offline'})
    assert any(f['name'] == 'sensors' for f in state.snapshot()['health']['faults'] if f['type'] == 'external')

    restarted = hcm.State(cfg(tmp_path, role='device'))
    assert any(f['name'] == 'sensors' for f in restarted.snapshot()['health']['faults'] if f['type'] == 'external')
    restarted.control({'action': 'fault_clear', 'name': 'sensors'})
    assert not any(f.get('name') == 'sensors' for f in restarted.snapshot()['health']['faults'])


def test_missing_application_watchdog_degrades_health(tmp_path, monkeypatch):
    patch_host(monkeypatch)
    config = cfg(tmp_path, role='device')
    config['watchdogs'] = {'rcm_app': 0.01}
    state = hcm.State(config)
    time.sleep(0.02)

    snapshot = state.snapshot()

    assert snapshot['health']['state'] == 'fault'
    assert any(f.get('type') == 'watchdog' and f.get('name') == 'rcm_app' for f in snapshot['health']['faults'])


def test_full_two_way_heartbeat_exchange(tmp_path, monkeypatch):
    patch_host(monkeypatch)
    conflict = hcm.State(cfg(tmp_path))
    server = hcm.HTTPServer(('127.0.0.1', 0), hcm.Handler)
    server.state = conflict
    port = server.server_address[1]
    import threading
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    try:
        from urllib.request import Request, urlopen
        req = Request(
            'http://127.0.0.1:{}/heartbeat'.format(port),
            data=json.dumps(heartbeat()).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        reply = json.loads(urlopen(req, timeout=3).read().decode('utf-8'))
    finally:
        server.shutdown()
        server.server_close()
        conflict.store.close()

    assert reply['protocol'] == 'hcm-heartbeat'
    assert reply['version'] == 3
    assert reply['reply_to'] == 1
    assert reply['reply_boot_id'] == 'boot-a'
    assert reply['device_id'] == '48b02d87db16'


def test_updated_conflict_accepts_legacy_colon_mac_heartbeat(tmp_path, monkeypatch):
    patch_host(monkeypatch)
    config = cfg(tmp_path)
    config['allowed_device_ids'] = ['48b02d87db16']
    conflict = hcm.State(config)
    server = hcm.HTTPServer(('127.0.0.1', 0), hcm.Handler)
    server.state = conflict
    port = server.server_address[1]
    import threading
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    try:
        from urllib.request import Request, urlopen
        req = Request(
            'http://127.0.0.1:{}/heartbeat'.format(port),
            data=json.dumps(heartbeat(device_id='48:b0:2d:87:db:16')).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        reply = json.loads(urlopen(req, timeout=3).read().decode('utf-8'))
        rows = conflict.store.conn.execute('SELECT device_id FROM devices').fetchall()
    finally:
        server.shutdown()
        server.server_close()
        conflict.store.close()

    assert reply['reply_to'] == 1
    assert [row['device_id'] for row in rows] == ['48b02d87db16']


def test_colon_and_normalized_identity_share_one_registry_record(tmp_path, monkeypatch):
    patch_host(monkeypatch)
    state = hcm.State(cfg(tmp_path))
    legacy = heartbeat(device_id='48:b0:2d:87:db:16', seq=1, boot='boot-a')
    modern = heartbeat(device_id='48b02d87db16', seq=2, boot='boot-a')

    state.store.record_heartbeat(hcm.normalize_device_id(legacy['device_id']), legacy, '192.168.20.27', 15)
    state.store.record_heartbeat(hcm.normalize_device_id(modern['device_id']), modern, '192.168.20.27', 15)

    rows = state.store.conn.execute('SELECT device_id, last_sequence FROM devices').fetchall()
    assert [(row['device_id'], row['last_sequence']) for row in rows] == [('48b02d87db16', 2)]
    assert set(state.snapshot()['status']['registry']) == {'48b02d87db16'}
    state.store.close()


def test_offline_then_recovery_transition(tmp_path, monkeypatch):
    patch_host(monkeypatch)
    state = hcm.State(cfg(tmp_path))
    state.store.record_heartbeat('48b02d87db16', heartbeat(), '192.168.20.31', 15)
    state.store.conn.execute('UPDATE devices SET last_seen=? WHERE device_id=?', (int(time.time()) - 30, '48b02d87db16'))
    state.store.conn.commit()
    assert state.snapshot()['status']['registry']['48b02d87db16']['online'] is False

    state.store.record_heartbeat('48b02d87db16', heartbeat(seq=2), '192.168.20.31', 15)
    assert state.snapshot()['status']['registry']['48b02d87db16']['online'] is True
    state.store.close()


def test_conflict_rejects_empty_allowlist_unknown_device(tmp_path, monkeypatch):
    patch_host(monkeypatch)
    config = cfg(tmp_path)
    config['allowed_device_ids'] = []
    conflict = hcm.State(config)
    server = hcm.HTTPServer(('127.0.0.1', 0), hcm.Handler)
    server.state = conflict
    port = server.server_address[1]
    import threading
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    try:
        from urllib.error import HTTPError
        from urllib.request import Request, urlopen
        req = Request(
            'http://127.0.0.1:{}/heartbeat'.format(port),
            data=json.dumps(heartbeat()).encode('utf-8'),
            headers={'Content-Type': 'application/json'},
            method='POST',
        )
        with pytest.raises(HTTPError) as exc:
            urlopen(req, timeout=3)
    finally:
        server.shutdown()
        server.server_close()
        conflict.store.close()

    assert exc.value.code == 403


def test_communication_loss_fault_deduplicates_and_recovers(tmp_path, monkeypatch):
    patch_host(monkeypatch)
    state = hcm.State(cfg(tmp_path))
    state.store.record_heartbeat('48b02d87db16', heartbeat(), '192.168.20.31', 15)
    old = int(time.time()) - 30
    state.store.conn.execute('UPDATE devices SET last_seen=? WHERE device_id=?', (old, '48b02d87db16'))
    state.store.conn.commit()

    assert state.store.mark_offline_overdue(15, 5) == ['48b02d87db16']
    assert state.store.mark_offline_overdue(15, 5) == []

    rows = state.store.conn.execute('SELECT code, active FROM communication_faults').fetchall()
    assert [(row['code'], row['active']) for row in rows] == [('COMMUNICATION_LOSS', 1)]
    registry = state.snapshot()['status']['registry']['48b02d87db16']
    assert registry['active_fault']['code'] == 'COMMUNICATION_LOSS'

    state.store.record_heartbeat('48b02d87db16', heartbeat(seq=2), '192.168.20.31', 15)
    rows = state.store.conn.execute('SELECT code, active, resolved_at FROM communication_faults').fetchall()
    assert [(row['code'], row['active'], row['resolved_at'] is not None) for row in rows] == [('COMMUNICATION_LOSS', 0, True)]
    state.store.close()


def test_replay_sequence_rejected(tmp_path, monkeypatch):
    patch_host(monkeypatch)
    state = hcm.State(cfg(tmp_path))
    state.store.record_heartbeat('48b02d87db16', heartbeat(seq=7), '192.168.20.31', 15)

    with pytest.raises(ValueError, match='sequence replay'):
        state.store.record_heartbeat('48b02d87db16', heartbeat(seq=7), '192.168.20.31', 15)

    state.store.close()


def test_hmac_authenticated_heartbeat(tmp_path, monkeypatch):
    patch_host(monkeypatch)
    secret_path = write_secret(tmp_path)
    config = cfg(tmp_path)
    config['heartbeat_auth_mode'] = 'hmac-sha256'
    config['heartbeat_auth_secret_file'] = str(secret_path)
    conflict = hcm.State(config)
    server = hcm.HTTPServer(('127.0.0.1', 0), hcm.Handler)
    server.state = conflict
    port = server.server_address[1]
    import threading
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    try:
        from urllib.request import Request, urlopen
        msg = heartbeat()
        body = json.dumps(msg, sort_keys=True, separators=(',', ':')).encode('utf-8')
        signature = sign_body(secret_path, body)
        req = Request(
            'http://127.0.0.1:{}/heartbeat'.format(port),
            data=body,
            headers={'Content-Type': 'application/json', 'X-HomeControl-Signature': signature},
            method='POST',
        )
        with urlopen(req, timeout=3) as response:
            raw = response.read()
            response_signature = response.headers.get('X-HomeControl-Signature')
        reply = json.loads(raw.decode('utf-8'))
    finally:
        server.shutdown()
        server.server_close()
        conflict.store.close()

    assert reply['reply_to'] == 1
    assert response_signature == sign_body(secret_path, raw)


def test_hmac_rejects_bad_request_signature(tmp_path, monkeypatch):
    patch_host(monkeypatch)
    secret_path = write_secret(tmp_path)
    config = cfg(tmp_path)
    config['heartbeat_auth_mode'] = 'hmac-sha256'
    config['heartbeat_auth_secret_file'] = str(secret_path)
    conflict = hcm.State(config)
    server = hcm.HTTPServer(('127.0.0.1', 0), hcm.Handler)
    server.state = conflict
    port = server.server_address[1]
    import threading
    thread = threading.Thread(target=server.serve_forever)
    thread.daemon = True
    thread.start()
    try:
        from urllib.error import HTTPError
        from urllib.request import Request, urlopen
        body = json.dumps(heartbeat(), sort_keys=True, separators=(',', ':')).encode('utf-8')
        req = Request(
            'http://127.0.0.1:{}/heartbeat'.format(port),
            data=body,
            headers={'Content-Type': 'application/json', 'X-HomeControl-Signature': 'bad'},
            method='POST',
        )
        with pytest.raises(HTTPError) as exc:
            urlopen(req, timeout=3)
    finally:
        server.shutdown()
        server.server_close()
        conflict.store.close()

    assert exc.value.code == 400


def test_hmac_config_fails_closed_without_secret(tmp_path, monkeypatch):
    patch_host(monkeypatch)
    config = cfg(tmp_path)
    config['heartbeat_auth_mode'] = 'hmac-sha256'
    config['heartbeat_auth_secret_file'] = str(tmp_path / 'missing.secret')

    with pytest.raises(IOError):
        hcm.State(config)


def test_authenticated_multi_device_monitoring_and_jetson_continues_during_lab1_loss(tmp_path, monkeypatch):
    patch_host(monkeypatch)
    secret_path = write_secret(tmp_path)
    config = cfg(tmp_path)
    config['heartbeat_auth_mode'] = 'hmac-sha256'
    config['heartbeat_auth_secret_file'] = str(secret_path)
    config['allowed_device_ids'] = ['48b02d87db16', '2ccf675d3414']
    config['authorized_devices'] = [
        {'device_id': '48b02d87db16', 'hostname': 'jetson', 'ip_address': '192.168.20.27'},
        {'device_id': '2ccf675d3414', 'hostname': 'lab1', 'ip_address': '192.168.20.36'},
    ]
    state = hcm.State(config)
    jetson = heartbeat(device_id='48b02d87db16', hostname='jetson', ip='192.168.20.27', seq=1, boot='jetson-boot')
    lab1 = heartbeat(device_id='2ccf675d3414', hostname='lab1', ip='192.168.20.36', seq=1, boot='lab1-boot')
    state.store.record_heartbeat('48b02d87db16', jetson, '192.168.20.27', 15)
    state.store.record_heartbeat('2ccf675d3414', lab1, '192.168.20.36', 15)
    old = int(time.time()) - 30
    state.store.conn.execute('UPDATE devices SET last_seen=? WHERE device_id=?', (old, '2ccf675d3414'))
    state.store.conn.commit()

    changed = state.store.mark_offline_overdue(15, 5)
    state.store.record_heartbeat(
        '48b02d87db16',
        heartbeat(device_id='48b02d87db16', hostname='jetson', ip='192.168.20.27', seq=2, boot='jetson-boot'),
        '192.168.20.27',
        15,
    )
    registry = state.snapshot()['status']['registry']
    state.store.close()

    assert changed == ['2ccf675d3414']
    assert registry['48b02d87db16']['online'] is True
    assert registry['48b02d87db16']['active_fault'] is None
    assert registry['2ccf675d3414']['online'] is False
    assert registry['2ccf675d3414']['active_fault']['code'] == 'COMMUNICATION_LOSS'


def test_active_communication_fault_persists_across_conflict_restart(tmp_path, monkeypatch):
    patch_host(monkeypatch)
    state = hcm.State(cfg(tmp_path))
    state.store.record_heartbeat('48b02d87db16', heartbeat(), '192.168.20.31', 15)
    state.store.conn.execute('UPDATE devices SET last_seen=? WHERE device_id=?', (int(time.time()) - 30, '48b02d87db16'))
    state.store.conn.commit()
    state.store.mark_offline_overdue(15, 5)
    state.store.close()

    restarted = hcm.State(cfg(tmp_path))
    registry = restarted.snapshot()['status']['registry']
    rows = restarted.store.conn.execute('SELECT code, active FROM communication_faults WHERE device_id=?', ('48b02d87db16',)).fetchall()
    restarted.store.close()

    assert registry['48b02d87db16']['active_fault']['code'] == 'COMMUNICATION_LOSS'
    assert [(row['code'], row['active']) for row in rows] == [('COMMUNICATION_LOSS', 1)]


def test_lab1_installer_mode_is_supported_and_preserves_lab_agent_boundary():
    install_script = (ROOT / '00_Heartbeat/install.sh').read_text()
    lab1_config = json.loads((ROOT / '00_Heartbeat/config-lab1.json').read_text())

    assert 'lab1) TARGET=lab1; CFG=config-lab1.json ;;' in install_script
    assert 'homecontrol-lab.service' in install_script
    assert 'systemctl restart homecontrol-lab.service' not in install_script
    assert 'hostnamectl' not in install_script
    assert 'nmcli' not in install_script
    assert lab1_config['heartbeat_auth_mode'] == 'hmac-sha256'
    assert lab1_config['heartbeat_auth_secret_file'] == '/etc/hcm-heartbeat/heartbeat-auth.secret'


def test_heartbeat_templates_are_fail_closed_for_staged_lab_authentication():
    for name in ('config-conflict.json', 'config-jetson.json', 'config-lab1.json'):
        data = json.loads((ROOT / '00_Heartbeat' / name).read_text())
        assert data['heartbeat_auth_mode'] == 'hmac-sha256'
        assert data['heartbeat_auth_secret_file'] == '/etc/hcm-heartbeat/heartbeat-auth.secret'
