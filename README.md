# AI Video Editor Desktop V2

A Windows desktop application for lecturer-supervised editing of educational videos. The native UI is built with React and Tauri; a managed FastAPI engine handles projects, media processing, and exports.

![Windows](https://img.shields.io/badge/platform-Windows%2010%2F11%20x64-0078d4)
![Tauri](https://img.shields.io/badge/Tauri-2-24C8DB)
![React](https://img.shields.io/badge/React-19-149ECA)
![Release status](https://img.shields.io/badge/status-RC6%20developer%2Ftest-orange)
[![Desktop V2 CI](https://github.com/desanv01/ai-video-editor-desktop-v2/actions/workflows/ci.yml/badge.svg)](https://github.com/desanv01/ai-video-editor-desktop-v2/actions/workflows/ci.yml)

[Status](#current-status) · [Architecture](#architecture) · [Development](#build-and-development) · [Checks](#checks) · [Data paths](#installation-and-data-boundaries) · [History](#development-history)

## Current status

The current source checkpoint is **2.0.0-rc.6**, with installer recovery work recorded on 4 September 2026. RC6 is a developer/test release candidate, not a production-ready release. Its installer is not Authenticode-signed, and the current source still needs clean-machine release validation and production signing evidence.

The current source checkpoint makes no claim to a production installer or a cleanly validated lecturer handoff. A test handoff requires a matched catalog and engine/FFmpeg component archives. Do not treat the test Ed25519 key or component signatures as a commercial publisher identity.

| Area | State |
|---|---|
| Native Windows shell and managed engine architecture | Implemented in source |
| Windows CI | Configured; check the [Actions page](https://github.com/desanv01/ai-video-editor-desktop-v2/actions) for the latest run |
| RC6 clean-machine installation evidence | Still required |
| Authenticode signing | Not present |
| Production release | Not ready |

## Product workflow

- Creates projects and imports lecture recordings and course materials.
- Guides a lecturer through source checks, processing, transcript review, edit decisions, and export.
- Runs a separately managed native engine and communicates with it over authenticated loopback HTTP.
- Installs engine and FFmpeg components through a manager that checks signed manifests, hashes, archive contents, and component self-tests before activation.
- Stages component updates and records activation state to support repair and recovery.
- Keeps projects and exports outside the installer directory; ordinary uninstall preserves user data.

## Architecture

~~~mermaid
flowchart LR
    UI[React and TypeScript UI] --> Shell[Tauri Windows shell]
    Shell --> Supervisor[Engine supervisor]
    Supervisor -->|dynamic loopback port plus bearer token| Engine[Managed FastAPI engine]
    Components[Verified engine and FFmpeg components] --> Engine
    Engine --> DB[(Native relational storage)]
    Engine --> Media[User projects, uploads, and exports]
~~~

The shell is a small per-machine application. The component manager verifies and activates the larger engine and FFmpeg runtime separately. The supervisor starts only the activated engine, selects a loopback port dynamically, supplies a generated bearer token, waits for the authenticated readiness handshake, and supports graceful shutdown.

The native engine profile uses local application storage rather than requiring Docker for the installed application. The source repository also retains a browser-development route from the earlier FYP line; running Vite in a browser is not the same as launching or validating the native Desktop V2 shell.

## Technical stack

| Area | Implementation |
|---|---|
| Desktop shell | Tauri 2.11.2, Rust, and the Windows NSIS/MSI packaging configuration |
| Frontend | React 19, TypeScript 5.7, Vite 6, and Tailwind CSS |
| Engine | FastAPI/Python 3.12, launched and supervised as a separate native process |
| Native data profile | SQLite and per-user filesystem storage; vector capability can be degraded when optional local vector services are unavailable |
| Media runtime | Managed FFmpeg 8.1.1 component |
| Shell-to-engine security | Dynamic loopback binding, generated bearer token, and authenticated readiness/control calls |
| Component integrity | Signed catalog and manifests, SHA-256 inventory checks, staging, activation, and recovery metadata |

## Repository structure

| Path | Contents |
|---|---|
| desktop/ | React application, Tauri shell, and installer configuration |
| backend/ | FastAPI engine and backend tests |
| contracts/ | Versioned runtime contracts and release provenance fixtures |
| scripts/desktop-v2/ | Packaging, installer, and validation tools |
| docs/desktop-v2/ | Architecture, setup, operations, and release evidence |
| fixtures/ | Synthetic inputs for selected checks |

## Build and development

### Requirements for source development

| Tool | Use |
|---|---|
| Windows 10 or 11 x64 | Target native shell and installer |
| Node.js 22 and npm | Frontend dependencies and build; Node 22 is used by CI |
| Stable Rust toolchain | Tauri shell |
| Visual Studio C++ Build Tools | Native Windows dependencies for Tauri |
| WebView2 Runtime | Windows web content inside the native shell |
| Python 3.12 | Backend unit tests and engine development |

The installed lecturer application is intended to use its managed engine and FFmpeg components; it does not depend on system Python, Node.js, Docker, or a system FFmpeg installation. The current RC6 handoff remains a developer/test build and has not passed the production release gates.

### Clone and build the frontend

~~~powershell
git clone https://github.com/desanv01/ai-video-editor-desktop-v2.git
Set-Location ai-video-editor-desktop-v2

npm ci --prefix desktop
npm run build --prefix desktop
~~~

### Browser development mode

~~~powershell
npm run dev --prefix desktop
~~~

Vite serves on port 1420. Browser mode follows the retained web/FYP path and may use the API on port 8000. It does not start the native V2 engine or prove that an installed component handoff works.

### Native Tauri development mode

~~~powershell
Set-Location desktop
npx tauri dev
~~~

A source-built shell does not include the generated release catalog or component archives. To exercise component installation, use a complete, matching developer/test handoff with its Catalog and Components folders kept together.

## Checks

The [Windows CI workflow](.github/workflows/ci.yml) runs frontend build, Rust formatting/checks/tests, unsigned NSIS source generation, desktop contract and installer checks, and the backend unit suite. The rendered-NSIS tests need generated installer source, so build the NSIS source before running npm test.

~~~powershell
npm ci --prefix desktop
npm run build --prefix desktop

Push-Location desktop
npx tauri build --bundles nsis --no-sign
Pop-Location

npm test --prefix desktop
cargo fmt --all --check --manifest-path desktop/src-tauri/Cargo.toml
cargo check --locked --manifest-path desktop/src-tauri/Cargo.toml
cargo test --locked --manifest-path desktop/src-tauri/Cargo.toml

py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt
.\.venv\Scripts\python.exe -m unittest discover -s backend/tests -p "test_*.py"
~~~

A passing CI or source test run does not replace a clean-machine installer test, release handoff verification, or Authenticode signing.

## Installation and data boundaries

A complete test handoff starts with an empty shell. Setup Center imports the release catalog, validates its component references, and installs the engine and FFmpeg components before the application can run the full native workflow. Keep Catalog and Components as sibling folders; if the handoff is moved, import the catalog again from its new location.

| Data | Default location |
|---|---|
| Per-machine shell | %ProgramFiles%\AI Video Editor Desktop V2\Shell |
| Components, catalog, and activation state | %ProgramData%\AI Video Editor |
| Per-user settings and disposable runtime state | %LocalAppData%\AI Video Editor |
| Projects, uploads, models, and exports | %USERPROFILE%\Documents\AI Video Editor |
| Provider credentials | Windows Credential Manager |

The default uninstall preserves user projects, uploads, models, databases, exports, settings, and stored credentials. A separate full-wipe operation is destructive and requires its own explicit confirmation. Never commit provider credentials, signing seeds, certificates, user databases, recordings, course materials, generated media, or release binaries.

Provider-backed AI features need the relevant lecturer-owned credentials. Local and manual workflows can run without provider keys where the selected workflow supports them.

## Development history

The milestone refs preserve the Desktop V2 work in chronological order. The product history ends with the September 4, 2026 RC6 work; later repository setup adds documentation and CI without claiming the RC6 release gates have passed.

| Date | Milestone | Historical ref or checkpoint |
|---|---|---|
| 2026-08-20 | Phase 0: protected baseline | codex/desktop-v2-phase-0 |
| 2026-08-20 | Phase 1: runtime contracts | codex/desktop-v2-phase-1 |
| 2026-08-20 | Phase 2: thin Tauri shell | codex/desktop-v2-phase-2 |
| 2026-08-20 | Phase 3: component manager | codex/desktop-v2-phase-3 |
| 2026-08-20 | Phase 4: native engine and FFmpeg components | codex/desktop-v2-phase-4 |
| 2026-08-20 | Phase 5: engine supervisor | codex/desktop-v2-phase-5 |
| 2026-08-20 | Phase 6: Setup Center | codex/desktop-v2-phase-6 |
| 2026-08-20 | Phase 7: migration and uninstall safety | codex/desktop-v2-phase-7 |
| 2026-08-21 | Phase 8: desktop product workflow | codex/desktop-v2-phase-8 |
| 2026-08-21 | Phase 9 and RC1 (2.0.0-rc.1): release handoff | codex/desktop-v2-phase-9; commit 2ccea79 |
| 2026-08-22 | RC2 (2.0.0-rc.2): installer ACL hotfix | codex/desktop-v2-installer-acl-hotfix; commit a7da1b4 |
| 2026-08-24 | RC3: lecturer handoff evidence hardening | codex/desktop-v2-rc3-lecturer-handoff-hardening |
| 2026-08-28 | RC4: first-run recovery hardening | codex/desktop-v2-rc4-first-run-recovery |
| 2026-09-02 | RC5: native runtime lifecycle hardening | codex/desktop-v2-rc5-commercial-overhaul |
| 2026-09-03–04 | RC6: transactional installer and interrupted-uninstall recovery | codex/desktop-v2-rc6-commercial-overhaul → codex/desktop-v2-rc6-installer-recovery-sep4 |

The Git history retains ancestry from the FYP repository. The separate 1.0.x standalone release-work copy is a legacy line and is not represented by these V2 milestone refs.

## Technical documentation

- [Architecture and operations](docs/desktop-v2/FINAL_ARCHITECTURE_AND_OPERATIONS.md)
- [RC6 lecturer setup](docs/desktop-v2/RC6_LECTURER_SETUP.md)
- [RC6 installation](docs/desktop-v2/RC6_LECTURER_INSTALL.md)
- [RC6 configuration](docs/desktop-v2/RC6_LECTURER_CONFIGURATION.md)
- [RC6 troubleshooting](docs/desktop-v2/RC6_LECTURER_TROUBLESHOOTING.md)
- [RC6 release provenance and gates](docs/desktop-v2/RC6_RELEASE_PROVENANCE.md)
- [RC3 clean Windows validation notes](docs/desktop-v2/CLEAN_WINDOWS_VALIDATION_RC3.md)

## Related project

The academic source and thesis evidence remain in the [AI Video Editor FYP repository](https://github.com/desanv01/ai-video-editor). This repository documents the separate Desktop V2 application line.