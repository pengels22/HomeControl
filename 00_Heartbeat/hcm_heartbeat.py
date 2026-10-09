#!/usr/bin/env python3
"""HCM Unified Heartbeat v3. Python 3.6+ standard library only."""
import argparse
import copy
import json
import os
import signal
import socket
import socketserver
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer as BaseHTTPServer
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

VERSION = 3
MAX_BODY = 65536

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
        mac = f.read().strip().lower()
    if len(mac.split(':')) != 6 or mac == '00:00:00:00:00:00':
        raise ValueError('invalid MAC on {}'.format(iface))
    return mac

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
        self.cfg = cfg
        self.lock = threading.RLock()
        self.started = time.monotonic()
        self.boot_id = str(uuid.uuid4())
        self.seq = 0
        self.hostname = socket.gethostname()
        self.device_id = mac_address(cfg['identity_interface'])
        self.saved = read_json(cfg['state_file'], {}) or {}
        self.faults = self.saved.get('faults', {})
        self.modules = self.saved.get('modules', {})
        self.pulses = {}  # Not carried across restarts; must be freshly asserted.
        self.peers = {}
        self.peer_health = None
        self.last_ack = None
        self.last_error = 'not yet connected'
        self.last_poll_started = False
        self.stop = threading.Event()

    def save(self):
        atomic_json(self.cfg['state_file'], {'faults': self.faults, 'modules': self.modules})

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
            for ident, entry in peers.items():
                age = now - entry['seen_mono']
                registry[ident] = {
                    'hostname': entry['hostname'], 'ip_address': entry['ip_address'],
                    'observed_ip': entry['observed_ip'], 'last_seen_seconds_ago': round(age, 1),
                    'online': age <= cfg['peer_timeout_seconds'],
                    'health': entry['health'], 'status': entry['status'],
                    'last_sequence': entry['sequence']
                }
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
            mac = data['device_id'].lower()
            if len(mac.split(':')) != 6 or any(len(x) != 2 for x in mac.split(':')):
                raise ValueError('invalid MAC')
            if not isinstance(data['hostname'], str) or not data['hostname']:
                raise ValueError('invalid hostname')
            if not isinstance(data['sequence'], int) or not isinstance(data['health'], dict) or not isinstance(data['status'], dict):
                raise ValueError('invalid heartbeat')
            allow = self.server.state.cfg.get('allowed_device_ids', [])
            if allow and mac not in allow:
                return self.send_json(403, {'error': 'unregistered device'})
            with self.server.state.lock:
                self.server.state.peers[mac] = {
                    'hostname': data['hostname'], 'ip_address': data.get('ip_address'),
                    'observed_ip': self.client_address[0], 'health': data['health'],
                    'status': {'state': data['status'].get('state'), 'modules': data['status'].get('modules', {})},
                    'seen_mono': time.monotonic(), 'sequence': data['sequence']
                }
                self.server.state.seq += 1
            reply = self.server.state.snapshot()
            reply['reply_to'] = data['sequence']
            reply['reply_boot_id'] = data.get('boot_id')
            self.send_json(200, reply)
        except (ValueError, KeyError, TypeError, UnicodeError) as e:
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
            req = Request('http://{}:{}/heartbeat'.format(cfg['conflict_address'], cfg['port']),
                          data=json.dumps(message).encode('utf-8'),
                          headers={'Content-Type': 'application/json'}, method='POST')
            with urlopen(req, timeout=cfg['request_timeout_seconds']) as response:
                raw = response.read(MAX_BODY + 1)
                if len(raw) > MAX_BODY:
                    raise ValueError('response too long')
                reply = json.loads(raw.decode('utf-8'))
            expected_mac = cfg.get('conflict_device_id')
            if reply.get('protocol') != 'hcm-heartbeat' or reply.get('version') != VERSION or reply.get('reply_to') != seq or reply.get('reply_boot_id') != state.boot_id:
                raise ValueError('invalid acknowledgment')
            if reply.get('hostname') != cfg['conflict_hostname']:
                raise ValueError('wrong conflict hostname')
            if expected_mac and reply.get('device_id', '').lower() != expected_mac.lower():
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
                'socket_path': '/run/hcm-heartbeat/control.sock', 'services': [], 'watchdogs': {},
                'min_available_memory_percent': 5, 'root_disk_percent_fail': 95,
                'thermal_celsius_fail': 90, 'interval_seconds': 5, 'peer_timeout_seconds': 15,
                'startup_grace_seconds': 45, 'request_timeout_seconds': 4,
                'conflict_address': '192.168.20.26', 'conflict_hostname': 'conflict',
                'allowed_device_ids': []}
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
