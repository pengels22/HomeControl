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
from homecontrol_identity import InvalidDeviceId, normalize_device_id
from . import global_config
from .module_infra import (
    I2C_COMPONENTS,
    LocalConfigStore,
    LocalAuthStore,
    OfflineEventQueue,
    PeripheralRegistry,
    StructuredEventLogger,
    compute_led_state,
    reconcile_lockouts,
    verify_config_package,
)
from .protocol import read_frame, write_frame

log = logging.getLogger(__name__)

class ModuleAgent:
    def __init__(self, module_type: str, config: dict[str, Any]):
        self.module_type = module_type.upper()
        self.config = config
        try:
            self.global_config = global_config.load_global_config(self.module_type)
        except global_config.GlobalConfigError:
            self.global_config = None
        self.hcm_host = config.get('hcm_host', '192.168.20.27')
        self.hcm_port = int(config.get('hcm_port', 6501))
        self.heartbeat_s = float(config.get('heartbeat_seconds', 5))
        self.reconnect_initial_s = float(config.get(
            'reconnect_initial_s',
            (getattr(self.global_config, 'Module_Connect_Backoff_Initial', 1000) / 1000.0) if self.global_config else 1.0,
        ))
        self.reconnect_max_s = float(config.get(
            'reconnect_max_s',
            (getattr(self.global_config, 'Module_Connect_Backoff_Max', 30000) / 1000.0) if self.global_config else 30.0,
        ))
        self.hcm_auth_timeout_s = float(config.get('hcm_auth_timeout_s', 5.0))
        self.identity_path = Path(config.get('identity_path', './runtime/identity.json'))
        self.identity_path.parent.mkdir(parents=True, exist_ok=True)
        self.identity = self._load_identity()
        self.state: dict[str, Any] = {}
        self.faults: dict[str, Any] = {}
        self.web = config.get('web', {})
        self.hcm_api_url = self.web.get('hcm_api_url', f'http://{self.hcm_host}:8080/api/v1').rstrip('/')
        self.hcm_connected = False
        self.last_valid_ack_ts: float | None = None
        self.start_time = time.time()
        heartbeat_cfg = config.get('heartbeat_v3', {})
        self.heartbeat_socket_path = heartbeat_cfg.get(
            'socket_path',
            config.get('heartbeat_socket_path', '/run/hcm-heartbeat/control.sock'),
        )
        self.heartbeat_watchdog_name = heartbeat_cfg.get('watchdog_name', f'{self.module_type.lower()}_app')
        self.heartbeat_status_name = heartbeat_cfg.get('status_name', f'{self.module_type.lower()}_app')
        self.runtime_root = Path(config.get('runtime_root', './runtime/homecontrol'))
        self.logical_id = str(self.identity.get('hostname') or self.identity.get('module_uuid') or self.module_type)
        self.peripherals = PeripheralRegistry()
        self._register_common_components()
        self.event_logger = StructuredEventLogger(
            self.logical_id,
            self.runtime_root / 'logs' / self.logical_id,
        )
        self.event_queue = OfflineEventQueue(self.runtime_root / 'logs' / self.logical_id / 'pending-events.json')
        self.config_store = LocalConfigStore(self.runtime_root, self.module_type, self.logical_id)
        self.local_auth = LocalAuthStore(self.runtime_root / 'config' / self.module_type / f'{self.logical_id}.auth.json')
        self.config_sync: dict[str, Any] = {
            'last_synchronized_revision': None,
            'current_local_revision': None,
            'state': 'unsynchronized',
            'conflicts': [],
        }
        self.running = True

    def _register_common_components(self) -> None:
        for key, item in I2C_COMPONENTS.items():
            self.peripherals.register(
                key,
                name=item['name'],
                category='i2c',
                address=f"0x{int(item['address']):02X}",
                metadata={'verified_contract': True},
            )

    def _machine_id(self) -> str:
        for p in ('/etc/machine-id', '/var/lib/dbus/machine-id'):
            try:
                val = Path(p).read_text().strip()
                if val:
                    return val
            except OSError:
                pass
        return str(uuid.getnode())

    def _identity_device_id(self) -> str | None:
        identity_cfg = self.config.get('identity', {})
        configured = identity_cfg.get('device_id') or self.config.get('device_id')
        if configured:
            return normalize_device_id(configured)
        iface = identity_cfg.get('interface') or self.config.get('identity_interface')
        if not iface:
            return None
        try:
            return normalize_device_id(Path(f'/sys/class/net/{iface}/address').read_text().strip())
        except (OSError, InvalidDeviceId):
            return None

    def _load_identity(self) -> dict[str, Any]:
        if self.identity_path.exists():
            identity = json.loads(self.identity_path.read_text())
        else:
            identity = {
            'module_type': self.module_type,
            'module_uuid': str(uuid.uuid5(uuid.NAMESPACE_DNS, f'homecontrol:{self.module_type}:{self._machine_id()}')),
            'hostname': self.module_type,
            'assigned_ip': None,
            'commissioned': False,
            'config_version': 0,
        }
        device_id = self._identity_device_id()
        if identity.get('module_type') != self.module_type:
            identity['module_type'] = self.module_type
        if device_id:
            identity['device_id'] = device_id
        return identity

    def save_identity(self) -> None:
        self.identity_path.write_text(json.dumps(self.identity, indent=2))

    async def collect_state(self) -> dict[str, Any]:
        return self.state

    async def heartbeat_control(self, action: str, name: str, value: Any | None = None) -> None:
        payload = {'action': action, 'name': name}
        if value is not None:
            payload['value'] = value
        try:
            reader, writer = await asyncio.open_unix_connection(self.heartbeat_socket_path)
            writer.write((json.dumps(payload) + '\n').encode('utf-8'))
            await writer.drain()
            raw = await asyncio.wait_for(reader.readline(), timeout=1.0)
            writer.close()
            try:
                await writer.wait_closed()
            except AttributeError:
                pass
            if raw:
                result = json.loads(raw.decode('utf-8'))
                if not result.get('ok'):
                    log.warning('heartbeat v3 control rejected %s for %s: %s', action, name, result.get('error'))
        except (OSError, asyncio.TimeoutError, ValueError, json.JSONDecodeError):
            log.debug('heartbeat v3 local control unavailable for %s', self.module_type, exc_info=True)

    async def heartbeat_status(self, name: str, value: str) -> None:
        await self.heartbeat_control('status_set', name, value)

    async def heartbeat_fault(self, name: str, detail: str | None) -> None:
        if detail:
            await self.heartbeat_control('fault_set', name, detail)
        else:
            await self.heartbeat_control('fault_clear', name)

    async def heartbeat_pulse(self) -> None:
        await self.heartbeat_control('pulse', self.heartbeat_watchdog_name)

    async def poll_local_inputs(self) -> None:
        """Hook for modules with a bounded local input polling loop."""

    async def apply_command(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {'ok': False, 'error': 'command_not_implemented'}

    async def web_status(self) -> dict[str, Any]:
        active_faults = self.peripherals.active_faults()
        heartbeat_ack_current = self.last_valid_ack_ts is not None and (time.time() - self.last_valid_ack_ts) <= max(self.heartbeat_s * 3, 15)
        return {
            'module_type': self.module_type,
            'identity': self.identity,
            'config': self._public_config(),
            'state': await self.collect_state(),
            'faults': self.faults,
            'hcm_host': self.hcm_host,
            'hcm_connected': self.hcm_connected,
            'software_version': self.config.get('software_version', '0.1.0'),
            'uptime_status': 'running' if self.running else 'stopped',
            'uptime_seconds': round(time.time() - self.start_time, 3),
            'hcm_heartbeat_health': {
                'connected': self.hcm_connected,
                'last_valid_ack_ts': self.last_valid_ack_ts,
                'ack_current': heartbeat_ack_current,
            },
            'component_health': self.peripherals.grouped(),
            'active_faults': active_faults,
            'known_commanded_output_state': await self.collect_state(),
            'pending_hcm_log_delivery_count': self.event_queue.count(),
            'recent_logs': self.event_logger.recent(limit=20),
            'config_sync': dict(self.config_sync),
            'local_configuration_revision': self.config_sync.get('current_local_revision'),
            'led_state': compute_led_state(
                initialized=True,
                heartbeat_ack_current=heartbeat_ack_current,
                active_faults=active_faults,
            ),
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
        if self.module_type == 'LCM':
            return self._lcm_emergency_web_html()
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
  <section id="config-view" hidden>
    <h2>Emergency Configuration</h2>
    <p>Read-only local view. Configuration changes remain HCM-authorized.</p>
    <pre id="config"></pre>
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
  $('config-view').hidden = !show;
  $('logout').hidden = !show;
}}
async function refresh() {{
  $('status-error').textContent = '';
  const status = await api('/api/module/status');
  $('status').textContent = JSON.stringify(status, null, 2);
  const config = await api('/api/module/config');
  $('config').textContent = JSON.stringify(config, null, 2);
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

    def _lcm_emergency_web_html(self) -> str:
        """Compact local-only LCM configuration view; hardware state is never inferred."""
        return """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>HomeControl LCM emergency configuration</title>
<style>
:root{color-scheme:dark;font-family:system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#0f1113;color:#f4f2ec}
body{margin:0;background:#0f1113}main{width:min(1180px,calc(100% - 28px));margin:auto;padding:22px 0 40px}
header{display:flex;justify-content:space-between;align-items:center;gap:16px;margin-bottom:18px}h1,h2,h3,p{margin:0}h1{font-size:1.35rem}h2{font-size:1rem}p,.muted{color:#a8b0ad;font-size:.86rem}button,input{font:inherit}button{border:0;border-radius:7px;padding:.65rem .9rem;background:#347d68;color:#fff;cursor:pointer;min-height:44px}button.secondary{background:#30363a}button:focus-visible,input:focus-visible{outline:3px solid #7dd3b0;outline-offset:2px}input{width:100%;box-sizing:border-box;border:1px solid #505a60;border-radius:6px;background:#16191c;color:#f4f2ec;padding:.65rem}label{display:grid;gap:5px;color:#cbd0cd;margin-bottom:12px}.error{color:#ffb7ad;min-height:1.25rem}
section{border:1px solid #2b3236;background:#181c1f;border-radius:8px;padding:14px;margin-bottom:14px}.toolbar{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:12px}.toolbar-actions{display:flex;gap:8px;flex-wrap:wrap}
.columns{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}.column{min-width:0}.column h3{font-size:.9rem;padding-bottom:8px;border-bottom:1px solid #30383b}.count{color:#8e9995;font-weight:400}.channel{padding:10px 0;border-bottom:1px solid #293033}.channel:last-child{border-bottom:0}.channel-top{display:flex;justify-content:space-between;align-items:center;gap:8px}.channel-name{font-weight:600;overflow-wrap:anywhere}.channel-id{font-size:.75rem;color:#8e9995;margin-top:2px}.channel-meta{display:flex;gap:8px;flex-wrap:wrap;color:#a8b0ad;font-size:.74rem;margin-top:6px}.channel-meta .locked{color:#ffb7ad}.channel input[type=text]{margin-top:7px}.switch{position:relative;display:inline-flex;align-items:center;flex:0 0 auto}.switch input{position:absolute;opacity:0;width:1px;height:1px}.track{width:46px;height:27px;border-radius:999px;background:#485158;display:block;position:relative;transition:.15s}.track:after{content:"";position:absolute;width:21px;height:21px;left:3px;top:3px;border-radius:50%;background:#fff;transition:.15s;box-shadow:0 1px 3px #0008}.switch input:checked+.track{background:#35a77c}.switch input:checked+.track:after{transform:translateX(19px)}.switch input:disabled+.track{opacity:.42;cursor:not-allowed}.unknown{color:#a8b0ad}.hidden{display:none!important}.state{font-size:.75rem}.status-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}.status-item{background:#121517;border-radius:6px;padding:9px}.status-item strong{display:block;font-size:.78rem}.status-item span{display:block;margin-top:3px;color:#a8b0ad;font-size:.78rem;overflow-wrap:anywhere}
@media(max-width:900px){.columns{grid-template-columns:repeat(2,minmax(0,1fr))}}@media(max-width:600px){main{width:min(100% - 20px,520px);padding-top:14px}.columns{grid-template-columns:1fr}.status-grid{grid-template-columns:repeat(2,minmax(0,1fr))}header{align-items:flex-start}.toolbar{align-items:flex-start;flex-direction:column}}
</style></head><body><main>
<header><div><h1>LCM emergency configuration</h1><p>Local administrator access. Simulated outputs only; no physical state is confirmed.</p></div><button id="logout" class="secondary hidden">Log out</button></header>
<section id="login-view"><h2>Local administrator sign in</h2><p class="muted">This login remains available when HCM is offline.</p><form id="login-form"><label>Username<input id="username" autocomplete="username" required></label><label>Password<input id="password" type="password" autocomplete="current-password" required></label><button>Sign in</button></form><p id="login-error" class="error" role="alert"></p></section>
<div id="app-view" class="hidden"><section><div class="toolbar"><div><h2>Module status</h2><p id="revision" class="muted"></p></div><div class="toolbar-actions"><button id="refresh" class="secondary">Refresh</button></div></div><div id="status-grid" class="status-grid"></div><p id="app-error" class="error" role="alert"></p></section>
<section><div class="toolbar"><div><h2>Channel configuration</h2><p class="muted">Edits are local and queued for HCM reconciliation. Lockouts are preserved during sync.</p></div></div><div id="channels" class="columns"></div></section></div>
</main><script>
let csrf="", loggedIn=false; const $=id=>document.getElementById(id);
async function api(path,options={}){const headers={'Content-Type':'application/json',...(options.headers||{})};if(csrf)headers['X-CSRF-Token']=csrf;const r=await fetch(path,{...options,headers});const data=await r.json();if(!r.ok)throw new Error(data.detail||'Request failed');return data}
function showApp(show){loggedIn=show;$('login-view').classList.toggle('hidden',show);$('app-view').classList.toggle('hidden',!show);$('logout').classList.toggle('hidden',!show)}
function channelCard(item,kind){const id=String(item.channel), name=String(item.name||'');const locked=Boolean(item.lockout);const isRelay=kind==='relay';const dimmer=!isRelay;return `<article class="channel" data-channel="${id}"><div class="channel-top"><div><div class="channel-name">${name||'<span class="unknown">Unnamed</span>'}</div><div class="channel-id">${id} · ${item.type||'Unknown'}</div></div><span class="state unknown">${isRelay?'Simulated state unavailable':'Brightness unknown'}</span></div><div class="channel-meta">${locked?'<span class="locked">Maintenance locked</span>':'<span>Available</span>'}<span>${item.eLight?'eLight':'Standard'}</span>${dimmer?'<span>Max '+(item.max_intensity??'Unknown')+'%</span>':''}</div><label class="muted">Name<input type="text" data-name="${id}" value="${name.replaceAll('"','&quot;')}" aria-label="Name for ${id}"></label><div class="channel-meta"><label><input type="checkbox" data-setting="lockout" data-channel="${id}" ${locked?'checked':''}> Maintenance lock</label><label><input type="checkbox" data-setting="emergency_lighting" data-channel="${id}" ${item.emergency_lighting?'checked':''}> eLight</label>${dimmer?'<label>Max brightness <input type="number" min="0" max="100" step="1" data-setting="max_intensity" data-channel="'+id+'" value="'+(item.max_intensity??'')+'"></label><label>Fade seconds <input type="number" min="0" max="3600" step="0.1" data-setting="fade_seconds" data-channel="'+id+'" value="'+(item.fade_seconds??'3')+'"></label>':''}</div></article>`}
function render(config){const channels=config.channels||[];const groups=[['Relays','relay',channels.filter(x=>x.type==='Relay')],['0–10V dimmers','dimmer',channels.filter(x=>x.type==='0-10V')],['110V dimmers','dimmer',channels.filter(x=>x.type==='110V')]];$('channels').innerHTML=groups.map(([title,kind,items])=>`<div class="column"><h3>${title} <span class="count">${items.length}</span></h3>${items.map(x=>channelCard(x,kind)).join('')}</div>`).join('')||'<p class="unknown">No channel configuration available.</p>';$('channels').querySelectorAll('[data-name]').forEach(input=>input.addEventListener('blur',()=>save({channels:channels.map(x=>x.channel===input.dataset.name?{...x,name:input.value}:x)}).catch(showError)));$('channels').querySelectorAll('[data-setting]').forEach(input=>{const event=input.type==='checkbox'?'change':'blur';input.addEventListener(event,()=>{const channel=input.dataset.channel,field=input.dataset.setting;const value=input.type==='checkbox'?input.checked:Number(input.value);save({channels:channels.map(x=>x.channel===channel?{...x,[field]:value}:x)}).catch(showError)})})}
async function save(body){await api('/config',{method:'PATCH',body:JSON.stringify(body)});await refresh()}
function showError(error){$('app-error').textContent=error.message||String(error)}
async function refresh(){const [health,config]=await Promise.all([fetch('/health').then(r=>r.json()),api('/config')]);const identity=health.identity||{};$('revision').textContent='Revision '+(config.config_sync?.current_local_revision||'Unknown')+' · '+(config.config_sync?.state||'Unknown');const items=[['Identity',identity.device_id||'Unknown'],['Role',identity.role||'LCM'],['Simulation',identity.simulation===true?'Enabled':'Unknown'],['Physical outputs',identity.physical_outputs_enabled===false?'Disabled':'Unknown'],['HCM heartbeat',health.hcm_heartbeat_health?.connected?'Connected':'Offline'],['Config sync',config.config_sync?.state||'Unknown'],['Faults',(health.active_faults||[]).length],['Pending logs',health.pending_hcm_log_delivery_count??'Unknown']];$('status-grid').innerHTML=items.map(([a,b])=>`<div class="status-item"><strong>${a}</strong><span>${b}</span></div>`).join('');const persisted=config.persisted_config||{};render({channels:persisted.config?.channels||persisted.channels||[]})}
async function login(event){event.preventDefault();$('login-error').textContent='';try{const result=await api('/login',{method:'POST',body:JSON.stringify({username:$('username').value,password:$('password').value})});csrf=result.csrf;showApp(true);await refresh()}catch(error){$('login-error').textContent=error.message}}
$('login-form').addEventListener('submit',login);$('refresh').addEventListener('click',()=>refresh().catch(showError));$('logout').addEventListener('click',async()=>{await fetch('/logout',{method:'POST'});csrf='';showApp(false)});showApp(false);
</script></body></html>"""

    def _build_web_app(self):
        from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Response
        from fastapi.responses import HTMLResponse

        app = FastAPI(title=f'HomeControl {self.module_type}', version=self.config.get('software_version', '0.1.0'))

        async def require_hcm_user(authorization: str | None = Header(default=None)) -> dict[str, Any]:
            if not authorization or not authorization.startswith('Bearer '):
                raise HTTPException(401, 'missing bearer token')
            async with httpx.AsyncClient(timeout=self.hcm_auth_timeout_s) as client:
                try:
                    response = await client.get(f'{self.hcm_api_url}/auth/session', headers={'Authorization': authorization})
                except httpx.HTTPError as exc:
                    raise HTTPException(503, 'HCM auth unavailable') from exc
            if response.status_code != 200:
                raise HTTPException(401, 'invalid HCM token')
            return response.json()

        async def require_local_user(homecontrol_local_session: str | None = Cookie(default=None)) -> dict[str, Any]:
            session = self.local_auth.session(homecontrol_local_session)
            if not session:
                raise HTTPException(401, 'local login required')
            return session

        async def require_local_admin(user=Depends(require_local_user)) -> dict[str, Any]:
            if user.get('role') != 'ADMIN':
                raise HTTPException(403, 'administrator role required')
            return user

        @app.get('/', response_class=HTMLResponse)
        async def index():
            return self._module_web_html()

        @app.post('/api/module/login')
        async def login(body: dict[str, Any]):
            async with httpx.AsyncClient(timeout=self.hcm_auth_timeout_s) as client:
                try:
                    response = await client.post(f'{self.hcm_api_url}/auth/login', json=body)
                except httpx.HTTPError as exc:
                    raise HTTPException(503, 'HCM auth unavailable') from exc
            if response.status_code != 200:
                raise HTTPException(response.status_code, response.text)
            return response.json()

        @app.post('/login')
        async def local_login(body: dict[str, Any], response: Response):
            session = self.local_auth.authenticate(str(body.get('username', '')), str(body.get('password', '')))
            if not session:
                self._audit_local('login_failed', {'username': str(body.get('username', ''))})
                raise HTTPException(401, 'invalid local credentials')
            response.set_cookie(
                'homecontrol_local_session',
                session['token'],
                max_age=self.local_auth.session_ttl_s,
                httponly=True,
                secure=bool(self.web.get('secure_cookies', False)),
                samesite='strict',
            )
            self._audit_local('login', {'username': session['username']})
            return {'ok': True, 'csrf': session['csrf'], 'expires_at': session['expires_at']}

        @app.post('/logout')
        async def local_logout(response: Response, homecontrol_local_session: str | None = Cookie(default=None)):
            if homecontrol_local_session:
                self.local_auth.sessions.pop(homecontrol_local_session, None)
            response.delete_cookie('homecontrol_local_session')
            return {'ok': True}

        @app.get('/api/module/session')
        async def session(user=Depends(require_hcm_user)):
            return user

        @app.get('/api/module/status')
        async def status(user=Depends(require_hcm_user)):
            data = await self.web_status()
            data['user'] = user
            return data

        @app.get('/api/module/health')
        async def health(user=Depends(require_hcm_user)):
            status = await self.web_status()
            return {
                'ok': not bool(status['active_faults']),
                'component_health': status['component_health'],
                'hcm_heartbeat_health': status['hcm_heartbeat_health'],
                'pending_hcm_log_delivery_count': status['pending_hcm_log_delivery_count'],
            }

        @app.get('/health')
        async def offline_health():
            # Keep emergency health useful without exposing detailed config,
            # logs, and component metadata on an unauthenticated route.
            status = await self.web_status()
            return {
                'ok': not bool(status['active_faults']),
                'module_type': status['module_type'],
                'identity': {
                    key: status['identity'].get(key)
                    for key in ('module_type', 'device_id', 'hostname', 'simulation', 'physical_outputs_enabled')
                },
                'software_version': status['software_version'],
                'uptime_seconds': status['uptime_seconds'],
                'hcm_heartbeat_health': status['hcm_heartbeat_health'],
                'active_fault_count': len(status['active_faults']),
            }

        @app.get('/api/module/diagnostics')
        async def diagnostics(user=Depends(require_hcm_user)):
            return await self.web_status()

        @app.get('/api/module/config')
        async def config(user=Depends(require_hcm_user)):
            return {
                'identity': self.identity,
                'config': self._public_config(),
                'persisted_config': self.config_store.load_json(),
                'mode': 'read_only_hcm_authorized',
            }

        @app.get('/config')
        async def offline_config(user=Depends(require_local_user)):
            persisted = self.config_store.load_json()
            if self.module_type == 'LCM':
                persisted = {**persisted, 'channels': self.config_store.load_lcm_csv()}
            return {
                'identity': self.identity,
                'module_type': self.module_type,
                'persisted_config': persisted,
                'config_sync': dict(self.config_sync),
                'mode': 'local_offline',
                'user': {'username': user['username'], 'role': user['role']},
            }

        @app.patch('/config')
        async def update_offline_config(body: dict[str, Any], x_csrf_token: str | None = Header(default=None), homecontrol_local_session: str | None = Cookie(default=None), user=Depends(require_local_admin)):
            if not self.local_auth.require_csrf(homecontrol_local_session, x_csrf_token):
                raise HTTPException(403, 'csrf validation failed')
            result = await self.apply_local_config_edit(body, actor=user['username'])
            return result

        return app

    def _audit_local(self, action: str, metadata: dict[str, Any]) -> None:
        record = self.event_logger.log(
            component='local_emergency_auth',
            category='auth',
            severity='info',
            code=action,
            message=f'local emergency {action}',
            metadata={k: v for k, v in metadata.items() if 'password' not in k.lower() and 'token' not in k.lower()},
        )
        if record:
            self.event_queue.enqueue(record)

    async def _run_web(self) -> None:
        import uvicorn

        host = self.web.get('host', '0.0.0.0')
        port = int(self.web.get('port', 6010))
        config = uvicorn.Config(self._build_web_app(), host=host, port=port, log_level='info')
        server = uvicorn.Server(config)
        await server.serve()

    def accept_channel_metadata(self, rows):
        from .channel_metadata import validate_metadata, hvac_conflict
        if self.module_type not in {'RCM', 'LCM'} or not isinstance(rows, list):
            return {'ok': False, 'error': 'invalid metadata snapshot'}
        validated = {}
        try:
            from .module_infra import RCM_RELAY_CHANNELS, LCM_RELAY_CHANNELS, LCM_ANALOG_DIMMER_CHANNELS, LCM_HV_DIMMER_CHANNELS
            expected = set(RCM_RELAY_CHANNELS if self.module_type == 'RCM' else LCM_RELAY_CHANNELS + LCM_ANALOG_DIMMER_CHANNELS + LCM_HV_DIMMER_CHANNELS)
            for row in rows:
                channel = row['channel_id']
                kind = 'relay' if channel in (RCM_RELAY_CHANNELS if self.module_type == 'RCM' else LCM_RELAY_CHANNELS) else 'lv_dimmer' if channel in LCM_ANALOG_DIMMER_CHANNELS else 'hv_dimmer'
                if channel not in expected or channel in validated:
                    raise ValueError('invalid or duplicate channel')
                validated[channel] = validate_metadata(self.module_type, kind, row['metadata']).model_dump(mode='json')
            if set(validated) != expected:
                raise ValueError('incomplete metadata snapshot')
            roles = {ch: value['hvac_control'] for ch, value in validated.items() if value['purpose'] == 'HVAC'}
            if hasattr(self, 'relays') and hvac_conflict(roles, self.relays.snapshot()):
                raise ValueError('metadata would classify active heat and cool together')
        except (ValueError, KeyError, TypeError) as exc:
            return {'ok': False, 'error': str(exc)}
        # A separate durable snapshot survives legacy CSV/package reconciliation.
        from .module_infra import atomic_write_text
        if not hasattr(self, 'channel_metadata'):
            legacy_emergency = set(self.config.get('safety', {}).get('emergency_lighting_channels', []))
            if any(ch not in validated or not validated[ch]['emergency'] for ch in legacy_emergency):
                return {'ok': False, 'error': 'legacy emergency designations require reconciliation in HCM'}
        atomic_write_text(self.runtime_root / '.state' / f'channel-metadata-{self.module_type}.json', json.dumps(validated))
        self.channel_metadata = validated
        if hasattr(self, 'safety'):
            self.safety.hvac_shutdown_channels = set(roles) | set(self.config.get('safety', {}).get('hvac_shutdown_channels', []))
            self.safety.emergency_lighting_channels = {ch for ch, value in validated.items() if value['purpose'] == 'LIGHTING' and value['emergency'] and value['enabled']}
        return {'ok': True, 'metadata_contract': 1, 'metadata_channels': len(validated), 'physical_outputs_commanded': False}

    async def apply_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        if 'channel_metadata' in payload:
            return self.accept_channel_metadata(payload['channel_metadata'])
        snapshot = payload.get('user_snapshot')
        if isinstance(snapshot, dict):
            self.local_auth.provision_snapshot(snapshot, device_id=str(self.identity.get('device_id') or ''))
        package = payload.get('package') if isinstance(payload.get('package'), dict) else payload if 'checksum' in payload else None
        if package:
            verify_config_package(package, module_type=self.module_type, logical_id=self.identity.get('hostname'))
            current_revision = self.config_sync.get('current_local_revision')
            if current_revision and payload.get('base_revision') and payload['base_revision'] != current_revision:
                self.config_sync.update({'state': 'stale_rejected', 'pending_hcm_revision': package['revision']})
                return {'ok': False, 'error': 'stale_configuration', 'current_local_revision': current_revision}
            local_config = self.config_store.load_json().get('config', {})
            merged_config, conflicts = reconcile_lockouts(package.get('config', {}), local_config)
            package = {**package, 'config': merged_config}
            self._persist_module_config_files(package)
            saved = self.config_store.save_json(package)
            self.config_sync.update({
                'last_synchronized_revision': package['revision'],
                'current_local_revision': saved['revision'],
                'state': 'conflict' if conflicts else 'synchronized',
                'conflicts': conflicts,
            })
        self.identity['config_version'] = int(payload.get('version', self.identity.get('config_version', 0)))
        if 'heartbeat_supervisor' in payload:
            # Persist only the authenticated endpoint metadata from HCM. Private keys or
            # secret material are intentionally not provisioned through this channel.
            self.identity['heartbeat_supervisor'] = payload['heartbeat_supervisor']
        if isinstance(payload.get('offline_admins'), list):
            self.local_auth.provision_hashes(payload['offline_admins'])
        self.save_identity()
        if not package:
            saved = self.config_store.save_json({'identity': self.identity, 'payload': payload})
            self.config_sync.update({
                'last_synchronized_revision': str(payload.get('version', saved['revision'])),
                'current_local_revision': saved['revision'],
                'state': 'synchronized',
                'conflicts': [],
            })
            return {'ok': True, 'config_version': self.identity['config_version']}
        return {'ok': True, 'config_version': self.identity['config_version'], 'config_sync': dict(self.config_sync)}

    def _persist_module_config_files(self, package: dict[str, Any]) -> None:
        config = package.get('config') if isinstance(package.get('config'), dict) else {}
        if self.module_type == 'RCM':
            channels = config.get('channels')
            if isinstance(channels, list):
                self.config_store.save_rcm_csv(channels)
        elif self.module_type == 'LCM':
            channels = config.get('channels')
            if isinstance(channels, list):
                self.config_store.save_lcm_csv(channels)

    async def apply_local_config_edit(self, body: dict[str, Any], *, actor: str) -> dict[str, Any]:
        current = self.config_store.load_json()
        current_config = current.get('config') if isinstance(current.get('config'), dict) else current
        next_config = {**current_config, **{k: v for k, v in body.items() if k not in {'revision', 'checksum'}}}
        if self.module_type == 'LCM' and isinstance(body.get('channels'), list):
            self.config_store.save_lcm_csv(body['channels'])
        saved = self.config_store.save_json({'config': next_config, 'local_edit_by': actor})
        self.config_sync.update({
            'current_local_revision': saved['revision'],
            'state': 'local_changes_pending_hcm_reconciliation',
        })
        record = self.event_logger.log(
            component='local_emergency_config',
            category='config',
            severity='info',
            code='local_config_edit',
            message='local emergency configuration edited',
            metadata={'actor': actor, 'revision': saved['revision']},
        )
        if record:
            self.event_queue.enqueue(record)
        return {'ok': True, 'revision': saved['revision'], 'config_sync': dict(self.config_sync)}

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
        await self.heartbeat_status('hcm_tcp_session', 'connected')
        await self.heartbeat_fault('hcm_tcp_session', None)
        await self.heartbeat_status(self.heartbeat_status_name, 'running')
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
                        'device_id': self.identity.get('device_id'),
                        'hostname': self.identity['hostname'],
                        'ts': time.time(),
                        'state': state,
                        'faults': self.faults,
                        'config_sync': dict(self.config_sync),
                        'pending_log_events': self.event_queue.count(),
                        **self._emergency_ui_advertisement(),
                    }
                })
                await self._deliver_log_events(writer)
                await self.heartbeat_pulse()
                await self.heartbeat_status(self.heartbeat_status_name, 'running')

        hb = asyncio.create_task(heartbeat_loop())
        try:
            while self.running:
                msg = await read_frame(reader)
                typ = msg.get('type')
                if typ == 'heartbeat_ack':
                    self.last_valid_ack_ts = time.time()
                    continue
                if typ == 'log_ack':
                    payload = msg.get('payload') or {}
                    event_ids = payload.get('event_ids') or []
                    if isinstance(event_ids, list):
                        self.event_queue.mark_delivered([str(item) for item in event_ids])
                    continue
                if typ == 'command':
                    result = await self.apply_command(msg.get('payload', {}))
                    await write_frame(writer, {'type': 'command_ack', 'payload': result, 'request_id': msg.get('request_id')})
                elif typ == 'config':
                    result = await self.apply_config(msg.get('payload', {}))
                    await write_frame(writer, {'type': 'command_ack', 'payload': result, 'request_id': msg.get('request_id')})
        finally:
            self.hcm_connected = False
            await self.heartbeat_status('hcm_tcp_session', 'disconnected')
            await self.heartbeat_fault('hcm_tcp_session', 'module TCP session disconnected')
            hb.cancel()
            writer.close()
            await writer.wait_closed()

    async def _deliver_log_events(self, writer) -> None:
        batch = self.event_queue.batch(limit=100)
        if not batch:
            return
        await write_frame(writer, {'type': 'log_events', 'payload': {'events': batch}})

    def _emergency_ui_advertisement(self) -> dict[str, Any]:
        if not self.web.get('enabled') or int(self.web.get('port', 0)) != 6010:
            return {}
        return {
            'emergency_ui': {
                'enabled': True,
                'available': True,
                'protocol': 'http',
                'port': 6010,
                'config_path': '/config',
                'health_path': '/health',
            }
        }

    async def run(self) -> None:
        web_task = None
        input_task = None
        if self.web.get('enabled', False):
            web_task = asyncio.create_task(self._run_web())
        poll_interval = getattr(self, 'local_input_poll_interval_s', None)
        if poll_interval:
            async def local_input_loop():
                while self.running:
                    await self.poll_local_inputs()
                    await asyncio.sleep(float(poll_interval))
            input_task = asyncio.create_task(local_input_loop())
        delay = self.reconnect_initial_s
        try:
            while self.running:
                try:
                    await self._session()
                    delay = self.reconnect_initial_s
                except (OSError, asyncio.IncompleteReadError, ConnectionError) as exc:
                    log.warning('%s disconnected: %s', self.module_type, exc)
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, self.reconnect_max_s)
        finally:
            if web_task:
                web_task.cancel()
            if input_task:
                input_task.cancel()
