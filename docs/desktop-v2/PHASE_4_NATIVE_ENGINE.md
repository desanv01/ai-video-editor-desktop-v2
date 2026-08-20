# Desktop V2 — Phase 4 native core engine

Status: implementation complete on `codex/desktop-v2-phase-4`. Phase 4 adds a
Docker-free source/frozen native core and a separately versioned FFmpeg tool
component. It does not add the Phase 5 supervisor or the Phase 6 Setup Center.

## Architecture and mode boundary

The native profile is selected explicitly with `RUNTIME_PROFILE=desktop-native`
by `backend/native_engine.py`. The normal `backend/app/main.py` path and the
Docker/PostgreSQL/Redis/external-Qdrant configuration remain the default and
are not fallback targets for the native profile.

| Concern | Docker/browser profile | Native desktop profile |
| --- | --- | --- |
| Entry point | Existing `app.main`/Uvicorn workflow | `backend/native_engine.py`, no reload, `127.0.0.1` only |
| Database | Existing PostgreSQL URL/SQLAlchemy behavior | File-backed SQLite with `aiosqlite`, portable UUID adapter, migrations |
| Jobs/events | Existing application behavior and Docker services | Durable `desktop_jobs`/`desktop_job_events` SQLite store |
| Vector store | External Qdrant host/port | Qdrant client local/path mode; explicit SQLite cosine fallback if unavailable |
| Media tools | Existing `ffmpeg`/`ffprobe` resolution | Activated component-root absolute paths only |
| Authentication | Existing browser/Docker behavior | Bearer session on every route except exact `/live` |
| Runtime dependencies | Docker-provided services/tools | Frozen onedir Python engine plus separately activated FFmpeg component |

Native source mode is intended for development and verification. The onedir
component embeds the Python runtime; it does not require system Python when
installed and started from its component directory.

## Storage and path policy

`NativeDesktopPaths` requires `--data-root` or `AIVE_DESKTOP_DATA_ROOT` and
derives or accepts explicit overrides for database, vector store, uploads,
proxies, temp, logs, config, backups, models, projects, exports, components,
and the FFmpeg component root. The resolved paths are returned by
`/api/v1/runtime/paths` and in the Phase 1 engine-control `storagePaths`
object. All native writes are user-data writes; Program Files and Program
Files (x86) are rejected, including their descendants.

The default layout under the supplied root is:

```text
Config/engine.sqlite3       Config/ and Backups/
VectorStore/                Uploads/ and Proxies/
Temp/                       Logs/
Models/                     Projects/ and Exports/
Components/ffmpeg/         Components/ (other activated components)
```

SQLite startup sets `journal_mode=WAL`, `synchronous=NORMAL`,
`foreign_keys=ON`, and a 30-second busy timeout on every connection. Each
job/vector/backup operation closes its own connection; mutating job operations
use `BEGIN IMMEDIATE` and the same transaction writes the status and event.
`backup_database` uses SQLite's online backup API and integrity-checks the
result. `restore_database` requires active SQLAlchemy connections to be
disposed and retains a `.pre-restore.bak` by default.

The native schema ledger is forward-only and currently records:

| Revision | Purpose |
| --- | --- |
| `001_initial` | Core ORM tables |
| `002_app_ai_settings` | Persisted AI settings |
| `003_project_assets` | Project/project-asset compatibility |
| `004_project_media_sources` | Source type and sync role columns |
| `005_large_file_size_bigint` | Large-upload compatibility marker |

`PortableUUID` stores canonical text in SQLite and delegates to PostgreSQL's
native UUID type in the Docker dialect. Existing project, video, settings and
media routes are included by the native app, so the PostgreSQL model contract
is not forked.

## Jobs, vectors, health, and auth

The native API exposes durable job creation, listing, status, and event routes
under `/api/v1/jobs`. On startup queued/running/cancel-requested jobs are
marked `interrupted` with a recovery event. This is a single-machine durable
status/event mechanism; it does not claim Redis/Celery wire compatibility.

The vector abstraction first opens `QdrantClient(path=<vector-root>)` without a
host or port. If that local/path mode cannot initialize, the fallback is a
persistent SQLite cosine store and the capability is explicitly reported as
`sqlite-cosine-fallback`, state `degraded`, with
`VECTOR_STORE_UNAVAILABLE`. It is deliberately not silently presented as an
external-Qdrant equivalent.

The engine emits the Phase 1 `desktop.health-readiness.v1`,
`desktop.capabilities.v1`, and `desktop.engine-control.v1` payload shapes.
`/live` is the only unauthenticated route. `/health`, `/readiness`,
`/capabilities`, `/engine-control`, static mounts, OpenAPI, and all existing
API routes require the exact configured bearer token; failed requests receive
401 and `WWW-Authenticate: Bearer`.

The entrypoint accepts a required token and an optional/requested port. It
binds only to loopback, passes `reload=False`, logs structured JSON to stdout
and the configured log file, runs preflight/schema/vector/tool probes, and
handles SIGINT/SIGTERM/SIGBREAK with graceful SQLAlchemy shutdown. Phase 5 may
later own dynamic allocation and lifecycle; Phase 4 does not.

## FFmpeg component policy

Desktop mode never searches global PATH. Discovery accepts the activated
component root, finds `bin/ffmpeg.exe` and `bin/ffprobe.exe` (or root-level
executables), probes `-version`, then runs deterministic encode/decode probes.
The result and remediation codes are in the health/capability payloads.

Production packaging accepts only a caller-supplied local source directory or
archive. It requires the exact SHA-256 supplied by the release operator; the
archive extractor rejects traversal, links, and special files. No URL,
“latest” lookup, or unpinned binary download exists in the script. A source
must contain `ffmpeg.exe`, `ffprobe.exe`, a license/notice file, and valid
`source.json` metadata. The staging step writes the pinned version, source
hash, and version-probe record before invoking the Phase 3 packager.

Example production gate (the hash must come from the release input review):

```powershell
$hash = python scripts\desktop-v2\package_ffmpeg_component.py `
  --source-archive C:\release-inputs\ffmpeg-7.0.0-win64.zip `
  --print-source-hash --version 7.0.0 `
  --output-dir build\desktop-v2\artifacts\ffmpeg

python scripts\desktop-v2\package_ffmpeg_component.py `
  --source-archive C:\release-inputs\ffmpeg-7.0.0-win64.zip `
  --sha256 <reviewed-64-hex-sha256> --version 7.0.0 `
  --output-dir build\desktop-v2\artifacts\ffmpeg `
  --artifact-url https://updates.example.invalid/components/ffmpeg-7.0.0.tar.gz
```

The repository's command fixtures are explicitly test-only and are not
FFmpeg binaries. They exercise discovery and the packaging pipeline without
introducing a redistributable binary or a production license claim.

## Frozen engine and component boundaries

`scripts/desktop-v2/build_native_engine.py` generates a PyInstaller spec with
`Analysis`, explicit hidden imports/data files/native-library collection, and
`COLLECT`/`EXE` onedir output. It never uses one-file extraction. The build
dependency is pinned in `scripts/desktop-v2/requirements-native-build.txt`:

```powershell
python -m pip install -r scripts\desktop-v2\requirements-native-build.txt
python scripts\desktop-v2\build_native_engine.py `
  --output-dir build\desktop-v2\native-engine --clean --self-test
```

`package_native_engine.py` and `package_ffmpeg_component.py` invoke the Phase
3 `package_component.py`, producing separate manifests, deterministic tar.gz
archives, and detached signatures. Local validation uses the Phase 3
non-production fixture key only; no private key is in the repository. Build,
archive, manifest, signature, frozen runtime, and cache directories are
ignored and are not release inputs.

## Limitations and remediation

- Source smoke uses the host Python by definition; the frozen onedir smoke is
  the no-system-Python check.
- The installed qdrant-client may reject local/path mode after freezing or on
  a different stack. The explicit SQLite fallback keeps single-machine
  persistence but is degraded and must be surfaced to the user.
- Phase 4 does not ship local AI models, an FFmpeg binary, a supervisor,
  dynamic token/port ownership, or a polished Setup Center.
- The FFmpeg production gate remains release-input dependent: a reviewed,
  pinned archive/directory, hash, license bundle, source metadata, and
  protected production signing key must be supplied by release automation.

## Exact verification record

The following checks were run in the supplied worktree. Generated outputs were
under ignored `build/` or `tmp_*/` roots and are not commit content.

| Check | Result |
| --- | --- |
| Focused native unittest suite | PASS — 7 tests, including SQLite CRUD/locking/migrations/backup, durable recovery, vector persistence/filtering, path isolation, auth, health, FFmpeg probes, source smoke, and graceful shutdown |
| Existing project/model regression | PASS — 14 tests |
| Source entrypoint self-test | PASS — `backend/native_engine.py --self-test` |
| PyInstaller onedir build/self-test | PASS — PyInstaller 6.11.1; executable 23,966,073 bytes; onedir tree 376,880,320 bytes |
| Frozen engine smoke | PASS — `/live` 200, unauthenticated `/health` 401, bearer `/health` degraded with explicit SQLite vector fallback and FFmpeg ready; graceful shutdown log emitted |
| Native engine test-signed package | PASS — `aive-engine-1.0.0.tar.gz`, 166,145,820 bytes; manifest/signature emitted locally |
| FFmpeg test component package | PASS — synthetic version probes `7.0.0`; source fixture hash `0952c4a8d5ccdc40c5901fc5361a9404feb986266b33a23dd2ca64844d92f3c7`; separate 697-byte archive plus manifest/signature emitted locally |
| Phase 1 contract tests | PASS — 6 schemas, 11 fixtures |
| Phase 2 tests | PASS — boot transitions, missing-component startup, path invariants, diagnostics redaction, and runtime routing |
| Phase 3 Rust manager tests | PASS — 17 library tests, 0 failures |
| Rust cargo check | PASS |
| Frontend production build | PASS — 1,601 modules transformed; Vite build completed |
| Safety verifier | PASS after final source staging; the first pre-staging invocation was interrupted by the repository's `core.autocrlf=true` warning, not a safety finding |
| Docker compose configuration | BLOCKED — `docker compose config --quiet` reports `env file C:\Users\Dv\.codex\worktrees\ef97\ai-video-editor\.env not found`; no private `.env` was copied or created, so the existing localhost configuration was not started or modified |
| Full backend discovery | Attempted in isolated roots; blocked by the host Windows sandbox denying Python `tempfile` directories used by 35 pre-existing temp-heavy tests. Focused native (7) and project/model regression (14) suites pass. |
| `git diff --check` | PASS after final staging |

## Gate

PASS WITH RECORDED ENVIRONMENT BLOCKERS — the Phase 4 acceptance target is met by the source no-Docker
SQLite/vector smoke, deterministic token/path/health/FFmpeg behavior,
executable onedir build, and separately hash-gated FFmpeg packaging workflow.
Phase 5 has not been started. The full legacy backend discovery limitation is
environmental and is recorded above. Compose verification is also blocked by
the intentionally absent private `.env`; the Docker code path was not changed
by this phase, but a local Compose parse could not be claimed from this clean
worktree.
