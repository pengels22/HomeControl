#!/usr/bin/env python3
"""Dependency-free LAB1 local emergency configuration server."""
from __future__ import annotations
import http.server
import json
import secrets
import sys
import time
from importlib import import_module
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
infra = import_module('module_infra')
STATE_PATH = ROOT / 'state' / 'module.json'
RUNTIME_ROOT = ROOT / 'state' / 'homecontrol'
AUTH = infra.LocalAuthStore(RUNTIME_ROOT / 'config' / 'LCM' / 'lab1.auth.json')
LOGGER = infra.StructuredEventLogger('lab1', RUNTIME_ROOT / 'logs' / 'lab1')
QUEUE = infra.OfflineEventQueue(RUNTIME_ROOT / 'logs' / 'lab1' / 'pending-events.json')

HTML = """<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>LAB1 emergency configuration</title>
<style>body{margin:auto;max-width:1180px;padding:20px;background:#101214;color:#f4f2ec;font:15px system-ui}section{background:#181c1f;border:1px solid #30383b;border-radius:8px;padding:14px;margin:12px 0}.cols{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.channel{border-bottom:1px solid #30383b;padding:10px 0}.meta{color:#9da7a3;font-size:12px}input,button{font:inherit;padding:9px;border-radius:6px}input{background:#121517;color:#fff;border:1px solid #566168}button{background:#347d68;color:white;border:0;cursor:pointer;min-height:42px}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.box{background:#121517;padding:8px;border-radius:6px}.muted{color:#9da7a3}.error{color:#ffb7ad}@media(max-width:850px){.cols{grid-template-columns:repeat(2,1fr)}}@media(max-width:560px){.cols,.grid{grid-template-columns:1fr}}</style>
<main><header><h1>LAB1 emergency configuration</h1><p class=muted>Local administrator access. Simulation only; physical output state is not confirmed.</p></header><section id=login><h2>Local administrator sign in</h2><form><input id=u autocomplete=username placeholder=Username required><input id=p type=password autocomplete=current-password placeholder=Password required><button>Sign in</button></form><p id=le class=error></p></section><div id=app hidden><section><h2>Module status</h2><div id=status class=grid></div><p id=err class=error></p></section><section><h2>Role configuration</h2><p class=muted>Local changes use the active operational role and reconcile with HCM when available.</p><div id=channels class=cols></div></section></div></main>
<script>let csrf='';const $=x=>document.getElementById(x);async function api(path,opt={}){opt.headers={'Content-Type':'application/json','X-CSRF-Token':csrf,...(opt.headers||{})};let r=await fetch(path,opt),j=await r.json();if(!r.ok)throw Error(j.detail||'Request failed');return j}function esc(x){return String(x??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]))}function draw(c){let groups=[['Relays',c.filter(x=>x.type==='Relay')],['0-10V dimmers',c.filter(x=>x.type==='0-10V')],['110V dimmers',c.filter(x=>x.type==='110V')]];$('channels').innerHTML=groups.map(([title,a])=>`<div><h3>${title} <span class=meta>${a.length}</span></h3>${a.map(x=>`<article class=channel><b>${esc(x.name)||'Unnamed'}</b><div class=meta>${esc(x.channel)} · ${esc(x.type)} · ${x.lockout?'Maintenance locked':'Available'}</div><label class=meta>Name <input data-name=${esc(x.channel)} value="${esc(x.name)}"></label><label class=meta><input type=checkbox data-lock=${esc(x.channel)} ${x.lockout?'checked':''}> Lockout</label><label class=meta><input type=checkbox data-light=${esc(x.channel)} ${x.emergency_lighting?'checked':''}> eLight</label>${x.type!=='Relay'?`<label class=meta>Max brightness <input type=number min=0 max=100 data-max=${esc(x.channel)} value=${x.max_intensity??''}></label><label class=meta>Fade seconds <input type=number min=0 max=3600 step=.1 data-fade=${esc(x.channel)} value=${x.fade_seconds??3}></label>`:''}<div class=meta>Simulated state: Unknown</div></article>`).join('')}</div>`).join('')}async function refresh(){let [h,c]=await Promise.all([fetch('/health').then(r=>r.json()),api('/config')]);let i=h.identity||{};let vals=[['Device',i.device_id],['Role',i.role],['Simulation',i.simulation?'Enabled':'Unknown'],['Physical outputs',i.physical_outputs_enabled===false?'Disabled':'Unknown'],['HCM heartbeat',h.hcm_heartbeat_health?.connected?'Connected':'Offline'],['Config sync',c.config_sync?.state||'Unknown'],['Faults',(h.active_faults||[]).length],['Pending logs',h.pending_hcm_log_delivery_count??'Unknown']];$('status').innerHTML=vals.map(x=>`<div class=box><b>${esc(x[0])}</b><br><span class=muted>${esc(x[1])}</span></div>`).join('');draw(c.channels||[]);$('app').hidden=false;$('login').hidden=true}async function save(){let c=(await api('/config')).channels||[];document.querySelectorAll('[data-name]').forEach(e=>{let x=c.find(x=>x.channel===e.dataset.name);if(x)x.name=e.value});document.querySelectorAll('[data-lock]').forEach(e=>{let x=c.find(x=>x.channel===e.dataset.lock);if(x)x.lockout=e.checked});document.querySelectorAll('[data-light]').forEach(e=>{let x=c.find(x=>x.channel===e.dataset.light);if(x)x.emergency_lighting=e.checked});document.querySelectorAll('[data-max]').forEach(e=>{let x=c.find(x=>x.channel===e.dataset.max);if(x)x.max_intensity=Number(e.value)});document.querySelectorAll('[data-fade]').forEach(e=>{let x=c.find(x=>x.channel===e.dataset.fade);if(x)x.fade_seconds=Number(e.value)});await api('/config',{method:'PATCH',body:JSON.stringify({channels:c})});await refresh()}document.querySelector('form').onsubmit=async e=>{e.preventDefault();try{let r=await api('/login',{method:'POST',body:JSON.stringify({username:$('u').value,password:$('p').value})});csrf=r.csrf;await refresh()}catch(x){$('le').textContent=x.message}};document.addEventListener('change',e=>{if(e.target.matches('[data-lock],[data-light],[data-max],[data-fade]'))save().catch(x=>$('err').textContent=x.message)});document.addEventListener('blur',e=>{if(e.target.matches('[data-name]'))save().catch(x=>$('err').textContent=x.message)},true);</script></html>"""

DYNAMIC_SCRIPT = r"""<script>
function renderRoleInterface(config, health){
  const role=config.role||'UNASSIGNED', admin=config.user?.role==='ADMIN', channels=config.channels||[];
  if(role==='UNASSIGNED'||role==='SIM'){
    const identity=health?.identity||{};
    $('channels').innerHTML=`<div class=box><b>${role==='SIM'?'SIM dashboard':'Unassigned module'}</b><br><span class=muted>Role: ${esc(role)} · Device: ${esc(identity.device_id||'Unknown')} · Simulation: ${identity.simulation===true?'Enabled':'Unknown'} · Physical outputs: ${identity.physical_outputs_enabled===false?'Disabled':'Unknown'}</span><p class=muted>${role==='SIM'?'No output controls are exposed for this simulation role.':'Assign an operational role through authenticated HCM administration before configuring outputs.'}</p></div>`;return}
  const groups=role==='RCM'?[['Relays',channels]]:[['Relays',channels.filter(x=>x.type==='Relay')],['0-10V dimmers',channels.filter(x=>x.type==='0-10V')],['110V dimmers',channels.filter(x=>x.type==='110V')]];
  $('channels').innerHTML=groups.map(([title,items])=>`<div><h3>${title} <span class=meta>${items.length}</span></h3>${items.map(x=>`<article class=channel><b>${esc(x.name)||'Unnamed'}</b><div class=meta>${esc(x.channel)} · ${esc(x.type||'Relay')} · ${x.lockout?'Maintenance locked':'Available'}</div><label class=meta>Name <input data-name=${esc(x.channel)} value="${esc(x.name)}" ${admin?'':'disabled'}></label><label class=meta><input type=checkbox data-lock=${esc(x.channel)} ${x.lockout?'checked':''} ${admin?'':'disabled'}> Lockout</label>${role==='LCM'?`<label class=meta><input type=checkbox data-light=${esc(x.channel)} ${x.emergency_lighting?'checked':''} ${admin?'':'disabled'}> eLight</label>${x.type!=='Relay'?`<label class=meta>Max brightness <input type=number min=0 max=100 data-max=${esc(x.channel)} value=${x.max_intensity??''} ${admin?'':'disabled'}></label><label class=meta>Fade seconds <input type=number min=0 max=3600 step=.1 data-fade=${esc(x.channel)} value=${x.fade_seconds??3} ${admin?'':'disabled'}></label>`:''}`:''}<div class=meta>Simulated state: Unknown</div></article>`).join('')}</div>`).join('');
}
async function dynamicRefresh(){let [h,c]=await Promise.all([fetch('/health').then(r=>r.json()),api('/config')]);let i=h.identity||{};let vals=[['Device',i.device_id],['Role',c.role||i.role],['Simulation',i.simulation===true?'Enabled':'Unknown'],['Physical outputs',i.physical_outputs_enabled===false?'Disabled':'Unknown'],['HCM heartbeat',h.hcm_heartbeat_health?.connected?'Connected':'Offline'],['Config sync',c.config_sync?.state||'Unknown'],['Faults',(h.active_faults||[]).length],['Pending logs',h.pending_hcm_log_delivery_count??'Unknown']];$('status').innerHTML=vals.map(x=>`<div class=box><b>${esc(x[0])}</b><br><span class=muted>${esc(x[1])}</span></div>`).join('');renderRoleInterface(c,h);$('app').hidden=false;$('login').hidden=true}
async function dynamicSave(){let c=(await api('/config')).channels||[];document.querySelectorAll('[data-name]').forEach(e=>{let x=c.find(x=>x.channel===e.dataset.name);if(x)x.name=e.value});document.querySelectorAll('[data-lock]').forEach(e=>{let x=c.find(x=>x.channel===e.dataset.lock);if(x)x.lockout=e.checked});document.querySelectorAll('[data-light]').forEach(e=>{let x=c.find(x=>x.channel===e.dataset.light);if(x)x.emergency_lighting=e.checked});document.querySelectorAll('[data-max]').forEach(e=>{let x=c.find(x=>x.channel===e.dataset.max);if(x)x.max_intensity=Number(e.value)});document.querySelectorAll('[data-fade]').forEach(e=>{let x=c.find(x=>x.channel===e.dataset.fade);if(x)x.fade_seconds=Number(e.value)});await api('/config',{method:'PATCH',body:JSON.stringify({channels:c})});await dynamicRefresh()}
refresh=dynamicRefresh;save=dynamicSave;dynamicRefresh().catch(()=>{});
</script>"""

def state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except (OSError, ValueError):
        return {}

def audit(action: str, user: str) -> None:
    record = LOGGER.log(component='local_emergency_config', category='config', severity='info', code=action, message=action, metadata={'actor': user})
    if record:
        QUEUE.enqueue(record)

def active_role() -> str:
    role = str(state().get('role') or 'UNASSIGNED').upper()
    return role if role in {'RCM', 'LCM', 'SIM', 'UNASSIGNED'} else 'UNASSIGNED'

def role_store(role: str):
    return infra.LocalConfigStore(RUNTIME_ROOT, role, 'lab1')

def role_config(role: str) -> dict:
    store = role_store(role)
    if role == 'RCM':
        channels = store.load_rcm_csv()
        return {'channels': channels or infra.default_rcm_config()}
    if role == 'LCM':
        channels = store.load_lcm_csv()
        return {'channels': channels or infra.default_lcm_channels()}
    return store.load_json()

def health() -> dict:
    current = state(); role = active_role(); saved = role_config(role)
    return {'module_type': role, 'identity': {**current, 'role': role, 'simulation': current.get('simulation') is True, 'physical_outputs_enabled': current.get('physical_outputs_enabled') is True}, 'software_version':'lab1-emergency-ui', 'uptime_seconds':0, 'hcm_heartbeat_health':{'connected':False,'last_valid_ack_ts':None,'ack_current':False}, 'component_health':{'simulation_only':[{'name':f'{role or "module"} outputs','status':'simulation_only','ok':True}]}, 'active_faults':[], 'local_configuration_revision':saved.get('revision'),'config_sync':saved.get('config_sync',{'state':'local_only'}),'pending_hcm_log_delivery_count':QUEUE.count(),'recent_logs':LOGGER.recent(limit=20)}

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def send_json(self, data, code=200):
        raw=json.dumps(data).encode(); self.send_response(code); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def body(self):
        length=int(self.headers.get('Content-Length','0')); return json.loads(self.rfile.read(length) or b'{}')
    def token(self): return parse_qs(self.headers.get('Cookie','').replace('; ','&')).get('homecontrol_local_session',[None])[0]
    def user(self):
        return AUTH.session(self.token())
    def do_GET(self):
        path=urlparse(self.path).path
        if path=='/':
            raw=HTML.replace('</html>', DYNAMIC_SCRIPT+'</html>').encode(); self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw); return
        if path=='/health': self.send_json(health()); return
        if path=='/config':
            user=self.user()
            if not user: self.send_json({'detail':'local administrator login required'},401); return
            role=active_role(); saved=role_config(role)
            self.send_json({'identity':{**state(),'role':role},'module_type':role,'role':role,'channels':saved.get('channels',[]),'config_sync':saved.get('config_sync',{'state':'local_only'}),'user':{'username':user['username'],'role':user['role']}}); return
        self.send_json({'detail':'not found'},404)
    def do_POST(self):
        path=urlparse(self.path).path
        if path=='/login':
            body=self.body(); user=AUTH.authenticate(str(body.get('username','')),str(body.get('password','')))
            if not user: self.send_json({'detail':'invalid local credentials'},401); return
            token=user['token']; raw=json.dumps({'ok':True,'csrf':user['csrf'],'username':user['username'],'role':user['role']}).encode(); self.send_response(200); self.send_header('Set-Cookie',f'homecontrol_local_session={token}; HttpOnly; SameSite=Strict; Path=/'); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw); return
        if path=='/logout':
            token=self.token()
            if token: AUTH.sessions.pop(token, None)
            self.send_response(204); self.send_header('Set-Cookie','homecontrol_local_session=; Max-Age=0; HttpOnly; SameSite=Strict; Path=/'); self.end_headers(); return
        self.send_json({'detail':'not found'},404)
    def do_PATCH(self):
        if urlparse(self.path).path!='/config': self.send_json({'detail':'not found'},404); return
        user=self.user(); body=self.body()
        if not user: self.send_json({'detail':'local login required'},401); return
        if user.get('role') != 'ADMIN': self.send_json({'detail':'administrator role required'},403); return
        if not AUTH.require_csrf(self.token(),self.headers.get('X-CSRF-Token')): self.send_json({'detail':'csrf validation failed'},403); return
        role=active_role(); channels=body.get('channels')
        if not isinstance(channels,list): self.send_json({'detail':'channels must be a list'},400); return
        try:
            if role == 'RCM': csv_result=role_store(role).save_rcm_csv(channels)
            elif role == 'LCM': csv_result=role_store(role).save_lcm_csv(channels)
            else: self.send_json({'detail':'configuration is unavailable for this role'},409); return
        except (TypeError,ValueError,KeyError) as exc: self.send_json({'detail':str(exc)},400); return
        sync=__import__('lab1_user_sync').queue_local_config_update(role, channels, user['username']); audit('local_config_edit',user['username']); self.send_json({'ok':True,'revision':sync['revision'],'csv':csv_result,'config_sync':sync})

def main():
    RUNTIME_ROOT.mkdir(parents=True,exist_ok=True); http.server.ThreadingHTTPServer(('0.0.0.0',6010),Handler).serve_forever()

if __name__=='__main__': main()
