# Private demo dossiers, imports, and diagnostics

This consolidated technical report explains the new native private administration, safe dossier imports, Manager deployment changes, validation evidence, and operating limits. It depends on Backend v0.2.0, Frontend v0.2.0, Manager v0.3.0, the existing native dossier/result schemas, Docker Compose, and private local storage. It supplements the deployment architecture document; no application source is patched during builds.

## Components and changed files

Backend owns `api/private_demo/`: server-side authentication, bounded native ZIP bundles, immutable template revisions, registry mappings, independent materialization, and authenticated routes. Capture admission selects a template before invoking native camera or scan services. `scans/jobs.py` rejects real scans for simulated evidence and prevents unmatched real inference while private demo operation is enabled. E-Constat routes reuse prepared OCR and cannot silently start real OCR for prepared dossiers. `scripts/demo_admin.py` initializes/rotates a local scrypt secret; `scripts/import_dossiers.py` performs validated additive imports.

Backend repository/schema/service changes expose `demo: true` on simulated dossier responses while retaining production response shapes. Original photos, annotation identities, financial data, PDF references, E-Constat documents and compatible caches use native contracts. Reports materialized from templates receive a visible demonstration footer. Verification contains only native before/after evidence and no AI result. Imported captures do not automatically resume analysis after a container restart.

Frontend adds `PrivateDemoAdmin`, `DemoTemplateEditor`, and an authenticated transport using expiring HttpOnly cookies. Settings' version entry opens the login after five taps within three seconds. Administrative controls are not mounted before authentication. There is no ordinary Settings demo switch. The camera picker distinguishes prepared demonstrations from unavailable physical cameras; the capture store follows a new independently cloned expertise identity. Existing operator detail, annotation, comparison and report components remain in use. Normal diagnostic cards display the actual explanation with Disponible / À vérifier / Erreur / Désactivé / Non testé, preserving Dynamic Island for significant operational notifications.

Manager owns private mounts, backups, credential initialization, additive import orchestration and read-only host network diagnostics. `compose.py`, `backups.py`, `dossier_import.py`, `demo_secret.py`, `network_diagnostics.py`, API import handling and the Manager import form are the relevant changes. Shared deployment recipes stay exclusively in Manager.

## Persistent storage and initial configuration

Manager binds these directories beneath its configured station data root:

- `dossiers/`: normal production and materialized demo dossiers; templates are never stored here.
- `private-demo/`: the secret hash, server session digests, private registry, immutable template revisions and private documents/results.
- `demo-photos/`: ordinary sample-camera photographs, configured through `CABEK_MOCK_PHOTOS_DIR=/data/demo-photos` and mounted read-only into the backend.
- `runtime/`, `ocr-output/`, existing models and SQL retain their existing roles.

Private administration uses `CABEK_DEMO_DIR=/data/private-demo` and `CABEK_DEMO_SECRET_FILE=/data/private-demo/secret.json`. No password/hash is returned by Manager configuration APIs or ordinary application APIs. These values are not part of a public setup form. Private directories and runtime data remain ignored by Git.

After the native releases and Manager deployment are installed, initialize the owner's password locally:

```sh
cd /path/to/Cabek-AI-Manager
.venv/bin/python -m manager.demo_secret --home /absolute/path/to/Manager/.local
```

The command prompts twice without echo, sends the password to the existing backend over stdin, and writes only a scrypt record with mode 0600. Enter the exact owner-provided password, including punctuation and its final backslash; it is intentionally absent from this document and committed code. The native equivalent is `python scripts/demo_admin.py --secret-file /data/private-demo/secret.json` inside the managed backend. Existing secrets are never overwritten without explicit `--rotate`.

Sessions expire after 30 minutes, use HttpOnly/SameSite Strict cookies, and are stored only as token digests on the server. Password rotation changes the epoch and revokes every existing session. Logout revokes the current token. Five failed guesses trigger persistent increasing delays, capped at fifteen minutes. Every administration endpoint checks the server session; mutations additionally require the private custom header and existing local settings boundary. Private responses prohibit caching; diagnostic logs redact private endpoint identities.

For sample-camera previews, supply owner-selected JPEG/PNG photographs under `demo-photos/front`, `rear`, `left`, `right`, or use side-prefixed filenames. `before/` and `after/` may each contain their own four side folders. The unphased preview uses `before/` when phase folders exist. Missing phases, invalid image data and missing configured storage produce explicit errors. Private template photographs are never silently exposed as global sample previews. No synthetic sample dataset is installed into production.

## Preparing and using a template

1. Open normal Cabek Settings; tap the version five times and authenticate.
2. Create an inactive template for the required dossier type and normalized matricule, or import a native single-dossier ZIP with `metadata.json` at its root.
3. Edit vehicle metadata, native photo records and camera identity mappings. Upload original images, aligned annotation images, E-Constat PDFs, optional report and prepared result JSON under their native relative paths. The metadata editor uses the native contract rather than an invented demonstration schema.
4. Save a new inactive revision. Upload artifacts before adding their manifest references. Photo stems must be unique across both verification phases, as required by the native repository. Original and annotation dimensions must match.
5. For expertise/quick estimation, supply valid native `StoredAnalysis` JSON: `schema_version`, `dossier_id`, `vehicle`, `financial`, `parts`, `detections`, `photos`. Financial totals retain existing validation. A missing optional report is generated through the native report service using the prepared financial breakdown. Verification requires four before and four after sides and rejects an AI result.
6. Validate and activate. A second active mapping for the same normalized matricule and type is rejected atomically. Revisions are immutable; edits create a new revision. Deactivate before deletion. Deletion removes the registry entry while retaining private revisions for recovery. Existing materialized demonstrations remain independent.
7. Enable demo operation privately, then use the ordinary operator workflow with the registered matricule. Creation may remain a draft until registration is known. Capture performs lookup server-side and publishes independent evidence/results. Expertise keeps its externally owned originating dossier and returns a new normal dossier identity. The frontend follows that identity.
8. Disable demo operation before real inspection. Unmatched registrations fail clearly while demo operation is enabled. Existing simulated dossiers never become eligible for physical recapture or real inference merely because operation returns to real mode.

The existing frontend capture/result transitions are reused. Prepared copies are not advertised as genuine running AI jobs; their native scan progress remains absent. The capture source and immutable metadata provenance identify simulation. The native completion path can finish immediately because results are already prepared.

Uploads are bounded to 10 MiB per artifact, 128 MiB per private ZIP, 512 MiB unpacked and 5,000 files. Archives reject traversal, duplicate paths, links, special files and encrypted entries. Images use native full decoding and size limits. Imports reject active captures and queued/processing worker state. Strict registration handling reuses the native Moroccan Latin/Arabic-letter rules.

## Additive imports for the four E-Constat dossiers

Use Manager's import section with the local native dossier root and these optional IDs:

```text
DOS-ECONSTAT-875915-A,DOS-ECONSTAT-892246-A,DOS-ECONSTAT-892323-B,DOS-ECONSTAT-895671-A
```

Run **Validate import**, inspect Activity, then **Import validated dossiers**. A local directory or ZIP is accepted. Manager mounts the selected source read-only, closes write admission for publication, waits for native work, and invokes the native validator/importer. Identical copies are reported as duplicates. Conflicts stop publication; no production dossier is silently replaced. A partial failed batch rolls back newly published imports. Data enters existing persistent dossier storage and existing backups. The destructive seed script is never called.

The standalone native importer supports `--destination`, optional `--ids`, and an explicit `--apply`. Without `--apply` it only validates. Use standalone publication only while the backend is quiesced; the Manager interface owns the live admission barrier. Imports add an internal flag preventing automatic capture-to-inference resumption on startup, without dropping original evidence or result data.

## Backup, rollback, and recovery

Every Manager update backup includes `private-demo/` and `demo-photos/` alongside dossiers, runtime and OCR output. Secrets and mappings therefore survive normal recreation, updates and recovery. Private archive permissions and the broader private Manager installation directory remain the host access boundary. Backups contain credentials and must remain private.

Failed template registry publication retains the prior revision. Incomplete materialization remains hidden, and failed draft publication restores previous metadata/removes newly created artifacts. Native dossier admission locks serialize capture/cloning. Verification's before/after finalization remains durable. A changed/deactivated template cannot silently replace an already collected before phase.

Restore through Manager's existing recovery flow rather than manually mixing private registry versions and public dossier data. Password rollback restores the backed-up password record; rotate again after a security-driven recovery. Expired sessions remain expired. Do not erase private revisions or data directories during application upgrades.

## Network diagnostics

Manager reports process health, actual camera image availability, NVR route/RTSP connectivity and Shelly availability independently. Read-only `ip -j address` and `ip -j route get` identify Ethernet without IPv4 and suspicious Wi-Fi/tunnel/gateway routes for direct cables. RTSP OPTIONS on port 554 confirms a responding RTSP endpoint, not credentials or usable frames. Guidance asks the operator to check compatible IPv4 subnets, cabling, NVR power and routes. No address, route, interface or host network setting is changed automatically.

## Release/deployment sequence

1. Commit Backend changes coherently and publish stable **v0.2.0** on its existing `dev` branch.
2. Commit Frontend changes coherently and publish stable **v0.2.0** on `master`.
3. Commit Manager deployment, tests and this report coherently and publish stable **v0.3.0** on `main` after checks pass.
4. Use **Check for updates**, then **Update All**. For the one-time upgrade from the older renderer, wait for the new Manager to restart, then choose **Apply configuration** when shown to add the private mounts. New installations use the correct mounts immediately. There is no automatic disruptive startup migration. Manager downloads published stable archives; branch commits, plain tags, drafts and prereleases are not deployment inputs.
5. Initialize the local private password, validate/import the four requested dossiers, and prepare owner-selected templates. Keep demo operation disabled after acceptance.

No tags are rewritten. Existing application data and unrelated local projects remain in place. Rollback backups retain the previous installed revisions.

## Verification and manual checklist

Recorded checks before publication: Backend **422 passed**, Frontend **779 passed / 106 files**, Manager **67 passed** plus **6 Node UI state tests**; including read-only one-time mount detection. Automated evidence includes full Backend, Frontend and Manager regression suites, private API tests for all three categories, password/session/CSRF/rate-limit boundaries, template privacy, conflict/concurrency and rollback, original/annotation validation, independent cloning, native financial/result/PDF compatibility, E-Constat preview, verification finalization, unmatched blocking, native production resumption and backup/restore of private assets.

Live acceptance used a running native backend and actual HTTP operator endpoints with isolated controlled photo/PDF fixtures, rather than relying only on mocked unit results. It exercised quick results/annotations/reports, expertise identity redirection and unchanged external inputs, E-Constat preview, eight-photo verification finalization and unmatched blocking. A bounded real frontend browser check confirmed hidden controls before authentication, five-tap access, password login and the authenticated dashboard; no Playwright was used. Controlled fixtures remain outside production dossier/template storage.

- [x] Hidden dashboard and every management API require server authentication.
- [x] Native fixtures for all three dossier types validate and materialize through ordinary operator endpoints.
- [x] Private templates never enter public dossier listings or public media storage.
- [x] Prepared demonstrations do not invoke physical capture or model inference in acceptance checks.
- [x] Normal production API behavior and regression suites remain covered.
- [x] Backup/restore tests preserve private templates and sample photos.
- [x] Browser login interaction and diagnostic presentation reviewed.
- [ ] Verify the final installed stable releases and enabled Manager user service on the station.
- [ ] Confirm the four real E-Constat dossiers import without conflicts and review their existing PDFs/OCR data.
- [ ] Prepare owner-approved production templates and review their actual results visually.
- [ ] Confirm direct Ethernet and RTSP guidance against the station's connected NVR.
- [ ] Verify real ESP32/Shelly output and normal real capture after disabling demo operation.
- [ ] Review narrow-screen administration and the full operator capture transition with the station operator.

Remaining physical checks cannot be inferred from API health, USB detection or prepared demonstrations. Sample photos are supplied by the owner; the installer does not invent vehicle evidence. This version uses the native JSON contract for detailed prepared result editing rather than a new financial/detection form editor.

Suggested commit messages: `feat(backend): add authenticated private demo dossiers and safe native imports`; `feat(frontend): add hidden demo administration and truthful diagnostics`; `feat(manager): preserve private demo data and guard dossier imports`.
