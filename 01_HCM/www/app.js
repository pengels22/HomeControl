const $ = (id) => document.getElementById(id);
let token = localStorage.getItem("homecontrol_token") || "";
let registryState = {modules: [], logical_devices: [], device_bindings: []};

async function api(path, options = {}) {
  const headers = {"Content-Type": "application/json", ...(options.headers || {})};
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(`/api/v1${path}`, {...options, headers});
  const data = await response.json();
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

function showApp(show) {
  $("login-view").hidden = show;
  $("app-view").hidden = !show;
  $("logout").hidden = !show;
}

async function refreshHvac() {
  const hvac = await api("/hvac");
  $("hvac-mode").textContent = hvac.mode;
  $("hvac-setpoint").textContent = `${hvac.setpoint_f} F`;
  $("hvac-average").textContent = hvac.average_f == null ? "-" : `${hvac.average_f.toFixed(1)} F`;
  $("mode").value = hvac.mode;
  $("setpoint").value = hvac.setpoint_f;
}

async function refreshPairingKeys() {
  const data = await api("/pairing-keys");
  $("pairing-list").innerHTML = "";
  for (const item of data.pairing_keys) {
    const row = document.createElement("tr");
    row.innerHTML = `<td>${item.label}</td><td>${item.target_type}</td><td>${new Date(item.expires_at).toLocaleString()}</td><td>${item.used_at ? "Yes" : "No"}</td>`;
    $("pairing-list").appendChild(row);
  }
}

function statusPill(module) {
  const online = module.online || module.control_session_online;
  return `<span class="status-pill ${online ? "" : "offline"}">${online ? "Online" : "Offline"}</span>`;
}

async function refreshRegistry() {
  const [modules, logical, bindings] = await Promise.all([
    api("/modules"),
    api("/logical-devices"),
    api("/device-bindings"),
  ]);
  registryState = {
    modules: modules.modules || [],
    logical_devices: logical.logical_devices || [],
    device_bindings: bindings.device_bindings || [],
  };
  renderRegistry();
}

function renderRegistry() {
  $("module-list").innerHTML = registryState.modules.map((module) => {
    const caps = (module.capabilities || []).map((item) => item.capability).join(", ") || "-";
    const identity = module.device_id || module.module_uuid || "-";
    return `<tr>
      <td>${esc(module.hostname)}<br><span>${esc(module.module_type)}</span></td>
      <td>${esc(identity)}</td>
      <td>${esc(module.ip_address)}</td>
      <td>${statusPill(module)}</td>
      <td>${esc(caps)}</td>
    </tr>`;
  }).join("");

  $("logical-list").innerHTML = registryState.logical_devices.map((device) => `<tr>
    <td>${esc(device.logical_name)}</td>
    <td>${esc(device.device_class)}</td>
    <td>${device.enabled ? "Yes" : "No"}</td>
    <td>${device.maintenance_locked ? "Locked" : "-"}</td>
  </tr>`).join("");

  $("binding-list").innerHTML = registryState.device_bindings.map((binding) => `<tr>
    <td>${esc(binding.logical_name)}</td>
    <td>${esc(binding.module_hostname)}</td>
    <td>${esc(binding.channel || "-")}</td>
    <td>${esc(binding.binding_type)}</td>
  </tr>`).join("");

  $("binding-logical").innerHTML = registryState.logical_devices.map((device) =>
    `<option value="${esc(device.logical_name)}">${esc(device.logical_name)}</option>`
  ).join("");
  $("binding-module").innerHTML = registryState.modules.map((module) =>
    `<option value="${esc(module.hostname)}">${esc(module.hostname)}</option>`
  ).join("");
}

async function refreshAll() {
  $("app-error").textContent = "";
  await refreshHvac();
  await refreshPairingKeys();
  await refreshRegistry();
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
    showApp(true);
    await refreshAll();
  } catch (error) {
    $("login-error").textContent = error.message;
  }
};

$("logout").onclick = () => {
  token = "";
  localStorage.removeItem("homecontrol_token");
  showApp(false);
};

$("apply-hvac").onclick = async () => {
  try {
    await api("/hvac/mode", {method: "PUT", body: JSON.stringify({mode: $("mode").value})});
    await api("/hvac/setpoint", {method: "PUT", body: JSON.stringify({setpoint_f: Number($("setpoint").value)})});
    await refreshHvac();
  } catch (error) {
    $("app-error").textContent = error.message;
  }
};

$("create-pairing").onclick = async () => {
  try {
    const data = await api("/pairing-keys", {
      method: "POST",
      body: JSON.stringify({
        label: $("pair-label").value || $("pair-type").value,
        target_type: $("pair-type").value,
        ttl_minutes: 30,
      }),
    });
    $("pairing-output").hidden = false;
    $("pairing-output").textContent = `Pairing key for ${data.label}: ${data.pairing_key}`;
    await refreshPairingKeys();
  } catch (error) {
    $("app-error").textContent = error.message;
  }
};

$("refresh-registry").onclick = () => refreshRegistry().catch((error) => {
  $("app-error").textContent = error.message;
});

$("create-logical").onclick = async () => {
  try {
    await api("/logical-devices", {
      method: "POST",
      body: JSON.stringify({
        logical_name: $("logical-name").value,
        device_class: $("device-class").value,
      }),
    });
    $("logical-name").value = "";
    $("device-class").value = "";
    await refreshRegistry();
  } catch (error) {
    $("app-error").textContent = error.message;
  }
};

$("create-binding").onclick = async () => {
  try {
    await api("/device-bindings", {
      method: "POST",
      body: JSON.stringify({
        logical_name: $("binding-logical").value,
        module_identifier: $("binding-module").value,
        channel: $("binding-channel").value || null,
        binding_type: "primary",
      }),
    });
    $("binding-channel").value = "";
    await refreshRegistry();
  } catch (error) {
    $("app-error").textContent = error.message;
  }
};

(async () => {
  if (!token) {
    showApp(false);
    return;
  }
  try {
    showApp(true);
    await refreshAll();
  } catch {
    token = "";
    localStorage.removeItem("homecontrol_token");
    showApp(false);
  }
})();
