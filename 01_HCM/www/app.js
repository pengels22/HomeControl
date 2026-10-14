const $ = (id) => document.getElementById(id);
let token = localStorage.getItem("homecontrol_token") || "";
let currentUser = null;
let lastModules = [];
let roleManagementByDevice = new Map();
let moduleRoleOptions = ["UNASSIGNED", "RCM", "SIM", "LCM"];
const pending = new Set();
let activeDialog = null;
let previewMode = false;

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
  return device.effective_role || moduleEffectiveRole(device.module || device);
}

function reportedRole(module) {
  return moduleEffectiveRole(module);
}

function moduleState(module) {
  return module?.last_state?.state || {};
}

function moduleEffectiveRole(module) {
  const state = moduleState(module);
  return state.lab_role || state.operational_role || state.role || module?.effective_role || module?.module_type || "UNASSIGNED";
}

function online(module) {
  return Boolean(module.online || module.control_session_online);
}

async function loadRegistry() {
  const data = await api("/modules");
  lastModules = data.modules || [];
  return lastModules;
}

async function loadRoleManagement() {
  try {
    const data = await api("/module-roles");
    moduleRoleOptions = data.roles || moduleRoleOptions;
    roleManagementByDevice = new Map((data.modules || []).map((module) => [module.device_id, module]));
    return data;
  } catch {
    roleManagementByDevice = new Map();
    return {modules: [], roles: moduleRoleOptions};
  }
}

function roleManagementFor(module) {
  return roleManagementByDevice.get(module?.device_id) || null;
}

function assignedRoleLabel(module) {
  const managed = roleManagementFor(module);
  const info = managed?.role_management;
  const transition = info?.last_transition;
  if (info?.requested_role) return `${info.requested_role} (${transition?.status || "requested"})`;
  if (transition?.requested_role) return `${transition.requested_role} (${transition.status || "recorded"})`;
  return "Unknown";
}

async function detectPreviewMode() {
  try {
    const data = await api("/preview-mode");
    previewMode = Boolean(data.preview);
    $("preview-banner").hidden = !previewMode;
  } catch {
    previewMode = false;
    $("preview-banner").hidden = true;
  }
}

function deviceLink(module) {
  return `/devices/${encodeURIComponent(module.hostname)}`;
}

async function renderDashboard() {
  setTitle("Overview", "Dashboard");
  $("content").innerHTML = `<div class="loading">Loading HCM health...</div>`;
  const [healthResult, hvacResult, modulesResult, logicalResult] = await Promise.allSettled([
    api("/health"),
    api("/hvac"),
    loadRegistry(),
    api("/dashboard/status"),
  ]);
  const health = settledValue(healthResult, {});
  const hvac = settledValue(hvacResult, null);
  const modules = settledValue(modulesResult, []);
  const dashboardStatus = settledValue(logicalResult, null);
  const onlineCount = modules.filter(online).length;
  const offlineModules = modules.filter((module) => !online(module));
  const lockoutItems = Array.isArray(dashboardStatus?.maintenance_lockouts?.items) ? dashboardStatus.maintenance_lockouts.items : null;
  const faultItems = Array.isArray(dashboardStatus?.active_faults?.items) ? dashboardStatus.active_faults.items : null;
  const maintenanceCount = lockoutItems ? Number(dashboardStatus.maintenance_lockouts.count ?? lockoutItems.length) : unavailableValue();
  const activeFaultCount = faultItems ? Number(dashboardStatus.active_faults.count ?? faultItems.length) : unavailableValue();
  const conflictSupervisor = dashboardStatus?.conflict_supervisor || health.heartbeat_supervisor || health.conflict_heartbeat || null;
  const conflictStatus = conflictSupervisor?.status || null;
  const fireStatus = health.fire_life_safety?.status || health.life_safety?.status || null;
  const conflictReported = statusKnown(conflictStatus);
  const fireReported = statusKnown(fireStatus);
  const moduleTotals = moduleTypeTotals(modules);
  const attention = attentionItems({
    offlineModules,
    maintenanceCount,
    activeFaultCount,
    conflictReported,
    conflictStatus,
    fireReported,
    healthOk: healthResult.status === "fulfilled" && Boolean(health.ok),
    hvacAvailable: hvacResult.status === "fulfilled",
  });
  $("content").innerHTML = `
    <section class="dashboard-grid">
      <article class="summary dashboard-card">
        <span>HCM Backend</span>
        <strong>${healthResult.status === "fulfilled" && health.ok ? "Healthy" : "Unavailable"}</strong>
        ${statusPill(healthResult.status === "fulfilled" && Boolean(health.ok), healthResult.status === "fulfilled" && health.ok ? "API responding" : "Check failed")}
      </article>
      <article class="summary dashboard-card">
        <span>Conflict Supervisor</span>
        <strong>${esc(conflictStatus || "Unavailable")}</strong>
        <p>${conflictStatusDetail(conflictSupervisor)}</p>
      </article>
      <article class="summary dashboard-card">
        <span>Modules</span>
        <strong>${modulesResult.status === "fulfilled" ? `${onlineCount}/${modules.length}` : "Unavailable"}</strong>
        <p>connected / registered</p>
      </article>
      <article class="summary dashboard-card">
        <span>Fire / Life Safety</span>
        <strong>${esc(fireStatus || "Unavailable")}</strong>
        <p>${fireReported ? "Reported by HCM health data" : "No safety status API value reported"}</p>
      </article>
      <button class="summary dashboard-card" type="button" data-open-lockouts>
        <span>Maintenance Lockouts</span>
        <strong>${displayMetric(maintenanceCount)}</strong>
        <p>${lockoutItems ? "active bound channel lockouts" : "Dashboard status API unavailable"}</p>
      </button>
      <button class="summary dashboard-card" type="button" data-open-faults>
        <span>Active Faults</span>
        <strong>${displayMetric(activeFaultCount)}</strong>
        <p>${faultItems ? "current active fault aggregation" : "Dashboard status API unavailable"}</p>
      </button>
      ${hvacSummaryCard(hvac, hvacResult.status === "fulfilled")}
    </section>
    <section class="dashboard-row">
      <section class="panel attention-panel">
        <div class="panel-head"><h3>Attention Required</h3><span class="muted">${attention.length} items</span></div>
        ${attention.length ? `<div class="attention-list">${attention.map(attentionItem).join("")}</div>` : `<div class="empty">No offline modules or reported abnormal conditions in the available HCM data.</div>`}
      </section>
      <section class="panel module-totals-panel">
        <div class="panel-head"><h3>Module Totals</h3><a class="text-link" href="/devices">Open Devices</a></div>
        <div class="module-totals">${moduleTotals.map(moduleTotalCard).join("") || `<div class="empty">No module registry data available.</div>`}</div>
      </section>
    </section>`;
}

function conflictStatusDetail(conflictSupervisor) {
  if (!conflictSupervisor) return "No authenticated supervisor status reported";
  const age = Number(conflictSupervisor.last_ack_age_seconds);
  if (Number.isFinite(age)) return `Last ACK ${Math.round(age)}s ago`;
  if (conflictSupervisor.host) return `${esc(conflictSupervisor.host)}:${esc(conflictSupervisor.port || "")}`;
  return esc(conflictSupervisor.reason || "Supervisor status unavailable");
}

function settledValue(result, fallback) {
  return result.status === "fulfilled" ? result.value : fallback;
}

function unavailableValue() {
  return Number.NaN;
}

function firstKnownNumber(...values) {
  for (const value of values) {
    const number = Number(value);
    if (Number.isFinite(number)) return number;
  }
  return unavailableValue();
}

function displayMetric(value) {
  return Number.isFinite(value) ? String(value) : "Unavailable";
}

function statusKnown(status) {
  const clean = String(status || "").trim().toLowerCase();
  return Boolean(clean) && !["unknown", "unavailable", "unsupported"].includes(clean);
}

function moduleTypeTotals(modules) {
  const counts = new Map();
  modules.forEach((module) => {
    const role = moduleEffectiveRole(module);
    const existing = counts.get(role) || {role, total: 0, online: 0};
    existing.total += 1;
    if (online(module)) existing.online += 1;
    counts.set(role, existing);
  });
  return [...counts.values()].sort((a, b) => a.role.localeCompare(b.role));
}

function moduleTotalCard(item) {
  return `<a class="module-total" href="/devices">
    <strong>${esc(item.role)}</strong>
    <span>${item.online}/${item.total} online</span>
  </a>`;
}

function attentionItems({offlineModules, maintenanceCount, activeFaultCount, conflictReported, conflictStatus, fireReported, healthOk, hvacAvailable}) {
  const items = [];
  offlineModules.forEach((module) => {
    items.push({level: "warn", title: `${module.hostname} offline`, detail: `${moduleEffectiveRole(module)} / ${module.supervision_state || "unknown"}`});
  });
  if (!healthOk) items.push({level: "critical", title: "HCM backend health unavailable", detail: "The health check did not return an OK response."});
  if (!hvacAvailable) items.push({level: "warn", title: "HVAC status unavailable", detail: "The authenticated HVAC API did not return current state."});
  if (!conflictReported) {
    items.push({level: "unknown", title: "Conflict supervisor status unavailable", detail: "HCM could not verify recent heartbeat acknowledgments from the authenticated dashboard status API."});
  } else if (["Degraded", "Offline"].includes(conflictStatus)) {
    items.push({level: conflictStatus === "Offline" ? "critical" : "warn", title: `Conflict supervisor ${conflictStatus.toLowerCase()}`, detail: "Review heartbeat acknowledgments before treating supervision as healthy."});
  }
  if (!fireReported) items.push({level: "unknown", title: "Fire/life-safety status unavailable", detail: "No authenticated HCM status value is exposed yet."});
  if (Number.isFinite(maintenanceCount) && maintenanceCount > 0) {
    items.push({level: "warn", title: `${maintenanceCount} maintenance lockout${maintenanceCount === 1 ? "" : "s"} active`, detail: "Controlled outputs remain inhibited by HCM safety lockout."});
  }
  if (Number.isFinite(activeFaultCount) && activeFaultCount > 0) {
    items.push({level: "critical", title: `${activeFaultCount} active fault${activeFaultCount === 1 ? "" : "s"}`, detail: "Review service diagnostics before clearing conditions."});
  }
  if (!Number.isFinite(activeFaultCount)) {
    items.push({level: "unknown", title: "Active fault count unavailable", detail: "No fault count API value is exposed yet."});
  }
  return items;
}

function attentionItem(item) {
  return `<article class="attention-item ${esc(item.level)}">
    <strong>${esc(item.title)}</strong>
    <span>${esc(item.detail)}</span>
  </article>`;
}

function hvacSummaryCard(hvac, available) {
  if (!available || !hvac) {
    return `<button class="summary dashboard-card hvac-card" type="button" data-open-hvac>
      <span>HVAC</span>
      <strong>Unavailable</strong>
      <p>Open thermostat controls</p>
    </button>`;
  }
  const mode = normalizeHvacMode(hvac.mode);
  const target = hvacTargetText(hvac);
  return `<button class="summary dashboard-card hvac-card" type="button" data-open-hvac aria-label="Open thermostat controls">
    <span>HVAC</span>
    <strong>${esc(mode.label)}</strong>
    <p>${esc(target)}</p>
    ${mode.value === "HEAT_COOL" ? `<p>${esc(hvacBandText(Number(hvac.setpoint_f)))}</p>` : ""}
  </button>`;
}

function normalizeHvacMode(mode) {
  const value = String(mode || "OFF").toUpperCase().replace(/[-\s/]+/g, "_");
  if (value === "AUTO" || value === "HEAT_COOL" || value === "HEATCOOL") return {value: "HEAT_COOL", label: "Heat/Cool"};
  if (value === "HEAT") return {value: "HEAT", label: "Heat"};
  if (value === "COOL") return {value: "COOL", label: "Cool"};
  if (value === "FAN") return {value: "FAN", label: "Fan"};
  return {value: "OFF", label: "Off"};
}

function hvacTargetText(hvac) {
  const target = Number(hvac?.setpoint_f);
  if (!Number.isFinite(target)) return "Target unavailable";
  return `${formatTemp(target)} target`;
}

function formatTemp(value) {
  return `${Math.round(Number(value))} F`;
}

function hvacBand(target) {
  return {heat: target - 3, cool: target + 2};
}

function hvacBandText(target) {
  if (!Number.isFinite(target)) return "Automatic range unavailable";
  const band = hvacBand(target);
  return `Heat at ${formatTemp(band.heat)} / Cool at ${formatTemp(band.cool)}`;
}

async function dashboardStatus() {
  return await api("/dashboard/status");
}

function groupBy(items, keyFn) {
  const groups = new Map();
  items.forEach((item) => {
    const key = keyFn(item) || "Unknown";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(item);
  });
  return [...groups.entries()];
}

function openLoadingDialog(title, message = "Loading current HCM status...") {
  modal(`<section class="modal detail-modal" role="dialog" aria-modal="true" aria-labelledby="detail-title">
    <div class="modal-head">
      <h3 id="detail-title">${esc(title)}</h3>
      <button type="button" class="secondary icon-button" data-close-dialog aria-label="Close">x</button>
    </div>
    <div class="loading">${esc(message)}</div>
  </section>`);
}

async function openLockoutsDialog() {
  openLoadingDialog("Maintenance Lockouts");
  try {
    const status = await dashboardStatus();
    const items = status.maintenance_lockouts?.items;
    if (!Array.isArray(items)) throw new Error("Maintenance lockout data is unavailable");
    modal(`<section class="modal detail-modal" role="dialog" aria-modal="true" aria-labelledby="lockouts-title">
      <div class="modal-head">
        <h3 id="lockouts-title">Maintenance Lockouts</h3>
        <button type="button" class="secondary icon-button" data-close-dialog aria-label="Close">x</button>
      </div>
      <p class="muted">${items.length} locked bound channel${items.length === 1 ? "" : "s"}</p>
      ${items.length ? `<div class="detail-groups">${groupBy(items, (item) => item.module).map(lockoutGroup).join("")}</div>` : `<div class="empty">No current maintenance lockouts reported by HCM.</div>`}
    </section>`);
  } catch (error) {
    modalUnavailable("Maintenance Lockouts", error.message);
  }
}

function lockoutGroup([module, items]) {
  return `<section class="detail-group">
    <h4>${esc(module)}</h4>
    <div class="detail-list">${items.map(lockoutItem).join("")}</div>
  </section>`;
}

function lockoutItem(item) {
  return `<a class="detail-item" href="/devices/${encodeURIComponent(item.module)}">
    <strong>${esc(item.channel_name || item.logical_name || item.channel || "Unnamed channel")}</strong>
    <div class="detail-fields">
      ${detailField("Module", item.module || "Unknown module")}
      ${detailField("Channel", item.channel || "Unknown")}
      ${detailField("Status", item.locked ? "Locked" : "Not locked")}
      ${item.reason ? detailField("Reason", item.reason) : ""}
      ${item.locked_at ? detailField("Locked at", item.locked_at) : ""}
    </div>
  </a>`;
}

async function openFaultsDialog() {
  openLoadingDialog("Active Faults");
  try {
    const status = await dashboardStatus();
    const items = status.active_faults?.items;
    if (!Array.isArray(items)) throw new Error("Active fault data is unavailable");
    modal(`<section class="modal detail-modal" role="dialog" aria-modal="true" aria-labelledby="faults-title">
      <div class="modal-head">
        <h3 id="faults-title">Active Faults</h3>
        <button type="button" class="secondary icon-button" data-close-dialog aria-label="Close">x</button>
      </div>
      <p class="muted">${items.length} current active fault${items.length === 1 ? "" : "s"}</p>
      ${items.length ? `<div class="detail-groups">${groupBy(items, (item) => item.module || item.component || item.source).map(faultGroup).join("")}</div>` : `<div class="empty">No current active faults reported by HCM.</div>`}
      ${status.active_faults?.unsupported_sources?.length ? `<div class="notice">${status.active_faults.unsupported_sources.map(esc).join("<br>")}</div>` : ""}
    </section>`);
  } catch (error) {
    modalUnavailable("Active Faults", error.message);
  }
}

function faultGroup([module, items]) {
  return `<section class="detail-group">
    <h4>${esc(module)}</h4>
    <div class="detail-list">${items.map(faultItem).join("")}</div>
  </section>`;
}

function faultItem(item) {
  const title = item.description || item.code || "Fault";
  const module = item.module ? `/devices/${encodeURIComponent(item.module)}` : null;
  const body = `<strong>${esc(title)}</strong>
    <div class="detail-fields">
      ${detailField("Severity", item.severity || "unknown")}
      ${item.module ? detailField("Module", item.module) : ""}
      ${item.component ? detailField("Component", item.component) : ""}
      ${item.code ? detailField("Code", item.code) : ""}
      ${item.reported_at ? detailField("Reported", item.reported_at) : ""}
      ${detailField("State", item.active === false ? "Cleared" : "Active")}
    </div>`;
  return module ? `<a class="detail-item ${esc(item.severity || "unknown")}" href="${module}">${body}</a>` : `<article class="detail-item ${esc(item.severity || "unknown")}">${body}</article>`;
}

function detailField(label, value) {
  return `<span class="detail-field"><span>${esc(label)}</span><strong>${esc(value ?? "Unknown")}</strong></span>`;
}

function modalUnavailable(title, message) {
  modal(`<section class="modal detail-modal" role="dialog" aria-modal="true" aria-labelledby="unavailable-title">
    <div class="modal-head">
      <h3 id="unavailable-title">${esc(title)}</h3>
      <button type="button" class="secondary icon-button" data-close-dialog aria-label="Close">x</button>
    </div>
    <div class="notice warn">Unavailable: ${esc(message)}</div>
    <div class="modal-actions"><button type="button" data-close-dialog>Close</button></div>
  </section>`);
}

function roleOptions(selected) {
  return (window.__authRoles || ["ADMIN", "READONLY"]).map((role) => `<option value="${esc(role)}" ${role === selected ? "selected" : ""}>${esc(role)}</option>`).join("");
}

function openAddUserDialog() {
  modal(`<section class="modal" role="dialog" aria-modal="true" aria-labelledby="add-user-title">
    <div class="modal-head">
      <h3 id="add-user-title">Add User</h3>
      <button type="button" class="secondary icon-button" data-close-dialog aria-label="Close">x</button>
    </div>
    <label>Username <input data-user-username autocomplete="off"></label>
    <label>Password <input type="password" data-user-password autocomplete="new-password"></label>
    <label>Confirm password <input type="password" data-user-password-confirm autocomplete="new-password"></label>
    <label>Role <select data-user-role>${roleOptions("READONLY")}</select></label>
    <div class="modal-error" role="status" aria-live="polite" data-user-modal-status></div>
    <div class="modal-actions">
      <button type="button" class="secondary" data-close-dialog>Cancel</button>
      <button type="button" data-save-add-user>Create</button>
    </div>
  </section>`);
}

function openChangeRoleDialog(username) {
  const user = (window.__lastUsers || []).find((item) => item.username === username);
  if (!user) return;
  modal(`<section class="modal" role="dialog" aria-modal="true" aria-labelledby="role-title">
    <div class="modal-head">
      <h3 id="role-title">Change Role</h3>
      <button type="button" class="secondary icon-button" data-close-dialog aria-label="Close">x</button>
    </div>
    <div class="diagnostic-grid">
      ${kv("Username", user.username)}
      ${kv("Current role", user.role)}
    </div>
    <label>New role <select data-user-role>${roleOptions(user.role)}</select></label>
    <div class="modal-error" role="status" aria-live="polite" data-user-modal-status></div>
    <div class="modal-actions">
      <button type="button" class="secondary" data-close-dialog>Cancel</button>
      <button type="button" data-save-role="${esc(user.username)}">Save</button>
    </div>
  </section>`);
}

function openResetPasswordDialog(username) {
  const user = (window.__lastUsers || []).find((item) => item.username === username);
  if (!user) return;
  modal(`<section class="modal" role="dialog" aria-modal="true" aria-labelledby="password-title">
    <div class="modal-head">
      <h3 id="password-title">Reset Password</h3>
      <button type="button" class="secondary icon-button" data-close-dialog aria-label="Close">x</button>
    </div>
    <div class="diagnostic-grid">${kv("Username", user.username)}</div>
    <label>New password <input type="password" data-user-password autocomplete="new-password"></label>
    <label>Confirm new password <input type="password" data-user-password-confirm autocomplete="new-password"></label>
    <div class="modal-error" role="status" aria-live="polite" data-user-modal-status></div>
    <div class="modal-actions">
      <button type="button" class="secondary" data-close-dialog>Cancel</button>
      <button type="button" data-save-password="${esc(user.username)}">Save</button>
    </div>
  </section>`);
}

function moduleRoleOptionList(selected) {
  return moduleRoleOptions.map((role) => `<option value="${esc(role)}" ${role === selected ? "selected" : ""}>${esc(role)}</option>`).join("");
}

function openModuleRoleDialog(deviceId) {
  const managed = roleManagementByDevice.get(deviceId);
  if (!managed) return;
  const info = managed.role_management || {};
  const current = reportedRole(managed);
  modal(`<section class="modal" role="dialog" aria-modal="true" aria-labelledby="module-role-title">
    <div class="modal-head">
      <h3 id="module-role-title">Change Module Role</h3>
      <button type="button" class="secondary icon-button" data-close-dialog aria-label="Close">x</button>
    </div>
    <div class="diagnostic-grid">
      ${kv("Hostname", managed.hostname)}
      ${kv("Device ID", managed.device_id)}
      ${kv("Registered type", managed.module_type)}
      ${kv("Reported role", current)}
      ${kv("Assigned/requested role", assignedRoleLabel(managed))}
      ${kv("Control session", managed.control_session_online ? "Authenticated" : "Unavailable")}
      ${kv("Simulation", info.simulation === true ? "Enabled" : info.simulation === false ? "Disabled" : "Unknown")}
      ${kv("Physical outputs", info.physical_outputs_enabled === true ? "Enabled" : info.physical_outputs_enabled === false ? "Disabled" : "Unknown")}
    </div>
    <label>Requested role <select data-module-role>${moduleRoleOptionList(current)}</select></label>
    <div class="notice warn">HCM will send this request to the authenticated module session and wait for the module acknowledgment. This does not enable physical outputs or create logical bindings.</div>
    <div class="modal-error" role="status" aria-live="polite" data-module-role-status></div>
    <div class="modal-actions">
      <button type="button" class="secondary" data-close-dialog>Cancel</button>
      <button type="button" data-save-module-role="${esc(deviceId)}">Request Role Change</button>
    </div>
  </section>`);
}

function moduleRoleStatus(message) {
  const status = activeDialog?.querySelector("[data-module-role-status]");
  if (status) status.textContent = message;
}

async function pollModuleRoleTransition(operationId) {
  let latest = null;
  for (let attempt = 0; attempt < 15; attempt += 1) {
    latest = await api(`/module-role-transitions/${encodeURIComponent(operationId)}`);
    if (["CONFIRMED", "REJECTED", "TIMED_OUT", "FAILED"].includes(latest.status)) return latest;
    moduleRoleStatus(`Transition ${latest.status.toLowerCase()}; waiting for module confirmation...`);
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  return latest;
}

async function saveModuleRole(deviceId) {
  const requestedRole = activeDialog.querySelector("[data-module-role]").value;
  const save = activeDialog.querySelector("[data-save-module-role]");
  try {
    if (save) {
      save.disabled = true;
      save.textContent = "Sending...";
    }
    moduleRoleStatus("Sending role request to HCM...");
    const transition = await api(`/modules/${encodeURIComponent(deviceId)}/role`, {
      method: "POST",
      body: JSON.stringify({requested_role: requestedRole, confirm: true}),
    });
    moduleRoleStatus(`Module acknowledged: ${transition.status}. Waiting for reported role confirmation...`);
    const final = await pollModuleRoleTransition(transition.operation_id);
    if (final?.status === "CONFIRMED") {
      closeDialog();
      await loadRoleManagement();
      await renderDeviceDetail(selectedDeviceIdentifier());
      return;
    }
    moduleRoleStatus(`Transition ${final?.status || transition.status}: ${final?.rejection_reason || final?.error || "No final confirmation yet."}`);
    if (save) {
      save.disabled = false;
      save.textContent = "Request Role Change";
    }
  } catch (error) {
    moduleRoleStatus(`Role change failed: ${error.message}`);
    setError(error.message);
    if (save) {
      save.disabled = false;
      save.textContent = "Request Role Change";
    }
  }
}

function userModalStatus(message) {
  const status = activeDialog?.querySelector("[data-user-modal-status]");
  if (status) status.textContent = message;
}

function matchingPasswords() {
  const password = activeDialog?.querySelector("[data-user-password]")?.value || "";
  const confirm = activeDialog?.querySelector("[data-user-password-confirm]")?.value || "";
  if (password !== confirm) throw new Error("Passwords do not match");
  return password;
}

async function saveAddUser() {
  try {
    const username = activeDialog.querySelector("[data-user-username]").value.trim();
    const role = activeDialog.querySelector("[data-user-role]").value;
    const password = matchingPasswords();
    if (!username) throw new Error("Username is required");
    await api("/auth/users", {
      method: "POST",
      body: JSON.stringify({username, password, role}),
    });
    closeDialog();
    await renderUsers();
    setError("User created.");
  } catch (error) {
    userModalStatus(error.message);
  }
}

async function saveUserRole(username) {
  try {
    const role = activeDialog.querySelector("[data-user-role]").value;
    await api(`/auth/users/${encodeURIComponent(username)}/role`, {
      method: "PATCH",
      body: JSON.stringify({role}),
    });
    closeDialog();
    await renderUsers();
    setError("User role updated.");
  } catch (error) {
    userModalStatus(error.message);
  }
}

async function saveUserPassword(username) {
  try {
    const password = matchingPasswords();
    await api(`/auth/users/${encodeURIComponent(username)}/password`, {
      method: "POST",
      body: JSON.stringify({password}),
    });
    closeDialog();
    await renderUsers();
    setError("Password reset. Existing sessions for that user were revoked.");
  } catch (error) {
    userModalStatus(error.message);
  }
}

async function saveGitSettings() {
  const status = document.querySelector("[data-git-status]");
  if (status) status.textContent = "Saving repository settings...";
  try {
    const pat = document.querySelector("[data-git-pat]")?.value || "";
    const enabled = Boolean(document.querySelector("[data-git-enabled]")?.checked);
    const result = await api(pat && enabled ? "/settings/github/connect" : "/settings/git", {
      method: pat && enabled ? "POST" : "PUT",
      body: JSON.stringify({
        commit_name: document.querySelector("[data-git-name]")?.value || "",
        commit_email: document.querySelector("[data-git-email]")?.value || "",
        repo_url: document.querySelector("[data-git-repo]")?.value || "",
        github_pat: pat,
        github_enabled: enabled,
      }),
    });
    if (status) status.textContent = result.status?.display || "Git Repository: Not Synced";
    const patInput = document.querySelector("[data-git-pat]");
    if (patInput) patInput.value = "";
  } catch (error) {
    if (status) status.textContent = `Save failed: ${error.message}`;
  }
}

async function disconnectGithub() {
  const status = document.querySelector("[data-git-status]");
  if (status) status.textContent = "Disconnecting GitHub...";
  try {
    const result = await api("/settings/github", {method: "DELETE"});
    if (status) status.textContent = result.status?.display || "Git Repository: Not Synced";
    await renderSettings();
  } catch (error) {
    if (status) status.textContent = `Disconnect failed: ${error.message}`;
  }
}

function deviceTable(modules) {
  if (!modules.length) return `<div class="empty">No registered devices returned by HCM.</div>`;
  return `<div class="table-wrap"><table>
    <thead><tr><th>Logical Hostname</th><th>Registered Role</th><th>Status</th><th>Physical Device ID</th><th>Heartbeat / Supervision</th></tr></thead>
    <tbody>${modules.map((module) => `
      <tr>
        <td><a href="${deviceLink(module)}">${esc(module.hostname)}</a></td>
        <td>${esc(moduleEffectiveRole(module))}${moduleEffectiveRole(module) !== module.module_type ? `<br><span>registered ${esc(module.module_type)}</span>` : ""}</td>
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
  const sync = device.config_sync;
  return `<section class="identity-grid">
    <div><span>Hostname</span><strong>${esc(module.hostname)}</strong></div>
    <div><span>Registered Module Type</span><strong>${esc(module.module_type)}</strong></div>
    <div><span>Assigned / Requested Role</span><strong>${esc(assignedRoleLabel(module))}</strong></div>
    <div><span>Reported Operational Role</span><strong>${esc(roleLabel(device))}</strong></div>
    <div><span>Status</span><strong>${online(module) ? "Online" : "Offline"}</strong></div>
    <div><span>Device ID</span><strong><code>${esc(module.device_id || "-")}</code></strong></div>
    <div><span>Control Session</span><strong>${module.control_session_online ? "Authenticated" : "Unavailable"}</strong></div>
    <div><span>Simulation</span><strong>${device.simulation === true ? "Enabled" : device.simulation === false ? "Disabled" : "Unknown"}</strong></div>
    <div><span>Physical Outputs</span><strong>${device.physical_outputs_enabled === true ? "Enabled" : device.physical_outputs_enabled === false ? "Disabled" : "Unknown"}</strong></div>
  </section>
  ${sync?.state && sync.state !== "synchronized" ? `<div class="notice warn">Configuration synchronization: ${esc(sync.state)}${sync.conflicts?.length ? ` (${sync.conflicts.length} conflict${sync.conflicts.length === 1 ? "" : "s"})` : ""}</div>` : ""}`;
}

async function renderDeviceDetail(identifier) {
  $("content").innerHTML = `<div class="loading">Resolving selected device through HCM...</div>`;
  const [device] = await Promise.all([
    api(`/device-admin/${encodeURIComponent(identifier)}`),
    loadRoleManagement(),
  ]);
  setTitle("Device", device.module.hostname);
  const role = roleLabel(device);
  if (role === "RCM") return renderRcm(device);
  if (role === "LCM") return renderLcm(device);
  if (role === "SIM") return renderSim(device);
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
      ${roleManagementBlock(device)}
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
      ${roleManagementBlock(data.device)}
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

function roleManagementBlock(device) {
  const module = device.module;
  const managed = roleManagementFor(module);
  const info = managed?.role_management;
  if (!managed || !info?.enabled) {
    return `<div class="role-admin-strip">
      <span>Module role administration</span>
      <strong>Unavailable</strong>
      <p>No verified backend role-switching contract is available for this physical device ID.</p>
    </div>`;
  }
  const admin = currentUser?.role === "ADMIN";
  const disabled = !admin || !module.control_session_online;
  const reason = !admin ? "ADMIN role required" : !module.control_session_online ? "Authenticated control session required" : "Uses permanent device ID";
  const transition = info.last_transition;
  return `<div class="role-admin-strip">
    <span>Module role administration</span>
    <strong>${esc(info.requested_role || transition?.status || "Ready")}</strong>
    <p>${esc(reason)}${transition?.requested_role ? `; latest request ${esc(transition.requested_role)} / ${esc(transition.status)}` : ""}</p>
    <button type="button" class="secondary compact-button" data-module-role-change="${esc(module.device_id)}" ${disabled ? "disabled" : ""}>Change Module Role</button>
  </div>`;
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
      ${roleManagementBlock(data.device)}
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

async function renderSim(device) {
  const data = await api(`/device-admin/${encodeURIComponent(device.module.hostname)}/sim-dashboard`);
  window.__lastSimDashboard = data;
  $("content").innerHTML = `
    <section class="panel">
      <div class="panel-head">
        <div>
          <h3>${esc(data.device.module.hostname)} - Sensor Interface Module</h3>
          <p class="device-subtitle">${simCanSubtitle(data.can_loops)}</p>
        </div>
        ${statusPill(online(data.device.module))}
      </div>
      ${identityBlock(data.device)}
      ${roleManagementBlock(data.device)}
    </section>
    <section class="panel sim-panel">
      <div class="panel-head">
        <h3>Room Clusters</h3>
        <span class="muted">${data.rmcs.length} RMC nodes</span>
      </div>
      <div class="rmc-grid">${data.rmcs.length ? data.rmcs.map(rmcCard).join("") : `<div class="empty">No RMC telemetry reported for this SIM.</div>`}</div>
    </section>
    <section class="panel sim-panel">
      <div class="panel-head">
        <h3>Analog Inputs</h3>
        <span class="muted">${data.analog_inputs.length} physical inputs</span>
      </div>
      <div class="sim-ai-grid">${data.analog_inputs.map(analogInputCard).join("")}</div>
    </section>
    <section class="panel sim-panel">
      <details>
        <summary>SIM Diagnostics</summary>
        <div class="sim-diagnostics">
          ${data.can_loops.map(canDiagnostic).join("")}
          <div><span>Hexa board</span><strong>${esc(data.diagnostics.hexa_board_model || "Unknown")}</strong></div>
          <div><span>I/O mode</span><strong>${esc(data.diagnostics.io_mode || "Unknown")}</strong></div>
        </div>
      </details>
    </section>`;
}

function simCanSubtitle(loops) {
  return loops.map((loop) => `<span class="can-status ${simStatusClass(loop.status)}"><span aria-hidden="true"></span>CAN ${esc(loop.label)}: ${esc(loop.status || "Unknown")}</span>`).join(" · ");
}

function simStatusClass(status) {
  const clean = String(status || "Unknown").toLowerCase();
  if (clean === "online") return "online";
  if (clean === "fault") return "fault";
  if (clean === "offline") return "offline";
  if (clean === "stale") return "stale";
  return "unknown";
}

function rmcCard(rmc) {
  return `<article class="rmc-card ${simStatusClass(rmc.status)}">
    <div class="rmc-head">
      <div class="rmc-title-block">
        <strong>${esc(rmc.name || rmc.id)}</strong>
        <span>${esc(rmc.id)} / ${esc(rmc.can_interface || "Unknown")}</span>
      </div>
      <div class="rmc-actions">
        <span class="status-chip ${simStatusClass(rmc.status)}">${esc(rmc.status || "Unknown")}</span>
        <button class="icon-button cog-button" type="button" data-sim-rmc-settings="${esc(rmc.id)}" aria-label="Open ${esc(rmc.name || rmc.id)} settings">⚙</button>
      </div>
    </div>
    <div class="rmc-readings">
      ${readingCell("Temp", rmc.readings.temperature_f, (value) => `${value} F`)}
      ${readingCell("Humidity", rmc.readings.humidity_pct, (value) => `${value}%`)}
      ${readingCell("Light", rmc.readings.lux, (value) => `${value} lux`)}
      ${readingCell("AQI", rmc.readings.aqi, (value) => `${value}`)}
      ${readingCell("Presence", rmc.readings.presence, (value) => value ? "Detected" : "Clear")}
    </div>
  </article>`;
}

function readingCell(label, reading, format) {
  const status = reading?.status || "Unknown";
  const value = reading?.value;
  const text = value === null || value === undefined ? status : format(value);
  return `<div class="reading ${simStatusClass(status)}"><span>${esc(label)}</span><strong>${esc(text)}</strong></div>`;
}

function kv(label, value) {
  return `<div><span>${esc(label)}</span><strong>${esc(value ?? "Unknown")}</strong></div>`;
}

function analogInputCard(input) {
  const value = input.value === null || input.value === undefined ? "Unknown" : `${input.value} ${input.unit || ""}`.trim();
  return `<article class="ai-card ${input.bound ? "" : "disabled"}">
    <div class="lcm-channel-main">
      <button class="channel-title" type="button" data-sim-ai-settings="${esc(input.channel)}" ${input.config_enabled ? "" : "disabled"}>${esc(input.name || "Unbound")}</button>
      <span class="channel-meta">${esc(input.channel)}${input.firmware_channel ? ` / ${esc(input.firmware_channel)}` : ""}</span>
    </div>
    <div class="ai-reading">
      <strong>${esc(value)}</strong>
      <span>${esc(input.disabled_reason || input.status || "Unknown")}</span>
    </div>
  </article>`;
}

function canDiagnostic(loop) {
  return `<div>
    <span>CAN ${esc(loop.label)} / ${esc(loop.interface || "Unknown")}</span>
    <strong>${esc(loop.status || "Unknown")}</strong>
  </div>`;
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

async function renderSettings() {
  setTitle("Configuration", "Settings");
  $("content").innerHTML = `<div class="loading">Loading network settings...</div>`;
  const [networkResult, gitResult] = await Promise.allSettled([
    api("/settings/network"),
    api("/settings/git"),
  ]);
  if (networkResult.status !== "fulfilled") throw networkResult.reason;
  const data = networkResult.value;
  const git = gitResult.status === "fulfilled" ? gitResult.value : null;
  const interfaces = data.host_interfaces?.interfaces || [];
  const modules = data.modules || [];
  $("content").innerHTML = `
    <section class="panel">
      <div class="panel-head">
        <h3>HCM Network Interfaces</h3>
        <span class="muted">${data.host_interfaces?.available ? "Host provider" : "Unavailable"}</span>
      </div>
      ${data.host_interfaces?.available ? interfaceTable(interfaces) : `<div class="notice warn">${esc(data.host_interfaces?.reason || "Host interface data is unavailable")}</div>`}
    </section>
    <section class="panel">
      <div class="panel-head">
        <h3>Registered Module Network Access</h3>
        <span class="muted">${modules.length} registered modules</span>
      </div>
      ${moduleNetworkTable(modules)}
    </section>
    <section class="panel">
      <div class="panel-head">
        <h3>Configuration Repository</h3>
        <span class="muted">${git ? esc(git.status?.display || "Git Repository: Not Synced") : "Unavailable"}</span>
      </div>
      ${git ? gitSettingsForm(git) : `<div class="notice warn">Git repository settings are unavailable for this account or HCM instance.</div>`}
    </section>`;
}

function gitSettingsForm(git) {
  return `<div class="settings-grid">
    <label>Commit name <input data-git-name value="${esc(git.commit_name || "")}" autocomplete="off"></label>
    <label>Commit email <input data-git-email value="${esc(git.commit_email || "")}" autocomplete="off"></label>
    <label>GitHub repository URL <input data-git-repo value="${esc(git.repo_url || "")}" placeholder="https://github.com/owner/repo.git" autocomplete="off"></label>
    <label>Personal access token <input data-git-pat type="password" placeholder="${git.github_token_configured ? "Configured" : "Not configured"}" autocomplete="off"></label>
  </div>
  <label class="settings-check"><input type="checkbox" data-git-enabled ${git.github_enabled ? "checked" : ""}> Enable GitHub sync when configured</label>
  <div class="modal-actions inline-actions">
    <button type="button" class="secondary" data-disconnect-github ${git.github_enabled || git.github_token_configured ? "" : "disabled"}>Disconnect GitHub</button>
    <button type="button" data-save-git-settings>Save Repository Settings</button>
  </div>
  <p class="muted" data-git-status>${esc(git.status?.display || "Git Repository: Not Synced")}</p>`;
}

async function renderUsers() {
  setTitle("Access", "Users");
  const session = currentUser || await api("/auth/session");
  currentUser = session;
  if (session.role !== "ADMIN") {
    $("content").innerHTML = `<section class="panel"><h3>User Management</h3><div class="notice warn">Your account can view the current session, but user administration requires an ADMIN role.</div>${sessionBlock(session)}</section>`;
    return;
  }
  $("content").innerHTML = `<div class="loading">Loading users...</div>`;
  const data = await api("/auth/users");
  window.__lastUsers = data.users || [];
  window.__authRoles = data.roles || ["ADMIN", "READONLY"];
  $("content").innerHTML = `
    <section class="panel">
      <div class="panel-head">
        <h3>User Management</h3>
        <button type="button" data-add-user>Add User</button>
      </div>
      ${sessionBlock(session)}
      ${userTable(window.__lastUsers)}
    </section>`;
}

function interfaceTable(interfaces) {
  if (!interfaces.length) return `<div class="empty">No HCM host interfaces reported.</div>`;
  return `<div class="table-wrap"><table>
    <thead><tr><th>Interface</th><th>IPv4</th><th>IPv6</th><th>Status</th><th>Network</th><th>Default route</th></tr></thead>
    <tbody>${interfaces.map((item) => `<tr>
      <td><code>${esc(item.name)}</code></td>
      <td>${addressList(item.ipv4)}</td>
      <td>${addressList(item.ipv6)}</td>
      <td>${esc(item.status || "Unknown")}</td>
      <td>${esc(item.network || "Unknown")}</td>
      <td>${item.default_route ? esc([item.default_route.gateway, item.default_route.interface].filter(Boolean).join(" via ")) : "Unknown"}</td>
    </tr>`).join("")}</tbody>
  </table></div>`;
}

function addressList(addresses) {
  const list = Array.isArray(addresses) ? addresses : addresses ? [addresses] : [];
  return list.length ? list.map((item) => `<code>${esc(item)}</code>`).join("<br>") : "Unknown";
}

function moduleNetworkTable(modules) {
  if (!modules.length) return `<div class="empty">No registered modules returned by HCM.</div>`;
  return `<div class="table-wrap"><table>
    <thead><tr><th>Module</th><th>Type</th><th>IP Address</th><th>Status</th><th>Emergency UI</th></tr></thead>
    <tbody>${modules.map((module) => `<tr>
      <td><a href="/devices/${encodeURIComponent(module.hostname)}">${esc(module.hostname)}</a></td>
      <td>${esc(module.effective_role || module.module_type || "UNASSIGNED")}</td>
      <td>${module.ip_address ? `<code>${esc(module.ip_address)}</code><br><span>${esc(module.address_source || "unknown")}</span>` : "Unknown"}</td>
      <td>${statusPill(module.online, module.status || (module.online ? "Online" : "Offline"))}</td>
      <td>${emergencyLink(module.emergency_interface)}</td>
    </tr>`).join("")}</tbody>
  </table></div>`;
}

function emergencyLink(emergency) {
  if (emergency?.available && emergency.url) {
    return `<a class="button-link" href="${esc(emergency.url)}" target="_blank" rel="noopener noreferrer">Open</a>`;
  }
  return `<button type="button" class="secondary compact-button" disabled title="${esc(emergency?.reason || "Emergency interface unavailable")}">Unavailable</button>`;
}

function sessionBlock(session) {
  return `<div class="identity-grid"><div><span>Signed in as</span><strong>${esc(session.user)}</strong></div><div><span>Role</span><strong>${esc(session.role)}</strong></div></div>`;
}

function userTable(users) {
  if (!users.length) return `<div class="empty">No users returned by HCM.</div>`;
  return `<div class="table-wrap"><table>
    <thead><tr><th>Username</th><th>Role</th><th>Status</th><th>Actions</th></tr></thead>
    <tbody>${users.map((user) => `<tr>
      <td>${esc(user.username)}</td>
      <td>${esc(user.role)}</td>
      <td>${user.enabled ? "Enabled" : "Disabled"}</td>
      <td class="actions-cell">
        <button type="button" class="secondary compact-button" data-change-role="${esc(user.username)}">Change Role</button>
        <button type="button" class="secondary compact-button" data-reset-password="${esc(user.username)}">Reset Password</button>
      </td>
    </tr>`).join("")}</tbody>
  </table></div>`;
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

function simRmc(rmcId) {
  return (window.__lastSimDashboard?.rmcs || []).find((item) => item.id === rmcId);
}

function simAnalog(channelId) {
  return (window.__lastSimDashboard?.analog_inputs || []).find((item) => item.channel === channelId);
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

function openSimRmcDialog(rmcId) {
  const rmc = simRmc(rmcId);
  if (!rmc) return;
  const nameField = rmc.bound
    ? `<label>RMC name <input value="${esc(rmc.name || "")}" data-sim-name></label>`
    : `<div class="notice warn">This RMC is not bound to a logical device. Diagnostics are read-only until HCM has a valid binding.</div>`;
  const actions = rmc.bound
    ? `<button type="button" class="secondary" data-close-dialog>Cancel</button><button type="button" data-save-sim-rmc="${esc(rmc.id)}">Save</button>`
    : `<button type="button" data-close-dialog>Close</button>`;
  modal(`<section class="modal" role="dialog" aria-modal="true" aria-labelledby="sim-rmc-title">
    <div class="modal-head">
      <h3 id="sim-rmc-title">${esc(rmc.name || rmc.id)}</h3>
      <button type="button" class="secondary icon-button" data-close-dialog aria-label="Close">x</button>
    </div>
    ${nameField}
    <div class="diagnostic-grid">
      ${kv("Logical ID", rmc.logical_identifier)}
      ${kv("Permanent ID", rmc.id)}
      ${kv("CAN loop", rmc.can_interface)}
      ${kv("CAN node", rmc.can_node_address)}
      ${kv("Room", rmc.room)}
      ${kv("Last heartbeat", rmc.last_heartbeat)}
      ${kv("Last seen", rmc.last_seen)}
      ${kv("Firmware", rmc.firmware_version)}
      ${kv("Hardware", rmc.hardware_revision)}
      ${kv("Health flags", rmc.health_flags)}
      ${kv("Faults", rmc.faults?.length ? rmc.faults.join(", ") : "None")}
      ${kv("Binding", rmc.bound ? "Bound" : "Unbound")}
    </div>
    <div class="modal-actions">
      ${actions}
    </div>
  </section>`);
}

function openSimAnalogDialog(channelId) {
  const input = simAnalog(channelId);
  if (!input || !input.config_enabled) return;
  modal(`<section class="modal" role="dialog" aria-modal="true" aria-labelledby="sim-ai-title">
    <div class="modal-head">
      <h3 id="sim-ai-title">${esc(input.name || input.channel)}</h3>
      <button type="button" class="secondary icon-button" data-close-dialog aria-label="Close">x</button>
    </div>
    <label>Input name <input value="${esc(input.name || "")}" data-sim-name></label>
    <div class="diagnostic-grid">
      ${kv("Physical input", input.channel)}
      ${kv("Firmware input", input.firmware_channel)}
      ${kv("Source", input.source)}
      ${kv("Unit", input.unit)}
    </div>
    <div class="modal-actions">
      <button type="button" class="secondary" data-close-dialog>Cancel</button>
      <button type="button" data-save-sim-ai="${esc(input.channel)}">Save</button>
    </div>
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

async function openHvacDialog() {
  let hvac = null;
  try {
    hvac = await api("/hvac");
  } catch (error) {
    modal(`<section class="modal thermostat-modal" role="dialog" aria-modal="true" aria-labelledby="hvac-title">
      <div class="modal-head">
        <h3 id="hvac-title">Thermostat</h3>
        <button type="button" class="secondary icon-button" data-close-dialog aria-label="Close">x</button>
      </div>
      <div class="notice warn">HVAC status is unavailable: ${esc(error.message)}</div>
      <div class="modal-actions"><button type="button" data-close-dialog>Close</button></div>
    </section>`);
    return;
  }
  const mode = normalizeHvacMode(hvac.mode);
  const target = Number.isFinite(Number(hvac.setpoint_f)) ? Number(hvac.setpoint_f) : 70;
  modal(`<section class="modal thermostat-modal" role="dialog" aria-modal="true" aria-labelledby="hvac-title">
    <div class="modal-head">
      <h3 id="hvac-title">Thermostat</h3>
      <button type="button" class="secondary icon-button" data-close-dialog aria-label="Close">x</button>
    </div>
    <div class="thermostat-status">
      <div><span>Requested mode</span><strong>${esc(mode.label)}</strong></div>
      <div><span>Target</span><strong>${esc(hvacTargetText(hvac))}</strong></div>
      <div><span>Equipment state</span><strong>${esc(equipmentStateText(hvac))}</strong></div>
    </div>
    <fieldset class="mode-grid" aria-label="Requested HVAC mode">
      ${hvacModeOption("HEAT", "Heat", mode.value)}
      ${hvacModeOption("COOL", "Cool", mode.value)}
      ${hvacModeOption("HEAT_COOL", "Heat/Cool", mode.value)}
      ${hvacModeOption("FAN", "Fan", mode.value)}
      ${hvacModeOption("OFF", "Off", mode.value)}
    </fieldset>
    <label class="target-control" data-hvac-target-wrap>Target temperature
      <input type="number" min="45" max="90" step="1" value="${esc(target)}" data-hvac-target aria-describedby="hvac-thresholds">
    </label>
    <div class="threshold-preview" id="hvac-thresholds" data-hvac-thresholds>${esc(hvacBandText(target))}</div>
    <div class="notice warn" data-hvac-gap ${previewMode ? "hidden" : ""}>Heat/Cool is not supported by the current production HCM HVAC API. It is available here only as a frontend preview state.</div>
    <div class="modal-error" role="status" aria-live="polite" data-hvac-modal-status></div>
    <div class="modal-actions">
      <button type="button" class="secondary" data-close-dialog>Cancel</button>
      <button type="button" data-save-hvac>Apply</button>
    </div>
  </section>`);
  syncHvacDialog();
}

function hvacModeOption(value, label, selected) {
  return `<label class="mode-option">
    <input type="radio" name="hvac-mode" value="${esc(value)}" ${value === selected ? "checked" : ""}>
    <span>${esc(label)}</span>
  </label>`;
}

function equipmentStateText(hvac) {
  const active = [];
  if (hvac.heat) active.push("heat output");
  if (hvac.cool) active.push("cool output");
  if (hvac.fan) active.push("fan");
  return active.length ? active.join(", ") : "No active equipment reported";
}

function selectedHvacMode() {
  return activeDialog?.querySelector("input[name='hvac-mode']:checked")?.value || "OFF";
}

function syncHvacDialog() {
  if (!activeDialog) return;
  const mode = selectedHvacMode();
  const targetInput = activeDialog.querySelector("[data-hvac-target]");
  const targetWrap = activeDialog.querySelector("[data-hvac-target-wrap]");
  const thresholds = activeDialog.querySelector("[data-hvac-thresholds]");
  const gap = activeDialog.querySelector("[data-hvac-gap]");
  const save = activeDialog.querySelector("[data-save-hvac]");
  const usesTemperature = ["HEAT", "COOL", "HEAT_COOL"].includes(mode);
  const target = Number(targetInput?.value);
  if (targetInput) targetInput.disabled = !usesTemperature;
  if (targetWrap) targetWrap.classList.toggle("disabled", !usesTemperature);
  if (thresholds) {
    thresholds.hidden = mode !== "HEAT_COOL";
    thresholds.textContent = hvacBandText(target);
  }
  if (gap) gap.hidden = previewMode || mode !== "HEAT_COOL";
  if (save) save.disabled = !previewMode && mode === "HEAT_COOL";
}

async function saveHvacSettings() {
  if (!activeDialog) return;
  const mode = selectedHvacMode();
  const target = Number(activeDialog.querySelector("[data-hvac-target]")?.value);
  const status = activeDialog.querySelector("[data-hvac-modal-status]");
  const save = activeDialog.querySelector("[data-save-hvac]");
  const usesTemperature = ["HEAT", "COOL", "HEAT_COOL"].includes(mode);
  if (mode === "HEAT_COOL" && !previewMode) {
    if (status) status.textContent = "Heat/Cool is not supported by the current HCM HVAC backend.";
    return;
  }
  if (usesTemperature && !Number.isFinite(target)) {
    if (status) status.textContent = "Enter a valid target temperature.";
    return;
  }
  try {
    if (save) {
      save.disabled = true;
      save.textContent = "Applying...";
    }
    if (status) status.textContent = "Applying thermostat request...";
    if (usesTemperature) {
      await api("/hvac/setpoint", {
        method: "PUT",
        body: JSON.stringify({setpoint_f: target}),
      });
    }
    await api("/hvac/mode", {
      method: "PUT",
      body: JSON.stringify({mode}),
    });
    closeDialog();
    await renderDashboard();
  } catch (error) {
    if (status) status.textContent = `HVAC command failed: ${error.message}`;
    if (save) {
      save.disabled = false;
      save.textContent = "Apply";
    }
    setError(error.message);
  }
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
    if (parts[0] === "service") return go("/dashboard");
    if (parts[0] === "settings") return await renderSettings();
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
  const hvacOpen = event.target.closest("[data-open-hvac]");
  if (hvacOpen) {
    await openHvacDialog();
    return;
  }
  const lockoutsOpen = event.target.closest("[data-open-lockouts]");
  if (lockoutsOpen) {
    await openLockoutsDialog();
    return;
  }
  const faultsOpen = event.target.closest("[data-open-faults]");
  if (faultsOpen) {
    await openFaultsDialog();
    return;
  }
  const addUser = event.target.closest("[data-add-user]");
  if (addUser) {
    openAddUserDialog();
    return;
  }
  const changeRole = event.target.closest("[data-change-role]");
  if (changeRole) {
    openChangeRoleDialog(changeRole.dataset.changeRole);
    return;
  }
  const moduleRoleChange = event.target.closest("[data-module-role-change]");
  if (moduleRoleChange) {
    openModuleRoleDialog(moduleRoleChange.dataset.moduleRoleChange);
    return;
  }
  const resetPassword = event.target.closest("[data-reset-password]");
  if (resetPassword) {
    openResetPasswordDialog(resetPassword.dataset.resetPassword);
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
  const simRmcSettings = event.target.closest("[data-sim-rmc-settings]");
  if (simRmcSettings) {
    openSimRmcDialog(simRmcSettings.dataset.simRmcSettings);
    return;
  }
  const simAiSettings = event.target.closest("[data-sim-ai-settings]");
  if (simAiSettings) {
    openSimAnalogDialog(simAiSettings.dataset.simAiSettings);
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
    return;
  }
  const saveSimRmc = event.target.closest("[data-save-sim-rmc]");
  if (saveSimRmc) {
    await saveSimRmcSettings(saveSimRmc.dataset.saveSimRmc);
    return;
  }
  const saveSimAi = event.target.closest("[data-save-sim-ai]");
  if (saveSimAi) {
    await saveSimAnalogSettings(saveSimAi.dataset.saveSimAi);
    return;
  }
  const saveHvac = event.target.closest("[data-save-hvac]");
  if (saveHvac) {
    await saveHvacSettings();
    return;
  }
  const saveAdd = event.target.closest("[data-save-add-user]");
  if (saveAdd) {
    await saveAddUser();
    return;
  }
  const saveRole = event.target.closest("[data-save-role]");
  if (saveRole) {
    await saveUserRole(saveRole.dataset.saveRole);
    return;
  }
  const saveModuleRoleButton = event.target.closest("[data-save-module-role]");
  if (saveModuleRoleButton) {
    await saveModuleRole(saveModuleRoleButton.dataset.saveModuleRole);
    return;
  }
  const savePassword = event.target.closest("[data-save-password]");
  if (savePassword) {
    await saveUserPassword(savePassword.dataset.savePassword);
    return;
  }
  const saveGit = event.target.closest("[data-save-git-settings]");
  if (saveGit) {
    await saveGitSettings();
    return;
  }
  const disconnectGitHub = event.target.closest("[data-disconnect-github]");
  if (disconnectGitHub) {
    await disconnectGithub();
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
  if (slider) {
    const readout = activeDialog?.querySelector("[data-dimmer-readout]");
    if (readout) readout.textContent = `${slider.value}%`;
    return;
  }
  if (event.target.closest("[data-hvac-target]")) {
    syncHvacDialog();
  }
});

document.addEventListener("change", async (event) => {
  if (event.target.closest("input[name='hvac-mode']")) {
    syncHvacDialog();
    return;
  }
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

async function currentSimDashboard() {
  const identifier = selectedDeviceIdentifier();
  const data = await api(`/device-admin/${encodeURIComponent(identifier)}/sim-dashboard`);
  window.__lastSimDashboard = data;
  return data;
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

async function saveSimRmcSettings(rmcId) {
  try {
    const name = activeDialog.querySelector("[data-sim-name]").value.trim();
    if (!name) throw new Error("Name is required");
    await api(`/device-admin/${encodeURIComponent(selectedDeviceIdentifier())}/sim-rmcs/${encodeURIComponent(rmcId)}/settings`, {
      method: "PATCH",
      body: JSON.stringify({name}),
    });
    closeDialog();
    await renderDeviceDetail(selectedDeviceIdentifier());
  } catch (error) {
    setError(error.message);
  }
}

async function saveSimAnalogSettings(channel) {
  try {
    const name = activeDialog.querySelector("[data-sim-name]").value.trim();
    if (!name) throw new Error("Name is required");
    await api(`/device-admin/${encodeURIComponent(selectedDeviceIdentifier())}/sim-analog-inputs/${encodeURIComponent(channel)}/settings`, {
      method: "PATCH",
      body: JSON.stringify({name}),
    });
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
