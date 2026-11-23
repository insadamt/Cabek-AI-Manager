# Deployment reliability audit — November 2026

This report records the deployment failures, corrective architecture, reproducible
checks, and station upgrade procedure. It depends on Manager 0.3.3, Backend 0.3.0,
Frontend 0.3.0, native application APIs, Docker Compose and private persistent data.
Physical readiness remains separate from software health. Docker namespace and
health-check semantics were checked against the official [Rootless Docker](https://docs.docker.com/engine/security/rootless/)
and [Compose service](https://docs.docker.com/reference/compose-file/services/) documentation.

## Findings and corrections

| Issue | Root cause and affected implementation | Correction and evidence | Remaining limit |
| --- | --- | --- | --- |
| Rootless UID mapping | Host UID 1000 is a subordinate UID inside Rootless Docker, while host-owned mounts appear owned by namespace UID 0. | `system.py`, `compose.py`, `runtime_storage.py`: daemon security-option detection, fail closed on missing mode, rootless namespace UID 0 only for the affected Python services, actual host-owner write probe, narrowly scoped ownership initialization. Rootful services retain the host UID. All Python application capabilities are dropped and privilege escalation is disabled. | Real Rootless daemon validation is required; this audit host has only a Rootful daemon. Rootful ownership repair is exercised with deliberately foreign-owned files. |
| OCR output/model access | Model and output mounts were not initialized for the daemon's user namespace. | All six writable directories are initialized, including custom data roots. Mount roots are private; symlink roots and hard-linked files are rejected. Content is preserved. | Existing data on unsupported filesystems or an inaccessible custom location fails explicitly. |
| Private demo startup | Backend correctly enforced mode 0700, but its container UID did not own the bind mount. | Repair the deployment identity and managed ownership, retaining strict 0700 directories and 0600 private files. Backend security checks remain enabled. | A correctly mapped Rootless station must still be tested. |
| Health-check serialization | Exec-form Python programs were split by the affected Compose serialization path. | Quoted `CMD-SHELL` Python checks are retained and compared against actual `docker inspect` configuration. MariaDB, PHP-FPM/Laravel, pricing HTTP, gateway, backend, cameras, lighting, OCR and frontend all have software checks. | Host Compose here is 5.7.0. The station's Compose V2 needs the same inspection check. |
| Lighting health | A TCP socket alone did not establish that the control API was serving requests. | Probe the native POST-only control route with GET and require its 405/Allow: POST response. This verifies HTTP routing without sending a hardware command. | Physical serial acknowledgement and visible LED output remain separate. |
| Gateway recreation | Containers sharing `service:gateway` prevent removing the gateway first. Whole-project `down` also replaced the database unnecessarily. | `lifecycle.py`: remove project-scoped orphan applications and namespace consumers before gateway; retain MariaDB; start database with `--no-recreate`; start application groups with `--no-deps`. The same ordering is used for rollback. | Actual station reboot and daemon restart have not been performed. |
| MariaDB health race | Recreating the staging database and then replacing it again during full-stack startup invalidated the container being awaited. | Full application startup never selects the database. Repeated migrations/seeders and real SQL rollback retain the same database container and named volume. | Upgrading the MariaDB server image itself requires a separate explicit database upgrade plan. |
| Retry and interruption | Before-backup shutdown was not journaled; failed first installations could retain containers and occupy their own ports. | Journal before stopping backend; preserve project identity and named volume; allow retries with a saved Compose definition; recover the before-backup phase without SQL restoration. | First-install retry with no prior complete backup preserves the existing volume and takes a snapshot before migrations when an existing database definition is present. |
| Backup/restore | OCR models were omitted; rollback started applications before restoring configuration and could reuse an incompatible gateway namespace. | `backups.py`: include models and pricing-client state, use installed custom storage, checksum snapshots, fully decompress and validate before mutation, remove candidate namespace consumers, restore state before startup. Replaced files are retained under `data/recovery/`. New cache files are retained for EasyOCR checksum validation. | SQL rollback retains the database and grants, restores the verified dump and removes only tables absent from the snapshot table manifest. It is never used as initial database setup. Retained recovery files consume disk until deliberately archived. |
| Credential preservation | A failed token-verification command was treated as an invalid token; missing database secrets could be regenerated. | Distinguish valid/invalid tokens from infrastructure failures and merged Compose progress output; retain tokens on verification errors. Refuse generating replacement database secrets for an existing database definition. | Recover missing credentials from an existing trusted backup. They cannot be reconstructed from application code. |
| USB reconnect | Re-rendering lighting omitted daemon mode and could revert Rootless UID selection. | `serial_devices.py` now detects daemon mode during reconciliation. Regression verifies UID 0 remains selected under Rootless mode. | Rootless supplementary serial-device group access needs actual station validation. |
| Hardware diagnostics | Camera failure entered an exception handler that referenced an unassigned response. | `readiness.py` reports disconnected cameras directly and continues reporting ESP32/Shelly state. | A responding endpoint does not prove valid images or visible lighting. |
| Lighting warnings | All exceptions appeared as `HTTPError` and were logged every second. | Backend distinguishes ESP32 unavailable (503), unsupported firmware (501), HTTP API rejection and unreachable HTTP service. Repeated identical warnings are limited to one every 30 seconds; retries continue. | No firmware or effects contract changed. |
| Camera topology | Manager default opened 13 channels, inconsistent with the station's expected four streams. | Default channels are the existing essential mappings 4, 13, 14 and 10. Explicit saved/imported channel lists and local addresses remain unchanged. | Actual dual-sensor NVR mapping, credentials, RTSP reconnect and Ethernet routing need hardware verification. |
| Prepared result polling | Backend emitted a managed processing status without required progress fields during photo publication. | `api/private_demo/mock_results.py` publishes valid preparing progress. Regression polls the real dossier API between file writes and rejects premature result visibility. | No synthetic output is claimed as real YOLO inference. |
| Dossier imports | Four native E-Constat sources needed confirmation against actual artifacts. | Validate/import copies, repeat validation for duplicate detection, and compare original PDFs/images/annotations byte for byte. Native importer retains IDs and rejects conflicts. | Source production directories are read-only and unchanged. |
| Demo photos and diagnostics | Missing sample assets must remain explicit; warning/error diagnostics must not claim success. | Persistent read-only demo-photo mount remains separate from private templates. Backend/frontend regression suites cover missing samples, prepared workflows and distinct diagnostic messages. | Owner-selected demo photographs and template activation are station acceptance steps. |
| Release/bootstrap | Manager 0.3.2 still reported its runtime version as 0.3.1, defeating bootstrap's version match. | Manager runtime version is 0.3.3. Backend/frontend editor feature versions are 0.3.0. Existing published tags are never moved. | Use the one-time host upgrade below so the old orchestration path does not perform this upgrade. |

## Repositories and contracts

Manager owns Compose, initializer, lifecycle, health checks, backup/restore and
recovery changes. Backend includes the existing structured private editor,
annotation authoring and prepared engine input changes, plus the polling and
lighting fixes. Frontend includes the existing private editor, annotation/history
workflow, transport and navigation changes. These feature changes are released
together as 0.3.0. Normal dossier result schemas remain compatible. Private editor
endpoints and DTOs are additive; demo provenance remains explicit.

OCR and AutoEstimate have only private tooling ignore-list housekeeping where
needed; their application code is unchanged. Cameras and capture-lights require
no source changes. Existing stable native application releases remain compatible.
Repository-local instructions prohibit reports in Backend and Frontend, so this
consolidated report lives in Manager.

## Verification matrix

| Verification | Result |
| --- | --- |
| Backend complete regression suite, including existing editor work | 468 passed in the complete suite, plus 10 focused checks after final version/lighting regression additions; host Python 3.14, application containers Python 3.12. |
| Frontend complete unit suite | 832 passed; no Playwright or browser automation used. |
| Frontend production build | Passed; existing large-chunk warning remains. |
| Lighting HTTP/serial/effects tests | 93 passed with simulated serial hardware. |
| AutoEstimate native tests | 21 passed, 69 assertions, SQLite in memory. |
| Manager Python regression suite | 83 passed; 10 Docker scenarios are opt-in and skipped in the default run. |
| Manager Node UI state tests | 6 passed. |
| Every application image build | Passed against combined source snapshots. |
| Nine-service Rootful Docker startup | Passed in project `cabek-audit-20261123`, ports 28180/28181. Production project untouched. |
| Actual Docker health command serialization | Passed against `docker inspect` for every service. |
| Gateway/frontend/backend/AutoEstimate API | Passed against running containers. |
| Private administration access boundary | Unauthenticated template access returns 401. |
| French/English EasyOCR, CPU inference | Models downloaded; real text recognized; second initialization reused model files. |
| OCR authenticated HTTP processing of a real E-Constat PDF | Passed with an actual source PDF; authenticated HTTP 200 and matched registration. |
| Real four-dossier import and duplicate detection | Passed; imported media matches source bytes. |
| Gateway replacement, database identity retention | Passed with actual containers. |
| Real MariaDB backup/rollback | Passed; prior row restored, migration-added table removed, same container retained. |
| Interrupted before-backup recovery | Passed with actual containers. |
| Rootless daemon deployment | Not tested; host lacks Rootless runtime tools. Configuration and reconciliation regression coverage only. |
| Compose V2 on target Ubuntu station | Not tested on target. |
| Daemon restart/station reboot | Not performed; no restart of shared host infrastructure. |
| NVR/RTSP physical capture, ESP32 LEDs, Shelly output | Requires physical station. |

Initial test failures were corrected and rerun: prepared publication omitted
progress; an initial lighting health probe assumed OpenAPI was enabled; the
integration report parser initially treated Compose progress output as JSON; token
verification likewise initially compared merged progress and verdict output.
None is counted as a passing result until its corrected check is rerun.

## Reproducible checks

```sh
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
node --test tests/web-state.test.mjs
```

The real Docker suite is opt-in. Supply a disposable, already built installation
whose Compose name starts with `cabek-audit-`, with independent ports, private
credentials, bind mounts and a dedicated MariaDB named volume. Never point it at
production. Tests intentionally replace applications and restore isolated SQL.

```sh
CABEK_TEST_HOME=/absolute/path/to/audit-state \
CABEK_TEST_DOSSIERS=/absolute/path/to/read-only/source-dossiers \
python -m pytest tests/integration -q
```

Prepare the isolated station reproducibly from selected application checkouts:

```sh
python tests/integration/prepare_station.py --home /absolute/new-empty-audit-home \
  --source backend=/absolute/backend --source frontend=/absolute/frontend \
  --source cameras=/absolute/cameras --source lighting=/absolute/lighting \
  --source ocr=/absolute/ocr --source autoestimate=/absolute/autoestimate
```

The initializer snapshots Git-listed local sources, builds the current Manager
recipes, uses independent ports/credentials/volume and deliberately selects a
nonexistent serial device. Its content fingerprints identify local test inputs,
not published release SHAs. An optional `--model-cache` copies an existing cache.
Only an empty audit home is accepted; existing installations are never cleared.

The source directory must contain the four requested native dossier directories.
Tests do not invent their documents or alter the source folders. Docker checks
work against whichever daemon the isolated Compose file was prepared for; repeat
on a real Rootless daemon and Compose V2 before station acceptance.

## Upgrade the existing failed Ubuntu installation

1. Wait for captures/OCR/analysis to finish. Stop only the host Manager process
   with Ctrl-C or its configured service supervisor. Keep application containers,
   `.local`, database volume, custom data root and credentials in place. Preserve
   existing trusted backups. Do not use volume deletion, pruning or permission
   repair commands.
2. In `~/Desktop/Cabek-AI-Manager`, fetch the new stable tag and switch to it. A
   dirty checkout must be committed/preserved first; do not force checkout.

   ```sh
   cd ~/Desktop/Cabek-AI-Manager
   git fetch origin --tags
   git switch --detach v0.3.3
   .venv/bin/python -m pip install -r requirements.txt
   CABEK_MANAGER_HOME="$PWD/.local" .venv/bin/python -m manager --port 8179
   ```

   If a nondefault Manager state home is already configured, use that exact
   existing absolute path instead of `$PWD/.local`. The custom station data root
   is read from saved configuration; do not change it during this upgrade.
   Launching the checked-out Manager directly avoids an older bootstrap selection
   temporarily launching the old updater.
3. Open `http://127.0.0.1:8179` and confirm version 0.3.3. If recovery is required,
   use **Recover interrupted operation** first. Choose **Update All** for a
   recorded installation, or **Install ecosystem** for a failed first install.
   Manager builds before interruption, drains admitted work, initializes mapped
   mounts, verifies a backup before SQL migrations, retains MariaDB and recreates
   namespace consumers in the required order. Do not manually remove containers.
4. Follow Activity through storage initialization, native migrations/seeders,
   pricing-token verification, application startup, French/English CPU model
   preparation and native connectivity checks. Download errors are explicit;
   preserve the cache and retry after resolving connectivity/disk problems.
   Missing database credentials stop deployment and require recovery from backup.
5. After the operation completes, stop the directly launched host Manager and run
   `./start.sh`. The prepared `manager-next` selection is adopted by the bootstrap
   with the existing `.local` state and checked against runtime version 0.3.3.
6. Verify all nine services and the commands Docker actually received:

   ```sh
   docker compose -f .local/compose.json ps --all
   for id in $(docker compose -f .local/compose.json ps -q); do
       docker inspect "$id" --format '{{.Name}} {{.State.Health.Status}} {{json .Config.Healthcheck.Test}}'
   done
   curl --fail http://127.0.0.1:8180/health
   curl --fail http://127.0.0.1:8181/_manager/health
   curl --fail http://127.0.0.1:8181/api/settings/operation
   curl --fail http://127.0.0.1:8181/api/vehicles/marques
   ```

   Use the saved application/API ports if customized. The expected services are
   gateway, database, pricing, pricing-web, cameras, lighting, ocr, backend and
   frontend. Every one must report `healthy`; running alone is insufficient.
7. Validate/import the four E-Constat IDs through Manager before applying the
   import. Review conflicts rather than replacing production dossiers. Initialize
   or rotate private demo passwords only through the existing private local tool;
   never regenerate them as part of an ordinary update.

## Manual station acceptance checklist

- [ ] Confirm daemon security options contain `name=rootless` on the target.
- [ ] Repeat all nine health and actual command inspections on Compose V2.
- [ ] Confirm mapped writes and 0700 private demo directories without manual repairs.
- [ ] Verify existing MariaDB records, API credentials, dossiers, private templates,
      demo photos and OCR model cache after install retry and update.
- [ ] Test missing-internet installation with a complete cached model set, and
      recovery from an interrupted first model download.
- [ ] Confirm two dual-sensor cameras supply the expected four configured streams.
- [ ] Disconnect/reconnect Ethernet and verify previews, capture timeouts and useful
      French frontend errors without falsely unhealthy software services.
- [ ] Reconnect the selected ESP32 under Rootless Docker; verify serial access,
      on/off, brightness, speed, repeating effects and visible scan/error effects.
- [ ] Confirm Shelly switch ID/address, local power-on acknowledgement, stabilization
      before capture, failure messaging and safe OFF following failed capture.
- [ ] Exercise all three private demo categories; confirm immutable templates,
      independent dossiers, protected administration and no real inference on demo data.
- [ ] Import each requested E-Constat dossier, repeat for duplicate reporting, and
      check PDFs, OCR preparation/results, original photos and annotations.
- [ ] Restart Docker and reboot the dedicated station; verify all nine services,
      frontend, cached OCR, persistence and USB reconnection.
- [ ] Run a deliberately failed update and interrupted update only on a disposable
      station copy; verify recovery and retained recovery files before production.
- [ ] Confirm Manager discovers the new published stable release SHAs and safely
      returns through its host bootstrap without moving existing version tags.
