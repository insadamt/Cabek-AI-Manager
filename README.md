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
