/** Render station health and operation activity; depends on API snapshots and view-state helpers. */
import {
  applicationDetails,
  configurationGaps,
  elapsedTime,
  runtimeState,
} from "./view-state.mjs";
const $ = (selector) => document.querySelector(selector);
const iconPaths = {
  station: "M4 4h16v12H4z M8 20h8 M12 16v4",
  layers: "m12 3 9 5-9 5-9-5 9-5 M3 12l9 5 9-5 M3 16l9 5 9-5",
  screen: "M3 4h18v14H3z M8 22h8 M12 18v4",
  chart: "M4 3v17h17 M8 15v-4 M13 15V7 M18 15V4",
  camera: "M3 7h12v12H3z m12 4 6-4v12l-6-4",
  sun: "M12 3v2 M12 19v2 M3 12h2 M19 12h2 M5 5l2 2 M17 17l2 2 M5 19l2-2 M17 7l2-2 M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0",
  document: "M5 3h10l4 4v14H5z M14 3v5h5 M8 12h8 M8 16h6",
};
function element(tag, text = "", className = "") {
  const node = document.createElement(tag);
  node.textContent = text;
  node.className = className;
  return node;
}
function icon(name) {
  const box = element("span", "", "application-icon");
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  const path = document.createElementNS(svg.namespaceURI, "path");
  path.setAttribute("d", iconPaths[name] || iconPaths.station);
  svg.append(path);
  box.append(svg);
  return box;
}
export function renderApplications(status, snapshot) {
  const body = $("#components");
  body.replaceChildren();
  for (const item of status.updates.components) {
    const row = document.createElement("tr");
    const name = document.createElement("td");
    const details = applicationDetails[item.key] || applicationDetails.manager;
    const identity = element("div", "", "application-identity");
    const words = element("div");
    words.append(
      element("strong", item.name),
      element("small", details.description),
    );
    identity.append(icon(details.icon), words);
    name.append(identity);
    row.append(name);
    const installed = status.installed[item.key];
    row.append(
      element("td", installed?.tag || "Not installed", "version-cell"),
    );
    const latest = document.createElement("td");
    const release = item.latest;
    if (release?.url?.startsWith("https://github.com/")) {
      const link = element("a", release.tag, "release-link");
      link.href = release.url;
      link.target = "_blank";
      link.rel = "noopener";
      latest.append(link);
    } else
      latest.append(
        element(
          "span",
          release?.tag || (item.error ? "Unavailable" : "Checking"),
        ),
      );
    if (item.error) {
      const warning = element("small", "Release check failed", "bad");
      warning.title = item.error;
      latest.append(warning);
    } else if (item.update_available)
      latest.append(element("small", "Update available", "warning"));
    row.append(latest);
    const state = runtimeState(item.key, installed, snapshot);
    const runtime = document.createElement("td");
    runtime.append(element("span", state.label, `status-pill ${state.tone}`));
    row.append(runtime);
    body.append(row);
  }
}
export function renderOverview(status, config, snapshot) {
  const installed = Object.keys(status.installed).length > 0;
  const services = snapshot?.services || [];
  const running = services.filter(
    (item) => item.State === "running" && item.Health !== "unhealthy",
  ).length;
  const updates = status.updates.components.filter(
    (item) => item.update_available,
  ).length;
  $("#running-count").textContent = snapshot ? running : "—";
  $("#runtime-label").textContent =
    `of ${services.length || 9} services running`;
  $("#application-count").textContent = status.updates.components.length;
  $("#update-count").textContent = updates;
  const healthy =
    installed && !snapshot?.error && services.length === 9 && running === 9;
  const title = !installed
    ? "Set up your Cabek station"
    : !snapshot
      ? "Checking your applications"
      : healthy
        ? "Applications are running"
        : "Your station needs attention";
  $("#runtime-title").textContent = title;
  $("#runtime-badge").textContent = !installed
    ? "Not installed"
    : healthy
      ? "Running"
      : "Checking / attention";
  $("#runtime-badge").className = `status-pill ${healthy ? "good" : "neutral"}`;
  $("#installation-state").textContent = installed
    ? "All applications included"
    : "Full ecosystem setup";
  $("#update-banner").hidden = !installed || !updates;
  $("#update-banner-title").textContent =
    `${updates} published update${updates === 1 ? "" : "s"} available`;
  for (const [id, done] of [
    ["config", !configurationGaps(config).length],
    ["install", installed],
    [
      "connect",
      snapshot?.hardware?.length &&
        snapshot.hardware.every((item) => item.state === "ready"),
    ],
  ]) {
    const step = $(`#step-${id}`);
    step.classList.toggle("complete", Boolean(done));
    step.setAttribute("aria-label", `${id}: ${done ? "complete" : "pending"}`);
  }
}
export function renderHardware(snapshot, configure) {
  $("#hardware").replaceChildren();
  const checks = snapshot.hardware || [];
  $("#connection-count").textContent =
    `${checks.filter((item) => item.state === "ready").length} of ${checks.length} ready`;
  for (const check of checks) {
    const card = element("article", "", "hardware-card");
    const top = element("div", "", "hardware-card-top");
    top.append(
      element("strong", check.name),
      element(
        "span",
        check.state === "ready"
          ? "Connected"
          : check.state === "detected"
            ? "Verify output"
            : "Needs connection",
        `status-pill ${check.state === "ready" ? "good" : "warning"}`,
      ),
    );
    card.append(top, element("p", check.message, "hardware-description"));
    const button = element("button", "Review configuration →", "text-button");
    button.addEventListener("click", () =>
      configure(
        check.name.includes("ESP32")
          ? "serial_device"
          : check.name.includes("Shelly")
            ? "interior_url"
            : "nvr_host",
      ),
    );
    card.append(button);
    $("#hardware").append(card);
  }
  if (!checks.length)
    $("#hardware").append(
      element(
        "p",
        snapshot.error || "Connections are checked after installation.",
        "muted",
      ),
    );
}
export function renderDiagnostics(snapshot, showLogs) {
  $("#services").replaceChildren();
  $("#service-summary").textContent = snapshot.error
    ? "Status unavailable"
    : `${snapshot.services.length} services`;
  for (const service of snapshot.services) {
    const button = element(
      "button",
      `${service.Service} · ${service.Health || service.State}`,
    );
    button.addEventListener("click", () => showLogs(service.Service));
    $("#services").append(button);
  }
}
export function renderActivity(job) {
  const status = job?.status || "Idle";
  const running = status === "running";
  $("#job-status").textContent =
    status.charAt(0).toUpperCase() + status.slice(1);
  $("#job-title").textContent = job?.name || "Your station activity";
  $("#activity-symbol").textContent = running
    ? "↻"
    : status === "failed" || status === "interrupted"
      ? "!"
      : "✓";
  $("#activity-symbol").classList.toggle("working", running);
  $("#activity-message").textContent =
    job?.error ||
    job?.events.at(-1)?.message ||
    "Installations, updates, and system checks appear here.";
  $("#job-time").textContent = job
    ? `${running ? "Elapsed" : "Duration"} ${elapsedTime(job.started_at, running ? Date.now() : Date.parse(job.finished_at || job.started_at))}`
    : "";
  if (job)
    $("#events").textContent =
      job.events
        .map(
          (event) =>
            `${new Date(event.at).toLocaleTimeString()}  ${event.message}`,
        )
        .join("\n") + (job.error ? `\n\n${job.error}` : "");
}
