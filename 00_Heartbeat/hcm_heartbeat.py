#!/usr/bin/env python3
"""HCM Unified Heartbeat v3. Python 3.6+ standard library only."""
import argparse
import copy
import hashlib
import hmac
import json
import os
import signal
import socket
import socketserver
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer as BaseHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

from homecontrol_identity import InvalidDeviceId, normalize_device_id

VERSION = 3
MAX_BODY = 65536
COMMUNICATION_LOSS = 'COMMUNICATION_LOSS'

def read_json(path, default=None):
    try:
        with open(path) as f:
            return json.load(f)
    except (IOError, ValueError):
        return default

def atomic_json(path, value):
    folder = os.path.dirname(path)
    if not os.path.isdir(folder):
        os.makedirs(folder)
    fd, tmp = tempfile.mkstemp(prefix='.hcm-', dir=folder)
    try:
        with os.fdopen(fd, 'w') as f:
            json.dump(value, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.rename(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

def mac_address(iface):
    with open('/sys/class/net/{}/address'.format(iface)) as f:
        mac = f.read().strip()
    try:
        return normalize_device_id(mac)
    except InvalidDeviceId:
        raise ValueError('invalid MAC on {}'.format(iface))

def normalize_allowlist(values):
    result = []
    for value in values or []:
        result.append(normalize_device_id(value))
    return result

def load_secret(path):
    if not path:
        return None
    with open(path, 'rb') as f:
        value = f.read().strip()
    if not value:
        raise ValueError('heartbeat auth secret file is empty')
    return value

def heartbeat_signature(secret, body):
    return hmac.new(secret, body, hashlib.sha256).hexdigest()

def constant_time_equal(left, right):
    return hmac.compare_digest(str(left or ''), str(right or ''))

def validate_auth_config(cfg):
    mode = cfg.get('heartbeat_auth_mode', 'none')
    if mode == 'none':
        return
    if mode != 'hmac-sha256':
        raise ValueError('unsupported heartbeat_auth_mode')
    path = cfg.get('heartbeat_auth_secret_file')
    if not path:
        raise ValueError('heartbeat_auth_secret_file is required for hmac-sha256')
    load_secret(path)

def sign_if_configured(cfg, body):
    if cfg.get('heartbeat_auth_mode', 'none') != 'hmac-sha256':
        return None
    return heartbeat_signature(load_secret(cfg.get('heartbeat_auth_secret_file')), body)

def validate_signature(cfg, supplied, body):
    expected = sign_if_configured(cfg, body)
    if expected is None:
        return
    if not constant_time_equal(supplied, expected):
        raise ValueError('invalid heartbeat signature')

class ConflictStore(object):
    def __init__(self, path):
        self.path = path
        self.lock = threading.RLock()
        folder = os.path.dirname(path)
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._init()

    def _init(self):
        with self.lock:
            self.conn.execute('PRAGMA journal_mode=WAL')
            self.conn.execute('PRAGMA synchronous=NORMAL')
            self.conn.execute('PRAGMA busy_timeout=5000')
            self.conn.execute('PRAGMA foreign_keys=ON')
            self.conn.execute('''
                CREATE TABLE IF NOT EXISTS devices (
                    device_id TEXT PRIMARY KEY,
                    hostname TEXT NOT NULL,
                    ip_address TEXT,
                    observed_ip TEXT,
                    boot_id TEXT,
                    first_seen INTEGER NOT NULL,
                    last_seen INTEGER NOT NULL,
                    last_sequence INTEGER,
                    last_health TEXT,
                    last_status TEXT,
                    last_reachable INTEGER NOT NULL DEFAULT 1,
                    offline_since INTEGER
                )
            ''')
            self.conn.execute('''
                CREATE TABLE IF NOT EXISTS authorized_devices (
                    device_id TEXT PRIMARY KEY,
                    hostname TEXT,
                    ip_address TEXT,
                    active INTEGER NOT NULL DEFAULT 1,
                    maintenance INTEGER NOT NULL DEFAULT 0,
                    source TEXT NOT NULL DEFAULT 'config',
                    authorized_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL,
                    decommissioned_at INTEGER
                )
            ''')
            self.conn.execute('''
                CREATE TABLE IF NOT EXISTS communication_faults (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    device_id TEXT NOT NULL,
                    code TEXT NOT NULL,
                    hostname TEXT,
                    ip_address TEXT,
                    last_heartbeat_ts INTEGER,
                    detected_at INTEGER NOT NULL,
                    expected_interval_seconds INTEGER NOT NULL,
                    timeout_seconds INTEGER NOT NULL,
                    active INTEGER NOT NULL DEFAULT 1,
                    resolved_at INTEGER,
                    recovery_heartbeat_ts INTEGER,
                    details TEXT NOT NULL DEFAULT '{}'
                )
            ''')
            self.conn.execute('''
                CREATE TABLE IF NOT EXISTS heartbeat_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts INTEGER NOT NULL,
                    device_id TEXT,
                    event_type TEXT NOT NULL,
                    details TEXT NOT NULL
                )
            ''')
            self.conn.execute('CREATE INDEX IF NOT EXISTS idx_heartbeat_events_device_ts ON heartbeat_events(device_id, ts)')
            self.conn.execute('CREATE INDEX IF NOT EXISTS idx_authorized_devices_active ON authorized_devices(active)')
            self.conn.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_comm_fault_active_unique ON communication_faults(device_id, code) WHERE active=1')
            self.conn.execute('CREATE INDEX IF NOT EXISTS idx_comm_fault_device_active ON communication_faults(device_id, active)')
            now = int(time.time())
            self.conn.execute('''
                UPDATE devices
                SET last_reachable=0, offline_since=COALESCE(offline_since, ?)
                WHERE last_reachable=1
            ''', (now,))
            self.conn.execute(
                'INSERT INTO heartbeat_events(ts,device_id,event_type,details) VALUES(?,?,?,?)',
                (now, None, 'supervisor_restart', json.dumps({'registry_db': self.path}, sort_keys=True)),
            )
            self.conn.commit()

    def close(self):
        with self.lock:
            self.conn.close()

    def event(self, event_type, device_id=None, details=None):
        payload = json.dumps(details or {}, sort_keys=True)
        with self.lock:
            with self.conn:
                self.conn.execute(
                    'INSERT INTO heartbeat_events(ts,device_id,event_type,details) VALUES(?,?,?,?)',
                    (int(time.time()), device_id, event_type, payload),
                )

    def authorize_device(self, device_id, hostname=None, ip_address=None, source='config', active=True, maintenance=False):
        device_id = normalize_device_id(device_id)
        now = int(time.time())
        with self.lock:
            with self.conn:
                existing = self.conn.execute('SELECT * FROM authorized_devices WHERE device_id=?', (device_id,)).fetchone()
                if existing is None:
                    self.conn.execute('''
                        INSERT INTO authorized_devices(
                            device_id, hostname, ip_address, active, maintenance, source,
                            authorized_at, updated_at, decommissioned_at
                        )
                        VALUES(?,?,?,?,?,?,?,?,NULL)
                    ''', (device_id, hostname, ip_address, 1 if active else 0, 1 if maintenance else 0, source, now, now))
                    self.conn.execute(
                        'INSERT INTO heartbeat_events(ts,device_id,event_type,details) VALUES(?,?,?,?)',
                        (now, device_id, 'device_authorized', json.dumps({'hostname': hostname, 'ip_address': ip_address, 'source': source}, sort_keys=True)),
                    )
                else:
                    self.conn.execute('''
                        UPDATE authorized_devices
                        SET hostname=COALESCE(?, hostname),
                            ip_address=COALESCE(?, ip_address),
                            active=?,
                            maintenance=?,
                            source=?,
                            updated_at=?,
                            decommissioned_at=CASE WHEN ? THEN NULL ELSE COALESCE(decommissioned_at, ?) END
                        WHERE device_id=?
                    ''', (
                        hostname, ip_address, 1 if active else 0, 1 if maintenance else 0, source,
                        now, 1 if active else 0, now, device_id,
                    ))

    def seed_authorized_devices(self, devices):
        for entry in devices or []:
            if isinstance(entry, str):
                self.authorize_device(entry)
            elif isinstance(entry, dict):
                self.authorize_device(
                    entry.get('device_id'),
                    hostname=entry.get('hostname'),
                    ip_address=entry.get('ip_address'),
                    source=entry.get('source') or 'config',
                    active=entry.get('active', True) is not False,
                    maintenance=entry.get('maintenance', False) is True,
                )

    def is_authorized(self, device_id):
        with self.lock:
            row = self.conn.execute('SELECT active FROM authorized_devices WHERE device_id=?', (device_id,)).fetchone()
        return bool(row and row['active'])

    def _resolve_communication_fault(self, device_id, now):
        cursor = self.conn.execute('''
            UPDATE communication_faults
            SET active=0, resolved_at=?, recovery_heartbeat_ts=?
            WHERE device_id=? AND code=? AND active=1
        ''', (now, now, device_id, COMMUNICATION_LOSS))
        if cursor.rowcount:
            self.conn.execute(
                'INSERT INTO heartbeat_events(ts,device_id,event_type,details) VALUES(?,?,?,?)',
                (now, device_id, 'communication_restored', json.dumps({'code': COMMUNICATION_LOSS}, sort_keys=True)),
            )

    def _active_communication_fault(self, device_id):
        return self.conn.execute('''
            SELECT * FROM communication_faults
            WHERE device_id=? AND code=? AND active=1
        ''', (device_id, COMMUNICATION_LOSS)).fetchone()

    def record_heartbeat(self, device_id, data, observed_ip, timeout_seconds):
        now = int(time.time())
        health = json.dumps(data.get('health', {}), sort_keys=True)
        status = json.dumps(data.get('status', {}), sort_keys=True)
        with self.lock:
            if not self.is_authorized(device_id):
                self.conn.execute(
                    'INSERT INTO heartbeat_events(ts,device_id,event_type,details) VALUES(?,?,?,?)',
                    (now, device_id, 'unauthorized_heartbeat', json.dumps({'observed_ip': observed_ip, 'hostname': data.get('hostname')}, sort_keys=True)),
                )
                self.conn.commit()
                raise PermissionError('device is not authorized for heartbeat supervision')
            row = self.conn.execute('SELECT last_reachable FROM devices WHERE device_id=?', (device_id,)).fetchone()
            full_row = self.conn.execute('SELECT * FROM devices WHERE device_id=?', (device_id,)).fetchone()
            if full_row is not None:
                recent = now - int(full_row['last_seen']) <= int(timeout_seconds)
                same_boot = (not data.get('boot_id')) or data.get('boot_id') == full_row['boot_id']
                same_source = observed_ip == full_row['observed_ip']
                if full_row['last_reachable'] and recent and not same_boot and not same_source:
                    self.conn.execute(
                        'INSERT INTO heartbeat_events(ts,device_id,event_type,details) VALUES(?,?,?,?)',
                        (now, device_id, 'duplicate_device_id', json.dumps({
                            'existing_observed_ip': full_row['observed_ip'],
                            'new_observed_ip': observed_ip,
                            'existing_boot_id': full_row['boot_id'],
                            'new_boot_id': data.get('boot_id'),
                        }, sort_keys=True)),
                    )
                    self.conn.commit()
                    raise ValueError('duplicate device_id from another reachable source')
                if same_boot and data.get('sequence') is not None and full_row['last_sequence'] is not None:
                    if int(data.get('sequence')) <= int(full_row['last_sequence']):
                        self.conn.execute(
                            'INSERT INTO heartbeat_events(ts,device_id,event_type,details) VALUES(?,?,?,?)',
                            (now, device_id, 'heartbeat_replay_rejected', json.dumps({
                                'last_sequence': full_row['last_sequence'],
                                'sequence': data.get('sequence'),
                                'boot_id': data.get('boot_id'),
                            }, sort_keys=True)),
                        )
                        self.conn.commit()
                        raise ValueError('heartbeat sequence replay')
                if not same_boot:
                    self.conn.execute(
                        'INSERT INTO heartbeat_events(ts,device_id,event_type,details) VALUES(?,?,?,?)',
                        (now, device_id, 'device_reboot_detected', json.dumps({
                            'previous_boot_id': full_row['boot_id'],
                            'new_boot_id': data.get('boot_id'),
                        }, sort_keys=True)),
                    )
            with self.conn:
                if row is None:
                    self.conn.execute(
                        'INSERT INTO heartbeat_events(ts,device_id,event_type,details) VALUES(?,?,?,?)',
                        (now, device_id, 'device_registered', json.dumps({'hostname': data.get('hostname'), 'observed_ip': observed_ip}, sort_keys=True)),
                    )
                elif not row['last_reachable']:
                    self.conn.execute(
                        'INSERT INTO heartbeat_events(ts,device_id,event_type,details) VALUES(?,?,?,?)',
                        (now, device_id, 'device_online', json.dumps({'hostname': data.get('hostname'), 'observed_ip': observed_ip}, sort_keys=True)),
                    )
                if row is None:
                    self.conn.execute('''
                        INSERT INTO devices(
                            device_id,hostname,ip_address,observed_ip,boot_id,first_seen,last_seen,
                            last_sequence,last_health,last_status,last_reachable,offline_since
                        )
                        VALUES(?,?,?,?,?,?,?,?,?,?,1,NULL)
                    ''', (
                        device_id, data.get('hostname'), data.get('ip_address'), observed_ip, data.get('boot_id'),
                        now, now, data.get('sequence'), health, status,
                    ))
                else:
                    self.conn.execute('''
                        UPDATE devices
                        SET hostname=?, ip_address=?, observed_ip=?, boot_id=?, last_seen=?,
                            last_sequence=?, last_health=?, last_status=?, last_reachable=1, offline_since=NULL
                        WHERE device_id=?
                    ''', (
                        data.get('hostname'), data.get('ip_address'), observed_ip, data.get('boot_id'),
                        now, data.get('sequence'), health, status, device_id,
                    ))
                self.conn.execute('''
                    INSERT INTO heartbeat_events(ts,device_id,event_type,details)
                    VALUES(?,?,?,?)
                ''', (now, device_id, 'heartbeat', json.dumps({'sequence': data.get('sequence'), 'hostname': data.get('hostname')}, sort_keys=True)))
                self._resolve_communication_fault(device_id, now)

    def mark_offline_overdue(self, timeout_seconds, interval_seconds=5):
        now = int(time.time())
        cutoff = now - int(timeout_seconds)
        changed = []
        with self.lock:
            rows = self.conn.execute('''
                SELECT ad.device_id,
                       COALESCE(d.hostname, ad.hostname, ad.device_id) AS hostname,
                       COALESCE(d.ip_address, ad.ip_address) AS ip_address,
                       d.last_seen,
                       d.last_reachable
                FROM authorized_devices ad
                LEFT JOIN devices d ON d.device_id=ad.device_id
                WHERE ad.active=1
                  AND (
                    d.device_id IS NULL
                    OR (d.last_reachable=1 AND d.last_seen < ?)
                  )
            ''', (cutoff,)).fetchall()
            for row in rows:
                with self.conn:
                    update_cursor = self.conn.execute(
                        'UPDATE devices SET last_reachable=0, offline_since=? WHERE device_id=?',
                        (now, row['device_id']),
                    )
                    changed_this_device = bool(update_cursor.rowcount)
                    if self._active_communication_fault(row['device_id']) is None:
                        self.conn.execute('''
                            INSERT INTO communication_faults(
                                device_id, code, hostname, ip_address, last_heartbeat_ts,
                                detected_at, expected_interval_seconds, timeout_seconds,
                                active, details
                            )
                            VALUES(?,?,?,?,?,?,?,?,1,?)
                        ''', (
                            row['device_id'], COMMUNICATION_LOSS, row['hostname'], row['ip_address'],
                            row['last_seen'], now, int(interval_seconds), int(timeout_seconds),
                            json.dumps({'last_seen': row['last_seen'], 'last_reachable': bool(row['last_reachable'])}, sort_keys=True),
                        ))
                        self.conn.execute(
                            'INSERT INTO heartbeat_events(ts,device_id,event_type,details) VALUES(?,?,?,?)',
                            (now, row['device_id'], 'communication_loss', json.dumps({'hostname': row['hostname'], 'last_seen': row['last_seen']}, sort_keys=True)),
                        )
                        changed_this_device = True
                    if changed_this_device:
                        changed.append(row['device_id'])
        return changed

    def registry(self, timeout_seconds, interval_seconds=5, evaluate=True):
        if evaluate:
            self.mark_offline_overdue(timeout_seconds, interval_seconds)
        now = int(time.time())
        with self.lock:
            rows = self.conn.execute('''
                SELECT ad.device_id AS authorized_device_id,
                       ad.active AS authorized_active,
                       ad.maintenance AS authorized_maintenance,
                       ad.hostname AS authorized_hostname,
                       ad.ip_address AS authorized_ip_address,
                       d.*
                FROM authorized_devices ad
                LEFT JOIN devices d ON d.device_id=ad.device_id
            ''').fetchall()
            faults = {
                row['device_id']: row
                for row in self.conn.execute('SELECT * FROM communication_faults WHERE active=1').fetchall()
            }
        result = {}
        for row in rows:
            last_seen = row['last_seen']
            age = max(0, now - int(last_seen)) if last_seen is not None else None
            online = bool(row['last_reachable']) and age is not None and age <= timeout_seconds
            try:
                health = json.loads(row['last_health'] or '{}')
            except ValueError:
                health = {}
            try:
                status = json.loads(row['last_status'] or '{}')
            except ValueError:
                status = {}
            fault = faults.get(row['authorized_device_id'])
            result[row['authorized_device_id']] = {
                'hostname': row['hostname'] or row['authorized_hostname'],
                'ip_address': row['ip_address'] or row['authorized_ip_address'],
                'observed_ip': row['observed_ip'],
                'last_seen_seconds_ago': round(float(age), 1) if age is not None else None,
                'online': online,
                'authorized': bool(row['authorized_active']),
                'maintenance': bool(row['authorized_maintenance']),
                'last_known_online': bool(row['last_reachable']) if row['last_reachable'] is not None else False,
                'offline_since': row['offline_since'],
                'active_fault': {
                    'code': fault['code'],
                    'detected_at': fault['detected_at'],
                    'timeout_seconds': fault['timeout_seconds'],
                } if fault else None,
                'health': health,
                'status': {'state': status.get('state'), 'modules': status.get('modules', {})},
                'last_sequence': row['last_sequence'],
            }
        return result

def uptime():
    with open('/proc/uptime') as f:
        return int(float(f.read().split()[0]))

def free_mem_percent():
    data = {}
    with open('/proc/meminfo') as f:
        for line in f:
            key, value = line.split(':', 1)
            data[key] = int(value.strip().split()[0])
    return round(100.0 * data.get('MemAvailable', data.get('MemFree', 0)) / max(1, data['MemTotal']), 2)

def temps():
    found = []
    root = '/sys/class/thermal'
    if os.path.isdir(root):
        for entry in os.listdir(root):
            if entry.startswith('thermal_zone'):
                try:
                    with open(os.path.join(root, entry, 'temp')) as f:
                        v = float(f.read().strip())
                    if abs(v) > 1000:
                        v /= 1000.0
                    if -20 < v < 150:
                        found.append(round(v, 1))
                except (IOError, ValueError):
                    pass
    return max(found) if found else None

def is_service_active(name):
    try:
        p = subprocess.Popen(['systemctl', 'is-active', '--quiet', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return p.wait(timeout=3) == 0
    except Exception:
        return False

def local_ip_for(target):
    # Reports the source IP the kernel selects for outbound heartbeat traffic.
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect((target, 6004))
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()

class State(object):
    def __init__(self, cfg):
        cfg.setdefault('authorized_devices', [])
        cfg.setdefault('max_timestamp_skew_seconds', 300)
        cfg.setdefault('heartbeat_auth_mode', 'none')
        cfg.setdefault('heartbeat_auth_secret_file', None)
        validate_auth_config(cfg)
        self.cfg = cfg
        self.lock = threading.RLock()
        self.started = time.monotonic()
        self.boot_id = str(uuid.uuid4())
        self.seq = 0
        self.hostname = socket.gethostname()
        self.device_id = mac_address(cfg['identity_interface'])
        self.conflict_device_id = normalize_device_id(cfg['conflict_device_id']) if cfg.get('conflict_device_id') else None
        self.allowed_device_ids = normalize_allowlist(cfg.get('allowed_device_ids', []))
        self.saved = read_json(cfg['state_file'], {}) or {}
        self.faults = self.saved.get('faults', {})
        self.modules = self.saved.get('modules', {})
        self.pulses = {}  # Not carried across restarts; must be freshly asserted.
        self.peers = {}
        self.store = None
        self.store_error = None
        if cfg['role'] == 'conflict':
            try:
                self.store = ConflictStore(cfg['registry_db'])
                authorized = [{'device_id': device_id, 'source': 'allowed_device_ids'} for device_id in self.allowed_device_ids]
                authorized.extend(cfg.get('authorized_devices', []))
                self.store.seed_authorized_devices(authorized)
            except sqlite3.Error as e:
                self.store_error = 'registry database unavailable: {}'.format(e)
        self.peer_health = None
        self.last_ack = None
        self.last_error = 'not yet connected'
        self.last_poll_started = False
        self.stop = threading.Event()

    def save(self):
        atomic_json(self.cfg['state_file'], {'faults': self.faults, 'modules': self.modules})

    def set_store_error(self, error):
        with self.lock:
            self.store_error = error

    def control(self, payload):
        action = payload.get('action')
        name = payload.get('name', '')
        if action not in ('fault_set', 'fault_clear', 'status_set', 'pulse', 'snapshot'):
            raise ValueError('unknown action')
        if action != 'snapshot' and (not isinstance(name, str) or not name or len(name) > 96):
            raise ValueError('invalid module/fault name')
        with self.lock:
            if action == 'fault_set':
                self.faults[name] = {'detail': str(payload.get('value', 'fault'))[:512], 'since': int(time.time())}
                self.save()
            elif action == 'fault_clear':
                self.faults.pop(name, None)
                self.save()
            elif action == 'status_set':
                self.modules[name] = {'state': str(payload.get('value', 'unknown'))[:80], 'since': int(time.time())}
                self.save()
            elif action == 'pulse':
                self.pulses[name] = time.monotonic()
        return self.snapshot() if action == 'snapshot' else {'ok': True}

    def snapshot(self):
        cfg = self.cfg
        with self.lock:
            external = copy.deepcopy(self.faults)
            modules = copy.deepcopy(self.modules)
            pulses = dict(self.pulses)
            peers = copy.deepcopy(self.peers)
            last_ack = self.last_ack
            peer_health = copy.deepcopy(self.peer_health)
            last_error = self.last_error
            store_error = self.store_error
            started = self.started
            first_poll = self.last_poll_started
            seq = self.seq
        system = {}
        faults = []
        available = free_mem_percent()
        system['memory_available_percent'] = available
        if available < cfg['min_available_memory_percent']:
            faults.append({'type': 'memory', 'detail': 'available memory below threshold'})
        st = os.statvfs('/')
        used = round(100.0 * (st.f_blocks - st.f_bfree) / max(1, st.f_blocks), 2)
        system['root_disk_used_percent'] = used
        if used >= cfg['root_disk_percent_fail']:
            faults.append({'type': 'disk', 'detail': 'root disk usage above threshold'})
        temp = temps()
        system['highest_thermal_celsius'] = temp
        if temp is not None and temp >= cfg['thermal_celsius_fail']:
            faults.append({'type': 'thermal', 'detail': 'temperature above threshold'})
        services = {}
        for service in cfg.get('services', []):
            active = is_service_active(service)
            services[service] = 'active' if active else 'inactive'
            if not active:
                faults.append({'type': 'service', 'name': service, 'detail': 'inactive'})
        for name, entry in external.items():
            faults.append({'type': 'external', 'name': name, 'detail': entry.get('detail', '')})
        now = time.monotonic()
        for name, seconds in cfg.get('watchdogs', {}).items():
            age = now - pulses[name] if name in pulses else now - started
            if age > float(seconds):
                faults.append({'type': 'watchdog', 'name': name, 'detail': 'pulse overdue or never received'})
        peer = {'enabled': cfg['role'] == 'device', 'online': None, 'last_error': last_error}
        if cfg['role'] == 'device':
            age = now - last_ack if last_ack is not None else None
            peer['seconds_since_ack'] = round(age, 1) if age is not None else None
            peer['identity'] = peer_health.get('device_id') if peer_health else None
            peer['hostname'] = peer_health.get('hostname') if peer_health else None
            grace = now - started <= cfg['startup_grace_seconds']
            peer['startup_grace'] = grace
            peer['online'] = age is not None and age <= cfg['peer_timeout_seconds']
            if not peer['online'] and not grace:
                faults.append({'type': 'peer_offline', 'detail': 'conflict heartbeat response overdue'})
        now_wall = int(time.time())
        registry = {}
        if cfg['role'] == 'conflict':
            if self.store:
                try:
                    registry = self.store.registry(cfg['peer_timeout_seconds'], cfg['interval_seconds'])
                    store_error = None
                except sqlite3.Error as e:
                    store_error = 'registry database unavailable: {}'.format(e)
            if store_error:
                faults.append({'type': 'registry_db', 'detail': store_error})
        # Peer faults belong to registry, not own health: prevents reciprocal fault cascades.
        result = {
            'protocol': 'hcm-heartbeat', 'version': VERSION,
            'hostname': self.hostname,
            'ip_address': cfg['advertise_ip'] or (local_ip_for(cfg['conflict_address']) if cfg['role'] == 'device' else cfg['bind_address']),
            'device_id': self.device_id, 'identity_interface': cfg['identity_interface'],
            'boot_id': self.boot_id, 'sequence': seq, 'timestamp': now_wall,
            'health': {'state': 'healthy' if not faults else 'fault', 'faults': faults, 'system': system, 'services': services},
            'status': {'state': 'operational' if not faults else 'degraded', 'uptime_seconds': uptime(),
                       'modules': modules, 'maintenance_lockout': cfg.get('maintenance_lockout', False),
                       'peer': peer},
        }
        if cfg['role'] == 'conflict':
            result['status']['registry'] = registry
        return result

class HTTPServer(socketserver.ThreadingMixIn, BaseHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass
    def send_json(self, status, data):
        body = json.dumps(data, sort_keys=True).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        signature = sign_if_configured(self.server.state.cfg, body)
        if signature:
            self.send_header('X-HomeControl-Signature', signature)
        self.end_headers()
        self.wfile.write(body)
    def do_GET(self):
        if self.path not in ('/health', '/status'):
            return self.send_json(404, {'error': 'not found'})
        data = self.server.state.snapshot()
        code = 200 if self.path == '/status' or data['health']['state'] == 'healthy' else 503
        self.send_json(code, data)
    def do_POST(self):
        if self.path != '/heartbeat' or self.server.state.cfg['role'] != 'conflict':
            return self.send_json(404, {'error': 'not found'})
        try:
            count = int(self.headers.get('Content-Length', '0'))
            if not 0 < count <= MAX_BODY:
                raise ValueError('invalid length')
            data = json.loads(self.rfile.read(count).decode('utf-8'))
            if data.get('protocol') != 'hcm-heartbeat' or data.get('version') != VERSION:
                raise ValueError('unsupported protocol')
            mac = normalize_device_id(data['device_id'])
            if not isinstance(data['hostname'], str) or not data['hostname']:
                raise ValueError('invalid hostname')
            if not isinstance(data['sequence'], int) or not isinstance(data['health'], dict) or not isinstance(data['status'], dict):
                raise ValueError('invalid heartbeat')
            if abs(int(data.get('timestamp', 0)) - int(time.time())) > int(self.server.state.cfg['max_timestamp_skew_seconds']):
                raise ValueError('heartbeat timestamp outside accepted window')
            allow = self.server.state.allowed_device_ids
            if self.server.state.store and not self.server.state.store.is_authorized(mac):
                return self.send_json(403, {'error': 'unregistered device'})
            if allow and mac not in allow:
                return self.send_json(403, {'error': 'unregistered device'})
            auth_mode = self.server.state.cfg.get('heartbeat_auth_mode', 'none')
            if auth_mode == 'hmac-sha256':
                validate_signature(
                    self.server.state.cfg,
                    self.headers.get('X-HomeControl-Signature'),
                    json.dumps(data, sort_keys=True, separators=(',', ':')).encode('utf-8'),
                )
            elif auth_mode != 'none':
                raise ValueError('unsupported heartbeat_auth_mode')
            with self.server.state.lock:
                self.server.state.peers[mac] = {
                    'hostname': data['hostname'], 'ip_address': data.get('ip_address'),
                    'observed_ip': self.client_address[0], 'health': data['health'],
                    'status': {'state': data['status'].get('state'), 'modules': data['status'].get('modules', {})},
                    'seen_mono': time.monotonic(), 'sequence': data['sequence']
                }
                self.server.state.seq += 1
                if self.server.state.store:
                    try:
                        self.server.state.store.record_heartbeat(mac, data, self.client_address[0], self.server.state.cfg['peer_timeout_seconds'])
                        self.server.state.set_store_error(None)
                    except sqlite3.Error as e:
                        self.server.state.set_store_error('registry database unavailable: {}'.format(e))
            reply = self.server.state.snapshot()
            reply['reply_to'] = data['sequence']
            reply['reply_boot_id'] = data.get('boot_id')
            self.send_json(200, reply)
        except (ValueError, KeyError, TypeError, UnicodeError, PermissionError) as e:
            self.send_json(400, {'error': str(e)})

class UnixHandler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            line = self.rfile.readline(MAX_BODY + 1)
            if len(line) > MAX_BODY:
                raise ValueError('request too long')
            value = self.server.state.control(json.loads(line.decode('utf-8')))
            result = {'ok': True, 'result': value}
        except (ValueError, KeyError, TypeError) as e:
            result = {'ok': False, 'error': str(e)}
        self.wfile.write((json.dumps(result) + '\n').encode('utf-8'))

class UnixServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True

def client_loop(state):
    cfg = state.cfg
    while not state.stop.is_set():
        with state.lock:
            state.seq += 1
            seq = state.seq
            state.last_poll_started = True
        message = state.snapshot()
        message['sequence'] = seq
        try:
            body = json.dumps(message, sort_keys=True, separators=(',', ':')).encode('utf-8')
            headers = {'Content-Type': 'application/json'}
            if cfg.get('heartbeat_auth_mode', 'none') == 'hmac-sha256':
                headers['X-HomeControl-Signature'] = heartbeat_signature(load_secret(cfg.get('heartbeat_auth_secret_file')), body)
            req = Request('http://{}:{}/heartbeat'.format(cfg['conflict_address'], cfg['port']),
                          data=body, headers=headers, method='POST')
            with urlopen(req, timeout=cfg['request_timeout_seconds']) as response:
                raw = response.read(MAX_BODY + 1)
                if len(raw) > MAX_BODY:
                    raise ValueError('response too long')
                validate_signature(cfg, response.headers.get('X-HomeControl-Signature'), raw)
                reply = json.loads(raw.decode('utf-8'))
            expected_mac = state.conflict_device_id
            if reply.get('protocol') != 'hcm-heartbeat' or reply.get('version') != VERSION or reply.get('reply_to') != seq or reply.get('reply_boot_id') != state.boot_id:
                raise ValueError('invalid acknowledgment')
            if reply.get('hostname') != cfg['conflict_hostname']:
                raise ValueError('wrong conflict hostname')
            if expected_mac and normalize_device_id(reply.get('device_id', '')) != expected_mac:
                raise ValueError('wrong conflict device ID')
            if not isinstance(reply.get('health'), dict) or not isinstance(reply.get('status'), dict):
                raise ValueError('missing conflict health/status')
            with state.lock:
                state.last_ack = time.monotonic()
                state.peer_health = reply
                state.last_error = None
        except (OSError, ValueError, HTTPError, URLError, TypeError) as e:
            with state.lock:
                state.last_error = str(e)
        state.stop.wait(cfg['interval_seconds'])

def conflict_monitor_loop(state):
    cfg = state.cfg
    while not state.stop.wait(1):
        if not state.store:
            continue
        try:
            state.store.mark_offline_overdue(cfg['peer_timeout_seconds'], cfg['interval_seconds'])
            state.set_store_error(None)
        except sqlite3.Error as e:
            state.set_store_error('registry database unavailable: {}'.format(e))

def serve(cfg):
    state = State(cfg)
    sockpath = cfg['socket_path']
    folder = os.path.dirname(sockpath)
    if not os.path.isdir(folder):
        os.makedirs(folder)
    if os.path.exists(sockpath):
        os.unlink(sockpath)
    unix = UnixServer(sockpath, UnixHandler)
    unix.state = state
    os.chmod(sockpath, 0o660)
    # service runs root; members of sudo group may submit local fault updates
    try:
        import grp
        os.chown(sockpath, 0, grp.getgrnam('sudo').gr_gid)
    except KeyError:
        pass
    web = HTTPServer((cfg['bind_address'], cfg['port']), Handler)
    web.state = state
    threads = [threading.Thread(target=unix.serve_forever, daemon=True), threading.Thread(target=web.serve_forever, daemon=True)]
    if cfg['role'] == 'device':
        threads.append(threading.Thread(target=client_loop, args=(state,), daemon=True))
    if cfg['role'] == 'conflict':
        threads.append(threading.Thread(target=conflict_monitor_loop, args=(state,), daemon=True))
    for thread in threads:
        thread.start()
    print('HCM heartbeat v3 on {}:{} role={} id={}'.format(cfg['bind_address'], cfg['port'], cfg['role'], state.device_id), flush=True)
    def stop(_signal, _frame):
        state.stop.set()
        web.shutdown()
        unix.shutdown()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not state.stop.wait(1):
        pass
    web.server_close()
    unix.server_close()
    if state.store:
        state.store.close()
    if os.path.exists(sockpath):
        os.unlink(sockpath)

def main():
    p = argparse.ArgumentParser(description='HCM Unified Heartbeat v3')
    p.add_argument('--config', default='/etc/hcm-heartbeat/config.json')
    sub = p.add_subparsers(dest='command')
    sub.add_parser('serve')
    fault = sub.add_parser('fault')
    fs = fault.add_subparsers(dest='action')
    for action in ('set', 'clear'):
        f = fs.add_parser(action)
        f.add_argument('name')
        if action == 'set':
            f.add_argument('value')
    status = sub.add_parser('status')
    status.add_argument('name')
    status.add_argument('value')
    pulse = sub.add_parser('pulse')
    pulse.add_argument('name')
    sub.add_parser('show')
    args = p.parse_args()
    cfg = read_json(args.config)
    if not isinstance(cfg, dict):
        p.error('configuration unavailable or invalid')
    if cfg.get('role') not in ('device', 'conflict'):
        p.error('role must be device or conflict')
    defaults = {'port': 6004, 'bind_address': '0.0.0.0', 'advertise_ip': '',
                'identity_interface': 'eth0', 'state_file': '/var/lib/hcm-heartbeat/state.json',
                'registry_db': '/var/lib/hcm-heartbeat/registry.sqlite3',
                'socket_path': '/run/hcm-heartbeat/control.sock', 'services': [], 'watchdogs': {},
                'min_available_memory_percent': 5, 'root_disk_percent_fail': 95,
                'thermal_celsius_fail': 90, 'interval_seconds': 5, 'peer_timeout_seconds': 15,
                'startup_grace_seconds': 45, 'request_timeout_seconds': 4,
                'conflict_address': '192.168.20.26', 'conflict_hostname': 'conflict',
                'allowed_device_ids': [], 'authorized_devices': [],
                'max_timestamp_skew_seconds': 300, 'heartbeat_auth_mode': 'none',
                'heartbeat_auth_secret_file': None}
    for key, value in defaults.items():
        cfg.setdefault(key, value)
    if args.command == 'serve':
        serve(cfg)
        return
    if args.command == 'fault' and args.action in ('set', 'clear'):
        payload = {'action': 'fault_' + args.action, 'name': args.name}
        if args.action == 'set':
            payload['value'] = args.value
    elif args.command == 'status':
        payload = {'action': 'status_set', 'name': args.name, 'value': args.value}
    elif args.command == 'pulse':
        payload = {'action': 'pulse', 'name': args.name}
    elif args.command == 'show':
        payload = {'action': 'snapshot'}
    else:
        p.error('command required')
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(cfg['socket_path'])
        sock.sendall((json.dumps(payload) + '\n').encode('utf-8'))
        f = sock.makefile('rb')
        result = json.loads(f.readline().decode('utf-8'))
        print(json.dumps(result, indent=2, sort_keys=True))
        if not result.get('ok'):
            sys.exit(1)
    finally:
        sock.close()

if __name__ == '__main__':
    main()
