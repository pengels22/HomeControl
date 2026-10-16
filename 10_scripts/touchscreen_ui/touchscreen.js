(() => {
  const app = document.getElementById('app');
  const toast = document.getElementById('toast');
  const params = new URLSearchParams(location.search);
  const role = (params.get('role') || 'RCM').toUpperCase();
  const icons = {status: '◉', relays: '◈', lights: '◈', network: '⌁', settings: '⚙', 'rmc-data': '⌁', sensors: '⌁'};
  let data = null;
  let page = params.get('page') || 'home';
  let history = [];
  let idle = null;
  const activeDimmers = new Set();
  const dimmerCommitTimers = new Map();
  const dimmerQueues = new Map();
  const suppressNextChanges = new Set();
  let requestSequence = 0;
  let latestMutationSequence = 0;
  let appliedRevision = -1;

  const esc = value => String(value ?? '').replace(/[&<>"']/g, character => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[character]));
  const showToast = (message, bad = false) => {
    toast.textContent = message;
    toast.className = 'toast';
    toast.style.borderColor = bad ? 'var(--bad)' : '';
    setTimeout(() => { toast.className = 'hide'; }, 2600);
  };

  async function load({renderPage = true} = {}) {
    const sequence = ++requestSequence;
    const response = await fetch(`/api/touchscreen/state?role=${role}`);
    const next = await response.json();
    if (sequence < latestMutationSequence || Number(next.state_revision ?? 0) < appliedRevision) return;
    data = next;
    appliedRevision = Math.max(appliedRevision, Number(next.state_revision ?? 0));
    if (renderPage || !document.querySelector('.shell')) render();
    else syncControls();
  }
  function resetIdle() { clearTimeout(idle); if (!activeDimmers.size) { const timeout = Number(data?.settings?.inactivity_seconds) || 10; idle = setTimeout(() => { page = 'home'; history = []; render(); }, timeout * 1000); } }
  function go(next) { if (next === 'home') { page = 'home'; history = []; } else { history.push(page); page = next; } render(); }
  function back() { page = history.pop() || 'home'; render(); }
  function tile(key, label) { return `<button class="tile" data-page="${key}"><span class="icon" aria-hidden="true">${icons[key] || '○'}</span><span>${label}</span></button>`; }
  function shell(content, title = '') { return `<section class="shell"><div class="subhead"><button class="back" aria-label="Back to previous page" data-back="true">‹</button><div class="page-title">${esc(title)}</div><div class="clock" id="clock"></div></div><div class="page-scroll">${content}</div><div class="footer">Touchscreen preview · simulated hardware only</div></section>`; }
  function home() { const pages = role === 'RCM' ? [tile('status', 'Status'), tile('relays', 'Relays'), tile('network', 'Network'), tile('settings', 'Settings')] : role === 'LCM' ? [tile('status', 'Status'), tile('lights', 'Lights'), tile('network', 'Network'), tile('settings', 'Settings')] : role === 'SIM' ? [tile('status', 'Status'), tile('rmc-data', 'RMC Data'), tile('network', 'Network'), tile('settings', 'Settings')] : [tile('status', 'Status'), tile('sensors', 'Sensors'), tile('network', 'Network'), tile('settings', 'Settings')]; return `<section class="shell"><div class="top"><div class="brand">HomeControl</div><div class="clock" id="clock"></div></div><button class="identity" data-page="status" aria-label="Open detailed status for ${esc(data.module.name)}"><h1>${esc(data.module.name)}</h1><div class="health"><span class="dot" aria-hidden="true"></span><span>${esc(data.health.status)}</span></div></button><div class="grid">${pages.join('')}</div><div class="footer">Return to Home after 10 seconds of inactivity</div></section>`; }
  function status() { const m = data.module, h = data.health, s = data.settings; return shell(`<div class="status-banner ${h.status === 'SIMULATED' ? 'warn' : 'ok'}">${esc(m.name)} · ${esc(h.status)}</div><div class="cards"><div class="card"><h2>Module</h2>${metric('Role', m.role)}${metric('Device identity', m.device_id)}</div><div class="card"><h2>Health</h2>${metric('Heartbeat', h.heartbeat)}${metric('Configuration', h.config_sync)}${metric('Faults', h.faults.length ? 'Active' : 'None')}</div><div class="card"><h2>Safety</h2>${metric('Simulation', m.simulation ? 'Enabled' : 'Unavailable')}${metric('Physical outputs', m.physical_outputs_enabled ? 'Enabled' : 'Disabled')}</div><div class="card"><h2>Profile</h2>${metric('Hardware profile', s.hardware_profile)}${metric('State', 'Read-only preview')}</div></div>`, 'Status'); }
  function metric(label, value) { return `<div class="metric"><span class="label">${esc(label)}</span><strong>${esc(value)}</strong></div>`; }
  function bankButton(index, label, selected) { return `<button class="bank-button ${selected ? 'selected' : ''}" data-bank="${index}" aria-pressed="${selected}" aria-label="Select relay bank ${esc(label)}">${esc(label)}</button>`; }
  function relays(title = 'Relays', items = data.relays) { const isRcm = role === 'RCM' && title === 'Relays'; const selector = data.bank_selector || {}; const selected = isRcm ? Number(selector.effective_bank || 0) : 0; const visible = isRcm ? items.filter(item => Math.floor((item.position - 1) / 8) === selected) : items; const banks = isRcm ? `<div class="bank-select" role="group" aria-label="RCM relay banks">${['1–8', '9–16', '17–24', '25–32'].map((label, index) => bankButton(index, label, index === selected)).join('')}</div><div class="section-note bank-source">Bank source: ${esc(selector.source || 'Unavailable')}${selector.physical_selector_authoritative ? ' · physical selector has authority' : ''}</div>` : ''; return shell(`<div class="status-banner">${esc(data.module.name)} · ${esc(title)}</div>${banks}${visible.map(item => `<div class="row"><strong>${esc(item.name)}</strong><span></span><button class="switch ${item.on ? 'on' : ''}" data-relay="${esc(item.channel)}" ${item.lockout ? 'disabled' : ''} aria-label="${esc(item.name)} ${item.on ? 'on' : 'off'}${item.lockout ? ', maintenance locked' : ''}" aria-pressed="${item.on}"><span></span></button></div>`).join('')}<div class="section-note">${data.module.simulation ? 'Simulation only · commands are software acknowledgments' : 'Unavailable · no physical confirmation'}</div>`, title); }
  function lights() { return shell(`<div class="cards">${tile('dimmers', 'Dimmers')}${tile('non-dimmers', 'Non-Dimmers')}</div>`, 'Lights'); }
  function dimmers() { return shell(`<div class="status-banner">${esc(data.module.name)} · Dimmers</div>${data.dimmers.map(item => `<div class="row"><strong>${esc(item.name)}</strong><div class="range-wrap"><input class="range" type="range" min="0" max="100" value="${item.percent}" data-dimmer="${item.channel}" aria-label="${esc(item.name)} brightness"></div><span class="percent">${item.percent}%</span></div>`).join('')}<div class="section-note">0–5% is normalized to OFF; commands acknowledge in simulated state only.</div>`, 'Dimmers'); }
  function network() { const n = data.network; return shell(`<div class="cards"><div class="card">${metric('Hostname', n.hostname)}${metric('IPv4', n.ipv4)}${metric('MAC / identity', n.mac)}</div><div class="card">${metric('Link', n.link)}${metric('HCM', n.hcm)}${metric('Last sync', n.last_sync)}</div></div>`, 'Network'); }
  function settings() { return shell(`<div class="card"><label class="metric timeout-setting"><span class="label">Screen timeout</span><input type="number" min="1" max="300" step="1" value="${data.settings.inactivity_seconds}" data-timeout aria-label="Screen timeout in seconds"><span class="label">seconds</span></label>${metric('Display brightness', data.settings.display_brightness + '%')}${metric('Local admin', data.settings.local_admin)}${metric('Role', data.settings.role)}${metric('Simulation', data.settings.simulation)}${metric('Hardware profile', data.settings.hardware_profile)}</div>`, 'Settings'); }
  function rooms() { return shell(data.rooms.map(room => `<div class="room"><h2>${esc(room.name)} · ${room.online ? 'Online' : 'Unavailable'}</h2><div class="sensor-grid">${[['Lux', room.lux == null ? 'Unavailable' : room.lux], ['Temperature', room.temperature_f == null ? 'Unavailable' : room.temperature_f + ' °F'], ['Humidity', room.humidity_pct == null ? 'Unavailable' : room.humidity_pct + ' %'], ['Presence', room.presence == null ? 'Unavailable' : room.presence ? 'Present' : 'Clear']].map(item => `<div class="sensor"><b>${item[0]}</b><span>${esc(item[1])}</span></div>`).join('')}</div></div>`).join(''), 'RMC Data'); }
  function sensors() { return shell(data.external_sensors.map(item => `<div class="metric"><span><strong>${esc(item.name)}</strong><small class="label">${esc(item.source)}</small></span><strong class="unavailable">${esc(item.value)}</strong></div>`).join(''), 'Sensors'); }

  function findControl(attribute, value) { return [...document.querySelectorAll(`[${attribute}]`)].find(element => element.getAttribute(attribute) === String(value)); }
  function queueDimmerCommit(channel, value, immediate = false) {
    clearTimeout(dimmerCommitTimers.get(channel));
    const commit = () => {
      dimmerCommitTimers.delete(channel);
      const previous = dimmerQueues.get(channel) || Promise.resolve();
      const next = previous.catch(() => {}).then(() => send({kind: 'dimmer', channel, value}));
      const queued = next.finally(() => { if (dimmerQueues.get(channel) === queued) dimmerQueues.delete(channel); });
      dimmerQueues.set(channel, queued);
    };
    if (immediate) commit();
    else dimmerCommitTimers.set(channel, setTimeout(commit, 120));
  }
  function commitDimerInput(input, immediate = false) {
    const channel = input.dataset.dimmer;
    activeDimmers.delete(channel);
    suppressNextChanges.add(channel);
    setTimeout(() => suppressNextChanges.delete(channel), 0);
    queueDimmerCommit(channel, Number(input.value), immediate);
    resetIdle();
  }
  function syncControls() {
    if (!data) return;
    data.relays?.forEach(item => { const button = findControl('data-relay', item.channel); if (!button) return; button.classList.toggle('on', Boolean(item.on)); button.setAttribute('aria-pressed', String(Boolean(item.on))); button.disabled = Boolean(item.lockout); button.setAttribute('aria-label', `${item.name} ${item.on ? 'on' : 'off'}${item.lockout ? ', maintenance locked' : ''}`); });
    data.dimmers?.forEach(item => { const input = findControl('data-dimmer', item.channel); if (!input || activeDimmers.has(item.channel) || document.activeElement === input) return; input.value = item.percent; const percent = input.closest('.row')?.querySelector('.percent'); if (percent) percent.textContent = `${item.percent}%`; });
    const selected = Number(data.bank_selector?.effective_bank || 0); document.querySelectorAll('[data-bank]').forEach(button => { const active = Number(button.dataset.bank) === selected; button.classList.toggle('selected', active); button.setAttribute('aria-pressed', String(active)); });
    const timeout = document.querySelector('[data-timeout]');
    if (timeout && document.activeElement !== timeout) timeout.value = data.settings.inactivity_seconds;
  }
  function render() { if (!data) return; const body = page === 'home' ? home() : page === 'status' ? status() : page === 'relays' ? relays() : page === 'lights' ? lights() : page === 'dimmers' ? dimmers() : page === 'non-dimmers' ? relays('Non-Dimmers', data.relays.slice(0, 8)) : page === 'network' ? network() : page === 'settings' ? settings() : page === 'rmc-data' ? rooms() : sensors(); app.innerHTML = body; document.querySelectorAll('[data-page]').forEach(button => button.addEventListener('click', () => go(button.dataset.page))); document.querySelectorAll('[data-back]').forEach(button => button.addEventListener('click', back)); document.querySelectorAll('[data-bank]').forEach(button => button.addEventListener('click', () => send({kind: 'bank_select', bank: Number(button.dataset.bank)}))); document.querySelectorAll('[data-relay]').forEach(button => button.addEventListener('click', () => send({kind: 'relay', channel: button.dataset.relay, value: !button.classList.contains('on')}))); document.querySelectorAll('[data-dimmer]').forEach(input => { input.addEventListener('pointerdown', event => { activeDimmers.add(input.dataset.dimmer); input.setPointerCapture?.(event.pointerId); resetIdle(); }); input.addEventListener('pointermove', resetIdle); input.addEventListener('keydown', event => { if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End', 'PageUp', 'PageDown'].includes(event.key)) { activeDimmers.add(input.dataset.dimmer); resetIdle(); } }); input.addEventListener('input', () => { const percent = input.closest('.row')?.querySelector('.percent'); if (percent) percent.textContent = `${input.value}%`; resetIdle(); }); input.addEventListener('change', () => { if (activeDimmers.has(input.dataset.dimmer)) return; if (suppressNextChanges.delete(input.dataset.dimmer)) return; queueDimmerCommit(input.dataset.dimmer, Number(input.value)); }); input.addEventListener('keyup', event => { if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End', 'PageUp', 'PageDown'].includes(event.key)) commitDimerInput(input); }); input.addEventListener('pointerup', event => { input.releasePointerCapture?.(event.pointerId); commitDimerInput(input, true); }); input.addEventListener('pointercancel', () => { activeDimmers.delete(input.dataset.dimmer); resetIdle(); }); input.addEventListener('blur', () => { if (activeDimmers.has(input.dataset.dimmer)) commitDimerInput(input); }); }); const timeout = document.querySelector('[data-timeout]'); if (timeout) timeout.addEventListener('change', () => { const value = Number(timeout.value); if (!Number.isInteger(value) || value < 1 || value > 300) { showToast('Screen timeout must be 1–300 seconds', true); syncControls(); return; } send({kind: 'setting', setting: 'screen_timeout', value}); }); const clock = document.getElementById('clock'); if (clock) { const tick = () => { clock.textContent = new Date().toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}); }; tick(); setInterval(tick, 1000); } resetIdle(); }
  async function send(payload) { const mutationSequence = ++requestSequence; latestMutationSequence = mutationSequence; try { const response = await fetch('/api/touchscreen/command', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({...payload, role})}); const result = await response.json(); if (!response.ok) throw new Error(result.detail); showToast(`Acknowledged ${result.channel || result.setting || (result.bank != null ? `bank ${result.bank + 1}` : 'update')}`); await load({renderPage: false}); if (payload.kind === 'setting') resetIdle(); } catch (error) { showToast(error.message, true); try { await load({renderPage: false}); } catch (_) { /* keep the current interaction if reconciliation is unavailable */ } } }
  document.addEventListener('pointerdown', resetIdle); document.addEventListener('pointermove', resetIdle); document.addEventListener('keydown', resetIdle); document.addEventListener('touchstart', resetIdle, {passive: true}); document.addEventListener('touchmove', resetIdle, {passive: true}); document.addEventListener('scroll', resetIdle, {passive: true}); load().then(() => { setInterval(() => load({renderPage: false}).catch(() => {}), 3000); }).catch(error => showToast(error.message, true));
})();
