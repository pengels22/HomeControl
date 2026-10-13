const $ = (id) => document.getElementById(id);
let token = localStorage.getItem("homecontrol_token") || "";
let currentUser = null;
let lastModules = [];
const pending = new Set();
let activeDialog = null;

async function api(path, options = {}) {
  const headers = {"Content-Type": "application/json", ...(options.headers || {})};
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(`/api/v1${path}`, {...options, headers});
  const text = await response.text();
  const data = text ? JSON.parse(text) : {};
  if (!response.ok) throw new Error(data.detail || JSON.stringify(data));
  return data;
}

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  }[ch]));
}

function routeParts() {
  const parts = window.location.pathname.split("/").filter(Boolean);
  if (!parts.length) return ["dashboard"];
  return parts;
}

function routeName() {
  return routeParts()[0] || "dashboard";
}

function selectedDeviceIdentifier() {
  return decodeURIComponent(routeParts().slice(1).join("/"));
}

function setTitle(kicker, title) {
  $("page-kicker").textContent = kicker;
  $("page-title").textContent = title;
  document.querySelectorAll(".nav a").forEach((link) => {
    link.classList.toggle("active", link.dataset.route === routeName());
  });
}

function showApp(show) {
  $("login-view").hidden = show;
  $("app-view").hidden = !show;
  $("logout").hidden = !show;
}

function setError(message = "") {
  $("app-error").textContent = message;
}

function statusPill(online, label = null) {
  const text = label || (online ? "Online" : "Offline");
  return `<span class="status-pill ${online ? "online" : "offline"}">${esc(text)}</span>`;
}

function roleLabel(device) {
  return device.effective_role || device.module?.module_type || "UNASSIGNED";
}

function online(module) {
  return Boolean(module.online || module.control_session_online);
}

async function loadRegistry() {
  const data = await api("/modules");
  lastModules = data.modules || [];
  return lastModules;
}

async function detectPreviewMode() {
  try {
    const data = await api("/preview-mode");
    $("preview-banner").hidden = !data.preview;
  } catch {
    $("preview-banner").hidden = true;
  }
}

function deviceLink(module) {
  return `/devices/${encodeURIComponent(module.hostname)}`;
}

async function renderDashboard() {
  setTitle("Overview", "Dashboard");
  $("content").innerHTML = `<div class="loading">Loading HCM health...</div>`;
  const [health, hvac, modules] = await Promise.all([
    api("/health"),
    api("/hvac"),
    loadRegistry(),
  ]);
  const onlineCount = modules.filter(online).length;
  $("content").innerHTML = `
    <section class="summary-grid">
      <article class="summary">
        <span>Backend</span>
        <strong>${health.ok ? "Healthy" : "Unavailable"}</strong>
        ${statusPill(Boolean(health.ok), health.ok ? "HTTP 200" : "Check failed")}
      </article>
      <article class="summary">
        <span>Registered Devices</span>
        <strong>${modules.length}</strong>
        <p>${onlineCount} online, ${modules.length - onlineCount} offline</p>
      </article>
      <article class="summary">
        <span>HVAC</span>
        <strong>${esc(hvac.mode)}</strong>
        <p>${esc(hvac.setpoint_f)} F setpoint</p>
      </article>
    </section>
    <section class="panel">
      <div class="panel-head"><h3>Device Status</h3><a class="text-link" href="/devices">Open Devices</a></div>
      ${deviceTable(modules)}
    </section>`;
}

function deviceTable(modules) {
  if (!modules.length) return `<div class="empty">No registered devices returned by HCM.</div>`;
  return `<div class="table-wrap"><table>
    <thead><tr><th>Logical Hostname</th><th>Registered Role</th><th>Status</th><th>Physical Device ID</th><th>Heartbeat / Supervision</th></tr></thead>
    <tbody>${modules.map((module) => `
      <tr>
        <td><a href="${deviceLink(module)}">${esc(module.hostname)}</a></td>
        <td>${esc(module.module_type)}</td>
        <td>${statusPill(online(module))}</td>
        <td><code>${esc(module.device_id || module.module_uuid || "-")}</code></td>
        <td>${esc(module.supervision_state || "unknown")}<br><span>${esc(module.supervision_last_seen || module.last_seen || "")}</span></td>
      </tr>`).join("")}</tbody>
  </table></div>`;
}

async function renderDevices() {
  setTitle("Registry", "Devices");
  $("content").innerHTML = `<div class="loading">Loading registered devices...</div>`;
  const modules = await loadRegistry();
  $("content").innerHTML = `
    <section class="panel">
      <div class="panel-head">
        <h3>Registered HCM Devices</h3>
        <span class="muted">${modules.length} returned by HCM</span>
      </div>
      ${deviceTable(modules)}
    </section>`;
}

function identityBlock(device) {
  const module = device.module;
  return `<section class="identity-grid">
    <div><span>Hostname</span><strong>${esc(module.hostname)}</strong></div>
    <div><span>Assigned Interface</span><strong>${esc(roleLabel(device))}</strong></div>
    <div><span>Registered Module Type</span><strong>${esc(module.module_type)}</strong></div>
    <div><span>Status</span><strong>${online(module) ? "Online" : "Offline"}</strong></div>
    <div><span>Device ID</span><strong><code>${esc(module.device_id || "-")}</code></strong></div>
    <div><span>Control Session</span><strong>${module.control_session_online ? "Authenticated" : "Unavailable"}</strong></div>
    <div><span>Simulation</span><strong>${device.simulation === true ? "Enabled" : device.simulation === false ? "Disabled" : "Unknown"}</strong></div>
    <div><span>Physical Outputs</span><strong>${device.physical_outputs_enabled === true ? "Enabled" : device.physical_outputs_enabled === false ? "Disabled" : "Unknown"}</strong></div>
  </section>`;
}

async function renderDeviceDetail(identifier) {
  $("content").innerHTML = `<div class="loading">Resolving selected device through HCM...</div>`;
  const device = await api(`/device-admin/${encodeURIComponent(identifier)}`);
  setTitle("Device", device.module.hostname);
  const role = roleLabel(device);
  if (role === "RCM") return renderRcm(device);
  if (role === "LCM") return renderLcm(device);
  if (role === "SIM") return renderRoleShell(device, "Sensor Interface Module");
  return renderRoleShell(device, "Unassigned Device");
}

function renderRoleShell(device, label) {
  $("content").innerHTML = `
    <section class="panel">
      <div class="panel-head">
        <h3>${esc(label)}</h3>
        ${statusPill(online(device.module))}
      </div>
      ${identityBlock(device)}
      <div class="notice">
        ${esc(device.module.hostname)} is shown from HCM registry and reported state. No controls are available for this role in this iteration.
      </div>
    </section>
    <section class="panel">
      <div class="panel-head"><h3>Replacement Readiness</h3></div>
      <p class="muted">${esc(device.replacement_ready.note)}</p>
    </section>`;
}

async function renderRcm(device) {
  const data = await api(`/device-admin/${encodeURIComponent(device.module.hostname)}/rcm-channels`);
  window.__lastRcmChannels = data.channels;
  $("content").innerHTML = `
    <section class="panel">
      <div class="panel-head">
        <h3>Relay Control Module</h3>
        ${statusPill(online(data.device.module))}
      </div>
      ${identityBlock(data.device)}
      ${data.device.physical_outputs_enabled === false ? `<div class="notice warn">Physical outputs are disabled by the registered device state. Controls remain unavailable until HCM receives a safe, confirmed state.</div>` : ""}
    </section>
    <section class="panel">
      <div class="panel-head">
        <h3>Channels</h3>
        <span class="muted">32 relay channels, routed by logical bindings</span>
      </div>
      <div class="rcm-grid">${data.channels.map(channelCard).join("")}</div>
    </section>`;
}

async function renderLcm(device) {
  const data = await api(`/device-admin/${encodeURIComponent(device.module.hostname)}/lcm-channels`);
  window.__lastLcmChannels = data.channels;
  const relays = data.channels.filter((channel) => channel.kind === "light");
  const lvDimmers = data.channels.filter((channel) => channel.kind === "dimmer" && channel.channel.startsWith("10-"));
  const hvDimmers = data.channels.filter((channel) => channel.kind === "dimmer" && channel.channel.startsWith("HV-"));
  $("content").innerHTML = `
    <section class="panel">
      <div class="panel-head">
        <h3>Lighting Control Module</h3>
        ${statusPill(online(data.device.module))}
      </div>
      ${identityBlock(data.device)}
    </section>
    <section class="panel lcm-panel">
      <div class="lcm-columns">
        ${lcmColumn("Relays", `${relays.length} outputs`, relays.map(lightRow).join(""))}
        ${lcmColumn("0-10V Dimmers", `${lvDimmers.length} outputs`, lvDimmers.map(dimmerTile).join(""))}
        ${lcmColumn("110V Dimmers", `${hvDimmers.length} outputs`, hvDimmers.map(dimmerTile).join(""))}
      </div>
    </section>`;
}

function lcmColumn(title, count, body) {
  return `<section class="lcm-column">
    <div class="lcm-column-head">
      <h3>${esc(title)}</h3>
      <span>${esc(count)}</span>
    </div>
    <div class="lcm-list">${body || `<div class="empty">No channels reported.</div>`}</div>
  </section>`;
}

function lightRow(channel) {
  const isPending = pending.has(channel.logical_name);
  const locked = channel.maintenance_locked;
  const value = channel.value === true;
  const canControl = channel.control_enabled && !isPending;
  const canConfigure = Boolean(channel.bound) && !isPending;
  const stateText = isPending ? "Pending backend acknowledgement" : channel.disabled_reason || (channel.value == null ? "Unknown" : value ? "On" : "Off");
  return `<article class="lcm-row ${locked ? "locked" : ""}" data-channel="${esc(channel.channel)}">
    <div class="lcm-channel-main">
      <button class="channel-title" type="button" data-settings-channel="${esc(channel.channel)}" ${canConfigure ? "" : "disabled"}>${esc(channel.name || "Unbound")}</button>
      <span class="channel-meta">${esc(channel.channel)}${channel.emergency_lighting ? " / eLight" : ""}</span>
    </div>
    <label class="toggle-control ${locked ? "relay-locked" : ""}">
      <span class="toggle-label">On</span>
      <input class="toggle-input" type="checkbox" data-lcm-light-channel="${esc(channel.channel)}" aria-label="${esc(channel.name || channel.channel)} light output" ${value ? "checked" : ""} ${canControl ? "" : "disabled"}>
      <span class="toggle-track" aria-hidden="true"><span class="toggle-thumb"></span></span>
    </label>
    <p class="channel-state">${esc(stateText)}</p>
  </article>`;
}

function dimmerTile(channel) {
  const knownPercent = channel.percent !== null && channel.percent !== undefined;
  const percent = knownPercent ? Math.round(Number(channel.percent)) : null;
  const locked = channel.maintenance_locked;
  const isPending = pending.has(channel.logical_name);
  const canConfigure = Boolean(channel.bound) && !isPending;
  const stateText = isPending ? "Pending backend acknowledgement" : channel.disabled_reason || `Max ${channel.max_intensity}% / Fade ${channel.fade_seconds}s`;
  return `<article class="dimmer-tile ${locked ? "locked" : ""}" data-channel="${esc(channel.channel)}">
    <div class="lcm-channel-main">
      <button class="channel-title" type="button" data-settings-channel="${esc(channel.channel)}" ${canConfigure ? "" : "disabled"}>${esc(channel.name || "Unbound")}</button>
      <span class="channel-meta">${esc(channel.channel)}${channel.emergency_lighting ? " / eLight" : ""}</span>
    </div>
    <button class="dimmer-button" type="button" data-dimmer-channel="${esc(channel.channel)}" ${channel.control_enabled && !isPending ? "" : "disabled"} aria-label="Adjust ${esc(channel.name || channel.channel)} brightness">
      <strong>${knownPercent ? `${percent}%` : "Unknown"}</strong>
      <span>${esc(stateText)}</span>
    </button>
  </article>`;
}

function channelCard(channel) {
  const pendingKey = `${channel.logical_name || channel.channel}`;
  const isPending = pending.has(pendingKey);
  const locked = channel.maintenance_locked;
  const value = channel.value === true;
  const canName = Boolean(channel.bound);
  const canControl = channel.control_enabled && !isPending;
  return `<article class="channel-card ${locked ? "locked" : ""}" data-channel="${esc(channel.channel)}">
    <div class="channel-top">
      <strong>${channel.number}</strong>
      <code>${esc(channel.channel)}</code>
    </div>
    <input class="channel-name" data-name-channel="${esc(channel.channel)}" value="${esc(channel.name)}" placeholder="${channel.bound ? "Channel name" : "No binding"}" ${canName ? "" : "disabled"}>
    <label class="switch-row toggle-control ${locked ? "relay-locked" : ""}">
      <span class="toggle-label">On</span>
      <input class="toggle-input" type="checkbox" data-output-channel="${esc(channel.channel)}" aria-label="${esc(channel.channel)} relay output" ${value ? "checked" : ""} ${canControl ? "" : "disabled"}>
      <span class="toggle-track" aria-hidden="true"><span class="toggle-thumb"></span></span>
    </label>
    <label class="switch-row toggle-control maintenance-toggle">
      <span class="toggle-label">Maintenance</span>
      <input class="toggle-input" type="checkbox" data-lock-channel="${esc(channel.channel)}" aria-label="${esc(channel.channel)} maintenance lockout" ${locked ? "checked" : ""} ${channel.bound && !isPending ? "" : "disabled"}>
      <span class="toggle-track" aria-hidden="true"><span class="toggle-thumb"></span></span>
    </label>
    <p class="channel-state">${isPending ? "Pending backend acknowledgement" : esc(channel.disabled_reason || (channel.value == null ? "State unknown" : value ? "Acknowledged on" : "Acknowledged off"))}</p>
  </article>`;
}

async function renderService() {
  setTitle("Diagnostics", "Service");
  $("content").innerHTML = `<div class="loading">Loading diagnostics...</div>`;
  const [health, relays, modules] = await Promise.allSettled([
    api("/health"),
    api("/safety/hcm-relays"),
    loadRegistry(),
  ]);
  $("content").innerHTML = `
    <section class="summary-grid">
      <article class="summary"><span>API Health</span><strong>${health.status === "fulfilled" && health.value.ok ? "Healthy" : "Failed"}</strong></article>
      <article class="summary"><span>Safety Relay Controller</span><strong>${relays.status === "fulfilled" ? "Available" : "Unavailable"}</strong></article>
      <article class="summary"><span>Registered Modules</span><strong>${modules.status === "fulfilled" ? modules.value.length : "-"}</strong></article>
    </section>
    <section class="panel"><h3>Diagnostics Foundation</h3><p class="muted">This page reports only live HCM diagnostics exposed by authenticated APIs. Watchdog, PostgreSQL, and host service controls are intentionally not exposed here.</p></section>`;
}

function renderSettings() {
  setTitle("Configuration", "Settings");
  $("content").innerHTML = `<section class="panel"><h3>Settings</h3><p class="muted">Configuration pages will be added here after their backend contracts are reviewed. No simulator state or unsafe replacement workflow is exposed.</p></section>`;
}

async function renderUsers() {
  setTitle("Access", "Users");
  const session = currentUser || await api("/auth/session");
  currentUser = session;
  $("content").innerHTML = `<section class="panel"><h3>User Management</h3><div class="identity-grid"><div><span>Signed in as</span><strong>${esc(session.user)}</strong></div><div><span>Role</span><strong>${esc(session.role)}</strong></div></div><p class="muted">Centralized user management remains tied to authenticated HCM APIs. Pairing-key administration has been removed from the production UI workflow.</p></section>`;
}

function modal(html) {
  closeDialog();
  activeDialog = document.createElement("div");
  activeDialog.className = "modal-backdrop";
  activeDialog.innerHTML = html;
  document.body.appendChild(activeDialog);
  const first = activeDialog.querySelector("input, button, select, textarea");
  if (first) first.focus();
}

function closeDialog() {
  if (activeDialog) {
    activeDialog.remove();
    activeDialog = null;
  }
}

function lcmChannel(channelId) {
  return (window.__lastLcmChannels || []).find((item) => item.channel === channelId);
}

function openDimmerDialog(channelId) {
  const channel = lcmChannel(channelId);
  if (!channel) return;
  const knownPercent = channel.percent !== null && channel.percent !== undefined;
  const percent = knownPercent ? Math.round(Number(channel.percent)) : 0;
  const acknowledged = knownPercent ? `${percent}%` : "Unknown";
  const max = Number(channel.max_intensity || 100);
  modal(`<section class="modal" role="dialog" aria-modal="true" aria-labelledby="dimmer-title">
    <div class="modal-head">
      <h3 id="dimmer-title">${esc(channel.name)}</h3>
      <button type="button" class="secondary icon-button" data-close-dialog aria-label="Close">x</button>
    </div>
    <p class="muted">${esc(channel.channel)} / acknowledged ${acknowledged} / maximum ${max}%</p>
    <div class="slider-readout"><strong data-dimmer-readout>${acknowledged}</strong></div>
    <input class="brightness-slider" type="range" min="0" max="${esc(max)}" step="1" value="${percent}" data-dimmer-slider="${esc(channel.channel)}" aria-label="${esc(channel.name)} brightness">
    <div class="modal-actions">
      <button type="button" class="secondary" data-dimmer-off="${esc(channel.channel)}">Off</button>
      <button type="button" data-dimmer-restore="${esc(channel.channel)}">Restore</button>
    </div>
    <p class="channel-state">Slider movement previews the target. One command is sent when the value is released or committed from the keyboard.</p>
  </section>`);
}

function openSettingsDialog(channelId) {
  const channel = lcmChannel(channelId);
  if (!channel || !channel.bound) return;
  const dimmerFields = channel.kind === "dimmer" ? `
    <label>Maximum intensity <input type="number" min="0" max="100" value="${esc(channel.max_intensity)}" data-settings-max></label>
    <label>Default fade seconds <input type="number" min="0" max="60" step="0.1" value="${esc(channel.fade_seconds)}" data-settings-fade></label>
  ` : "";
  modal(`<section class="modal" role="dialog" aria-modal="true" aria-labelledby="settings-title">
    <div class="modal-head">
      <h3 id="settings-title">${esc(channel.name)}</h3>
      <button type="button" class="secondary icon-button" data-close-dialog aria-label="Close">x</button>
    </div>
    <label>Channel name <input value="${esc(channel.name)}" data-settings-name></label>
    <label class="settings-check"><input type="checkbox" data-settings-elight ${channel.emergency_lighting ? "checked" : ""}> Emergency Lighting</label>
    <label class="settings-check"><input type="checkbox" data-settings-lock ${channel.maintenance_locked ? "checked" : ""}> Maintenance lockout</label>
    ${dimmerFields}
    <div class="modal-actions">
      <button type="button" class="secondary" data-close-dialog>Cancel</button>
      <button type="button" data-save-lcm-settings="${esc(channel.channel)}">Save</button>
    </div>
  </section>`);
}

async function renderRoute() {
  if (!token) {
    showApp(false);
    return;
  }
  showApp(true);
  setError("");
  try {
    const parts = routeParts();
    if (parts[0] === "devices" && parts[1]) return await renderDeviceDetail(decodeURIComponent(parts.slice(1).join("/")));
    if (parts[0] === "devices") return await renderDevices();
    if (parts[0] === "service") return await renderService();
    if (parts[0] === "settings") return renderSettings();
    if (parts[0] === "users") return await renderUsers();
    return await renderDashboard();
  } catch (error) {
    $("content").innerHTML = `<section class="panel"><h3>Unable to load page</h3><p class="muted">${esc(error.message)}</p></section>`;
    setError(error.message);
  }
}

function go(path) {
  history.pushState({}, "", path);
  renderRoute();
}

document.addEventListener("click", async (event) => {
  const link = event.target.closest("a[href^='/']");
  if (link) {
    event.preventDefault();
    go(link.getAttribute("href"));
    return;
  }
  const output = event.target.closest("[data-output-channel]");
  if (output) {
    const channel = output.dataset.outputChannel;
    await setOutput(channel, output.checked);
    return;
  }
  const lock = event.target.closest("[data-lock-channel]");
  if (lock) {
    const channel = lock.dataset.lockChannel;
    await setLockout(channel, lock.checked);
    return;
  }
  const light = event.target.closest("[data-lcm-light-channel]");
  if (light) {
    await setLcmLight(light.dataset.lcmLightChannel, light.checked);
    return;
  }
  const dimmer = event.target.closest("[data-dimmer-channel]");
  if (dimmer) {
    openDimmerDialog(dimmer.dataset.dimmerChannel);
    return;
  }
  const settings = event.target.closest("[data-settings-channel]");
  if (settings) {
    openSettingsDialog(settings.dataset.settingsChannel);
    return;
  }
  const close = event.target.closest("[data-close-dialog]");
  if (close) {
    closeDialog();
    return;
  }
  if (event.target.classList.contains("modal-backdrop")) {
    closeDialog();
    return;
  }
  const off = event.target.closest("[data-dimmer-off]");
  if (off) {
    await setLcmDimmer(off.dataset.dimmerOff, 0);
    closeDialog();
    return;
  }
  const restore = event.target.closest("[data-dimmer-restore]");
  if (restore) {
    const channel = lcmChannel(restore.dataset.dimmerRestore);
    await setLcmDimmer(restore.dataset.dimmerRestore, Number(channel?.last_nonzero_percent || channel?.max_intensity || 100));
    closeDialog();
    return;
  }
  const save = event.target.closest("[data-save-lcm-settings]");
  if (save) {
    await saveLcmSettings(save.dataset.saveLcmSettings);
  }
});

document.addEventListener("focusout", async (event) => {
  const input = event.target.closest("[data-name-channel]");
  if (!input) return;
  const channel = input.dataset.nameChannel;
  const identifier = selectedDeviceIdentifier();
  try {
    await api(`/device-admin/${encodeURIComponent(identifier)}/rcm-channels/${encodeURIComponent(channel)}/name`, {
      method: "PATCH",
      body: JSON.stringify({name: input.value}),
    });
  } catch (error) {
    setError(error.message);
  }
});

document.addEventListener("input", (event) => {
  const slider = event.target.closest("[data-dimmer-slider]");
  if (!slider) return;
  const readout = activeDialog?.querySelector("[data-dimmer-readout]");
  if (readout) readout.textContent = `${slider.value}%`;
});

document.addEventListener("change", async (event) => {
  const slider = event.target.closest("[data-dimmer-slider]");
  if (!slider) return;
  await setLcmDimmer(slider.dataset.dimmerSlider, Number(slider.value));
  closeDialog();
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && activeDialog) closeDialog();
});

function channelById(channel) {
  const cards = [...document.querySelectorAll(".channel-card")];
  return cards.find((card) => card.dataset.channel === channel);
}

function logicalForChannel(channel) {
  const index = Number(channelById(channel)?.querySelector(".channel-top strong")?.textContent);
  const data = window.__lastRcmChannels || [];
  return data.find((item) => item.number === index)?.logical_name;
}

async function currentRcmChannels() {
  const identifier = selectedDeviceIdentifier();
  const data = await api(`/device-admin/${encodeURIComponent(identifier)}/rcm-channels`);
  window.__lastRcmChannels = data.channels;
  return data.channels;
}

async function setOutput(channel, value) {
  try {
    const channels = await currentRcmChannels();
    const item = channels.find((entry) => entry.channel === channel);
    if (!item?.logical_name) throw new Error("Channel has no logical binding");
    pending.add(item.logical_name);
    await renderDeviceDetail(selectedDeviceIdentifier());
    await api("/device/command", {
      method: "POST",
      body: JSON.stringify({logical_name: item.logical_name, command: {op: "set_relay", value}}),
    });
    pending.delete(item.logical_name);
    await renderDeviceDetail(selectedDeviceIdentifier());
  } catch (error) {
    pending.clear();
    setError(error.message);
    await renderDeviceDetail(selectedDeviceIdentifier());
  }
}

async function setLockout(channel, active) {
  try {
    const channels = await currentRcmChannels();
    const item = channels.find((entry) => entry.channel === channel);
    if (!item?.logical_name) throw new Error("Channel has no logical binding");
    pending.add(item.logical_name);
    await renderDeviceDetail(selectedDeviceIdentifier());
    await api("/safety/maintenance-lockout", {
      method: "POST",
      body: JSON.stringify({logical_name: item.logical_name, active}),
    });
    pending.delete(item.logical_name);
    await renderDeviceDetail(selectedDeviceIdentifier());
  } catch (error) {
    pending.clear();
    setError(error.message);
    await renderDeviceDetail(selectedDeviceIdentifier());
  }
}

async function currentLcmChannels() {
  const identifier = selectedDeviceIdentifier();
  const data = await api(`/device-admin/${encodeURIComponent(identifier)}/lcm-channels`);
  window.__lastLcmChannels = data.channels;
  return data.channels;
}

async function setLcmLight(channel, value) {
  try {
    const channels = await currentLcmChannels();
    const item = channels.find((entry) => entry.channel === channel);
    if (!item?.logical_name) throw new Error("Channel has no logical binding");
    pending.add(item.logical_name);
    await renderDeviceDetail(selectedDeviceIdentifier());
    await api("/device/command", {
      method: "POST",
      body: JSON.stringify({logical_name: item.logical_name, command: {op: "set_relay", value}}),
    });
    pending.delete(item.logical_name);
    await renderDeviceDetail(selectedDeviceIdentifier());
  } catch (error) {
    pending.clear();
    setError(error.message);
    await renderDeviceDetail(selectedDeviceIdentifier());
  }
}

async function setLcmDimmer(channel, percent) {
  try {
    const channels = await currentLcmChannels();
    const item = channels.find((entry) => entry.channel === channel);
    if (!item?.logical_name) throw new Error("Channel has no logical binding");
    pending.add(item.logical_name);
    await renderDeviceDetail(selectedDeviceIdentifier());
    await api("/device/command", {
      method: "POST",
      body: JSON.stringify({logical_name: item.logical_name, command: {op: "set_dimmer", percent}}),
    });
    pending.delete(item.logical_name);
    await renderDeviceDetail(selectedDeviceIdentifier());
  } catch (error) {
    pending.clear();
    setError(error.message);
    await renderDeviceDetail(selectedDeviceIdentifier());
  }
}

async function saveLcmSettings(channel) {
  try {
    const existing = lcmChannel(channel);
    if (!existing?.logical_name) throw new Error("Channel has no logical binding");
    const name = activeDialog.querySelector("[data-settings-name]").value;
    const emergencyLighting = activeDialog.querySelector("[data-settings-elight]").checked;
    const maintenanceLocked = activeDialog.querySelector("[data-settings-lock]").checked;
    const maxInput = activeDialog.querySelector("[data-settings-max]");
    const fadeInput = activeDialog.querySelector("[data-settings-fade]");
    if (!name.trim()) throw new Error("Channel name is required");
    await api(`/device-admin/${encodeURIComponent(selectedDeviceIdentifier())}/lcm-channels/${encodeURIComponent(channel)}/settings`, {
      method: "PATCH",
      body: JSON.stringify({
        name,
        emergency_lighting: emergencyLighting,
        max_intensity: maxInput ? Number(maxInput.value) : null,
        fade_seconds: fadeInput ? Number(fadeInput.value) : null,
      }),
    });
    if (existing && maintenanceLocked !== existing.maintenance_locked) {
      await api("/safety/maintenance-lockout", {
        method: "POST",
        body: JSON.stringify({logical_name: existing.logical_name, active: maintenanceLocked}),
      });
    }
    closeDialog();
    await renderDeviceDetail(selectedDeviceIdentifier());
  } catch (error) {
    setError(error.message);
  }
}

$("login").onclick = async () => {
  $("login-error").textContent = "";
  try {
    const data = await api("/auth/login", {
      method: "POST",
      body: JSON.stringify({username: $("username").value, password: $("password").value}),
    });
    token = data.token;
    localStorage.setItem("homecontrol_token", token);
    currentUser = await api("/auth/session");
    await detectPreviewMode();
    await renderRoute();
  } catch (error) {
    $("login-error").textContent = error.message;
  }
};

$("logout").onclick = () => {
  token = "";
  currentUser = null;
  localStorage.removeItem("homecontrol_token");
  showApp(false);
};

$("refresh-page").onclick = () => renderRoute();
window.onpopstate = () => renderRoute();

(async () => {
  if (!token) {
    showApp(false);
    return;
  }
  try {
    currentUser = await api("/auth/session");
    await detectPreviewMode();
    await renderRoute();
  } catch {
    token = "";
    localStorage.removeItem("homecontrol_token");
    showApp(false);
  }
})();
