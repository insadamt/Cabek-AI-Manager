/** Describe real station state and next actions; depends only on Manager API snapshots. */
export const applicationDetails = {
  manager: {
    description: "Station setup & updates",
    icon: "station",
    services: [],
  },
  backend: {
    description: "Inspection workflows & AI analysis",
    icon: "layers",
    services: ["backend"],
  },
  frontend: {
    description: "Your Cabek operator workspace",
    icon: "screen",
    services: ["frontend"],
  },
  autoestimate: {
    description: "Pricing, references & observations",
    icon: "chart",
    services: ["database", "pricing", "pricing-web"],
  },
  cameras: {
    description: "Live NVR images & camera capture",
    icon: "camera",
    services: ["cameras"],
  },
  lighting: {
    description: "ESP32 lighting & serial connection",
    icon: "sun",
    services: ["lighting"],
  },
  ocr: {
    description: "E-Constat document recognition",
    icon: "document",
    services: ["ocr"],
  },
};
export function configurationGaps(config = {}) {
  return [
    ["nvr_host", "NVR address"],
    ["nvr_user", "NVR account"],
    ["nvr_password_configured", "NVR password"],
    ["interior_url", "Shelly address"],
  ]
    .filter(([key]) => !config[key])
    .map(([key, label]) => ({ key, label }));
}
export function runtimeState(component, installed, snapshot) {
  if (component === "manager") return { label: "Online", tone: "good" };
  if (!installed) return { label: "Included in setup", tone: "neutral" };
  if (!snapshot || snapshot.error)
    return { label: "Checking", tone: "neutral" };
  const names = applicationDetails[component]?.services || [];
  const matches = names.map((name) =>
    snapshot.services.find((item) => item.Service === name),
  );
  if (
    matches.every(
      (item) => item?.State === "running" && item.Health !== "unhealthy",
    )
  )
    return { label: "Running", tone: "good" };
  if (matches.some((item) => item?.State === "running"))
    return { label: "Needs attention", tone: "warning" };
  return { label: "Stopped", tone: "neutral" };
}
export function stationAction(status, config, services, dirty = false) {
  if (!status)
    return {
      title: "Checking your station",
      text: "Loading application versions and connection status.",
      label: "Checking…",
      kind: "waiting",
    };
  if (status.job?.status === "running")
    return {
      title: status.job.name,
      text: "The Manager is working. You can follow the live activity below.",
      label: "View progress",
      kind: "activity",
    };
  if (status.recovery_required)
    return {
      title: "Recover the interrupted operation",
      text: "Restore a consistent station state before making further changes.",
      label: "Recover station",
      kind: "recover",
    };
  if (dirty)
    return {
      title: "Save your station changes",
      text: "Your edits are kept in the form. Save them before applying configuration.",
      label: "Review changes",
      kind: "configuration",
    };
  const installed = Object.keys(status.installed).length > 0;
  const gaps = configurationGaps(config);
  if (!installed && gaps.length)
    return {
      title: "Let’s connect your station",
      text: "Enter your NVR and lighting details once. Every application will be set up together.",
      label: "Complete configuration",
      kind: "configuration",
      field: gaps[0].key,
    };
  if (!installed)
    return {
      title: "Ready to install the ecosystem",
      text: "The Manager will download, configure, and start every Cabek application.",
      label: "Install ecosystem",
      kind: "install",
    };
  const count = status.updates.components.filter(
    (item) => item.update_available,
  ).length;
  if (count)
    return {
      title: `${count} published update${count === 1 ? "" : "s"} available`,
      text: "Review the new releases, then update the complete ecosystem in one action.",
      label: "Review updates",
      kind: "applications",
    };
  if (status.configuration_pending)
    return {
      title: "Apply your saved settings",
      text: "The station is still using its installed configuration. Apply your changes when ready.",
      label: "Apply configuration",
      kind: "update-all",
    };
  if (!services || services.error)
    return {
      title: "Checking application health",
      text: "Reading the current service and hardware connections.",
      label: "Refresh status",
      kind: "refresh",
    };
  const stopped = services.services.filter(
    (item) => item.State !== "running" || item.Health === "unhealthy",
  );
  if (stopped.length || !services.services.length)
    return {
      title: "Bring your station online",
      text: "Start the complete station using your saved configuration and data.",
      label: "Start all services",
      kind: "start",
    };
  const attention =
    services.hardware?.filter((item) => item.state !== "ready") || [];
  if (attention.length)
    return {
      title: "Finish connecting your hardware",
      text: "The applications are running. Review the camera and lighting connections that need attention.",
      label: "Review connections",
      kind: "hardware",
    };
  return {
    title: "Your station is ready",
    text: "Your applications are running and the reported connections are ready.",
    label: "Open Cabek AI",
    kind: "open",
  };
}
export function elapsedTime(started, now = Date.now()) {
  const seconds = Math.max(0, Math.floor((now - Date.parse(started)) / 1000));
  if (!Number.isFinite(seconds)) return "Just started";
  return seconds < 60
    ? `${seconds}s`
    : `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}
