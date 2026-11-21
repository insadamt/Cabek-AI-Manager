# Installation, configuration, and update architecture

This document records the manager's important technical decisions and acceptance
criteria. It explains why installation state is separate from source checkouts
and depends on GitHub published releases, repository Dockerfiles, the backend's
maintenance API, and a single Linux host with Docker access.

## Ownership

Each service owns its API and Docker image. `manager/catalog.py` lists supported
repositories; `configuration.py` owns site settings and generated credentials.
`compose.py` translates them into one private `cabek-ai-manager` Compose project.
Existing projects on the same PC are outside its control.

The host-side manager uses background jobs for operations and atomic JSON files
for state. An OS file lock prevents concurrent mutations across manager processes.
The UI polls persisted operation events and can display service logs. Interrupted
operations remain visible after restart.

## Version selection

Candidates come from GitHub's Releases API, never its Tags API. A candidate must
be published, non-draft, non-prerelease, and have a numeric `vMAJOR.MINOR.PATCH` tag.
Selection compares version numbers numerically and resolves the selected release
tag to its exact commit. A moved tag for an installed version is rejected.

Each repository has an independent version. One Update All action resolves every
enabled component, retains newer installed versions instead of downgrading them,
and downloads only missing source archives. Application services build locally
from their release Dockerfiles. The manager has its own release and restart
supervisor; its private state outlives the source revision that runs it.

## Automatic configuration

The manager creates persistent database credentials, Laravel APP_KEY, camera
API key, OCR token, backend management key, and pricing client token once.
It passes settings directly into containers instead of modifying source `.env`
files. The production frontend proxies to its backend and reads connection mode
at runtime, allowing the same image to work on different installations.

AutoEstimate's command accepts credentials on standard input and validates the
canonical IDs used by Cabek. Dataset imports are checksum-tracked and validated
before writes. Repeated setup does not reset the SQL database or regenerate keys.

## Update transaction

1. Resolve published releases and download exact source revisions.
2. Render and validate candidate Compose configuration, then build images.
3. Prepare any manager self-update in its own Python environment.
4. Close backend write admission and wait for active requests, camera jobs,
   queued/running analyses, and OCR jobs to finish.
5. Back up SQL, dossiers, runtime state, configuration, and installed revisions.
6. Stop API/frontend writers, migrate, seed canonical references, and import any
   new validated datasets.
7. Start replacement services, wait for health, and probe the manager API.
8. Publish installed-version state and release maintenance. Queue a manager
   process restart only after the job is persisted as completed.

Failures before mutation leave the running stack untouched. Failures after a
backup trigger database/data restoration and restart the prior images. Original
data volumes are never removed by normal install, start, stop, or update actions.

## Manual acceptance checklist

- [ ] Fresh install completes through the interface without per-repository edits.
- [ ] Seeded part IDs match Cabek's pricing mappings; an imported price is returned.
- [ ] Repeating setup preserves credentials, dossiers, and pricing observations.
- [ ] A tag without a published release produces no update notice.
- [ ] Publishing a newer stable release produces a notice; Update All installs it.
- [ ] A running capture/analysis finishes before replacement begins.
- [ ] A failed build leaves the original services available.
- [ ] Failed migration/startup recovery restores prior SQL and dossier state.
- [ ] Manager self-update restarts into the new version and retains private state.
- [ ] Real NVR images, ESP32 output, and Shelly switching work on the physical station.
