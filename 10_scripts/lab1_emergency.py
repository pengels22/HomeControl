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
STORE = infra.LocalConfigStore(RUNTIME_ROOT, 'LCM', 'lab1')
AUTH = infra.LocalAuthStore(RUNTIME_ROOT / 'config' / 'LCM' / 'lab1.auth.json')
LOGGER = infra.StructuredEventLogger('lab1', RUNTIME_ROOT / 'logs' / 'lab1')
QUEUE = infra.OfflineEventQueue(RUNTIME_ROOT / 'logs' / 'lab1' / 'pending-events.json')
SESSIONS: dict[str, dict] = {}

HTML = """<!doctype html><html lang=en><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>LAB1 emergency configuration</title>
<style>body{margin:auto;max-width:1180px;padding:20px;background:#101214;color:#f4f2ec;font:15px system-ui}section{background:#181c1f;border:1px solid #30383b;border-radius:8px;padding:14px;margin:12px 0}.cols{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.channel{border-bottom:1px solid #30383b;padding:10px 0}.meta{color:#9da7a3;font-size:12px}input,button{font:inherit;padding:9px;border-radius:6px}input{background:#121517;color:#fff;border:1px solid #566168}button{background:#347d68;color:white;border:0;cursor:pointer;min-height:42px}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:8px}.box{background:#121517;padding:8px;border-radius:6px}.muted{color:#9da7a3}.error{color:#ffb7ad}@media(max-width:850px){.cols{grid-template-columns:repeat(2,1fr)}}@media(max-width:560px){.cols,.grid{grid-template-columns:1fr}}</style>
<main><header><h1>LAB1 emergency configuration</h1><p class=muted>Local administrator access. Simulation only; physical output state is not confirmed.</p></header><section id=login><h2>Local administrator sign in</h2><form><input id=u autocomplete=username placeholder=Username required><input id=p type=password autocomplete=current-password placeholder=Password required><button>Sign in</button></form><p id=le class=error></p></section><div id=app hidden><section><h2>Module status</h2><div id=status class=grid></div><p id=err class=error></p></section><section><h2>Channel configuration</h2><p class=muted>Edits are stored in the local LCM CSV and reconciled with HCM when available.</p><div id=channels class=cols></div></section></div></main>
<script>let csrf='';const $=x=>document.getElementById(x);async function api(path,opt={}){opt.headers={'Content-Type':'application/json','X-CSRF-Token':csrf,...(opt.headers||{})};let r=await fetch(path,opt),j=await r.json();if(!r.ok)throw Error(j.detail||'Request failed');return j}function esc(x){return String(x??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&#39;'}[c]))}function draw(c){let groups=[['Relays',c.filter(x=>x.type==='Relay')],['0-10V dimmers',c.filter(x=>x.type==='0-10V')],['110V dimmers',c.filter(x=>x.type==='110V')]];$('channels').innerHTML=groups.map(([title,a])=>`<div><h3>${title} <span class=meta>${a.length}</span></h3>${a.map(x=>`<article class=channel><b>${esc(x.name)||'Unnamed'}</b><div class=meta>${esc(x.channel)} · ${esc(x.type)} · ${x.lockout?'Maintenance locked':'Available'}</div><label class=meta>Name <input data-name=${esc(x.channel)} value="${esc(x.name)}"></label><label class=meta><input type=checkbox data-lock=${esc(x.channel)} ${x.lockout?'checked':''}> Lockout</label><label class=meta><input type=checkbox data-light=${esc(x.channel)} ${x.emergency_lighting?'checked':''}> eLight</label>${x.type!=='Relay'?`<label class=meta>Max brightness <input type=number min=0 max=100 data-max=${esc(x.channel)} value=${x.max_intensity??''}></label><label class=meta>Fade seconds <input type=number min=0 max=3600 step=.1 data-fade=${esc(x.channel)} value=${x.fade_seconds??3}></label>`:''}<div class=meta>Simulated state: Unknown</div></article>`).join('')}</div>`).join('')}async function refresh(){let [h,c]=await Promise.all([fetch('/health').then(r=>r.json()),api('/config')]);let i=h.identity||{};let vals=[['Device',i.device_id],['Role',i.role],['Simulation',i.simulation?'Enabled':'Unknown'],['Physical outputs',i.physical_outputs_enabled===false?'Disabled':'Unknown'],['HCM heartbeat',h.hcm_heartbeat_health?.connected?'Connected':'Offline'],['Config sync',c.config_sync?.state||'Unknown'],['Faults',(h.active_faults||[]).length],['Pending logs',h.pending_hcm_log_delivery_count??'Unknown']];$('status').innerHTML=vals.map(x=>`<div class=box><b>${esc(x[0])}</b><br><span class=muted>${esc(x[1])}</span></div>`).join('');draw(c.channels||[]);$('app').hidden=false;$('login').hidden=true}async function save(){let c=(await api('/config')).channels||[];document.querySelectorAll('[data-name]').forEach(e=>{let x=c.find(x=>x.channel===e.dataset.name);if(x)x.name=e.value});document.querySelectorAll('[data-lock]').forEach(e=>{let x=c.find(x=>x.channel===e.dataset.lock);if(x)x.lockout=e.checked});document.querySelectorAll('[data-light]').forEach(e=>{let x=c.find(x=>x.channel===e.dataset.light);if(x)x.emergency_lighting=e.checked});document.querySelectorAll('[data-max]').forEach(e=>{let x=c.find(x=>x.channel===e.dataset.max);if(x)x.max_intensity=Number(e.value)});document.querySelectorAll('[data-fade]').forEach(e=>{let x=c.find(x=>x.channel===e.dataset.fade);if(x)x.fade_seconds=Number(e.value)});await api('/config',{method:'PATCH',body:JSON.stringify({channels:c})});await refresh()}document.querySelector('form').onsubmit=async e=>{e.preventDefault();try{let r=await api('/login',{method:'POST',body:JSON.stringify({username:$('u').value,password:$('p').value})});csrf=r.csrf;await refresh()}catch(x){$('le').textContent=x.message}};document.addEventListener('change',e=>{if(e.target.matches('[data-lock],[data-light],[data-max],[data-fade]'))save().catch(x=>$('err').textContent=x.message)});document.addEventListener('blur',e=>{if(e.target.matches('[data-name]'))save().catch(x=>$('err').textContent=x.message)},true);</script></html>"""

def state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except (OSError, ValueError):
        return {}

def audit(action: str, user: str) -> None:
    record = LOGGER.log(component='local_emergency_config', category='config', severity='info', code=action, message=action, metadata={'actor': user})
    if record:
        QUEUE.enqueue(record)

def health() -> dict:
    current = state(); saved = STORE.load_json()
    return {'module_type':'LCM','identity':{**current,'role':current.get('role','UNASSIGNED'),'simulation':current.get('simulation') is True,'physical_outputs_enabled':current.get('physical_outputs_enabled') is True},'software_version':'lab1-emergency-ui','uptime_seconds':0,'hcm_heartbeat_health':{'connected':False,'last_valid_ack_ts':None,'ack_current':False},'component_health':{'simulated':[{'name':'LCM outputs','status':'simulation_only','ok':True}]},'active_faults':[],'local_configuration_revision':saved.get('revision'),'config_sync':saved.get('config_sync',{'state':'local_only'}),'pending_hcm_log_delivery_count':QUEUE.count(),'recent_logs':LOGGER.recent(limit=20)}

class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_): pass
    def send_json(self, data, code=200):
        raw=json.dumps(data).encode(); self.send_response(code); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def body(self):
        length=int(self.headers.get('Content-Length','0')); return json.loads(self.rfile.read(length) or b'{}')
    def token(self): return parse_qs(self.headers.get('Cookie','').replace('; ','&')).get('homecontrol_local_session',[None])[0]
    def user(self):
        token=self.token(); user=SESSIONS.get(token)
        if user and user['expires_at'] <= time.time(): SESSIONS.pop(token,None); return None
        return user
    def do_GET(self):
        path=urlparse(self.path).path
        if path=='/':
            raw=HTML.encode(); self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw); return
        if path=='/health': self.send_json(health()); return
        if path=='/config':
            user=self.user()
            if not user: self.send_json({'detail':'local administrator login required'},401); return
            self.send_json({'identity':state(),'module_type':'LCM','channels':STORE.load_lcm_csv(),'config_sync':STORE.load_json().get('config_sync',{'state':'local_only'}),'user':{'username':user['username'],'role':user['role']}}); return
        self.send_json({'detail':'not found'},404)
    def do_POST(self):
        path=urlparse(self.path).path
        if path=='/login':
            body=self.body(); user=AUTH.authenticate(str(body.get('username','')),str(body.get('password','')))
            if not user: self.send_json({'detail':'invalid local credentials'},401); return
            token=secrets.token_urlsafe(32); csrf=secrets.token_urlsafe(32); SESSIONS[token]={**user,'token':token,'csrf':csrf,'expires_at':time.time()+1800}; raw=json.dumps({'ok':True,'csrf':csrf}).encode(); self.send_response(200); self.send_header('Set-Cookie',f'homecontrol_local_session={token}; HttpOnly; SameSite=Strict; Path=/'); self.send_header('Content-Type','application/json'); self.send_header('Content-Length',str(len(raw))); self.end_headers(); self.wfile.write(raw); return
        if path=='/logout': self.send_response(204); self.end_headers(); return
        self.send_json({'detail':'not found'},404)
    def do_PATCH(self):
        if urlparse(self.path).path!='/config': self.send_json({'detail':'not found'},404); return
        user=self.user(); body=self.body()
        if not user: self.send_json({'detail':'local administrator login required'},401); return
        if not AUTH.require_csrf(self.token(),self.headers.get('X-CSRF-Token')): self.send_json({'detail':'csrf validation failed'},403); return
        channels=body.get('channels')
        if not isinstance(channels,list): self.send_json({'detail':'channels must be a list'},400); return
        try: csv_result=STORE.save_lcm_csv(channels)
        except (TypeError,ValueError,KeyError) as exc: self.send_json({'detail':str(exc)},400); return
        saved=STORE.save_json({'config':{'channels':channels},'config_sync':{'state':'local_changes_pending_hcm_reconciliation'},'local_edit_by':user['username']}); audit('local_config_edit',user['username']); self.send_json({'ok':True,'revision':saved['revision'],'csv':csv_result})

def main():
    RUNTIME_ROOT.mkdir(parents=True,exist_ok=True); http.server.ThreadingHTTPServer(('0.0.0.0',6010),Handler).serve_forever()

if __name__=='__main__': main()
