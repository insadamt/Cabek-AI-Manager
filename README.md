# Cabek AI Manager

Install, configure, run, and update the complete Cabek station on one Ubuntu/Linux PC.
Manager owns the Docker recipes, configuration, update gateway, and private state;
application repositories retain their original source and startup workflows.
Requires Python 3.11+ with venv, Docker Engine, Compose/Buildx, and GitHub access.

## Start

```bash
git clone https://github.com/insadamt/Cabek-AI-Manager.git
cd Cabek-AI-Manager
./start.sh
```

Open **http://localhost:8179**. Authenticate with `gh auth login` or provide a token
in the interface. Import existing Cabek station settings or enter the real NVR,
ESP32, and Shelly settings once. Then select **Install ecosystem**.

Every application is included: Cabek backend, Cabek frontend, Tiandy cameras,
ESP32 lighting, E-Constat OCR, and AutoEstimate backend with MariaDB and Nginx.
AutoEstimate Scrapper, its separate frontend, and legacy Streamlit remain excluded.
There is no Manager demo profile or application-selection switch.

Disconnected hardware remains configured and its application stays installed.
Runtime health and physical readiness are reported separately. A detected USB
device does not prove that LEDs respond; verify actual output on the station.
If several USB devices are present, select the ESP32's stable `/dev/serial/by-id/`
path. Manager refreshes its Docker mapping when that device reconnects and the
station is idle.

Application and API ports default to **8180** and **8181**. Private configuration,
credentials, exact source archives, backups, and station data live under `.local/`.
A custom data directory can be selected before installation. Existing dotenv
settings are read without modifying their files; internal connections are resolved
by Manager. Password fields can be left empty to retain saved credentials.

## Updates

Only **published stable semantic-version releases** produce update notices.
Commits, plain tags, drafts, and prereleases do not. **Update All** checks the
entire ecosystem and installs each application's latest published version.

Manager builds before interruption, closes new writes at its own gateway, waits
for accepted native work, backs up data, and replaces containers. It uses the
apps' existing APIs and locks; no application management endpoints are required.
Failed deployments restore the previous stack and data. Manager self-updates use
the host bootstrap and a prepared environment, retaining the installation state.

AutoEstimate initializes through its existing migrations, canonical seeders,
`api:token:create`, and `observations:import`. Saved credentials and completed
imports are retained across repeated setup and updates.

## Development checks

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests -q
node --check manager/web/app.js
```

See [architecture and acceptance checks](docs/architecture.md). Tests and deployment
recipes belong to Manager. Run original application regression tests without
editing their repositories. Physical capture and lighting checks require connected
hardware; simulated unit-test inputs do not establish station readiness.

## Private demo dossiers and additive imports

Native private administration, secure password initialization, sample storage, guarded E-Constat imports, backup/recovery, validation and the stable-release deployment order are documented in [the consolidated technical report](docs/private-demo-system.md). Deployment recipes remain owned by Manager.

## Rootless Docker and installation recovery

Manager detects Rootless Docker using the daemon security options before rendering
Compose. Its Manager-owned Python services use container UID/GID `0:0` **only in
rootless mode**, where namespace UID 0 maps to the unprivileged host Docker user.
On a conventional Docker daemon the services retain the host UID/GID. This lets
OCR create `/models/model` and `/app/output/api_uploads`, and lets the backend
secure `/data/private-demo` with mode 0700 without granting world-write access.
Do not apply `chmod 777` to private station directories.

The installer removes only this project's application containers, with namespace
consumers before their gateway, and retains the existing MariaDB container and
named volume. A scoped initializer repairs writable ownership and verifies the
daemon's actual host mapping; application containers drop all capabilities.
Health checks use quoted `CMD-SHELL` Python programs and cover all nine services.
Backups include OCR models and are validated before rollback. See the
[deployment audit, verification matrix and safe upgrade procedure](docs/deployment-audit-2026-11.md).

This change requires a newly published stable Manager release and an updated
host Manager process before a station can use it. A successful unit test does
not replace an end-to-end installation on both rootless and rootful Docker.
