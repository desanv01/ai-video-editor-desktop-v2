# Desktop V2 — Phase 1 Contracts

Status: implementation contract and gate record for Phase 1. This phase defines
versioned data shapes only. It does not start the downloader, installer,
component manager, process supervisor, migration runner or standalone runtime
planned for later phases.

## Scope and source of truth

The machine-readable schemas under
[contracts/desktop-v2/schemas/](../../contracts/desktop-v2/schemas/) are the
wire-format source of truth. The TypeScript validators in
[desktop/src/contracts/desktopV2.ts](../../desktop/src/contracts/desktopV2.ts)
and the Serde types/validators in
[desktop/src-tauri/src/contracts.rs](../../desktop/src-tauri/src/contracts.rs)
are executable repository representations of those shapes. Deterministic
examples and failure cases live under
[fixtures/desktop-v2/contracts/](../../fixtures/desktop-v2/contracts/).

| Contract | Version | Purpose |
| --- | --- | --- |
| Component manifest | desktop.component-manifest.v1 | Signed component identity, target, artifact, install layout, entrypoint, dependencies, capabilities, inventory, self-test, health and rollback metadata |
| Engine control | desktop.engine-control.v1 | Shell-to-backend startup, dynamic loopback allocation, session authentication, process identity, paths, capabilities and graceful shutdown |
| Health/readiness | desktop.health-readiness.v1 | Process liveness, API/database/vector-store/FFmpeg/model checks, degraded operation, fatal errors and remediation |
| Capabilities | desktop.capabilities.v1 | Requested and available component/host capabilities with source and remediation |
| Storage layout | desktop.storage-layout.v1 | Canonical Windows path templates, ownership, writers and runtime write boundaries |
| Update state | desktop.update-state.v1 | Resumable download journal, interrupted recovery, verification/activation checkpoints and rollback |

The TypeScript contract module exports validateComponentManifest,
validateEngineControl, validateHealthReadiness, validateCapabilities,
validateStorageLayout and validateUpdateState. Each returns the corresponding
strong type or throws ContractValidationError. Rust exposes the same six
contract families through Serde structs, validate() methods and parse helpers.
Serde field names use the same camelCase JSON names as the TypeScript types.

## Compatibility and version policy

1. Consumers select a contract by its exact schemaVersion string. An unknown
   version is rejected before use; there is no silent fallback to an older
   contract.
2. A breaking field rename, enum change, security-policy change, or semantic
   invariant creates a new versioned schema and new Rust/TypeScript
   representations. A v2 consumer must not reinterpret v1 data.
3. A v1 revision may add an optional field only when old consumers can safely
   ignore it. Because these schemas close objects with
   additionalProperties: false, such a revision must update the schema,
   fixtures, validators and compatibility tests together. Required fields and
   enum values are not changed in place.
4. Component version, minimumShellVersion and dependency constraints use
   semantic versions. A dependency constraint is evaluated against the
   installed component version by the future updater; a manifest is rejected
   if its constraint is malformed.
5. A shell accepts a component only when the manifest schema version, target OS
   and architecture, minimum shell version, signature key policy, artifact
   digest, file inventory and health contract are all compatible. This phase
   defines those checks; it does not implement download or activation.
6. Health payloads are intentionally additive at the check level: a missing
   optional aiModel check means “not reported/configured”, not “healthy”.
   Required checks remain api, database, vectorStore and ffmpeg.

## Security boundaries

- Component artifacts must use https://, carry a lowercase SHA-256 digest,
  and carry a detached Ed25519 signature with a key id. A future updater must
  verify the digest and signature before extracting or activating anything.
- Archive, entrypoint, inventory, activation and notice paths are safe relative
  paths. Parent traversal, rooted paths, drive-qualified paths and traversal
  are rejected.
- The shell is installed under
  %ProgramFiles%\AI Video Editor\Shell. programFilesRuntimeWritable is always
  false; the engine and components never write there at runtime.
- Downloaded immutable component versions and activation/update metadata live
  under %ProgramData%\AI Video Editor. The future update service owns writes
  to staging and activation metadata; the running engine treats activated
  component directories as read-only.
- Per-user config, cache, logs and resumable state live under
  %LocalAppData%\AI Video Editor. Projects and exports default to the user’s
  Documents folder and may be explicitly user-selected.
- Every engine control message carries a per-session bearer token. The engine
  binds only to 127.0.0.1 and requests port 0 for dynamic allocation. A
  fixed or non-loopback endpoint is not a valid Phase 1 startup contract.
- Health probes declare requiresBearerToken: true. Logs are user-owned and
  must be redacted; credentials, model files, uploads and private project data
  are outside these contracts.
- Activation is stage-then-atomic-rename. The active pointer is changed only
  after verification and the previous active version remains available for
  rollback. An interrupted download keeps only resumable journal metadata and
  a staging .part path; it is never treated as active.

## Canonical Windows storage layout

The TypeScript canonicalWindowsStorageLayout() function, Rust
canonical_windows_storage_layout() function and valid-storage-layout.json
fixture must remain equivalent.

| Path | Scope/owner | Runtime write policy |
| --- | --- | --- |
| %ProgramFiles%\AI Video Editor\Shell | Machine / installer | Never runtime-writable |
| %ProgramData%\AI Video Editor\Components | Machine / update service | Immutable activated component versions |
| %ProgramData%\AI Video Editor\Activation | Machine / update service | Update service journal and active-version metadata only |
| %ProgramData%\AI Video Editor\Downloads\Staging | Machine / update service | Interrupted/resumable download staging only |
| %LocalAppData%\AI Video Editor\Config | User / user runtime | Writable per-user config |
| %LocalAppData%\AI Video Editor\Cache | User / user runtime | Writable rebuildable cache |
| %LocalAppData%\AI Video Editor\Logs | User / user runtime | Writable redacted logs |
| %LocalAppData%\AI Video Editor\State | User / user runtime | Writable resumable operation state |
| %USERPROFILE%\Documents\AI Video Editor\Projects | User-selected / user runtime | Default or explicitly selected project location |
| %USERPROFILE%\Documents\AI Video Editor\Exports | User-selected / user runtime | Default or explicitly selected export location |

The engine control payload carries resolved paths plus the storage layout
version. It may report the immutable shell root, but component executables,
logs, staging and runtime state must not be redirected under Program Files.

## Health, readiness and remediation

process.alive answers whether the identified process exists. It is separate
from the required service checks:

- checks.api.state: healthy means the authenticated HTTP API responds.
- checks.database.state: ready means the database connection and required
  migrations are usable.
- checks.vectorStore.state: ready means vector retrieval is usable; it may be
  not-configured or not-ready without making the whole engine fatal when it is
  optional.
- checks.ffmpeg.state: ready means the required media tool self-test passed.
- checks.aiModel is optional and describes requested local/model readiness.

overallState is starting, ready, degraded or fatal. Degraded mode is valid
when optional capabilities are unavailable and remediation codes explain the
user/action path. Fatal mode requires a structured fatalError; it is not
represented by an HTTP status alone. Remediation codes are stable machine
values such as DATABASE_UNAVAILABLE, FFMPEG_MISSING, MODEL_NOT_INSTALLED,
SESSION_AUTH_FAILED, STORAGE_NOT_WRITABLE, MIGRATION_REQUIRED and
UPDATE_ROLLBACK_AVAILABLE.

## Update and rollback state

The intended journal sequence is:

    checking -> downloading -> interrupted/resume-available -> downloaded ->
    verifying -> staged -> activating -> active

On activation failure the journal retains previousVersion and previousPath,
records an error, and transitions through rolling-back -> rolled-back or
failed. atomicCommit: true and an active checkpoint are required before an
update can claim active. bytesDownloaded, resumeFromByte and
lastVerifiedByte make an interrupted download recoverable without trusting an
incomplete archive.

## Examples and migration

[valid-component-manifest.json](../../fixtures/desktop-v2/contracts/valid-component-manifest.json)
is the complete signed-manifest example. It demonstrates a Windows x86_64
backend with a SHA-256 digest, detached signature/key id, dependency
constraint, immutable ProgramData install layout, authenticated readiness
probe, inventory and automatic rollback policy.

[valid-engine-control-start.json](../../fixtures/desktop-v2/contracts/valid-engine-control-start.json)
demonstrates a start request with dynamic port allocation (requestedPort: 0)
and a session token. The assigned port appears only on a later ready message.
[valid-health-degraded.json](../../fixtures/desktop-v2/contracts/valid-health-degraded.json)
shows API/database/FFmpeg available while vector retrieval and an optional model
are degraded or unavailable.
[valid-update-interrupted.json](../../fixtures/desktop-v2/contracts/valid-update-interrupted.json)
shows a resumable .part download with the previous version retained.

The invalid fixtures intentionally cover missing manifest signatures, missing
session authentication, fatal readiness without a fatal error, writable
Program Files policy, and non-atomic activation. New contract changes must add
at least one valid and one invalid fixture for each changed invariant. A data
migration belongs to a later phase and must be versioned separately from these
wire contracts; Phase 1 does not migrate existing projects or databases.

## Exact checks

Run from the managed worktree:

    npm run contracts:check --prefix desktop
    npm install --prefix desktop       # only when desktop\node_modules is absent
    npm run build --prefix desktop
    rustfmt --edition 2021 --check desktop\src-tauri\src\contracts.rs
    cargo test --manifest-path desktop\src-tauri\Cargo.toml --lib contracts::tests
    cargo check --manifest-path desktop\src-tauri\Cargo.toml
    powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\desktop-v2\Verify-DesktopV2Baseline.ps1
    git diff --check

npm run contracts:check uses a dependency-free local draft-2020-12 subset
checker for the checked-in schemas and executes the TypeScript validators
against all deterministic fixtures. Rust tests deserialize and serialize the
same fixtures. No network, component archive, model, upload, database or
secret is needed by the contract tests.

## Verification record

The Phase 1 run from the managed worktree produced these results:

| Check | Result | Classification |
| --- | --- | --- |
| npm run contracts:check --prefix desktop | PASS | Six schemas and eleven fixtures passed the local schema subset and TypeScript validators |
| Python Draft 2020-12 fixture cross-check | PASS | The available local jsonschema package accepted every valid fixture and rejected every invalid fixture; no network was used |
| rustfmt --edition 2021 --check desktop\\src-tauri\\src\\contracts.rs | PASS | Phase 1 Rust contract module is formatted |
| cargo test --manifest-path desktop\\src-tauri\\Cargo.toml --lib contracts::tests | PASS | Four focused Rust contract tests passed |
| cargo check --manifest-path desktop\\src-tauri\\Cargo.toml | PASS | Tauri crate and contract module compile |
| npm run build --prefix desktop | PASS | Contract check, TypeScript compilation and Vite production build completed |
| Verify-DesktopV2Baseline.ps1 | PASS | Protected-path, secret, large-artifact, runtime-path and whitespace scans passed |
| cargo fmt --manifest-path desktop\\src-tauri\\Cargo.toml -- --check | BLOCKED BY BASELINE STYLE | Existing desktop\\src-tauri\\src\\lib.rs contains pre-existing rustfmt differences outside the Phase 1 contract module; it was not reformatted to avoid unrelated source changes. The Phase 1 module-specific rustfmt check passes. |

The dependency install was required because desktop\\node_modules was absent in
the supplied worktree. npm install exited 0 but reported the baseline package
audit/install-script warnings (19 audit findings and four pending scripts); no
audit fix or script approval was run, and node_modules/dist/target remain
ignored build outputs. No source, network artifact, secret, model, upload,
database or cache was staged.

## Phase 1 gate

Phase 1 is gated PASS only when:

1. All six versioned schemas, TypeScript validators and Rust Serde
   representations are present and agree on required fields and enum values.
2. Valid fixtures pass JSON Schema/TypeScript/Rust checks and invalid fixtures
   fail with no network dependency.
3. Session authentication, loopback-only dynamic allocation, immutable
   Program Files policy, signed/digested artifacts, atomic activation and
   rollback metadata are explicit and machine-checkable.
4. The existing localhost browser/Docker workflow and React/Tauri application
   behavior remain additive and unchanged.
5. Frontend build, Rust check/test, formatter/static checks and the read-only
   Phase 0 safety verifier are run and their environment blockers are recorded
   exactly.
6. The final commit contains only Phase 1 source, schemas, docs, tests and
   deterministic fixtures; no dependency directory, target output, build
   output, download, secret, model, upload, database or cache is staged.

Phase 2 is not started by this contract package.
