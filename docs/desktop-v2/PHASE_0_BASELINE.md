# Desktop V2 — Phase 0 Protected Implementation Baseline

Status: Phase 0 baseline prepared from origin/main at 4916303287ad22eb94736ef85c985f11743b0c2a.

This document is the handoff contract for Phase 1. It records what was observed, what is protected, what remains intentionally unchanged, and which checks must be repeated before implementation proceeds.

## 1. Baseline identity

The supplied worktree was inspected before any Phase 0 edits.

| Field | Observed value |
|---|---|
| Worktree | C:\Users\Dv\.codex\worktrees\3364\ai-video-editor |
| Repository root | C:\Users\Dv\.codex\worktrees\3364\ai-video-editor |
| Initial branch state | Detached HEAD; no local branch was checked out |
| Initial HEAD | 4916303287ad22eb94736ef85c985f11743b0c2a |
| origin/main | 4916303287ad22eb94736ef85c985f11743b0c2a |
| Initial working tree | Clean; status reported only the detached HEAD header |
| Remote | origin https://github.com/desanv01/ai-video-editor.git (fetch and push) |
| Phase 0 branch | codex/desktop-v2-phase-0 |
| Baseline source count | 247 tracked files |
| Baseline tracked size | 4,280,375 bytes (about 4.08 MiB) |
| Baseline date | 2026-08-20, Asia/Kuala_Lumpur |

The detached state was not changed until the clean commit was verified. The Phase 0 branch was then created at the exact baseline commit. No protected Desktop folder was used as a Git working directory or source for this work.

## 2. Source safety and preserved implementation

All Phase 0 work is confined to the supplied worktree. The following folders are outside the implementation scope and must remain untouched:

- C:\Users\Dv\Desktop\ai-video-editor
- C:\Users\Dv\Desktop\ai-video-editor-viva-clean
- C:\Users\Dv\Desktop\ai-video-editor-standalone-release-work

The protection is stronger than “do not commit changes”: do not edit, clean, reset, stash, checkout, delete, install into, copy from, or copy to any of those paths. Do not compare them by reading their files as part of a Phase 0 or Phase 1 workflow. The worktree is the only source of truth for this implementation line.

The existing localhost development path is preserved:

- docker-compose.yml remains the development stack: FastAPI on port 8000, PostgreSQL, Qdrant, Redis, and Docker-managed storage.
- desktop/src remains the React/Vite teacher-facing client.
- desktop/src-tauri remains the existing Tauri shell and native import/bootstrap surface.
- backend/app and backend/tests remain the backend implementation and canonical unit-test root.
- desktop/revideo and backend/revideo remain optional render support; Phase 0 does not remove or relocate them.
- docker-compose.desktop.yml is preserved as the current packaged-compose reference. Phase 0 does not retrofit it or make the development stack depend on Desktop V2.

No runtime ZIP, uploaded recording, course-material upload, model file, database volume, provider credential, .env, build output, dependency cache, or generated media is a Phase 0 source artifact. The existing docs/fyp_context_pack.zip is a 202,303-byte documentation archive already tracked at baseline; it is not a runtime bundle and is not a template for adding runtime archives.

## 3. Current source inventory

The baseline repository is a thesis/source snapshot with these active boundaries:

| Area | Role | Important entry points |
|---|---|---|
| backend/app | FastAPI API, SQLAlchemy/Alembic persistence, direct async agent orchestration, provider routing, RAG, extraction, rendering and exports | backend/app/main.py, backend/app/api/routes/, backend/app/agents/ |
| backend/tests | Canonical backend unit/service suite | backend/tests/test_*.py |
| desktop/src | React 19 + TypeScript + Vite UI | desktop/src/main.tsx, desktop/src/App.tsx, desktop/src/lib/api.ts |
| desktop/src-tauri | Tauri 2 native shell, IPC, storage layout, native import and current backend bootstrap | desktop/src-tauri/src/main.rs, desktop/src-tauri/src/lib.rs |
| desktop/revideo | Desktop-side optional Revideo scene/render helper | desktop/revideo/render.mjs |
| backend/revideo | Backend-side optional Revideo support | backend/revideo/render.mjs |
| docker-compose.yml | Local development services | FastAPI, PostgreSQL, Qdrant, Redis |
| docker-compose.desktop.yml | Existing packaged desktop service definition | Loopback services with host bind mounts |
| fixtures/synthetic_media | Privacy-safe deterministic test fixtures | Synthetic transcript, slides and manifest |
| docs | Reproducibility, audit and thesis evidence | docs/fyp_context_pack/, docs/reproducibility/ |
| scripts | Existing verification and source-package helpers | scripts/check_setup.py and test/verification scripts |

Dependency manifests present at baseline are desktop/package.json and desktop/package-lock.json, desktop/src-tauri/Cargo.toml and Cargo.lock, backend/requirements.txt, and the two Compose files. There is no root Node project. desktop/node_modules was absent at inspection time, so an install is allowed only as a proportionate local verification prerequisite and must remain ignored/uncommitted.

## 4. Current architecture

The active workflow is a teacher-supervised video editor:

    React/Tauri UI
        └─ HTTP/IPC
           FastAPI
            ├─ PostgreSQL for structured state
            ├─ filesystem for media and generated artifacts
            ├─ Qdrant for material retrieval when configured
            ├─ direct async agents and provider adapters
            └─ FFmpeg/native compositor (Revideo is optional)

There are two intentional localhost defaults:

- Browser development uses http://localhost:8000 and the development Compose stack.
- The current Tauri bootstrap targets http://127.0.0.1:18000, creates an app-data storage layout, writes a generated desktop backend environment file, invokes the external docker CLI/Compose, starts the aive-desktop project, and waits for /health.

The current Tauri configuration bundles docker-compose.desktop.yml and backend/**/* as resources. It does not make the application self-contained: Docker Desktop/engine, Compose, container base images or an equivalent portable runtime are external prerequisites. The current UI also contains browser defaults and native IPC paths, so a browser stack and a desktop stack can point at different databases and show different projects.

## 5. Known standalone failure mechanism

The current standalone path is a Docker-launcher path, not a self-contained desktop runtime. desktop/src-tauri/src/lib.rs generates AIVE_DESKTOP_ENV_FILE and the AIVE_HOST_* storage paths under per-user app data, then calls:

    docker compose --env-file <generated env> -f <desktop compose> -p aive-desktop up -d --build

docker-compose.desktop.yml has mandatory host bind mounts and an env_file whose values are supplied by that launcher-generated environment. Its bind-mount sources have no safe standalone defaults. Therefore, running the desktop Compose file directly, or launching from a package where the bootstrap/resource/runtime assumptions are not satisfied, produces empty or unresolved host paths, a missing environment file, or an unavailable Docker engine before the backend can become healthy. The recorded repository evidence classifies raw desktop Compose validation as failing without launcher-provided AIVE_HOST_* values.

The failure is a deployment-coupling mechanism with several contributing assumptions:

1. The Tauri process must find the Compose resource and the bundled backend context.
2. Docker CLI, Docker Compose and a reachable Docker engine must exist on the machine; the current shell may attempt to start Docker Desktop but cannot supply a Docker runtime in the installer.
3. The generated app-data environment and every host storage directory must be writable and valid for Docker bind mounts.
4. Required container images/build dependencies must be available or downloadable.
5. The frontend must switch from the browser default port 8000 to the bootstrapped loopback port 18000 only after a healthy bootstrap.

This baseline records the mechanism; it does not attempt to fix it. Desktop V2 will address it with a thin shell and signed, downloadable, versioned components while keeping the Docker localhost path intact for development.

## 6. Phase 0 non-goals

- No Phase 1 runtime, downloader, signer, installer, service supervisor or migration code.
- No changes to the FastAPI API contract, React workflow, Docker development stack or current renderer.
- No edits to the three protected Desktop folders.
- No copying or inspection of private media, uploads, models, volumes, logs, .env files or credentials.
- No installer build, clean-machine test, Docker image publication, provider call, database migration, or end-to-end render.
- No claim that the existing standalone path is fixed or production-ready.
- No cleanup of existing repository content, generated caches or unrelated worktree state.

## 7. Risks carried into Phase 1

| Risk | Consequence | Required response |
|---|---|---|
| External Docker/runtime coupling | Packaged launch fails before health | Define a portable component contract and explicit prerequisite matrix |
| Unsigned or partially downloaded components | Arbitrary code or corrupted runtime activation | Verify signature and digest before activation; stage atomically; retain rollback |
| Path/permission differences on Windows | Bind mounts, FFmpeg and uploads fail | Use per-user app data, normalized paths, preflight checks and safe errors |
| Data/schema incompatibility | Existing projects become unreadable after update | Version storage and API contracts; migrate forward with backup/rollback |
| Provider credentials and local models | Secrets leak or models inflate installer | Keep credentials outside components; use explicit user-owned model storage and redacted diagnostics |
| Large media and render resource pressure | Disk exhaustion, long startup, render failure | Quotas, free-space checks, cancellation/cleanup and measured performance gates |
| Browser/desktop split-brain state | User sees different projects/stacks | Make runtime identity and backend endpoint visible; keep dev and standalone profiles explicit |
| Lack of frontend/E2E coverage | Packaging regressions escape static builds | Add clean-machine smoke and component lifecycle tests before release |
| Revideo/native renderer optionality | Unsupported path becomes accidentally required | Keep native FFmpeg as the defined baseline and test optional paths separately |

## 8. Exact verification commands

Run from the supplied worktree only. These commands are read-only except for the explicitly allowed dependency/build outputs in ignored folders. Do not create .env to make a check pass.

    git rev-parse --show-toplevel
    git branch --show-current
    git rev-parse HEAD
    git status --short --branch
    git remote -v
    git ls-files

    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\desktop-v2\Verify-DesktopV2Baseline.ps1

    # Only when desktop\node_modules is absent:
    npm install --prefix desktop
    npm run build --prefix desktop

    # Use the isolated environment if present; do not install dependencies as part of Phase 0.
    .\.venv\Scripts\python.exe -m unittest discover -s backend\tests -p "test_*.py"

    cargo check --manifest-path desktop\src-tauri\Cargo.toml
    docker compose config --quiet
    docker compose -f docker-compose.desktop.yml config --quiet

If an environment-specific command cannot run, record the exact command, exit code, stderr classification and whether the blocker is missing tooling, missing isolated dependencies, network/sandbox policy, or a source defect. Do not replace a failed check with an unrecorded workaround.

## 9. Actual Phase 0 verification record

The following checks were run from this worktree. Generated node_modules, desktop/dist, Rust target files and the ignored tmp/desktop-v2-backend-tests test scratch directory were not staged.

| Check | Result | Evidence/classification |
|---|---|---|
| Git identity and clean-start inspection | PASS | Initial state was clean detached HEAD at 4916303287ad22eb94736ef85c985f11743b0c2a; origin/main pointed to the same commit; branch created as codex/desktop-v2-phase-0 |
| Desktop V2 read-only verifier | PASS | Exit 0 from Verify-DesktopV2Baseline.ps1; branch/status reported; secret, large-artifact, runtime/private-path and whitespace scans passed. Protected-path behavior is enforced before scanning; it was not executed from a forbidden folder. |
| Frontend dependency install | PASS WITH WARNINGS | npm install --prefix desktop exited 0; added 370 packages and audited 371. npm reported 19 vulnerabilities and four pending install scripts; no audit fix or script approval was run. |
| npm run build --prefix desktop | PASS | Exit 0; TypeScript/Vite build transformed 1,598 modules and completed in 8.27 seconds. |
| Canonical backend unit suite, default paths | BLOCKED BY ENVIRONMENT | python -m unittest discover -s backend\tests -p "test_*.py" reached all 193 tests but exited 1 with 1 failure and 35 errors. Failures were PermissionError/Access denied writing normal Windows temp paths and the default \data\videos path under the managed sandbox. |
| Canonical backend unit suite, safe worktree paths | BLOCKED BY ENVIRONMENT | The same command was retried with TEMP/TMP and all storage paths redirected to ignored tmp/desktop-v2-backend-tests. It again reached 193 tests with 1 failure and 35 PermissionError errors, including writes denied inside the worktree temp directory. Escalated execution was rejected because it would permit writes outside the authorized safety boundary. No further variants were attempted. |
| cargo check --manifest-path desktop\src-tauri\Cargo.toml | PASS | Exit 0; Rust/Tauri dev profile finished in 2m 51s. |
| Development Compose config | BLOCKED BY MISSING LOCAL CONFIG | docker compose config --quiet exited 1 because the ignored local .env file is absent. No .env was created. Passing .env.example with --env-file does not replace the Compose service env_file reference to .env, so that safe retry produced the same missing-file result. |
| Raw packaged Compose config | EXPECTED FAILURE CONFIRMED | docker compose -f docker-compose.desktop.yml config --quiet exited 1, warning that AIVE_HOST_* and AIVE_DESKTOP_ENV_FILE were unset, then reporting an empty bind-mount section. This reproduces the documented launcher-variable failure mechanism without starting services. |
| Artifact hygiene audit | PASS | Git-visible inventory and the verifier found no runtime/private tracked paths, live credential files, high-confidence token shapes or files over the 50 MiB threshold. Existing docs/fyp_context_pack.zip remains documentation evidence, not a runtime bundle. |

## 10. Phase 0 gate

Phase 0 is complete only when all of the following are true:

1. The branch is based directly on 4916303287ad22eb94736ef85c985f11743b0c2a and the initial clean state is recorded.
2. The three Phase 0 documents and the read-only verifier are committed under docs/desktop-v2/ and scripts/desktop-v2/.
3. The verifier cannot be run from any protected path and reports source status without writing to the repository.
4. Frontend, backend and Rust checks are run or precisely classified; no failure is hidden.
5. The Docker localhost implementation remains unchanged and available for development.
6. No private data, credentials, runtime artifact, build output or dependency cache is committed.
7. The commit hash is recorded in the handoff and the gate verdict is explicit.

Gate verdict: PASS WITH EXPLICIT ENVIRONMENT BLOCKER. The Phase 0 implementation baseline is complete and committed; the backend suite remains an execution-environment blocker, not a hidden pass or a proven source defect. The development Compose check also requires a user-provided local .env and was intentionally not made to pass by creating one. Phase 1 is not started.
