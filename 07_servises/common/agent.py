from __future__ import annotations

import asyncio
import json
import logging
import os
import socket
import ssl
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from .protocol import read_frame, write_frame

log = logging.getLogger(__name__)

class ModuleAgent:
    def __init__(self, module_type: str, config: dict[str, Any]):
        self.module_type = module_type.upper()
        self.config = config
        self.hcm_host = config.get('hcm_host', '192.168.60.1')
        self.hcm_port = int(config.get('hcm_port', 6501))
        self.heartbeat_s = float(config.get('heartbeat_seconds', 5))
        self.identity_path = Path(config.get('identity_path', './runtime/identity.json'))
        self.identity_path.parent.mkdir(parents=True, exist_ok=True)
        self.identity = self._load_identity()
        self.state: dict[str, Any] = {}
        self.faults: dict[str, Any] = {}
        self.web = config.get('web', {})
        self.hcm_api_url = self.web.get('hcm_api_url', f'http://{self.hcm_host}:8080/api/v1').rstrip('/')
        self.hcm_connected = False
        self.running = True

    def _machine_id(self) -> str:
        for p in ('/etc/machine-id', '/var/lib/dbus/machine-id'):
            try:
                val = Path(p).read_text().strip()
                if val:
                    return val
            except OSError:
                pass
        return str(uuid.getnode())

    def _load_identity(self) -> dict[str, Any]:
        if self.identity_path.exists():
            return json.loads(self.identity_path.read_text())
        return {
            'module_type': self.module_type,
            'module_uuid': str(uuid.uuid5(uuid.NAMESPACE_DNS, f'homecontrol:{self.module_type}:{self._machine_id()}')),
            'hostname': self.module_type,
            'assigned_ip': None,
            'commissioned': False,
            'config_version': 0,
        }

    def save_identity(self) -> None:
        self.identity_path.write_text(json.dumps(self.identity, indent=2))

    async def collect_state(self) -> dict[str, Any]:
        return self.state

    async def apply_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {'ok': False, 'error': 'command_not_implemented'}

    async def web_status(self) -> dict[str, Any]:
        return {
            'module_type': self.module_type,
            'identity': self.identity,
            'config': self._public_config(),
            'state': await self.collect_state(),
            'faults': self.faults,
            'hcm_host': self.hcm_host,
            'hcm_connected': self.hcm_connected,
        }

    def _public_config(self) -> dict[str, Any]:
        redacted = {}
        secret_words = ('key', 'cert', 'password', 'token', 'secret')
        for key, value in self.config.items():
            if any(word in key.lower() for word in secret_words):
                redacted[key] = '<redacted>'
            elif isinstance(value, dict):
                redacted[key] = {
                    k: ('<redacted>' if any(word in k.lower() for word in secret_words) else v)
                    for k, v in value.items()
                }
            else:
                redacted[key] = value
        return redacted

    def _module_web_html(self) -> str:
        title = f"HomeControl {self.module_type}"
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{ color-scheme: light dark; font-family: system-ui, -apple-system, Segoe UI, sans-serif; background:#101214; color:#f4f2ec; }}
    body {{ margin:0; }}
    main {{ width:min(960px, calc(100% - 32px)); margin:0 auto; padding:24px 0; }}
    header {{ display:flex; justify-content:space-between; gap:16px; align-items:center; margin-bottom:18px; }}
    h1,h2,p {{ margin:0; }}
    p {{ color:#aab2ae; margin-top:4px; }}
    section {{ border:1px solid #2b3035; background:#181c1f; border-radius:8px; padding:16px; margin-bottom:14px; }}
    label {{ display:grid; gap:6px; margin-bottom:12px; color:#c7cbc9; }}
    input,button {{ font:inherit; border-radius:6px; padding:.65rem; }}
    input {{ border:1px solid #555d64; background:#171a1d; color:#f4f2ec; }}
    button {{ border:0; background:#2f7d68; color:white; cursor:pointer; }}
    button.secondary {{ background:#363b3f; }}
    pre {{ overflow:auto; background:#101214; border:1px solid #2b3035; padding:12px; border-radius:6px; }}
    .error {{ color:#ffb2a8; }}
  </style>
</head>
<body>
<main>
  <header>
    <div><h1>{title}</h1><p>Authenticated module status</p></div>
    <button id="logout" class="secondary" hidden>Log out</button>
  </header>
  <section id="login-view">
    <h2>Sign in with HCM account</h2>
    <label>Username <input id="username" autocomplete="username"></label>
    <label>Password <input id="password" type="password" autocomplete="current-password"></label>
    <button id="login">Sign in</button>
    <p id="login-error" class="error"></p>
  </section>
  <section id="status-view" hidden>
    <h2>Status</h2>
    <pre id="status"></pre>
    <button id="refresh">Refresh</button>
    <p id="status-error" class="error"></p>
  </section>
</main>
<script>
let token = localStorage.getItem('homecontrol_token') || '';
const $ = id => document.getElementById(id);
async function api(path, opts={{}}) {{
  const headers = {{'Content-Type':'application/json', ...(opts.headers || {{}})}};
  if (token) headers.Authorization = `Bearer ${{token}}`;
  const r = await fetch(path, {{...opts, headers}});
  const j = await r.json();
  if (!r.ok) throw new Error(j.detail || JSON.stringify(j));
  return j;
}}
function showStatus(show) {{
  $('login-view').hidden = show;
  $('status-view').hidden = !show;
  $('logout').hidden = !show;
}}
async function refresh() {{
  $('status-error').textContent = '';
  const status = await api('/api/module/status');
  $('status').textContent = JSON.stringify(status, null, 2);
}}
$('login').onclick = async () => {{
  $('login-error').textContent = '';
  try {{
    const data = await api('/api/module/login', {{method:'POST', body:JSON.stringify({{username:$('username').value, password:$('password').value}})}});
    token = data.token;
    localStorage.setItem('homecontrol_token', token);
    showStatus(true);
    await refresh();
  }} catch (e) {{ $('login-error').textContent = e.message; }}
}};
$('logout').onclick = () => {{ token=''; localStorage.removeItem('homecontrol_token'); showStatus(false); }};
$('refresh').onclick = () => refresh().catch(e => $('status-error').textContent = e.message);
(async () => {{
  if (!token) return showStatus(false);
  try {{ await api('/api/module/session'); showStatus(true); await refresh(); }}
  catch {{ token=''; localStorage.removeItem('homecontrol_token'); showStatus(false); }}
}})();
</script>
</body>
</html>"""

    def _build_web_app(self):
        from fastapi import Depends, FastAPI, Header, HTTPException
        from fastapi.responses import HTMLResponse

        app = FastAPI(title=f'HomeControl {self.module_type}', version=self.config.get('software_version', '0.1.0'))

        async def require_hcm_user(authorization: str | None = Header(default=None)) -> dict[str, Any]:
            if not authorization or not authorization.startswith('Bearer '):
                raise HTTPException(401, 'missing bearer token')
            async with httpx.AsyncClient(timeout=5.0) as client:
                try:
                    response = await client.get(f'{self.hcm_api_url}/auth/session', headers={'Authorization': authorization})
                except httpx.HTTPError as exc:
                    raise HTTPException(503, 'HCM auth unavailable') from exc
            if response.status_code != 200:
                raise HTTPException(401, 'invalid HCM token')
            return response.json()

        @app.get('/', response_class=HTMLResponse)
        async def index():
            return self._module_web_html()

        @app.post('/api/module/login')
        async def login(body: dict[str, Any]):
            async with httpx.AsyncClient(timeout=5.0) as client:
                try:
                    response = await client.post(f'{self.hcm_api_url}/auth/login', json=body)
                except httpx.HTTPError as exc:
                    raise HTTPException(503, 'HCM auth unavailable') from exc
            if response.status_code != 200:
                raise HTTPException(response.status_code, response.text)
            return response.json()

        @app.get('/api/module/session')
        async def session(user=Depends(require_hcm_user)):
            return user

        @app.get('/api/module/status')
        async def status(user=Depends(require_hcm_user)):
            data = await self.web_status()
            data['user'] = user
            return data

        return app

    async def _run_web(self) -> None:
        import uvicorn

        host = self.web.get('host', '0.0.0.0')
        port = int(self.web.get('port', 8090))
        config = uvicorn.Config(self._build_web_app(), host=host, port=port, log_level='info')
        server = uvicorn.Server(config)
        await server.serve()

    async def apply_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.identity['config_version'] = int(payload.get('version', self.identity.get('config_version', 0)))
        self.save_identity()
        return {'ok': True, 'config_version': self.identity['config_version']}

    async def apply_assignment(self, payload: dict[str, Any]) -> dict[str, Any]:
        # First pass: persist the desired identity. OS hostname/network changes are intentionally
        # delegated to an installer/service hook so dev machines are never reconfigured by accident.
        self.identity.update({
            'hostname': payload['hostname'],
            'assigned_ip': payload['ip_address'],
            'commissioned': True,
        })
        self.save_identity()
        return {'ok': True, 'reboot_required': bool(payload.get('reboot_required', True))}

    def _ssl_context(self) -> ssl.SSLContext | None:
        tls = self.config.get('tls', {})
        if not tls.get('enabled', False):
            return None
        ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=tls.get('ca_file'))
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.check_hostname = bool(tls.get('check_hostname', True))
        cert = tls.get('cert_file')
        key = tls.get('key_file')
        if cert and key:
            ctx.load_cert_chain(cert, key)
        return ctx

    async def _session(self) -> None:
        tls = self.config.get('tls', {})
        server_hostname = tls.get('server_hostname', self.hcm_host) if tls.get('enabled', False) else None
        reader, writer = await asyncio.open_connection(
            self.hcm_host,
            self.hcm_port,
            ssl=self._ssl_context(),
            server_hostname=server_hostname,
        )
        self.hcm_connected = True
        await write_frame(writer, {
            'type': 'identify',
            'payload': {
                **self.identity,
                'reported_hostname': socket.gethostname(),
                'software_version': self.config.get('software_version', '0.1.0'),
                'capabilities': self.config.get('capabilities', []),
            }
        })
        reply = await read_frame(reader)
        if reply.get('type') == 'assignment':
            ack = await self.apply_assignment(reply.get('payload', {}))
            await write_frame(writer, {'type': 'command_ack', 'payload': ack, 'request_id': reply.get('request_id')})
            # Commissioning requires the module to return using its permanent identity.
            # The installer may replace this reconnect with a real OS hostname/IP update + reboot.
            writer.close()
            await writer.wait_closed()
            return
        if reply.get('type') == 'config':
            ack = await self.apply_config(reply.get('payload', {}))
            await write_frame(writer, {'type': 'command_ack', 'payload': ack, 'request_id': reply.get('request_id')})

        async def heartbeat_loop():
            while self.running:
                await asyncio.sleep(self.heartbeat_s)
                state = await self.collect_state()
                await write_frame(writer, {
                    'type': 'heartbeat',
                    'payload': {
                        'module_uuid': self.identity['module_uuid'],
                        'hostname': self.identity['hostname'],
                        'ts': time.time(),
                        'state': state,
                        'faults': self.faults,
                    }
                })

        hb = asyncio.create_task(heartbeat_loop())
        try:
            while self.running:
                msg = await read_frame(reader)
                typ = msg.get('type')
                if typ == 'heartbeat_ack':
                    continue
                if typ == 'command':
                    result = await self.apply_command(msg.get('payload', {}))
                    await write_frame(writer, {'type': 'command_ack', 'payload': result, 'request_id': msg.get('request_id')})
                elif typ == 'config':
                    result = await self.apply_config(msg.get('payload', {}))
                    await write_frame(writer, {'type': 'command_ack', 'payload': result, 'request_id': msg.get('request_id')})
        finally:
            self.hcm_connected = False
            hb.cancel()
            writer.close()
            await writer.wait_closed()

    async def run(self) -> None:
        web_task = None
        if self.web.get('enabled', False):
            web_task = asyncio.create_task(self._run_web())
        delay = 1
        try:
            while self.running:
                try:
                    await self._session()
                    delay = 1
                except (OSError, asyncio.IncompleteReadError, ConnectionError) as exc:
                    log.warning('%s disconnected: %s', self.module_type, exc)
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 30)
        finally:
            if web_task:
                web_task.cancel()
