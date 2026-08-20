# Desktop V2 — Phase 2 Thin Shell

Status: implementation complete on `codex/desktop-v2-phase-2`.

This phase delivers the small, installable Tauri shell only. It does not
download, install, activate, supervise, or package the core engine or any
other runtime component. The Phase 1 schemas and canonical storage layout
remain the source of truth.

## Architecture

The application now has two explicit runtime routes:

```text
Browser/Vite
  -> current React editor
  -> existing localhost API default (http://localhost:8000/api/v1)

Tauri Desktop V2
  -> get_shell_info
  -> desktop_v2_bootstrap
  -> offline-safe shell/setup/diagnostics UI
  -> no backend, Docker, Python, Node, FFmpeg, database, vector store,
     model, or engine startup
```

`desktop/src/App.tsx` detects Tauri through the read-only `get_shell_info`
command. A browser that cannot invoke Tauri continues to the existing editor
route. A Tauri window renders `DesktopV2Shell` and never enters the legacy
Docker bootstrap route.

The legacy `bootstrap_desktop_backend` command and native import surface remain
in the Rust crate for compatibility with the existing web/localhost workflow;
Desktop V2 does not call them during shell launch.

The Rust implementation is isolated in
`desktop/src-tauri/src/desktop_v2.rs`. It only performs local path discovery,
read-only activation metadata inspection, authorized per-user shell-state
persistence, and redacted diagnostic snapshot writes. The boot state machine
is:

`DesktopV2ErrorBoundary` keeps render failures in a structured recovery screen;
raw exception text is not shown as a startup error.

```text
starting -> shell-ready -> setup-required
                       \-> engine-available
                       \-> recoverable-error
```

An activated engine component can be discovered as `engine-available`, but
`engineReady` remains false. API-dependent views are enabled only when a later
supervisor-ready transition sets that flag; Phase 2 has no supervisor.

## Product and installer identity

The V2 installer uses:

- Product: `AI Video Editor Desktop V2`
- Version: `2.0.0`
- Identifier: `com.fyp.ai-video-editor.desktop-v2`
- Windows target: per-machine NSIS installation with elevation
- Start Menu folder: `AI Video Editor Desktop V2`
- Shortcuts: Tauri NSIS default Start Menu and Desktop shortcuts, grouped in
  the V2 Start Menu folder
- Resources: none; no Compose file, backend tree, runtime ZIP, model, or
  external engine is bundled

The thin shell is installed under `%ProgramFiles%\AI Video Editor\Shell` by
the NSIS hook. The existing identity is retained in
`desktop/src-tauri/tauri.legacy.identity.json` for compatibility references:
`AI Video Editor`, `1.0.0`, `com.fyp.ai-video-editor`. It is not an installer
profile for this phase.

The successful no-sign debug NSIS build produced this ignored artifact and it
was not installed:

```text
desktop/src-tauri/target/debug/bundle/nsis/
  AI Video Editor Desktop V2_2.0.0_x64-setup.exe
size: 3,970,640 bytes (3.79 MiB)
SHA-256: 9C2F3A04295168C7B720E3D48683CD29CE4620F8076A88C13F0907DD17CCBCD2
```

## Exact Windows paths and ownership

These paths match `desktop.storage-layout.v1` and the checked-in valid storage
fixture:

| Path | Owner | Phase 2 behavior |
| --- | --- | --- |
| `%ProgramFiles%\AI Video Editor\Shell` | machine installer | immutable shell binaries and static resources only |
| `%ProgramData%\AI Video Editor\Components` | future machine update service | read-only reference point; no Phase 2 writes |
| `%ProgramData%\AI Video Editor\Activation` | future machine update service | read-only metadata inspection; missing metadata is normal |
| `%ProgramData%\AI Video Editor\Downloads\Staging` | future machine update service | not touched by Phase 2 |
| `%LocalAppData%\AI Video Editor\Config` | user runtime | reserved for per-user config |
| `%LocalAppData%\AI Video Editor\Cache` | user runtime | reserved for rebuildable cache |
| `%LocalAppData%\AI Video Editor\Logs` | user runtime | redacted diagnostic snapshot output |
| `%LocalAppData%\AI Video Editor\State` | user runtime | `shell-state.json` persisted here |
| `%USERPROFILE%\Documents\AI Video Editor\Projects` | user runtime | default project location reserved by contract |
| `%USERPROFILE%\Documents\AI Video Editor\Exports` | user runtime | default export location reserved by contract |

The primary core-engine activation file read by the shell is
`%ProgramData%\AI Video Editor\Activation\aive-engine.json`. For forward
compatibility with the Phase 1 examples, the read-only inspector also accepts
`active.json` and `aive-engine\activation.json` when present. It never treats a
filename alone as trusted: the JSON must identify `aive-engine`, contain a
version and active checkpoint, and point below the immutable ProgramData
Components root.

No runtime-writable path is derived below Program Files. The shell state and
diagnostic commands validate their targets against the resolved LocalAppData
root before writing.

## Shell commands

The Tauri invoke commands are:

| Command | Effect |
| --- | --- |
| `get_shell_info` | returns V2 identity, shell version, launch policy and state path |
| `get_canonical_paths` | returns resolved Windows paths plus the Phase 1 storage layout |
| `inspect_activation_metadata` | reads optional ProgramData metadata and returns structured missing/available/invalid status |
| `get_safe_log_directory` | creates/returns only the per-user LocalAppData Logs directory |
| `desktop_v2_bootstrap` | performs the deterministic local boot transition and persists `shell-state.json` |
| `generate_diagnostic_snapshot` | writes a redacted JSON snapshot only under per-user Logs |

No command in this list starts a process or makes a network request. Technical
read errors are retained only in the redacted diagnostic snapshot; the UI
shows remediation codes and action-oriented messages rather than raw fetch or
filesystem errors.

## Offline-safe startup behavior

With zero components and zero Docker:

1. The shell renders product identity and version immediately.
2. Local path discovery and state persistence run under the user profile.
3. Missing activation metadata produces `setup-required`, not a fatal launch.
4. The component summary shows `Desktop V2 shell: available` and
   `Core engine: not-installed`.
5. Setup Center explains that signed component delivery is a later phase.
6. Diagnostics can create a redacted local snapshot.
7. Editor/API/upload/render views remain visibly gated; they cannot emit a
   raw `Failed to fetch` error from the Desktop V2 route.

## Tests and build commands

Run from the supplied managed worktree:

```powershell
npm install --prefix desktop                         # only when node_modules is absent
npm run contracts:check --prefix desktop
npm test --prefix desktop
npm run build --prefix desktop

rustfmt --edition 2021 --check desktop\src-tauri\src\desktop_v2.rs
cargo test --manifest-path desktop\src-tauri\Cargo.toml --lib desktop_v2::tests
cargo test --manifest-path desktop\src-tauri\Cargo.toml --lib contracts::tests
cargo check --manifest-path desktop\src-tauri\Cargo.toml

Push-Location desktop
npm run tauri -- build --bundles nsis --debug --no-sign
Pop-Location

powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\scripts\desktop-v2\Verify-DesktopV2Baseline.ps1
git diff --check
```

The frontend test command covers all six Phase 1 schema families plus the
Phase 2 boot transitions, missing-component startup, path invariants,
diagnostic redaction, engine-view gate, and browser-vs-Tauri routing.

## Limitations and phase boundary

- No Phase 3 downloader, signature verifier, archive extractor, updater,
  activation writer, rollback executor, engine supervisor, or health probe is
  included.
- Setup Center is explanatory only; it cannot download or install a component.
- A present activation record means “component available for a later
  supervisor”, not “engine process ready”.
- Tauri Desktop V2 intentionally does not show the current editor until a
  future supervisor establishes an authenticated ready state. Browser/Vite
  mode remains the current editor workflow.
- The legacy Tauri/Docker bootstrap code remains for additive compatibility but
  is not reachable from Desktop V2 startup.
- The installer was built and inspected but not installed on the protected
  machine profile.
- `npm install` reported the baseline dependency audit warnings (19 findings)
  and four install scripts awaiting explicit approval; no audit fix or script
  approval was run.
- The repository's pre-existing `lib.rs` formatting differences mean a full
  `cargo fmt -- --check` remains a baseline-style check; the new Phase 2 Rust
  module has a clean module-specific rustfmt check.

## Verification record and gate verdict

| Check | Result | Evidence |
| --- | --- | --- |
| Starting identity | PASS | Branch started at `codex/desktop-v2-phase-1`, commit `3ff44d9a4ef459d89beda4afdca9c7c880a0332b`, clean worktree |
| Phase 1 contract checks | PASS | `npm run contracts:check --prefix desktop`: 6 schemas and 11 fixtures |
| Phase 2 frontend/unit tests | PASS | `npm test --prefix desktop` |
| Frontend build | PASS | `npm run build --prefix desktop`; Vite transformed 1,601 modules |
| Focused Rust shell tests | PASS | 5 tests passed |
| Focused Rust contract tests | PASS | 4 tests passed |
| `cargo check` | PASS | Tauri crate compiled with the V2 shell module |
| New-module rustfmt | PASS | `rustfmt --edition 2021 --check desktop\src-tauri\src\desktop_v2.rs` |
| Installer/config inspection | PASS | V2 identity, `perMachine`, Start Menu folder, empty resources; no runtime bundle entries |
| NSIS artifact | PASS | 3.79 MiB no-sign debug installer built; not installed |
| Phase 0 verifier | PASS | Protected-path, secret, large-artifact, runtime-path and whitespace scans |
| Full crate rustfmt | QUALIFIED | Existing pre-Phase-2 `lib.rs` formatting differences remain; no unrelated reformat was applied |

Gate verdict: **PASS WITH BASELINE-STYLE QUALIFIER**. The thin shell is
installable, useful with no backend components, keeps the browser workflow
available, enforces the Phase 1 path boundary, and contains no bundled heavy
runtime. Phase 3 is not started.
