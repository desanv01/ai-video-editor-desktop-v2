# Rebuild architecture and acceptance contracts

## Ownership and identities

Electron owns windows, per-user paths, first-run preparation/components, private backend launch/shutdown, secure credentials, dialogs/downloads, updates and shell diagnostics. FastAPI owns domain APIs, projects/transcripts/teacher decisions, five agents, retrieval, render plans/outputs and application jobs. React displays their state and submits actions. No heavy model/media work runs in the renderer/main event loop.

Git base: Desktop origin/main `131606d8d9746378febb80a2403c271ed68f157a`. Original behavior source: `1e4a7d084d64e98646f495020f4b56b1649be298`. Rebuild engineering version: `2.1.0-rebuild.1`. Source pins and component identity must agree at release; stale RC6/RC8 engine versions must be changed when the backend is built.

## Paths and installation

- Windows x64, per-user assisted NSIS first. appId `com.aive.desktop.rebuild`, product `AIVE Desktop`. No all-users toggle in this first supported scope.
- Shell binaries: normal electron-builder per-user install location. Writable root: `%LOCALAPPDATA%/AIVE/Desktop`, independent of install directory and FYP/legacy app data. Electron Chromium userData: `%LOCALAPPDATA%/AIVE/Desktop/Shell`.
- Backend data root: `%LOCALAPPDATA%/AIVE/Desktop/Data`, with existing explicit NativeDesktopPaths Config/engine.sqlite3, Uploads, Projects, Exports, Models, VectorStore, Backups, Temp, Logs. Components root `%LOCALAPPDATA%/AIVE/Desktop/Components`.
- Controller state/cache/logs: `%LOCALAPPDATA%/AIVE/Desktop/{State,Cache,Logs}`. Component versions immutable under `Components/<id>/<version>`; active mapping in atomic JSON state, never rename a running version.
- No writes to installation binaries or FYP. No automatic legacy-data migration/deletion. Uninstall preserves projects/database/models/exports by default; separate explicit data removal is outside installer scope.

## Private backend lifecycle and authentication

Reuse `backend/native_engine.py` bound-loopback startup and `desktop.engine-handshake.v2`. Main creates TCP control server at 127.0.0.1 port 0, fresh random bearer token/sessionId/nonce; spawn activated aive-engine.exe with `windowsHide`, `shell:false`, supplied data/component/FFmpeg roots and port 0. Secrets go in child environment, not CLI/process logs. Verify bounded newline JSON handshake, protocol, nonce/session, child PID, engine identity/version from active manifest, host 127.0.0.1, valid port and HMAC. HMAC input is newline joining protocolVersion/sessionId/nonce/pid/componentId/componentVersion/host/assignedPort. Do not infer readiness from stdout.

Authenticated health follows handshake and must affirm API/database readiness. Capabilities can be unavailable without blocking dashboard; tools/model/provider requirements block only relevant work and setup's required capability gate. Start asynchronously after visible window. Startup timeout produces recoverable controller error; no repeated hidden auto-restarts. Shutdown POST /engine-control/shutdown, bounded 10s graceful wait then terminate owned child, handling process tree when necessary. A crash invalidates the session/endpoint immediately. Single instance owns one child and activation/download locks.

## Renderer transport, media and downloads

Register `aive` as standard, secure, supportFetchAPI, stream before app ready; do not bypass CSP. Load bundled frontend at `aive://app/`. `aive://app/api/v1/*` proxies through main to the verified backend and injects bearer token. Renderer never receives backend port or bearer token. Same-origin custom protocol serves JSON, multipart/chunk uploads, streams, thumbnails/subtitles and downloads with the ordinary API paths. The proxy rejects unknown hosts/path traversal, arbitrary targets, forbidden headers, unexpected methods and redirects; forwards range requests and preserves status/content-type/content-length/content-range/accept-ranges. Never buffer entire media in IPC. Requests cancel when caller aborts or session exits. Content-Disposition downloads use a narrow native save API and stream to user-selected output.

Preload exposes frozen typed methods only: getState, onState(unsubscribe), prepare/cancel/retry, restartEngine, pickMedia, saveResource(relative API path, suggested name), openDiagnostics, credential set/remove, bounded safe external links. Each IPC handler validates argument shape and sender main frame/origin. Never expose ipcRenderer, eval, exec, arbitrary filesystem reads or an unrestricted HTTP proxy. Electron `contextIsolation:true`, `sandbox:true`, `nodeIntegration:false`, `webSecurity:true`; deny unexpected navigation/popups/permissions. Packaged CSP limits resources to owned scheme/self and explicitly required blob/data media. Dev server support is an explicit developer mode only, no production localhost fallback.

Protocol and security reference: https://www.electronjs.org/docs/latest/api/protocol and https://www.electronjs.org/docs/latest/tutorial/security (read 2026-10-02). Protocol video stream privilege is explicit. Production range/seeking requires installed checks, not assumed fetch equivalence.

## Automatic component preparation

One versioned bundled manifest is owned by the release. User never selects catalog JSON. Discover packs from `resources/offline-components` and `offline-components` beside the installer/app handoff location where accessible; online only from HTTPS URLs pinned in the manifest. No arbitrary catalog URL prompt. Installer can seed/copy adjacent offline assets by standard resource packaging for the offline edition; availability must be proven at packaging.

Manifest `aive.components.v1`: releaseVersion/platform/architecture/components. Each component: id/version/archive filename/sha256/sizeBytes/expandedBytes/required/entrypoints/probes plus optional HTTPS URL. Entry points and archive names are relative paths with no traversal/absolute paths/drive prefix. Backend, FFmpeg/ffprobe and document pack are required for the full edition; Whisper runtime + selected model jointly form local-transcription capability. No fake hashes, URLs, sizes or successful probes. Until built packs exist, ship a clearly unconfigured manifest and truthful unavailable state.

Controller phases: checking -> awaiting_confirmation -> acquiring -> verifying -> extracting -> probing -> activating -> starting -> ready, plus cancelled/error. Persist operation id, fixed selected component list and byte denominator, per-component phase/bytes/versions/error. Publish stable progress using a fixed work plan; 100% means activated/probed, not merely downloaded. Check free space against compressed + expanded + retained current version + margin before extraction. Stream download to .part, HTTPS only, bounded redirects to approved HTTPS origins, resumable Range with validated Content-Range/ETag; if server ignores Range, explicitly restart bytes safely. Offline and online go through identical verification/probe/activation. Hash verification precedes extraction; reject archive traversal/symlinks and expansion beyond declared bound. Extract within a unique owned staging path. Probe before activation; atomic state replace, preserve last good version and journal interrupted operation. Cancellation stops acquisition/extraction, does not replace active version; retry reuses verified parts. Do not treat missing pack/model as optional ready.

`DesktopState` is authoritative: schemaVersion/releaseVersion/phase/setupComplete/engineState/components/capabilities/progress/error/canCancel/canRetry. React cannot manufacture readiness by merging old Tauri catalog flags. Shell/base workspace ready, individual component installed, provider configured and actual feature ready are separate meanings. No optional model/provider/update network call delays normal dashboard.

## Credentials

Windows Electron safeStorage encrypts provider credentials in an app-owned file; renderer receives only configured/redacted metadata. Entered keys reach main via typed method; main supplies secrets to the private backend via a later authenticated integration, never a public env file. If encryption unavailable, fail explicitly and preserve unsaved input in UI only. No raw credentials in SQLite, source, build/ZIP, diagnostics, URLs or logs. Existing backend settings encryption/credential API integration must be reviewed in Phase 3/4 to avoid duplicate competing stores.

Reference: https://www.electronjs.org/docs/latest/api/safe-storage (read 2026-10-02).

## SQLite and jobs

Retain SQLAlchemy model logical entities/UUIDs/enums/JSON/FK/delete relations. Desktop uses portable types with defined UTC API serialization (Z/+00:00); original naive UTC columns do not become local times. WAL, FK ON, synchronous FULL for authoritative edits, bounded busy timeout; backups via SQLite backup API including consistent committed state. Versioned migrations with pre-upgrade backup, atomic version marking, forward compatibility rejection and recovery. Never copy only hot database file.

AI/network/document/media compute must not retain write transactions. A2 segments committed before A3/A4 read; parallel computation remains but writes update only owned columns in short coordinated transactions. Use detached snapshots/revision checks where necessary, not arbitrary retries on stale full-row ORM state. App jobs/index state stored durably, restart converts in-flight work to interrupted/retryable, no invented completed jobs.

## LanceDB retrieval boundary

Replace Desktop embedded Qdrant/fallback behind rag.vector_store with LanceDB only. Preserve public ensure_collection/stats/reset/ingest_course_material/ingest_transcript/add_chunks/search/delete_by_source and source result shape. Preserve source original page chunk algorithm (~225 words, ~37 overlap for defaults 300/50) and transcript chunk algorithm (~60s groups, speaker metadata). Embedding model/dimension remain selected configured values (currently text-embedding-3-small/1536 by default), not hardcoded adapter defaults.

Use cosine distance and return similarity = 1-distance, round to 4 decimals after threshold filtering; threshold <=0 means no threshold, matching original. Source_type and source_id filters applied before ranking, top_k after filtering; exact search initially to avoid approximation drift. Stable UUIDv5 vector identity from source type/id/chunk index/configuration. Payload preserves text/source_id/source_type/chunk_index plus metadata dict. Enforce vector dimensions and finite values; do not silently re-embed mismatched index data.

SQLite source/chunk records include stable ID/text/metadata/config signature/vector snapshot or explicit rebuild source; indexing operation pending -> vectors replaced -> complete. Restart recovers incomplete replacements/deletes idempotently. Use complete visibility generation so partially replaced source cannot leak duplicate/stale context. Delete operations durable and recoverable. Re-embedding through hosted provider is deliberate and reports connectivity/cost. Empty/unavailable index differs from successful zero matches. No silent Qdrant/cosine fallback selected by failure.

## Dependency and render contract

Private Python onedir executable with pinned requirements and imported Windows wheels. Required FFmpeg/ffprobe must cover h264 CPU, AAC, libass captions, drawtext/fonts, scaling/crop/overlay/concat, audio mixing and probes for actual renderer use. PyMuPDF/PPTX/DOCX/OpenCV/audio libraries included only from active source paths. Managed LibreOffice + fonts for faithful PPTX; extraction alone is insufficient. whisper.cpp CPU executable/DLL/model pinned jointly, WAV conversion and real short transcription probe. GPU capability only after actual device/execution evidence. Native FFmpeg semantic render plan remains authoritative. Revideo disabled default is retained; special render dependencies traced before claiming equivalent full coverage.

## UI system and setup interaction

Design read: lecturer desktop editing workspace, calm/precise, preserve workflow and useful editing density. UI UX Pro Max primary, Taste limited to applicable preservation/type/spacing/consistency. 12ui explicitly excluded. Existing React 19/Vite/Tailwind 3/Lucide retained. Variance 3, motion 2, density 7. Current source uses Segoe UI stack, purple accent, charcoal surfaces and action colors; redesign may unify them while preserving action semantics. Use system Segoe UI for offline typography, semantic tokens and visible keyboard focus; compact UI labels >=13px, transcript >=15px, body ~14-16px. Small laptop and Windows 125/150/200% scaling reviewed. Dialog labels/errors/loading/empty states and scroll containment explicit.

Skill search returned a valid Productivity Tool category/minimal style but landing-page pattern/scroll-reveal/palette did not fit the multi-stage editor. Do not persist that output as an approved screen. Main design contract is a product-specific fallback synthesis: neutral surfaces, one restrained action accent, semantic action/status colors, no marketing heroes/images/scroll animations. Phase 2 setup minimal; final screen-by-screen tokens and layouts supplied before Phase 5.

## Acceptance gates (main owns execution)

1. Shell/provisioning: main-focused tests for manifest rejection, path confinement, verification-before-activation, partial/Range recovery, cancellation and durable state; installed window opens without developer tools.
2. Backend/storage: isolated SQLite migrations/backup/FK/teacher edits/concurrent agent writes; LanceDB same vectors/filter/threshold/top-k/delete/reopen/index interruption corpus.
3. Workflow: real single video, materials and multi-source project; original five agents and six stages; approval; teacher override reopen; representative layout/captions/overlays/cards; actual export probe/playback and academic/original-transcript files.
4. Lifecycle: actual local whisper transcription, interrupted setup/import/render, lean relaunch measurements with hardware/time identity, diagnostics, controlled child shutdown and Windows uninstall preserving data.
5. Release: main reviewed commits/push/PR; CI exact commit; uniquely named Desktop ZIP with exact verified installer/offline assets, guide, SHA-256/manifest/component/commit/CI identity, accurate signing/provider/clean-PC limitations. No merge without human authorization.

Build/test results indicate only what was executed. Clean-PC, other-laptop, live provider, GPU and signing checks are separate unverified gates until evidence exists. No packaged release is complete merely because one shell build succeeds.
