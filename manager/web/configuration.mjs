/** Guide one-time station configuration; depends on local APIs and existing hardware settings. */
export class StationConfiguration {
  constructor({ api, notify, afterSave, dirtyChanged }) {
    this.api = api;
    this.notify = notify;
    this.afterSave = afterSave;
    this.dirtyChanged = dirtyChanged;
    this.form = document.querySelector("#configuration-form");
    this.saved = {};
    this.dirty = false;
    this.busy = false;
    this.pending = false;
    this.storageLocked = false;
  }
  async load() {
    this.saved = await this.api("configuration");
    for (const [name, value] of Object.entries(this.saved)) {
      const field = this.form.elements.namedItem(name);
      if (!field) continue;
      field.value = Array.isArray(value)
        ? value.join(name === "dataset_paths" ? "\n" : ", ")
        : value;
    }
    for (const name of ["github_token", "nvr_password"]) {
      const field = this.form.elements.namedItem(name);
      field.value = "";
      field.placeholder = this.saved[`${name}_configured`]
        ? "Saved — leave blank to retain"
        : "Enter your credential";
    }
    this.form.elements.namedItem("nvr_password").required =
      !this.saved.nvr_password_configured;
    this.original = JSON.stringify(this.values());
    this.setDirty(false);
    document.querySelector("#imported-settings").textContent = this.saved
      .imported_setting_count
      ? `${this.saved.imported_setting_count} native settings retained`
      : "Import existing details or configure your station below";
  }
  values() {
    const fields = this.form.elements;
    const value = {};
    for (const name of [
      "nvr_host",
      "nvr_user",
      "nvr_password",
      "serial_device",
      "interior_url",
      "data_directory",
      "github_token",
    ])
      value[name] = fields.namedItem(name).value.trim();
    for (const name of ["app_port", "api_port", "interior_switch_id"])
      value[name] = Number(fields.namedItem(name).value);
    value.camera_channels = fields
      .namedItem("camera_channels")
      .value.split(",")
      .map((part) => Number(part.trim()));
    value.dataset_paths = fields
      .namedItem("dataset_paths")
      .value.split("\n")
      .map((path) => path.trim())
      .filter(Boolean);
    return value;
  }
  setDirty(value) {
    this.dirty = value;
    document.querySelector("#unsaved-label").hidden = !value;
    document.querySelector("#save-configuration").disabled =
      this.busy || !value;
    document.querySelector("#import-configuration").disabled =
      this.busy || this.pending || value;
    this.dirtyChanged();
  }
  setBusy(value) {
    this.busy = value;
    this.form.setAttribute("aria-busy", String(value));
    for (const field of this.form.elements)
      field.disabled = value || this.pending;
    this.form.elements.namedItem("data_directory").disabled =
      value || this.pending || this.storageLocked;
    for (const button of document.querySelectorAll("#configuration button"))
      button.disabled = value || this.pending;
    document.querySelector("#import-configuration").disabled =
      value || this.pending || this.dirty;
    document.querySelector("#save-configuration").disabled =
      value || this.pending || !this.dirty;
  }
  focus(name) {
    this.form.scrollIntoView({
      behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "auto"
        : "smooth",
      block: "start",
    });
    const field = this.form.elements.namedItem(
      name === "nvr_password_configured" ? "nvr_password" : name || "nvr_host",
    );
    if (field) {
      field.closest("details")?.setAttribute("open", "");
      setTimeout(() => field.focus({ preventScroll: true }), 200);
    }
  }
  bind() {
    this.form.addEventListener("input", () =>
      this.setDirty(JSON.stringify(this.values()) !== this.original),
    );
    this.form.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (!this.form.reportValidity()) return;
      this.pending = true;
      this.setBusy(this.busy);
      const error = document.querySelector("#configuration-error");
      error.hidden = true;
      try {
        await this.api("configuration", "PUT", this.values());
        await this.load();
        this.notify("Station settings saved. Apply them when you’re ready.");
        await this.afterSave();
      } catch (failure) {
        error.textContent = failure.message;
        error.hidden = false;
        error.scrollIntoView({ block: "nearest" });
      } finally {
        this.pending = false;
        this.setBusy(this.busy);
      }
    });
    document
      .querySelector("#import-configuration")
      .addEventListener("click", async () => {
        const button = document.querySelector("#import-configuration");
        button.disabled = true;
        button.textContent = "Finding settings…";
        try {
          await this.api("configuration/import", "POST", {
            directory: document.querySelector("#import-directory").value.trim(),
          });
          await this.load();
          await this.afterSave();
          this.notify(
            "Existing station settings imported. Credentials remain private.",
          );
        } catch (error) {
          this.notify(error.message, true);
        } finally {
          button.disabled = this.busy;
          button.textContent = "Import existing settings";
        }
      });
    document
      .querySelector("#check-prerequisites")
      .addEventListener("click", () => this.checkPrerequisites());
    addEventListener("beforeunload", (event) => {
      if (this.dirty) {
        event.preventDefault();
        event.returnValue = "";
      }
    });
  }
  async checkPrerequisites() {
    const button = document.querySelector("#check-prerequisites");
    button.disabled = true;
    button.textContent = "Checking…";
    try {
      const result = await this.api("prerequisites");
      const list = document.querySelector("#prerequisites");
      list.replaceChildren();
      for (const check of result.checks) {
        const row = document.createElement("div");
        row.className = `check ${check.ok ? "good" : "bad"}`;
        const title = document.createElement("strong");
        title.textContent = `${check.ok ? "✓" : "!"} ${check.name}`;
        const detail = document.createElement("span");
        detail.textContent = check.detail;
        row.append(title, detail);
        list.append(row);
      }
      const select = document.querySelector("#serial-devices");
      select.replaceChildren();
      for (const value of ["auto", ...result.serial_devices]) {
        const option = document.createElement("option");
        option.value = value;
        select.append(option);
      }
      document.querySelector("#prerequisites-state").textContent = result.ready
        ? "System checks passed"
        : "Some requirements need attention";
    } catch (error) {
      this.notify(error.message, true);
    } finally {
      button.disabled = this.busy;
      button.textContent = "Check requirements";
    }
  }
}
