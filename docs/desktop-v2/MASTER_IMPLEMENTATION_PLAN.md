# Desktop V2 — Master Implementation Plan

## Target outcome

Desktop V2 is a Windows-first desktop distribution with a thin Tauri shell and signed, downloadable, versioned runtime components. The shell owns the native window, user-visible readiness, secure IPC, per-user storage locations, component lifecycle, update/rollback state and diagnostics. Components own backend/service execution and are never trusted merely because they were downloaded.

The existing Docker localhost implementation remains the development reference throughout the work. Desktop V2 is additive and isolated: browser development continues to use docker-compose.yml on port 8000, while the standalone profile uses a separate loopback endpoint and per-user data root. No phase may make development depend on the standalone distribution.

## Invariants

- Components are addressed by a manifest containing name, version, platform, architecture, shell compatibility, API compatibility, URL, size, SHA-256 digest, signature, signing-key identity and release channel.
- Bytes are downloaded to a staging directory, verified before use, and activated atomically. A failed download or health check cannot replace the last known-good component.
- The shell never accepts an unsigned, hash-mismatched, incompatible or partially extracted component.
- Secrets, uploaded media, database volumes and user-owned model files are never embedded in a component package or logged in diagnostics.
- Runtime data is outside the install directory and is partitioned from component caches, temporary files, logs, backups and exports.
- The backend health contract reports component version, API compatibility, storage readiness and a redacted diagnostics identity.
- Updates are resumable where practical, cancellable, rollback-capable and observable in the UI.
- The current Docker development path, API routes and renderer remain available until a replacement has equivalent evidence.

## Phase map and acceptance gates

| Phase | Objective and bounded implementation | Depends on | Acceptance gate |
|---|---|---|---|
| 0. Protected baseline | Record source identity, architecture, standalone failure mechanism, safety rules and reproducible checks. Add only documentation and a read-only verifier. | None | Clean baseline recorded; Phase 0 commit exists; no protected-folder or private-data change; checks are passed or precisely classified. |
| 1. Runtime contract and threat model | Define the shell/component protocol, manifest schema, compatibility rules, local ports, storage layout, process states, failure taxonomy, signature policy, key rotation model and dev-versus-standalone boundary. | 0 | Versioned contract fixtures validate; threat model covers tampering, rollback, path traversal, downgrade, log leakage and partial activation; owner approves the component format and trust root. |
| 2. Component distribution and verification library | Implement a small Rust library/service surface for manifest parsing, HTTPS download, size/digest verification, signature verification, safe archive extraction, staging, atomic activation and rollback metadata. No backend behavior changes yet. | 1 | Unit tests reject bad signatures, wrong digests, path traversal, incompatible versions, truncation and downgrade; interrupted activation leaves the previous version runnable; test keys are isolated from release keys. |
| 3. Portable backend component | Package the FastAPI backend and its required runtime dependencies as a signed, platform-targeted component. Define how FFmpeg/FFprobe and optional render helpers are located without install-directory assumptions. Add a versioned health/capabilities contract and structured redacted logs. | 1, 2 | On a clean Windows test machine with no repository checkout, the component starts under the shell, reaches health on a reserved loopback port, serves a smoke API, and stops cleanly; no provider key or user data is in the package. |
| 4. Local services and data plane | Provide signed/downloadable or approved embedded equivalents for required local services, or explicitly narrow standalone prerequisites. Add per-user data roots, free-space checks, schema/version discovery, backup/restore and forward migration. Keep the development PostgreSQL/Qdrant/Redis stack unchanged. | 1, 2, 3 | Fresh profile creates only approved directories; restart preserves a synthetic project; migration and rollback tests cover representative data; no bind mount points at protected/source folders; missing optional services produce actionable readiness states. |
| 5. Thin-shell integration | Replace the current packaged Docker bootstrap path behind a runtime adapter, without rewriting the React workflow. Add component discovery, install/update/retry/rollback UI, endpoint handoff, readiness events, native file import routing and a visible runtime profile. Keep browser mode and existing Tauri IPC behavior compatible. | 2, 3, 4 | Browser dev still talks to port 8000; standalone talks only to its managed loopback component; shell never launches an unverified binary; start/stop/retry/rollback and native import smoke tests pass on clean profiles. |
| 6. Packaging, signing and update channel | Build the Tauri installer as a thin shell. Publish signed manifests and component artifacts through a controlled channel with release, staging and rollback metadata. Implement cache cleanup, resumable downloads, update prompts, offline behavior and signature/key rotation. | 2, 3, 4, 5 | Reproducible release artifacts have recorded hashes; installer size excludes backend source, uploads, models and secrets; clean install, upgrade, interrupted update and rollback all succeed; a revoked/bad artifact is rejected. |
| 7. Security, privacy and provider/model UX | Add secret storage/configuration boundaries, redacted diagnostics, provider readiness, explicit model download locations, model integrity checks, retention controls and user-facing consent for network/provider use. Review filesystem permissions, IPC allowlists and URL/CSP behavior. | 4, 5, 6 | Static secret scan and manual review pass; test credentials never appear in package/log/export; model downloads are verified and cancellable; provider/model failures do not corrupt projects or expose paths. |
| 8. Full verification and performance | Add clean-machine install/start/stop, frontend smoke, API smoke, synthetic upload/project/review/export flow, update/rollback, offline and failure-injection tests. Measure cold start, warm start, component download, disk use, large upload and representative render behavior. | 3, 4, 5, 6, 7 | A repeatable matrix passes on supported Windows environments; failures are classified with logs and reproduction steps; thresholds are agreed for startup, disk, download and render resource use; Docker localhost regression remains green. |
| 9. Release hardening and handoff | Freeze versioned contracts, publish operator/developer docs, support matrix, recovery guide, checksum/signature evidence, uninstall/data-retention behavior and a known-limitations register. Tag the release only after owner acceptance. | 8 | Release candidate installs and upgrades from a clean machine; artifacts and signatures are independently verifiable; rollback and data recovery are demonstrated; Phase 9 gate and final release commit are recorded. |

## Dependency and promotion rules

    Phase 0
       ↓
    Phase 1 ───────────────┐
       ↓                    │
    Phase 2 ────────┬───────┘
                    ├─ Phase 3 ──┐
                    └─ Phase 4 ──┼─ Phase 5 ── Phase 6 ── Phase 7 ── Phase 8 ── Phase 9
                                  └───────────────┘

- A phase may add tests, fixtures and documentation for a later phase, but it may not silently implement later runtime behavior.
- Every phase keeps a small, reviewable commit or commit series and records exact verification commands.
- A phase gate is a stop condition. A build passing is not sufficient where a clean-machine, signature, migration, security or runtime-health test is required.
- Any change that touches the Docker development path must include a separate regression result and owner approval; Desktop V2 work should normally avoid that path.
- Release artifacts are generated outside the source tree or under ignored output directories and are never committed unless a phase explicitly calls for a small, non-runtime test fixture.

## Component contract sketch

The exact artifact format is a Phase 1 decision, but every implementation must expose these concepts:

    manifest
      component_id
      component_version
      platform / architecture
      shell_min_version / api_compatibility
      artifact_url / size_bytes / sha256
      signature / signing_key_id / channel

    shell lifecycle
      discover → download → verify → stage → health-check → activate
      previous-good ← rollback on failure or explicit user recovery

    runtime health
      process state, endpoint, component version, API compatibility,
      storage readiness, dependency readiness, redacted diagnostic id

The shell must not infer trust from filenames, HTTP status codes, archive contents or a successful process spawn. The backend must not infer trust from a caller-supplied path outside the approved data root. All path and version checks are explicit and testable.

## Exit criteria for the overall program

Desktop V2 is ready for release only when:

1. A clean machine can install, start, use, update and roll back the application without a repository checkout or Docker Desktop requirement, subject to the explicitly documented support matrix.
2. The normal synthetic project flow works from import through review and export, and the existing browser/Docker development path still works.
3. Components are signed, hash-checked, compatibility-checked and recoverable after interruption.
4. User data, credentials, model files and generated media remain in documented per-user locations and are absent from release artifacts and logs.
5. The release evidence includes exact commits, artifact hashes, test matrix, limitations and recovery instructions.
