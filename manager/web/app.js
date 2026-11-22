/** Manage a complete real station; depends on same-origin JSON APIs and native service status. */
const $ = (selector) => document.querySelector(selector);
let lastStatus;
let lastJob;
let savedConfiguration;
let updateSignature = "";
async function api(path, method = "GET", body) {
  const response = await fetch(`/api/${path}`, {
    method,
    headers: method === "GET" ? {} : { "Content-Type": "application/json" },
    ...(body !== undefined ? { body: JSON.stringify(body) } : {}),
  });
  const value = await response.json();
  if (!response.ok)
    throw new Error(value.error || value.detail || "The request failed.");
  return value;
}
function notice(message, error = false) {
  $("#notice").textContent = message;
  $("#notice").hidden = !message;
  $("#notice").classList.toggle("error", error);
}
async function perform(action) {
  try {
    await api(action, "POST", {});
    notice("Operation started. Follow its progress in Activity.");
    await refresh();
  } catch (error) {
    notice(error.message, true);
  }
}
function cell(row, text, className = "") {
  const td = document.createElement("td");
  td.textContent = text;
  td.className = className;
  row.append(td);
}
function renderComponents(status) {
  const tbody = $("#components");
  tbody.replaceChildren();
  for (const item of status.updates.components) {
    const row = document.createElement("tr");
    cell(row, item.name);
    cell(row, status.installed[item.key]?.tag || "Not installed");
    cell(row, item.latest?.tag || "Checking");
    cell(
      row,
      item.error ||
        (item.update_available
          ? "Update available"
          : status.installed[item.key]
            ? "Up to date"
            : "Included in setup"),
      item.error ? "bad" : item.update_available ? "warning" : "",
    );
    tbody.append(row);
  }
}
async function refresh() {
  try {
    const status = await api("status");
    lastStatus = status;
    const installed = Object.keys(status.installed).length > 0;
    const running = status.job?.status === "running";
    const updates = status.updates.components.filter(
      (item) => item.update_available,
    );
    $("#version").textContent = `v${status.version}`;
    $("#update-count").textContent = updates.length;
    $("#installation-state").textContent = installed
      ? "Installed"
      : "Ready for setup";
    $("#install").hidden = installed;
    $("#update-all").hidden =
      !installed || (!updates.length && !status.configuration_pending);
    $("#update-all").textContent = updates.length
      ? "Update All"
      : "Apply configuration";
    for (const id of ["start", "stop", "open-app"])
      $(`#${id}`).hidden = !installed;
    $("#open-app").href = status.application_url;
    $("#recover").hidden = !status.recovery_required;
    for (const button of document.querySelectorAll(
      ".toolbar button,#configuration button",
    ))
      button.disabled = running;
    if (status.recovery_required) {
      for (const id of ["install", "update-all", "start", "stop"])
        $(`#${id}`).disabled = true;
      notice(
        "An interrupted operation requires recovery before continuing.",
        true,
      );
    }
    renderComponents(status);
    const signature = updates
      .map((item) => `${item.key}:${item.latest?.tag}`)
      .join(",");
    if (installed && signature && signature !== updateSignature && !running)
      notice(
        `${updates.length} published update${updates.length === 1 ? "" : "s"} available. Click Update All when ready.`,
      );
    updateSignature = signature;
    const job = status.job;
    $("#job-status").textContent = job?.status || "Idle";
    $("#job-title").textContent = job?.name || "Activity";
    if (job) {
      $("#events").textContent =
        job.events
          .map(
            (event) =>
              `${new Date(event.at).toLocaleTimeString()}  ${event.message}`,
          )
          .join("\n") || "Preparing operation…";
      if (job.error) $("#events").textContent += `\n\n${job.error}`;
      if (lastJob !== `${job.id}:${job.status}`) {
        if (job.status === "failed" || job.status === "interrupted")
          notice(job.error, true);
        if (job.status === "completed") {
          if (!updates.length) notice("Operation completed.");
          refreshServices();
        }
        lastJob = `${job.id}:${job.status}`;
      }
    }
  } catch (error) {
    notice(`Cannot reach the Manager: ${error.message}`, true);
  }
}
let refreshingServices = false;
async function refreshServices() {
  if (refreshingServices) return;
  refreshingServices = true;
  try {
    const result = await api("services");
    $("#running-count").textContent = result.services.filter(
      (item) => item.State === "running",
    ).length;
    $("#runtime-label").textContent =
      `of ${result.services.length || 9} application services`;
    $("#services").replaceChildren();
    for (const service of result.services) {
      const button = document.createElement("button");
      button.textContent = `${service.Service} · ${service.Health || service.State}`;
      button.addEventListener("click", async () => {
        try {
          const logs = await api(`logs/${encodeURIComponent(service.Service)}`);
          $("#logs-title").textContent = `${service.Service} logs`;
          $("#logs-text").textContent = logs.text || "No recent logs.";
          $("#logs-dialog").showModal();
        } catch (error) {
          notice(error.message, true);
        }
      });
      $("#services").append(button);
    }
    $("#hardware").replaceChildren();
    for (const check of result.hardware || []) {
      const card = document.createElement("article");
      card.className = "hardware-card";
      const name = document.createElement("strong");
      name.textContent = check.name;
      const state = document.createElement("span");
      state.className = `state ${check.state === "ready" ? "good" : "warning"}`;
      state.textContent = check.state.replaceAll("_", " ");
      const message = document.createElement("small");
      message.textContent = check.message;
      card.append(name, state, message);
      $("#hardware").append(card);
    }
  } catch (error) {
    notice(error.message, true);
  } finally {
    refreshingServices = false;
  }
}
async function loadConfiguration() {
  savedConfiguration = await api("configuration");
  const form = $("#configuration-form");
  for (const [name, value] of Object.entries(savedConfiguration)) {
    const field = form.elements.namedItem(name);
    if (!field) continue;
    field.value = Array.isArray(value)
      ? value.join(name === "dataset_paths" ? "\n" : ", ")
      : value;
  }
  for (const name of ["github_token", "nvr_password"])
    form.elements.namedItem(name).placeholder = savedConfiguration[
      `${name}_configured`
    ]
      ? "Saved · leave blank to retain"
      : "Not configured";
}
$("#configuration-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const value = Object.fromEntries(new FormData(form));
  for (const name of ["app_port", "api_port", "interior_switch_id"])
    value[name] = Number(value[name]);
  value.camera_channels = value.camera_channels
    .split(",")
    .map((part) => Number(part.trim()));
  value.dataset_paths = value.dataset_paths
    .split("\n")
    .map((path) => path.trim())
    .filter(Boolean);
  try {
    await api("configuration", "PUT", value);
    await loadConfiguration();
    await refresh();
    notice(
      "Configuration saved. Apply configuration to update installed service connections.",
    );
  } catch (error) {
    notice(error.message, true);
  }
});
for (const action of [
  "install",
  "update-all",
  "check-updates",
  "start",
  "stop",
  "recover",
])
  $(`#${action}`).addEventListener("click", () => perform(action));
$("#refresh-services").addEventListener("click", refreshServices);
$("#close-logs").addEventListener("click", () => $("#logs-dialog").close());
$("#import-configuration").addEventListener("click", async () => {
  try {
    await api("configuration/import", "POST", {
      directory: $("#import-directory").value.trim(),
    });
    await loadConfiguration();
    await refresh();
    notice("Existing station settings imported. Credentials stay private.");
  } catch (error) {
    notice(error.message, true);
  }
});
$("#check-prerequisites").addEventListener("click", async () => {
  try {
    const result = await api("prerequisites");
    $("#prerequisites").replaceChildren();
    for (const check of result.checks) {
      const row = document.createElement("div");
      row.className = `check ${check.ok ? "good" : "bad"}`;
      row.textContent = `${check.ok ? "✓" : "!"} ${check.name} — ${check.detail}`;
      $("#prerequisites").append(row);
    }
    $("#serial-devices").replaceChildren();
    const auto = document.createElement("option");
    auto.value = "auto";
    $("#serial-devices").append(auto);
    for (const device of result.serial_devices) {
      const option = document.createElement("option");
      option.value = device;
      $("#serial-devices").append(option);
    }
  } catch (error) {
    notice(error.message, true);
  }
});
loadConfiguration().catch((error) => notice(error.message, true));
refresh();
refreshServices();
setInterval(refresh, 2500);
setInterval(refreshServices, 15000);
