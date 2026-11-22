/** Coordinate the real station console; depends on same-origin Manager APIs and focused UI modules. */
import { stationAction, configurationGaps } from "./view-state.mjs";
import { StationConfiguration } from "./configuration.mjs";
import {
  renderApplications,
  renderOverview,
  renderHardware,
  renderDiagnostics,
  renderActivity,
} from "./rendering.mjs";
const $ = (selector) => document.querySelector(selector);
let lastStatus;
let services;
let lastJob;
let statusRequest;
let serviceRequest;
let submitting = false;
let nextAction;
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
  $("#notice-message").textContent =
    message.length > 240
      ? `${message.slice(0, 220)}… See Activity for full details.`
      : message;
  $("#notice").hidden = !message;
  $("#notice").classList.toggle("error", error);
  $("#notice").setAttribute("role", error ? "alert" : "status");
}
const configuration = new StationConfiguration({
  api,
  notify: notice,
  afterSave: refresh,
  dirtyChanged: render,
});
function render() {
  nextAction = stationAction(
    lastStatus,
    configuration.saved,
    services,
    configuration.dirty,
  );
  $("#next-title").textContent = nextAction.title;
  $("#next-description").textContent = nextAction.text;
  $("#next-action").textContent = nextAction.label;
  $("#next-action").disabled = submitting || nextAction.kind === "waiting";
  if (!lastStatus) return;
  const status = lastStatus;
  const installed = Object.keys(status.installed).length > 0;
  const busy = submitting || status.job?.status === "running";
  const blocked = status.recovery_required;
  $("#version").textContent = `v${status.version}`;
  $("#open-app").hidden = !installed;
  $("#open-app").href = status.application_url;
  $("#install").hidden = installed;
  $("#update-all").hidden =
    !installed ||
    (!status.updates.updates_available && !status.configuration_pending);
  $("#update-all").textContent = status.updates.updates_available
    ? "Update All"
    : "Apply configuration";
  $("#recover").hidden = !blocked;
  for (const action of [
    "install",
    "update-all",
    "check-updates",
    "start",
    "stop",
    "recover",
  ]) {
    const button = $(`#${action}`);
    button.disabled =
      busy ||
      (blocked && !["recover", "check-updates"].includes(action)) ||
      (configuration.dirty && ["install", "update-all"].includes(action));
    if (["start", "stop"].includes(action)) button.hidden = !installed;
  }
  $("#install").disabled ||= configurationGaps(configuration.saved).length > 0;
  configuration.storageLocked = installed;
  configuration.setBusy(busy || blocked);
  renderApplications(status, services);
  renderOverview(status, configuration.saved, services);
  renderActivity(status.job);
}
async function perform(action) {
  if (submitting || lastStatus?.job?.status === "running") return;
  if (configuration.dirty && ["install", "update-all"].includes(action)) {
    configuration.focus();
    return;
  }
  submitting = true;
  render();
  try {
    await api(action, "POST", {});
    notice("Operation started. Follow its progress in Activity.");
    $("#activity").scrollIntoView({ behavior: "smooth", block: "start" });
    await refresh();
  } catch (error) {
    notice(error.message, true);
  } finally {
    submitting = false;
    render();
  }
}
function refresh() {
  if (statusRequest) return statusRequest;
  statusRequest = (async () => {
    try {
      lastStatus = await api("status");
      render();
      const job = lastStatus.job;
      if (job && lastJob !== `${job.id}:${job.status}`) {
        if (job.status === "failed" || job.status === "interrupted")
          notice(
            job.error || "The operation needs attention. Review Activity.",
            true,
          );
        if (job.status === "completed") {
          if (lastJob) notice("Operation completed.");
          refreshServices();
        }
        lastJob = `${job.id}:${job.status}`;
      }
    } catch (error) {
      notice(
        `Cannot reach the Manager. Retrying automatically. ${error.message}`,
        true,
      );
    } finally {
      statusRequest = undefined;
    }
  })();
  return statusRequest;
}
function refreshServices() {
  if (serviceRequest) return serviceRequest;
  $("#refresh-services").disabled = true;
  serviceRequest = (async () => {
    try {
      services = await api("services");
      renderHardware(services, (field) => configuration.focus(field));
      renderDiagnostics(services, showLogs);
      render();
      $("#status-updated").textContent =
        services.error ||
        `Runtime checked at ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}. Hardware is reported separately below.`;
    } catch (error) {
      $("#status-updated").textContent = `Status unavailable: ${error.message}`;
    } finally {
      serviceRequest = undefined;
      $("#refresh-services").disabled = false;
    }
  })();
  return serviceRequest;
}
async function showLogs(service) {
  try {
    const result = await api(`logs/${encodeURIComponent(service)}`);
    $("#logs-title").textContent = `${service} logs`;
    $("#logs-text").textContent = result.text || "No recent logs.";
    $("#logs-dialog").showModal();
  } catch (error) {
    notice(error.message, true);
  }
}
$("#next-action").addEventListener("click", () => {
  const action = nextAction;
  if (action.kind === "configuration") configuration.focus(action.field);
  else if (
    ["activity", "applications", "hardware", "services"].includes(action.kind)
  ) {
    $(
      action.kind === "hardware" || action.kind === "services"
        ? "#connections"
        : `#${action.kind}`,
    ).scrollIntoView({ behavior: "smooth", block: "start" });
    if (action.kind === "services") $(".service-details").open = true;
  } else if (action.kind === "open") $("#open-app").click();
  else if (action.kind === "refresh") refreshServices();
  else if (action.kind !== "waiting") perform(action.kind);
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
$("#dismiss-notice").addEventListener("click", () => notice(""));
$("#close-logs").addEventListener("click", () => $("#logs-dialog").close());
$("#copy-log").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText($("#events").textContent);
    notice("Technical log copied.");
  } catch {
    notice("Copy unavailable. Select the technical log text to copy it.", true);
  }
});
for (const link of document.querySelectorAll(".header-nav a"))
  link.addEventListener("click", () => {
    for (const item of document.querySelectorAll(".header-nav a"))
      item.removeAttribute("aria-current");
    link.setAttribute("aria-current", "page");
  });
configuration.bind();
configuration
  .load()
  .then(render)
  .catch((error) => notice(error.message, true));
refresh();
refreshServices();
setInterval(refresh, 2500);
setInterval(refreshServices, 15000);

for (const [id, apply] of [['validate-dossier-import', false], ['apply-dossier-import', true]]) {
  document.querySelector(`#${id}`).addEventListener('click', async () => {
    try {
      await api('dossiers/import', 'POST', {source: document.querySelector('#dossier-import-source').value.trim(), apply, ids: document.querySelector('#dossier-import-ids').value.split(',').map(value=>value.trim()).filter(Boolean)});
      notice('Import operation started. Review Activity for validation and conflicts.');
      await refresh();
    } catch (error) { notice(error.message, true); }
  });
}
