# Desktop V2 — Phase 3 Component Manager

Status: implementation complete on branch codex/desktop-v2-phase-3 after the
final verification commands recorded below. Phase 4 runtime packaging is
explicitly out of scope.

## Scope and boundary

Phase 3 adds a small, machine-scoped component delivery subsystem behind the
Phase 2 thin shell. It can consume a signed manifest, resolve dependencies,
download a bounded archive resumably, verify it, extract it into an immutable
versioned staging directory, run a constrained self-test, publish it, select it
atomically, retain a last-known-good version, recover journal state, repair a
corrupt active version, roll back, and uninstall component-owned files.

It does not bundle or package the real backend, FFmpeg, Python/Node runtime,
database, vector store, model, renderer, or Docker image. Browser/Vite mode
continues to use the existing localhost API. The Phase 2 Tauri startup path
remains offline-safe and does not start the component manager automatically.

## Trust and security model

The manager accepts only desktop.component-manifest.v1 and uses strict serde
fields plus explicit semantic checks. Before any archive extraction it checks:

- HTTPS for production artifact URLs. file:// and localhost HTTP are available
  only when a debug build is called with allowTestSources: true and
  AIVE_COMPONENT_MANAGER_TEST_MODE=1. Release builds cannot enable that policy.
- exact artifact byte size, bounded artifact size, and SHA-256;
- detached Ed25519 signature and key id;
- a compiled, read-only trust root. The manifest cannot deliver or replace a
  public key;
- schema version, shell semantic-version floor, Windows/host architecture,
  dependency constraints, archive format, safe relative paths, and duplicate
  inventory paths;
- archive root, regular-file/directory kinds, exact byte sizes and hashes,
  duplicate paths, symlink/hardlink/device entries, reparse points, archive
  bounds, and total decompressed bytes;
- a self-test timeout, safe working directory, NUL-free arguments, cleared
  environment, and an allowlisted local interpreter or staged executable.

The checked-in trust root is intentionally non-production fixture material:

    key id:  test-fixture-2026
    algorithm: ed25519
    public key: hfqZ1Gk2qemcp+23vgMKpdMauxUlEXuBWF3NilhYA44=

Fixture mode derives this throwaway key from a public non-production label at
test/package runtime; no private seed file is committed. It must never be
promoted to a release trust root. Production signing belongs in protected
release automation; production private keys are not committed.

## ProgramData state layout

The manager receives the canonical ProgramData root from
desktop_v2::get_canonical_paths() and never silently falls back to AppData:

    %ProgramData%\AI Video Editor\
      Components\
        <component-id>\
          <version>\                 # published immutable version
          .staging\<version>-<op>\   # versioned pre-activation staging
          .verification\<version>-<time>\
      Activation\
        <component-id>\activation.json
        Journal\<operation-id>.json
      Catalog\
        <component-id>\<version>.json
      Downloads\Staging\
        <component-id>\<version>.part
        <component-id>\<version>.archive
        <component-id>\<version>.state.json
      component-manager.lock

Runtime component files never go under Program Files. User projects and
exports are outside this tree and are not targets of uninstall or cleanup.
The per-machine installer/update service is expected to own the ProgramData
directories with read access for the shell and write access for its elevated
service identity. If the current process cannot create or replace a
machine-scoped file, commands return ELEVATION_REQUIRED with
STORAGE_NOT_WRITABLE; no per-user fallback is attempted.

## State machine and recovery

Downloads persist .part bytes and .state.json after each bounded chunk. The
state records the expected size, digest, source URL, operation id, resume
cursor, and recovery status. A pause returns DOWNLOAD_PAUSED; cancellation
returns DOWNLOAD_CANCELLED; retry resumes the existing part where the source
supports a valid range. HTTP redirects are handled manually and are limited;
HTTPS never follows a downgrade.

Activation journals advance through:

    verifying -> staged -> published -> active
                             \-> failed

The publish step renames a same-volume versioned staging directory. Metadata is
written to a .part file, flushed, and replaced only after the published
version and exact inventory are valid. A journal left at published during a
crash is completed by component_recover; an invalid published directory is not
selected. Abandoned staging directories without a live staged journal are
removed only under the authorized Components root.

The active metadata retains previousVersion and previousPath. Retention is
bounded by the signed rollback count (1–5). component_rollback verifies the
retained inventory before selecting it. component_repair re-hashes the active
tree and automatically selects the retained last-known-good version when the
active tree is corrupt. A failed activation never deletes the previous
version.

The lock is a create-new file with a bounded stale-lock recovery window. A
live contention returns LOCK_CONTENDED and retryable remediation. Only one
manager operation can mutate the shared machine tree at a time.

## Tauri commands

| Command | Effect |
| --- | --- |
| component_intake_manifest | Strictly parse, validate, authenticate, and persist a catalog manifest |
| component_resolve_plan | Select a compatible version and resolve active dependency constraints |
| component_status | Report catalog, download, active, and repair-required state |
| component_download | Bounded HTTPS/local-test download to .part plus state metadata |
| component_pause / component_cancel | Request pause or cancellation for an operation id |
| component_retry | Resume a failed/interrupted download |
| component_verify | Recheck artifact size/hash/signature and archive inventory in verification staging |
| component_stage | Extract safely, validate exact inventory, and run the constrained self-test |
| component_activate | Publish the immutable version and atomically commit activation metadata |
| component_rollback | Select the verified retained previous version |
| component_repair | Verify active files and roll back when the last-known-good version is available |
| component_uninstall | Remove only component catalog/download/component/activation state |
| component_recover | Resume interrupted metadata recovery, clean abandoned staging, and repair download cursors |

Progress is emitted as component-operation-progress. The React bindings in
desktop/src/componentManager.ts and desktop/src/hooks/useComponentManager.ts
are intentionally compact; the polished Setup Center remains Phase 6 work.

## Deterministic packaging procedure

The fixture packager is standard-library Python and produces a deterministic
USTAR-in-gzip archive, inventory, manifest, manifest.sig, and (in fixture mode)
the public test key:

    python scripts\desktop-v2\package_component.py --component-dir fixtures\desktop-v2\component-manager\source --output-dir $env:TEMP\aive-component-fixture --component-id synthetic --version 1.0.0 --test-fixture

Fixture mode is local-only and visibly non-production. Production mode
requires --artifact-url=https://..., --key-id, and a private seed supplied from
protected release automation. Do not pass a production private key in a
repository file, shell history, fixture, manifest, or commit.

## Exact Phase 3 verification results

The final handoff records these checks from the supplied worktree:

| Check | Result |
| --- | --- |
| Phase 1 contract tests | PASS — 6 schemas and 11 fixtures |
| Phase 2 tests | PASS — boot transitions, missing-component startup, path invariants, diagnostics redaction, and runtime routing |
| Phase 3 Rust manager tests | PASS — 8 manager tests, including the local negative/security matrix |
| Full Rust library regression tests | PASS — 17 tests, 0 failures |
| Frontend TypeScript/build | PASS — `tsc` and Vite production build; 1,601 modules transformed |
| Rust focused tests and cargo check | PASS |
| Deterministic fixture packager | PASS — tar.gz, manifest, detached signature, and marked test public key emitted locally; no output is in the repository |
| Safety verifier | PASS — read-only secret, large-artifact, runtime/private, and whitespace scans |
| Installer configuration/resource inspection | PASS — thin shell resources remain empty and no runtime archive/model is tracked |
| git diff --check | PASS |

No network test source, downloaded runtime, model, database, key, upload,
installer artifact, node_modules, dist, or target output is part of the commit.
The exact commit hash and gate verdict are returned with the handoff.

## Gate

PASS — Phase 3 component manager gate. A tiny signed synthetic component can be
packaged, installed, verified, staged, self-tested, activated, resumed after
interruption, rolled back, repaired, and uninstalled locally. Tampered and
unsafe variants fail before activation; activation recovery is journaled;
Program Files is never runtime-writable; user data is preserved; and the Phase
2 thin installer/browser/Docker workflow remains buildable.

Phase 4 has not started.
