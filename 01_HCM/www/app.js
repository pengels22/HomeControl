const $ = (id) => document.getElementById(id);
let token = localStorage.getItem("homecontrol_token") || "";
let currentUser = null;
let lastModules = [];
const pending = new Set();

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
  if (role === "LCM") return renderRoleShell(device, "Lighting Control Module");
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
