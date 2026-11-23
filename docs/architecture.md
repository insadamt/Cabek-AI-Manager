# Native application deployment and update architecture

This document explains why Manager owns deployment rather than changing the apps.
It depends on published GitHub releases, original native configuration contracts,
Docker Compose, a single Linux PC, and durable private installation state.

## Ownership and compatibility

All Dockerfiles, dependency recipes, proxy configuration, and deployment tests live
in Manager. Exact application release archives are immutable inputs. Source files
are never patched, instrumented, or supplemented with Manager API routes. The
corrective application commits restore the approved native baselines; subsequent
integration work remains exclusively in this repository.

All six application repositories are mandatory. The separate AutoEstimate frontend,
Scrapper, and legacy Streamlit are excluded. Manager provides real station setup;
missing hardware is represented as disconnected or requiring attention.

## Runtime layout

The Manager-owned gateway owns the shared Docker network namespace and host ports.
The frontend serves on port 80 inside that namespace; its existing build-time API
setting points to the canonical local application origin. It proxies API traffic
through the gateway. Backend, cameras, lighting, and OCR use native loopback
addresses in the same namespace, preserving original local-settings restrictions.
Only gateway ports are published, bound to host loopback. AutoEstimate PHP-FPM,
Nginx, and MariaDB use private Compose networking with a persistent SQL volume.

The backend runs `python -m api`; lighting runs `python -m lighting_api`. Camera
startup is unchanged. OCR uses its native ASGI application and `/app/output`
mount. No runtime JavaScript injection, backend authentication bypass, new health
routes, changed seeders, or new Artisan commands are required in the apps.

Image identities include source revision, deployment recipe content, and build
parameters. Frontend port changes consequently produce a distinct recoverable
image. Runtime tuning imported from existing native dotenv files is retained;
Manager resolves container paths, credentials, native real-camera mode, and
internal service addresses. Private imported values are omitted from public APIs.

## Setup and persistent state

Manager generates stable database credentials, Laravel APP_KEY, camera/OCR keys,
and its private gateway-control key. AutoEstimate credentials are validated and
reused; fresh setup captures the existing native token command's output privately.
Native migrations and canonical seeders precede checksum-tracked imports.

Configuration no longer exposes profiles or per-application enable flags. The
station form collects NVR access, channels, ESP32 device, Shelly address, ports,
and storage locations. Existing application dotenv files are read only. Credentials
remain private under `.local/`; assistant tooling and runtime folders are ignored.

Application runtime and hardware readiness are independent. Camera readiness uses
native frame availability; Shelly uses its existing status endpoint. Lighting
process liveness and USB presence do not claim verified physical output. A device
identity watcher refreshes only the lighting container mapping while native work
is idle. Multiple devices require an explicit stable selection.

## Update transaction

1. Resolve every repository's newest published stable numeric release and exact SHA.
2. Download missing archives, render external recipes, build, and prepare Manager's environment.
3. Atomically close mutation admission at the Manager gateway and finish admitted
   HTTP requests. Stop preview streams so they do not hold native shutdown open.
4. Acquire the existing dossier admission/capture/scan locks and check native job
   states and OCR status. Complete a capture-to-analysis handoff before declaring idle.
   Work waiting for vehicle metadata leaves the update unapplied with an explanation.
5. Stop the backend only after native work is idle, then back up SQL, dossiers,
   runtime state, OCR output, configuration, imports, and installed revisions.
6. Journal before stopping backend, validate the backup, remove application
   namespace consumers before gateway, retain MariaDB with `--no-recreate`, run
   native migrations/seeders, provision/reuse credentials and import datasets.
7. Start the complete stack, set real camera operation through its existing API,
   check native connectivity, and open admission. Hardware may remain disconnected.
8. Publish installed revisions, clear the transaction, and queue a prepared Manager restart.

A failed build or admission drain leaves running applications untouched. A backup
failure restarts a stopped backend without applying migrations. Failures after
mutation restore the recorded SQL/data snapshot and previous Compose/images.
Interrupted operations remain recoverable through persisted transaction state.

## Corrective handover

The previous deployment is backed up before restoration. Its updater requires
Dockerfiles inside application repositories, so the corrected host Manager is
bootstrapped directly before using the new update path. Existing private files,
credentials, databases, and unrelated application work are preserved. Only known
Manager-generated sample dossiers/photos are quarantined outside active data;
quarantined files and pre-correction backups are never silently deleted.

## Manual acceptance checklist

- [ ] Install every application without modifying individual repositories or dotenv files.
- [ ] Confirm the light Cabek appearance and absence of Manager demo/selection controls.
- [ ] Verify disconnected NVR/ESP32/Shelly states while applications remain installed.
- [ ] Connect hardware and verify essential cameras, ESP32 effects, and Shelly output.
- [ ] Complete real capture, OCR, pricing, image analysis, and PDF workflows.
- [ ] Confirm tags/drafts/prereleases produce no notice; published stable releases do.
- [ ] Verify Update All waits for accepted work and preserves credentials and data.
- [ ] Verify failed deployment recovery and Manager restart retain the prior station state.

The [November deployment audit](deployment-audit-2026-11.md) records the subsequent
Rootless mapping initializer, all-nine-service software checks, database retention,
validated model-inclusive backups, real Docker evidence and station acceptance limits.
