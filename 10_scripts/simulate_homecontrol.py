#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import math
import sys
import time
from contextlib import asynccontextmanager
from importlib import import_module
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

common_can = import_module("07_servises.common.can")
common_cfg = import_module("07_servises.common.config")
common_pairing = import_module("07_servises.common.pairing_glyph")
hvac_mod = import_module("01_HCM.hvac")
lcm_mod = import_module("03_LCM.main")
rcm_mod = import_module("04_RCM.main")
sim_mod = import_module("02_SIM.main")
pnl_mod = import_module("05_PNL.main")


def cfg(path: str) -> dict[str, Any]:
    data = common_cfg.load_yaml(ROOT / path)
    data["hcm_host"] = "127.0.0.1"
    data["dev_mode"] = True
    data.setdefault("web", {})["enabled"] = False
    return data


class HomeControlSimulator:
    def __init__(self):
        self.rcm = rcm_mod.RCMAgent(cfg("06_config/04_RCM/rcm.yaml"))
        self.lcm = lcm_mod.LCMAgent(cfg("06_config/03_LCM/lcm.yaml"))
        self.sim = sim_mod.SIMAgent(cfg("06_config/02_SIM/sim.yaml"))
        self.pnl = pnl_mod.PNLAgent(cfg("06_config/05_PNL/pnl.yaml"))
        self.rcm_locks = {f"{bank}{ch}": False for bank in "ABCD" for ch in range(1, 9)}
        self.rcm_names = {f"{bank}{ch}": f"Relay {bank}{ch}" for bank in "ABCD" for ch in range(1, 9)}
        self.lcm_fades: dict[str, asyncio.Task] = {}
        self.lcm_names = self.default_lcm_names()
        self.pairing_code = "482913"
        self.hvac_events: list[dict[str, Any]] = []
        self.hvac = hvac_mod.HVACController(self.hvac_output, self.hvac_damper)
        self.hvac.DAMPER_LEAD_S = 0
        self.hvac.FAN_LEAD_S = 0
        self.hvac.RESTART_LOCKOUT_S = 0
        self.hvac.state.mode = hvac_mod.Mode.OFF
        self.hvac.state.setpoint_f = 70
        self.hvac.rooms = {
            "Office": hvac_mod.RoomReading("Office", 72, True, False),
            "Kitchen": hvac_mod.RoomReading("Kitchen", 71, True, True, "Kitchen Damper"),
        }
        self.started_at = time.time()
        self.running = True

    async def hvac_output(self, name: str, value: bool) -> None:
        relay = {"FAN": "A1", "COOL": "A2", "HEAT": "A3"}[name]
        await self.rcm.apply_command({"op": "set_relay", "channel": relay, "value": value})
        self.hvac_events.append({"ts": time.time(), "type": "output", "name": name, "value": value, "relay": relay})

    async def hvac_damper(self, room, open_: bool) -> None:
        relay = "A4"
        await self.rcm.apply_command({"op": "set_relay", "channel": relay, "value": not open_})
        self.hvac_events.append({"ts": time.time(), "type": "damper", "room": room.room, "open": open_, "relay": relay})

    def hvac_state(self) -> dict[str, Any]:
        s = self.hvac.state
        return {
            "mode": s.mode.value,
            "setpoint_f": s.setpoint_f,
            "average_f": self.hvac.average_temperature(),
            "fan": s.fan,
            "heat": s.heat,
            "cool": s.cool,
            "rooms": {name: room.__dict__ for name, room in self.hvac.rooms.items()},
            "events": self.hvac_events[-20:],
        }

    async def state(self) -> dict[str, Any]:
        rcm_state = await self.rcm.collect_state()
        rcm_state["locks"] = dict(self.rcm_locks)
        rcm_state["names"] = dict(self.rcm_names)
        lcm_state = await self.lcm.collect_state()
        lcm_state["names"] = dict(self.lcm_names)
        return {
            "uptime_s": round(time.time() - self.started_at, 1),
            "devices": self.devices(),
            "hcm": {"hvac": self.hvac_state(), "pairing": self.pairing_glyph()},
            "rcm": rcm_state,
            "lcm": lcm_state,
            "sim": await self.sim.collect_state(),
            "pnl": await self.pnl.collect_state(),
        }

    def devices(self) -> list[dict[str, str]]:
        return [
            {"type": "HCM", "id": "HCM01", "label": "House Control Module"},
            {"type": "RCM", "id": "RCM01", "label": "Relay Control Module"},
            {"type": "LCM", "id": "LCM01", "label": "Lighting Control Module"},
            {"type": "SIM", "id": "SIM01", "label": "Sensor Interface Module"},
            {"type": "PNL", "id": "PNL01", "label": "Panel"},
        ]

    def pairing_glyph(self) -> dict[str, Any]:
        glyph = common_pairing.encode_pairing_glyph("HCM01", self.pairing_code)
        return {
            "format": "HC-CIRCULAR-PAIR-1",
            "payload": glyph.payload,
            "code": glyph.code,
            "size": glyph.size,
            "matrix": glyph.matrix,
        }

    async def set_rcm_relay(self, channel: str, value: bool) -> dict[str, Any]:
        ch = channel.upper()
        if self.rcm_locks.get(ch):
            return {"ok": False, "locked": True, "channel": ch}
        return await self.rcm.apply_command({"op": "set_relay", "channel": ch, "value": value})

    def set_rcm_name(self, channel: str, name: str) -> dict[str, Any]:
        ch = channel.upper()
        if ch not in self.rcm_names:
            raise KeyError(ch)
        clean = str(name).strip()[:80] or ch
        self.rcm_names[ch] = clean
        return {"ok": True, "channel": ch, "name": clean}

    def lcm_dimmer_percent(self, channel: str) -> float:
        ch = channel.upper()
        state = self.lcm.hv_dimmers.snapshot() | self.lcm.lv_dimmers.snapshot()
        if ch not in state:
            raise KeyError(ch)
        return float(state[ch]["percent"])

    async def _fade_lcm_dimmer(self, channel: str, target: float, duration_s: float = 3.0, steps: int = 30) -> None:
        start = self.lcm_dimmer_percent(channel)
        clipped = max(0.0, min(100.0, float(target)))
        interval = duration_s / max(1, steps)
        try:
            for step in range(1, steps + 1):
                pct = start + (clipped - start) * step / steps
                await self.lcm.apply_command({"op": "set_dimmer", "channel": channel, "percent": pct})
                await asyncio.sleep(interval)
            await self.lcm.apply_command({"op": "set_dimmer", "channel": channel, "percent": clipped})
        finally:
            if self.lcm_fades.get(channel) is asyncio.current_task():
                self.lcm_fades.pop(channel, None)

    async def set_lcm_relay(self, channel: str, value: bool) -> dict[str, Any]:
        return await self.lcm.apply_command({"op": "set_relay", "channel": channel.upper(), "value": value})

    def default_lcm_names(self) -> dict[str, str]:
        names = {f"A{i}": f"Relay A{i}" for i in range(1, 9)}
        names.update({f"B{i}": f"Relay B{i}" for i in range(1, 5)})
        names.update({f"HV-{i}": f"Shelly dimmer {i}" for i in range(1, 5)})
        names.update({f"10-{i}": f"0-10 V output {i}" for i in range(1, 9)})
        return names

    def set_lcm_name(self, channel: str, name: str) -> dict[str, Any]:
        ch = channel.upper()
        if ch not in self.lcm_names:
            raise KeyError(ch)
        clean = str(name).strip()[:80] or ch
        self.lcm_names[ch] = clean
        return {"ok": True, "channel": ch, "name": clean}

    async def set_lcm_dimmer_fade(
        self,
        channel: str,
        percent: float,
        duration_s: float = 3.0,
        steps: int = 30,
    ) -> dict[str, Any]:
        ch = channel.upper()
        self.lcm_dimmer_percent(ch)
        existing = self.lcm_fades.get(ch)
        if existing:
            existing.cancel()
        task = asyncio.create_task(self._fade_lcm_dimmer(ch, percent, duration_s, steps))
        self.lcm_fades[ch] = task
        return {"ok": True, "channel": ch, "target_percent": max(0.0, min(100.0, float(percent))), "fade_s": duration_s}

    async def tick_rmc(self) -> dict[str, Any]:
        t = time.time() - self.started_at
        address = int(t // 5) % 4
        arbitration_id, data = common_can.encode_rmc_telemetry(
            address,
            presence=(int(t) // 6) % 2 == 0,
            temperature_c=21 + round(math.sin(t / 18.0) * 2),
            humidity_pct=45 + round(math.sin(t / 22.0) * 5),
            lux=350 + round(math.sin(t / 12.0) * 120),
            aqi=2,
            healthy=True,
        )
        return await self.sim.apply_command({
            "op": "inject_can_frame",
            "interface": "can0",
            "arbitration_id": arbitration_id,
            "data": data,
        })

    async def loop(self) -> None:
        while self.running:
            await self.tick_rmc()
            await asyncio.sleep(2)


sim = HomeControlSimulator()

@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.sim_task = asyncio.create_task(sim.loop())
    try:
        yield
    finally:
        sim.running = False
        app.state.sim_task.cancel()


app = FastAPI(title="HomeControl Simulator", version="0.1.0", lifespan=lifespan)


@app.get("/", response_class=HTMLResponse)
async def index():
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>HomeControl Simulator</title>
  <style>
    body{margin:0;background:#101214;color:#f4f2ec;font-family:system-ui,-apple-system,Segoe UI,sans-serif}
    main{width:min(1260px,calc(100% - 32px));margin:0 auto;padding:24px 0}
    h1{margin:0 0 4px;font-size:1.7rem} h2{margin:0 0 12px;font-size:1.05rem} h3{margin:18px 0 8px;font-size:.95rem;color:#cbd4cf} p{margin:0;color:#aab2ae}
    section,.panel{border:1px solid #2b3035;background:#181c1f;border-radius:8px;padding:16px}
    section{margin:12px 0}
    button,input,select{font:inherit;padding:.55rem;border-radius:6px}
    button{border:0;background:#2f7d68;color:white;cursor:pointer}
    button.secondary{background:#363b3f} button.warn{background:#7d5c2f} button.locked{background:#73515b}
    button:disabled{opacity:.45;cursor:not-allowed}
    input,select{border:1px solid #555d64;background:#171a1d;color:#f4f2ec}
    input[type=range]{width:100%;min-width:0;padding:0;border:0;background:transparent;accent-color:#2f7d68;cursor:pointer}
    .tabs{display:flex;gap:8px;flex-wrap:wrap;margin:18px 0 12px}
    .tabs button{background:#242a2e}.tabs button.active{background:#2f7d68}
    .layout{display:grid;grid-template-columns:280px 1fr;gap:14px;align-items:start}
    .nav button{width:100%;text-align:left;margin:4px 0;background:#242a2e}
    .nav button.active{background:#2f7d68}
    .status-grid{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}
    .metric{background:#111417;border:1px solid #2b3035;border-radius:6px;padding:12px}
    .metric span{display:block;color:#aab2ae;font-size:.85rem}.metric strong{display:block;font-size:1.25rem;margin-top:4px}
    .row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
    .channel-grid{display:grid;grid-template-columns:repeat(4,minmax(180px,1fr));gap:8px}
    .dimmer-grid{grid-template-columns:repeat(3,minmax(240px,1fr))}
    .channel{display:grid;grid-template-columns:52px 1fr 66px;gap:8px;align-items:center;background:#111417;border:1px solid #2b3035;border-radius:6px;padding:8px}
    .lcm-channel{grid-template-columns:54px 1fr 76px}
    .lcm-dimmer{grid-template-columns:54px minmax(130px,1fr) 54px}
    .name-input{grid-column:1 / -1;padding:.45rem}
    .channel .on{color:#8ee0be}.channel .off{color:#aab2ae}.channel .locked-label{color:#ffca8a}
    .screen-wrap{display:grid;grid-template-columns:minmax(260px,380px) 1fr;gap:16px;align-items:start;margin-top:14px}
    .screen-bezel{background:#050607;border:1px solid #32383d;border-radius:8px;padding:12px;box-shadow:inset 0 0 0 2px #0c0f11}
    .screen{aspect-ratio:4/3;background:#d8ecdf;color:#17201b;border-radius:4px;padding:12px;display:grid;grid-template-rows:auto 1fr auto;gap:10px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
    .screen-top,.screen-bottom{display:flex;justify-content:space-between;align-items:center;font-size:.78rem}
    .screen-title{font-weight:700;font-size:1.05rem}
    .screen-grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
    .screen-tile{border:1px solid rgba(23,32,27,.35);border-radius:4px;padding:8px;background:rgba(255,255,255,.28)}
    .screen-tile span{display:block;font-size:.68rem;color:#415047}.screen-tile strong{display:block;font-size:1rem;margin-top:2px}
    .screen-actions{display:grid;grid-template-columns:repeat(3,1fr);gap:6px}
    .screen-action{border:1px solid rgba(23,32,27,.35);border-radius:4px;padding:6px;text-align:center;font-size:.68rem;background:rgba(255,255,255,.24)}
    .pairing-screen{background:#080d0b;color:#ecfff4;place-items:center;text-align:center;overflow:hidden;position:relative}
    .pairing-screen:before{content:"";position:absolute;inset:-20%;background:radial-gradient(circle at 50% 45%,rgba(68,197,137,.24),transparent 36%),radial-gradient(circle at 35% 70%,rgba(141,229,186,.12),transparent 28%);animation:pairGlow 5s ease-in-out infinite alternate}
    .pairing-content{position:relative;z-index:1;display:grid;gap:9px;justify-items:center}
    .pair-code-glyph{width:136px;height:136px;border-radius:50%;display:grid;grid-template-columns:repeat(17,1fr);grid-template-rows:repeat(17,1fr);gap:2px;padding:10px;background:radial-gradient(circle,rgba(236,255,244,.08),rgba(68,197,137,.04));box-shadow:0 0 0 1px rgba(236,255,244,.22),0 0 34px rgba(68,197,137,.35);animation:pairBreathe 3.5s ease-in-out infinite}
    .pair-dot{border-radius:2px;background:transparent;opacity:0}
    .pair-dot.on{background:#ecfff4;box-shadow:0 0 6px rgba(236,255,244,.55);opacity:.95;animation:pairTwinkle 3.2s ease-in-out infinite}
    .pair-dot.soft{background:#8de5ba;opacity:.42}
    .pair-dot.eye{border-radius:3px;background:#ecfff4;box-shadow:0 0 10px rgba(236,255,244,.65);opacity:1}
    .pair-title{font-weight:700;letter-spacing:.08em;font-size:.74rem}.pair-code{font-size:1.02rem;font-weight:700;letter-spacing:.08em}.pair-help{font-size:.62rem;color:#a7d8bf}
    @keyframes pairBreathe{0%,100%{transform:scale(.985);filter:saturate(.9)}50%{transform:scale(1.015);filter:saturate(1.25)}}
    @keyframes pairTwinkle{0%,100%{opacity:.72}50%{opacity:1}}
    @keyframes pairGlow{from{transform:translate3d(-2%,0,0)}to{transform:translate3d(2%,1%,0)}}
    .led-row{display:flex;gap:8px;margin-top:10px}.led{width:10px;height:10px;border-radius:50%;background:#3c4441}.led.on{background:#44c589}.led.warn{background:#d99b43}
    .kv{display:grid;grid-template-columns:180px 1fr;gap:8px;padding:7px 0;border-bottom:1px solid #2b3035}
    .kv span:first-child{color:#aab2ae}
    .muted{color:#aab2ae}
    pre{overflow:auto;background:#0f1113;border:1px solid #2b3035;border-radius:6px;padding:12px}
    @media(max-width:900px){.layout{grid-template-columns:1fr}.status-grid{grid-template-columns:1fr 1fr}.channel-grid{grid-template-columns:1fr}}
  </style>
</head>
<body>
<main>
  <h1>HomeControl Simulator</h1>
  <p>Same workflows as a real controller, running against simulated IO on this Mac.</p>

  <nav class="tabs" id="tabs"></nav>
  <div id="tabContent"></div>
</main>
<script>
let appState=null;
let selectedTab='dashboard';
let selectedDevice='HCM:HCM01';
let editingName=false;
let slidingDimmer=false;
let pendingDimmerTargets={};
async function post(path,body){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}); if(!r.ok) throw new Error(await r.text()); await refresh()}
async function postNoRefresh(path,body){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}); if(!r.ok) throw new Error(await r.text()); return await r.json()}
async function refresh(){
  const r=await fetch('/api/state');
  appState=await r.json();
  reconcilePendingDimmers();
  if(!editingName && !slidingDimmer) render();
}
function reconcilePendingDimmers(){
  if(!appState?.lcm) return;
  const dimmers={...appState.lcm.hv_dimmers,...appState.lcm.lv_dimmers};
  for(const [ch,target] of Object.entries(pendingDimmerTargets)){
    if(dimmers[ch] && Math.round(dimmers[ch].percent)===Number(target)) delete pendingDimmerTargets[ch];
  }
}
function esc(value){return String(value ?? '').replace(/[&<>"']/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function pick(type,id){selectedDevice=`${type}:${id}`; render()}
function tab(name){selectedTab=name; render()}
function metric(label,value){return `<div class="metric"><span>${label}</span><strong>${value}</strong></div>`}
function render(){
  renderTabs();
  if(selectedTab==='devices') return renderDevicesTab();
  if(selectedTab==='service') return renderServiceTab();
  if(selectedTab==='settings') return renderSettingsTab();
  if(selectedTab==='users') return renderUsersTab();
  renderDashboard();
}
function renderTabs(){
  const items=[['dashboard','Dashboard'],['devices','Devices'],['service','Service'],['settings','Settings'],['users','Users']];
  tabs.innerHTML=items.map(([id,label])=>`<button class="${selectedTab===id?'active':''}" onclick="tab('${id}')">${label}</button>`).join('');
}
function renderDashboard(){
  const hvac=appState.hcm.hvac;
  const rmcCount=Object.keys(appState.sim.rmc_nodes).length;
  tabContent.innerHTML=`<section>
    <h2>Home Controller Simulator Status</h2>
    <p class="muted">Current state of the simulated HCM and connected modules.</p>
    <div class="status-grid" style="margin-top:14px">
      ${[
    metric('System uptime', `${appState.uptime_s}s`),
    metric('HVAC', `${hvac.mode} / ${hvac.setpoint_f}°F`),
    metric('House average', hvac.average_f==null ? '-' : `${hvac.average_f.toFixed(1)}°F`),
    metric('Active calls', ['fan','cool','heat'].filter(k=>hvac[k]).join(', ') || 'none'),
    metric('RCM relays on', Object.values(appState.rcm.relays).filter(Boolean).length),
    metric('LCM dimmers', Object.values(appState.lcm.lv_dimmers).filter(v=>v.percent>0).length + ' active'),
    metric('RMC nodes seen', rmcCount),
    metric('IO mode', appState.rcm.io_mode)
  ].join('')}
    </div>
    <div class="row" style="margin-top:14px">
      <select id="hvacMode"><option>OFF</option><option>HEAT</option><option>COOL</option><option>FAN</option></select>
      <input id="hvacSetpoint" type="number" min="45" max="90" value="70">
      <button onclick="applyHvac()">Apply HVAC</button>
      <button class="secondary" onclick="setRoomTemp(76)">Office Warm</button>
      <button class="secondary" onclick="setRoomTemp(66)">Office Cool</button>
    </div>
  </section>`;
  hvacMode.value=hvac.mode; hvacSetpoint.value=hvac.setpoint_f;
}
function renderDevicesTab(){
  tabContent.innerHTML=`<div class="layout">
    <section class="nav">
      <h2>Devices</h2>
      <p class="muted">Modules grouped by type and ID.</p>
      <div id="deviceNav" style="margin-top:12px"></div>
    </section>
    <section><div id="devicePage"></div></section>
  </div>`;
  renderNav();
  renderDevice();
}
function renderServiceTab(){
  tabContent.innerHTML=`<section>
    <h2>Service</h2>
    ${kv('Simulator process','Running')}
    ${kv('HCM API','Simulated locally')}
    ${kv('Module web auth','Delegates to HCM session model')}
    ${kv('SIM CAN backend',Object.keys(appState.sim.can).join(', '))}
    ${kv('RMC telemetry','Auto-injected every 2 seconds')}
    <h3>Recent HVAC Events</h3>
    <pre>${JSON.stringify(appState.hcm.hvac.events.slice(-10),null,2)}</pre>
  </section>`;
}
function renderSettingsTab(){
  tabContent.innerHTML=`<section>
    <h2>Settings</h2>
    ${kv('Global IO mode',appState.rcm.io_mode)}
    ${kv('RCM web port','8094')}
    ${kv('LCM web port','8093')}
    ${kv('SIM web port','8092')}
    ${kv('PNL web port','8095')}
    ${kv('LCM I2C bus',appState.lcm.i2c.bus)}
    ${kv('LCM mux address','0x'+appState.lcm.i2c.mux_address.toString(16))}
    ${kv('LCM DAC address','0x'+appState.lcm.i2c.dac_address.toString(16))}
  </section>`;
}
function renderUsersTab(){
  tabContent.innerHTML=`<section>
    <h2>Users</h2>
    <p class="muted">The simulator uses the HCM auth model. Production users are stored on HCM with hashed passwords.</p>
    ${kv('Current simulator user','local simulator')}
    ${kv('Session source','browser-local simulator session')}
    ${kv('Password storage','PBKDF2 hashes on HCM')}
  </section>`;
}
function renderNav(){
  const grouped={};
  for(const d of appState.devices){(grouped[d.type] ||= []).push(d)}
  deviceNav.innerHTML=Object.entries(grouped).map(([type,items])=>`
    <h3>${type}</h3>
    ${items.map(d=>`<button class="${selectedDevice===`${d.type}:${d.id}`?'active':''}" onclick="pick('${d.type}','${d.id}')">${d.id}<br><span class="muted">${d.label}</span></button>`).join('')}
  `).join('');
}
function kv(k,v){return `<div class="kv"><span>${k}</span><span>${v}</span></div>`}
function renderDevice(){
  const [type,id]=selectedDevice.split(':');
  if(type==='RCM') return renderRcm(id);
  if(type==='LCM') return renderLcm(id);
  if(type==='SIM') return renderSim(id);
  if(type==='PNL') return renderPnl(id);
  renderHcm(id);
}
function renderHcm(id){
  const hvac=appState.hcm.hvac;
  devicePage.innerHTML=`<h2>${id} Configuration</h2>
    ${kv('Role','Central authority')}
    ${kv('HVAC mode',hvac.mode)}
    ${kv('Setpoint',hvac.setpoint_f+'°F')}
    ${kv('Average temperature',hvac.average_f==null?'-':hvac.average_f.toFixed(1)+'°F')}
    ${kv('Rooms',Object.keys(hvac.rooms).join(', '))}
    <h3>3.3 Inch Local Screen</h3>
    ${screenMockup('hcm')}
    <h3>Recent HVAC Events</h3>
    <pre>${JSON.stringify(hvac.events.slice(-6),null,2)}</pre>`;
}
function renderRcm(id){
  const relays=appState.rcm.relays, locks=appState.rcm.locks || {}, names=appState.rcm.names || {};
  const channels=Object.keys(relays).sort((a,b)=>a.localeCompare(b,undefined,{numeric:true}));
  devicePage.innerHTML=`<h2>${id} Relay Configuration</h2>
    ${kv('Module type','RCM')}${kv('IO mode',appState.rcm.io_mode)}${kv('Channels','32')}
    <h3>Relay Channels</h3>
    <div class="channel-grid">${channels.map(ch=>{
      const locked=!!locks[ch], on=!!relays[ch];
      return `<div class="channel">
        <strong>${ch}</strong>
        <button ${locked?'disabled':''} onclick="toggleRelay('${ch}',${!on})" class="${on?'':'secondary'}">${on?'ON':'OFF'}</button>
        <button onclick="toggleLock('${ch}',${!locked})" class="${locked?'locked':'warn'}">${locked?'Locked':'Lock'}</button>
        ${nameInput(ch,names[ch],'rcm')}
      </div>`}).join('')}</div>`;
}
function renderLcm(id){
  const relays=appState.lcm.relays;
  const hv=appState.lcm.hv_dimmers;
  const lv=appState.lcm.lv_dimmers;
  const names=appState.lcm.names || {};
  const relayChannels=Object.keys(relays).sort((a,b)=>a.localeCompare(b,undefined,{numeric:true}));
  devicePage.innerHTML=`<h2>${id} Lighting Configuration</h2>
    ${kv('Module type','LCM')}${kv('IO mode',appState.lcm.i2c.io_mode)}${kv('HV dimmers','4 channels / 2 Shelly Dimmer Pro 2PM modules')}
    <h3>Relay Channels</h3>
    <div class="channel-grid">${relayChannels.map(ch=>{
      const on=!!relays[ch];
      return `<div class="channel lcm-channel">
        <strong>${ch}</strong>
        <button onclick="toggleLcmRelay('${ch}',${!on})" class="${on?'':'secondary'}">${on?'ON':'OFF'}</button>
        <span></span>
        ${nameInput(ch,names[ch],'lcm')}
      </div>`}).join('')}</div>
    <h3>High Voltage Dimmers</h3>
    <div class="channel-grid dimmer-grid">${Object.entries(hv).map(([ch,v])=>dimmerControl(ch,v,names[ch])).join('')}</div>
    <h3>0-10 V Outputs</h3>
    <div class="channel-grid dimmer-grid">${Object.entries(lv).map(([ch,v])=>dimmerControl(ch,v,names[ch])).join('')}</div>`;
}
function nameInput(ch,name,module='lcm'){
  const save=module==='rcm' ? 'saveRcmName' : 'saveLcmName';
  return `<input class="name-input" value="${esc(name || ch)}" onfocus="editingName=true" onblur="${save}('${ch}',this.value)">`;
}
function dimmerControl(ch,v,name){
  const pct=pendingDimmerTargets[ch] ?? Math.round(v.percent);
  return `<div class="channel lcm-dimmer">
    <strong>${ch}</strong>
    <input id="dim-${ch}" type="range" min="0" max="100" value="${pct}" onpointerdown="slidingDimmer=true" onpointerup="commitDimmer('${ch}',this.value)" onpointercancel="slidingDimmer=false" onkeydown="slidingDimmer=true" onkeyup="commitDimmer('${ch}',this.value)" oninput="dimValue('${ch}').textContent=this.value+'%'">
    <span id="dim-value-${ch}" class="${pct>0?'on':'off'}">${pct}%</span>
    ${nameInput(ch,name,'lcm')}
  </div>`;
}
function dimValue(ch){return document.getElementById(`dim-value-${ch}`)}
function renderSim(id){
  const nodes=appState.sim.rmc_nodes;
  devicePage.innerHTML=`<h2>${id} Sensor Interface Configuration</h2>
    ${kv('Module type','SIM')}${kv('IO mode',appState.sim.io_mode)}${kv('CAN interfaces',Object.keys(appState.sim.can).join(', '))}
    <h3>RMC Nodes</h3>
    ${Object.keys(nodes).length?Object.entries(nodes).map(([addr,n])=>`<div class="kv"><span>RMC ${addr}</span><span>${n.temperature_f ?? '-'}°F / ${n.humidity_pct ?? '-'}% RH / ${n.lux ?? '-'} lx / presence ${n.presence?'yes':'no'}</span></div>`).join(''):'<p class="muted">No RMC telemetry yet.</p>'}
    <div class="row" style="margin-top:14px"><button onclick="post('/api/sim/rmc-tick',{})">Inject RMC Frame</button></div>`;
}
function renderPnl(id){
  devicePage.innerHTML=`<h2>${id} Panel Configuration</h2>${kv('Module type','PNL')}${kv('Room',appState.pnl.room || 'unassigned')}${kv('Dashboard URL',appState.pnl.dashboard_url)}
    <h3>Panel Screen Preview</h3>
    ${screenMockup('pnl')}`;
}
function screenMockup(kind){
  const hvac=appState.hcm.hvac;
  const relaysOn=Object.values(appState.rcm.relays).filter(Boolean).length;
  const dimmersOn=Object.values(appState.lcm.hv_dimmers).concat(Object.values(appState.lcm.lv_dimmers)).filter(v=>v.percent>0).length;
  const moduleCount=appState.devices.length;
  const room=appState.pnl.room || 'House';
  const title=kind==='hcm' ? 'HomeControl HCM' : `${room} Panel`;
  const subtitle=kind==='hcm' ? 'PAIR 482913' : hvac.mode;
  const screenFace=kind==='hcm' ? pairingScreenFace() : statusScreenFace(title, subtitle, hvac, moduleCount, relaysOn, dimmersOn);
  return `<div class="screen-wrap">
    <div>
      <div class="screen-bezel">
        ${screenFace}
      </div>
      <div class="led-row"><span class="led on"></span><span class="led on"></span><span class="led ${hvac.heat||hvac.cool?'warn':'on'}"></span><span class="led"></span></div>
    </div>
    <div>
      ${kv('Screen size','3.3 inch')}
      ${kv('Display mode',kind==='hcm'?'HCM local status and pairing':'Room panel status')}
      ${kv('Touch actions','HVAC, lights, pairing/status')}
      ${kv('Auth source','HCM session and pairing keys')}
    </div>
  </div>`;
}
function pairingScreenFace(){
  const pairing=appState.hcm.pairing;
  return `<div class="screen pairing-screen">
    <div class="pairing-content">
      <div class="pair-title">PAIRING MODE</div>
      <div class="pair-code-glyph" aria-label="Circular pairing code">${pairGlyphCells(pairing.matrix)}</div>
      <div class="pair-code">${pairing.code.replace(/(\\d{3})(\\d{3})/,'$1 $2')}</div>
      <div class="pair-help">Scan from HomeControl setup</div>
    </div>
  </div>`;
}
function pairGlyphCells(matrix){
  let cells='';
  for(let y=0;y<matrix.length;y++){
    for(let x=0;x<matrix[y].length;x++){
      const value=matrix[y][x];
      const cls=value==='E' ? 'eye' : value==='1' ? 'on' : value==='0' ? 'soft' : '';
      const delay=((x+y)%6)*.08;
      cells+=`<span class="pair-dot ${cls}" style="animation-delay:${delay}s"></span>`;
    }
  }
  return cells;
}
function statusScreenFace(title, subtitle, hvac, moduleCount, relaysOn, dimmersOn){
  return `<div class="screen">
    <div class="screen-top"><span>${title}</span><span>${new Date().toLocaleTimeString([], {hour:'2-digit', minute:'2-digit'})}</span></div>
    <div>
      <div class="screen-title">${hvac.mode} ${hvac.setpoint_f}°F</div>
      <div class="screen-grid" style="margin-top:10px">
        <div class="screen-tile"><span>Average</span><strong>${hvac.average_f==null?'-':hvac.average_f.toFixed(1)}°F</strong></div>
        <div class="screen-tile"><span>Calls</span><strong>${['fan','cool','heat'].filter(k=>hvac[k]).join(' ') || 'Idle'}</strong></div>
        <div class="screen-tile"><span>Modules</span><strong>${moduleCount}</strong></div>
        <div class="screen-tile"><span>Lighting</span><strong>${relaysOn} / ${dimmersOn}</strong></div>
      </div>
    </div>
    <div>
      <div class="screen-actions"><div class="screen-action">HVAC</div><div class="screen-action">LIGHTS</div><div class="screen-action">${subtitle}</div></div>
    </div>
  </div>`;
}
async function toggleRelay(channel,value){await post('/api/rcm/relay',{channel,value})}
async function toggleLock(channel,locked){await post('/api/rcm/lock',{channel,locked})}
async function saveRcmName(channel,name){editingName=false; await post('/api/rcm/name',{channel,name})}
async function toggleLcmRelay(channel,value){await post('/api/lcm/relay',{channel,value})}
async function saveLcmName(channel,name){editingName=false; await post('/api/lcm/name',{channel,name})}
async function commitDimmer(channel,percent){
  const target=Number(percent);
  slidingDimmer=false;
  pendingDimmerTargets[channel]=target;
  const value=dimValue(channel);
  if(value) value.textContent=target+'%';
  await setDimmer(channel,target);
}
async function setDimmer(channel,percent){await postNoRefresh('/api/lcm/dimmer',{channel,percent})}
async function applyHvac(){await post('/api/hvac',{mode:hvacMode.value,setpoint_f:Number(hvacSetpoint.value)})}
async function setRoomTemp(temp){await post('/api/hvac/room',{room:'Office',temperature_f:temp,occupied:true,actuated_damper:false})}
setInterval(refresh,2000); refresh();
</script>
</body>
</html>"""


@app.get("/api/state")
async def state():
    return await sim.state()


@app.get("/api/pairing-glyph")
async def pairing_glyph():
    return sim.pairing_glyph()


@app.post("/api/rcm/relay")
async def rcm_relay(body: dict[str, Any]):
    return await sim.set_rcm_relay(str(body["channel"]), bool(body["value"]))


@app.post("/api/rcm/lock")
async def rcm_lock(body: dict[str, Any]):
    channel = str(body["channel"]).upper()
    if channel not in sim.rcm_locks:
        return {"ok": False, "error": "unknown_channel", "channel": channel}
    sim.rcm_locks[channel] = bool(body.get("locked", True))
    return {"ok": True, "channel": channel, "locked": sim.rcm_locks[channel]}


@app.post("/api/rcm/name")
async def rcm_name(body: dict[str, Any]):
    return sim.set_rcm_name(str(body["channel"]), str(body.get("name", "")))


@app.post("/api/hvac")
async def hvac_apply(body: dict[str, Any]):
    sim.hvac.state.mode = hvac_mod.Mode(body.get("mode", sim.hvac.state.mode.value))
    sim.hvac.state.setpoint_f = float(body.get("setpoint_f", sim.hvac.state.setpoint_f))
    await sim.hvac.evaluate()
    return sim.hvac_state()


@app.post("/api/hvac/room")
async def hvac_room(body: dict[str, Any]):
    name = body["room"]
    current = sim.hvac.rooms.get(name)
    sim.hvac.rooms[name] = hvac_mod.RoomReading(
        room=name,
        temperature_f=float(body.get("temperature_f", current.temperature_f if current else 70)),
        occupied=bool(body.get("occupied", current.occupied if current else False)),
        actuated_damper=bool(body.get("actuated_damper", current.actuated_damper if current else True)),
        damper_logical_device=body.get("damper_logical_device", current.damper_logical_device if current else None),
        sensor_ok=bool(body.get("sensor_ok", current.sensor_ok if current else True)),
    )
    await sim.hvac.evaluate()
    return sim.hvac_state()


@app.post("/api/lcm/dimmer")
async def lcm_dimmer(body: dict[str, Any]):
    return await sim.set_lcm_dimmer_fade(str(body["channel"]), float(body["percent"]))


@app.post("/api/lcm/relay")
async def lcm_relay(body: dict[str, Any]):
    return await sim.set_lcm_relay(str(body["channel"]), bool(body["value"]))


@app.post("/api/lcm/name")
async def lcm_name(body: dict[str, Any]):
    return sim.set_lcm_name(str(body["channel"]), str(body.get("name", "")))


@app.post("/api/sim/rmc-tick")
async def sim_rmc_tick():
    return await sim.tick_rmc()


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8088)
