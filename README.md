# Cabek AI Manager

Install, configure, run, and update the Cabek ecosystem on one Ubuntu/Linux PC.
The manager depends on Python 3.11+, Docker Engine with Compose and Buildx, and
access to the private GitHub repositories. Application services run in Docker;
the manager runs on the host so it stays available when a service fails.

## Start

```bash
git clone https://github.com/insadamt/Cabek-AI-Manager.git
cd Cabek-AI-Manager
./start.sh
```

Open **http://localhost:8179**. The bootstrap creates a private Python environment.
Authenticate with `gh auth login`, or enter a GitHub token in Configuration.
Check prerequisites, save the station settings, and click **Install ecosystem**.
No individual service environment files need editing.

Demo mode provides synthetic side-labelled camera images. A physical station
requires NVR credentials, actual channels, and any enabled ESP32/Shelly devices.
Use the prerequisite check to discover stable USB device paths.

## Included repositories

- Cabek-AI-Manager
- Cabek-AI-Backend
- Cabek-AI-Frontend
- Cabek-Autoestimate-Backend (Laravel, Nginx, MariaDB)
- Cabek-AI-Cam (station mode)
- Cabek-Capture-Lights (when enabled)
- Cabek-EConstat-OCR (when enabled)

AutoEstimate's separate frontend, the scraper, and the legacy Streamlit app are
excluded. AutoEstimate initializes through migrations, canonical seeders, and its
dataset importer. Bundled normalized archives are imported once per checksum;
additional dataset paths can be supplied in the interface.

## Updates

The manager checks GitHub on startup and every 15 minutes. **Only published stable
semantic-version releases qualify.** Commits, plain tags, draft releases, and
prereleases do not produce stable update notices.

Click **Update All** to resolve the newest published version of every included
repository. The manager downloads exact revisions, builds before interruption,
blocks new writes, waits for active work, backs up data, migrates, and verifies
the replacement services. Failed deployment attempts restore the previous stack
and database. Configuration and installation data remain private under `.local/`.

Start the application with `start.sh` to enable manager self-updates. Its host
bootstrap switches to a prepared revision only after service deployment succeeds.

## Development checks

```bash
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests -q
node --check manager/web/app.js
```

See [architecture and acceptance checks](docs/architecture.md). Physical camera,
serial, and lighting behavior must be verified on the connected station; synthetic
inputs and HTTP readiness do not prove physical operation.
