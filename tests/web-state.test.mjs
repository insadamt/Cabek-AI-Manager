/** Check setup guidance and runtime boundaries; depends only on Node and pure UI state helpers. */
import test from "node:test";
import assert from "node:assert/strict";
import {
  stationAction,
  runtimeState,
  configurationGaps,
  elapsedTime,
} from "../manager/web/view-state.mjs";
const configured = {
  nvr_host: "station",
  nvr_user: "operator",
  nvr_password_configured: true,
  interior_url: "http://lights",
};
const installed = {
  installed: { backend: { tag: "v0.1.1" } },
  updates: { components: [] },
};
const running = {
  services: [{ Service: "backend", State: "running" }],
  hardware: [{ state: "disconnected" }],
};
test("new station requests only missing external credentials before installing every app", () => {
  assert.equal(
    stationAction({ ...installed, installed: {} }, {}, null).kind,
    "configuration",
  );
  assert.equal(configurationGaps(configured).length, 0);
  assert.equal(
    stationAction({ ...installed, installed: {} }, configured, null).kind,
    "install",
  );
});
test("active work and interrupted recovery take priority over other actions", () => {
  assert.equal(
    stationAction(
      { ...installed, job: { status: "running", name: "Update" } },
      configured,
      running,
      true,
    ).kind,
    "activity",
  );
  assert.equal(
    stationAction(
      { ...installed, recovery_required: true },
      configured,
      running,
      true,
    ).kind,
    "recover",
  );
});
test("unsaved edits and saved unapplied settings receive distinct actions", () => {
  assert.equal(
    stationAction(installed, configured, running, true).kind,
    "configuration",
  );
  assert.equal(
    stationAction(
      { ...installed, configuration_pending: true },
      configured,
      running,
    ).kind,
    "update-all",
  );
});
test("published update notice precedes disconnected hardware guidance", () => {
  assert.equal(
    stationAction(
      { ...installed, updates: { components: [{ update_available: true }] } },
      configured,
      running,
    ).kind,
    "applications",
  );
  assert.equal(stationAction(installed, configured, running).kind, "hardware");
});
test("pricing runtime requires all three services while hardware is independent", () => {
  const snapshot = {
    services: ["pricing", "pricing-web", "database"].map((Service) => ({
      Service,
      State: "running",
    })),
    hardware: [{ state: "disconnected" }],
  };
  assert.equal(runtimeState("autoestimate", true, snapshot).label, "Running");
  snapshot.services.pop();
  assert.equal(
    runtimeState("autoestimate", true, snapshot).label,
    "Needs attention",
  );
  assert.equal(
    runtimeState("cameras", false, snapshot).label,
    "Included in setup",
  );
  assert.equal(
    runtimeState("backend", true, { error: "Docker unavailable" }).label,
    "Checking",
  );
});
test("stopped services prompt startup; elapsed time uses actual timestamps", () => {
  assert.equal(
    stationAction(installed, configured, { services: [], hardware: [] }).kind,
    "start",
  );
  assert.equal(
    elapsedTime("2026-11-22T00:00:00Z", Date.parse("2026-11-22T00:01:05Z")),
    "1m 5s",
  );
});
