# Desktop V2 — Phase 6 Setup Center

Status: implementation complete on `codex/desktop-v2-phase-6` after the
Phase 6 source, catalog, frontend, Rust, and safety checks recorded below.
Phase 7 legacy migration/uninstall and Phase 8 broad editor improvements are
not part of this change.

## Product flow

The installed product is intentionally split into a tiny immutable shell and
machine-scoped components. In Tauri mode, the shell opens Setup Center when
either required component is missing, unhealthy, incompatible, or the
authenticated supervisor cannot report readiness. Browser/Vite mode continues
directly to the existing editor and does not call the Setup Center commands.

The first-run flow is:

1. Welcome — explain the shell/component boundary and the readiness gate.
2. System check — supported Windows/architecture/shell version, disk space,
   storage roots, scoped write permission, network/catalog reachability, active
   versions, supervisor/native health, and optional GPU/model capability.
3. Choose components — core engine and FFmpeg are required. Optional local
   transcription, model, and render packs are shown as available only when a
   signed artifact exists; catalog-only entries never claim installation.
4. Review — show artifact sizes, source/license versions, staging/rollback
   behavior, and require an explicit license/source acknowledgement.
5. Download — real Phase 3 resumable manager operation with aggregate and
   per-component progress, pause, cancel, retry, saved operation ids, and
   restart recovery.
6. Verify — signed manifest, artifact hash, archive inventory, target, and
   compatibility checks.
7. Install/activate — safe extraction, signed self-test, immutable publish,
   and atomic active-version selection.
8. Engine readiness — start the Phase 5 supervisor, wait for authenticated
   loopback readiness and capabilities, and keep Launch editor disabled until
   the gate is true.
9. Complete — show active required versions and provide Launch editor and
   Component management.

On later starts, active required versions plus `ready`/`degraded` authenticated
   supervisor readiness bypass onboarding. The first successful setup is still
   persisted as non-secret state for recovery and display.

## Catalog/configuration policy

`desktop.setup-catalog.v1` is a signed, versioned envelope containing entries
that embed/reference the Phase 1 component-manifest contract. The envelope
signature has an Ed25519 algorithm, key id, and detached value. The shell uses
the compiled read-only trust root already owned by the Phase 3 manager; a key
delivered by a catalog is never trusted. Every embedded manifest is passed to
the existing Phase 3 intake, which verifies its own signature, artifact URL,
hash, target, layout, dependency, inventory, self-test, and health contract.

Production catalog URLs are build/release-time `AIVE_SETUP_CATALOG_URL`
configuration and must be HTTPS. Debug/lecturer builds may expose the same
setting at runtime for testing. The explicit Offline import path accepts a
local signed catalog only under the existing debug test policy
(`AIVE_COMPONENT_MANAGER_TEST_MODE=1`); it does not weaken the release trust
root. Catalog cache content contains no tokens or provider secrets and is
re-verified when read back.

Optional entries use `available`, `catalog-only`, or `unavailable` states.
`catalog-only` is the honest state for unreleased packs and carries no
installable manifest. Required entries are limited to `aive-engine` and
`ffmpeg`, and a catalog missing either required entry is rejected.

## ProgramData permission decision

The Phase 6 decision is an installer-created ACL, not permanent elevation:

- the per-machine NSIS installer creates `%ProgramData%\AI Video Editor` and
  grants the interactive Users group Modify access only to this component
  perimeter; SYSTEM and Administrators retain Full Control;
- the shell process remains non-elevated and never launches the entire app as
  administrator;
- Program Files remains the immutable shell location;
- the manager returns `ELEVATION_REQUIRED`/`STORAGE_NOT_WRITABLE` when the
  scoped ACL is absent or broken, and Setup Center explains repair/UAC steps;
- no fallback component/runtime path under AppData is attempted;
- before supervisor launch, the existing manager re-verifies the active
  manifest and exact installed inventory. A writable component perimeter is
  therefore paired with integrity verification rather than trusted by path.

The system check performs a bounded write probe of the component root and
LocalAppData state root. A cancelled UAC/permission repair is recoverable and
does not activate an unverified path.

## Durable state and recovery

`%LocalAppData%\AI Video Editor\State\setup-state.json` stores only:

- selected optional pack ids;
- accepted component license versions;
- stable/beta/nightly channel;
- last successful setup timestamp;
- component-to-operation ids for incomplete downloads/activation;
- onboarding completion and state schema version.

Catalog metadata is cached beside it after signature verification. No bearer
tokens, provider secrets, API keys, or model content is persisted by this
phase. On startup the shell calls the existing manager recovery command,
re-reads statuses, and offers Resume saved setup for interrupted operations.

## Error and diagnostics UX

The UI maps manager/supervisor codes to friendly recovery copy for offline,
proxy/TLS, insufficient disk, permission/UAC cancellation, bad hash/signature,
incompatible component, self-test failure, activation crash, repair-required,
rollback, and retry exhaustion. Raw exceptions are not shown as the primary
message; technical detail is expandable and redacted. Diagnostics export is
the existing redacted local snapshot plus Setup Center state/status summaries.

## Accessibility/responsiveness

The Setup Center uses semantic headings, labelled navigation, live progress
announcements, keyboard-visible focus, native checkbox/select semantics,
status text in addition to color, forced-colors-safe borders, reduced-motion
CSS, and a 1024×700 minimum Tauri window. Layout collapses to a single-column
flow below the desktop breakpoint while preserving all actions.

## Test coverage

Deterministic frontend tests use `createSetupClient` with a mock Tauri bridge
and cover state defaults, healthy bypass gating, required/optional truthfulness,
catalog envelope/schema rejection, progress aggregation, friendly recovery/error
redaction, pause/resume/cancel/rollback/repair command wiring, browser-mode
isolation, and ACL policy. Rust tests cover state validation and secret-like
state rejection, required catalog shape, signature payload normalization,
compiled-trust-root rejection, and HTTPS-only production configuration. The
existing Phase 3 manager tests cover resumable download/cancel, hash/signature,
disk/storage limits, activation rollback, repair, and archive safety; Phase 5
tests cover supervisor crash/readiness recovery. Existing browser/Docker source
paths remain in scope for the verification run.

## Verification record

The exact final commands and results are recorded here after the final clean
verification pass:

| Check | Result |
| --- | --- |
| Phase 1–5 contract/frontend checks | PASS — `npm run test`: 6 contract schemas/11 fixtures, Phase 2, and Phase 5 suites passed |
| Phase 6 frontend mock/store tests | PASS — `npm run test:desktop-v2`: Phase 6 state/catalog/mock-bridge/progress/recovery/browser/ACL checks passed |
| Frontend TypeScript/build | PASS — `npx tsc --noEmit`; `npm run build`; Vite transformed 1,605 modules |
| Rust full tests and `cargo check` | PASS — `cargo check`; `cargo test`: 34 tests passed, 0 failed |
| Native engine smoke | PASS — `python backend\native_engine.py --self-test`; `python -m unittest backend.tests.test_desktop_native`: 7 tests passed |
| Setup Center mocked end-to-end flow | PASS — deterministic mock Tauri bridge plus real manager queue command path and existing manager activation/recovery tests |
| Safety verifier | PASS — secret scan, large-artifact scan, protected-path/runtime scan, and staged diff checks |
| Accessibility/static inspection | PASS — focused Setup Center `rustfmt --check`, schema/static assertions, focus/reduced-motion/forced-colors rules, and redacted diagnostics assertions |
| Thin installer size/resource inspection | PASS — 1024×700 minimum, per-machine NSIS, 0 configured bundle resources, no Phase 6 component/runtime/model/archive payloads |
| `git diff --check` | PASS — no whitespace errors; repository autocrlf warnings are baseline-only |

## Gate

The Phase 6 gate is **PASS**. The final verification record is populated with
passing results; the known Vite chunk-size/dynamic-import messages and existing
repository autocrlf warnings are non-blocking baseline warnings. Phase 7 has
not started.
