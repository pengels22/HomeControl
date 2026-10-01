const $ = (id) => document.getElementById(id);
let token = localStorage.getItem("homecontrol_token") || "";

async function api(path, options = {}) {
  const headers = {"Content-Type": "application/json", ...(options.headers || {})};
  if (token) headers.Authorization = `Bearer ${token}`;
  const response = await fetch(`/api/v1${path}`, {...options, headers});
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || JSON.stringify(data));
  return data;
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

async function refreshAll() {
  $("app-error").textContent = "";
  await refreshHvac();
  await refreshPairingKeys();
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
