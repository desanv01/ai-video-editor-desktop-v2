# Desktop V2 — Phase 5 native engine supervisor

Status: implementation complete on `codex/desktop-v2-phase-5`. Phase 5 adds
the Tauri-native supervisor, an authenticated WebView bridge, readiness-gated
editor access, owned process lifecycle, bounded recovery, diagnostics, and
deterministic fixtures. It does not implement the polished Phase 6 Setup
Center, migration/uninstall work, or Phase 8 product improvements.

## Supervisor state machine

`desktop/src-tauri/src/supervisor.rs` owns one serialized runtime state. The
state is emitted as the `desktop-engine-status` Tauri event and is also
available through `supervisor_status` and `supervisor_diagnostics`.

| State | Meaning | Automatic recovery |
| --- | --- | --- |
| `stopped` | No engine process is owned. | Start/retry is manual or requested by the native shell. |
| `resolving` | ProgramData activation records are being checked. | Missing, corrupt, incompatible, and elevation-required records become structured `repair-required`; Docker/PATH fallback is never attempted. |
| `starting` | A verified core-engine executable is being launched. | Launch failures use bounded retry only when classified retryable. |
| `waiting-for-handshake` | The stdout reader is waiting for the one bounded startup JSON line. | Invalid handshakes are repair failures; no endpoint is guessed. |
| `probing` | Authenticated readiness and capability requests are in flight. | Retryable exits/timeouts use exponential backoff. |
| `ready` | The loopback port, owned PID, protocol, bearer session, readiness schema, and required checks are valid. | An unexpected exit enters crash recovery. |
| `degraded` | Authenticated readiness succeeded with optional capability degradation. | It is surfaced to the shell and remains locked from editor views until the strict `ready` gate. |
| `stopping` | Graceful shutdown or app-close cleanup is in progress. | A ten-second authenticated shutdown grace period is followed by owned-tree termination. |
| `crashed-backoff` | The owned engine exited unexpectedly and recovery is waiting. | Delays are 250 ms, 1 s, and 3 s, with a three-attempt budget. |
| `repair-required` | Local activation, component, protocol, auth, or configuration repair is required. | No automatic restart loop; the user can inspect diagnostics or manually retry. |
| `fatal` | Bounded recovery was exhausted or an unrecoverable supervisor error occurred. | Automatic recovery is paused; rollback is requested when a last-known-good version is available. |

`start` is idempotent while a start is in progress or the engine is ready or
degraded. `stop`, `restart`, and `retry` are serialized by the same mutex and
the restart path rotates the in-memory session after the old process has
stopped.

## Verified component launch

The supervisor calls `ComponentManager::verified_active_component` for exactly
`aive-engine` (`Backend`) and `ffmpeg` (`Ffmpeg`) using the production source
policy. The manager verifies:

- active metadata identity, active state, selected version, and immutable
  version path under ProgramData;
- the signed manifest, component type, elevation requirement, entrypoint and
  working-directory boundaries;
- the exact installed file inventory and entrypoint file; and
- the absence of unsafe activation metadata.

The launch plan is assembled only from this verified result. It never searches
PATH, accepts a WebView path, starts Docker, or silently uses a global FFmpeg.
Supervisor-owned arguments (`--port`, data/session/tool roots and test flags)
are removed from the signed argument list so the supervisor remains the source
of truth. A signed `--bearer-token` argument is rejected because the token is
never put on the command line.

The engine receives per-user data/log roots and the activated FFmpeg root.
Program Files remains read-only; activated component directories are treated
as immutable launch inputs.

## Handshake, authentication, and bridge

The native source entrypoint (`backend/native_engine.py`) and the deterministic
fake fixture bind `127.0.0.1` with requested port `0`. Before launch, the
supervisor binds a separate ephemeral loopback control listener and generates a
session nonce. After Uvicorn has actually bound its API socket, the engine sends
one bounded, HMAC-authenticated JSON message to that listener:

```json
{"assignedPort":43123,"componentId":"aive-engine","componentVersion":"2.0.0-rc.6","hmacSha256":"<64 lowercase hex characters>","host":"127.0.0.1","nonce":"<session nonce>","pid":1234,"protocolVersion":"desktop.engine-handshake.v2","sessionId":"<session id>","type":"aive-engine-startup"}
```

The supervisor accepts only a loopback peer and verifies the exact handshake
type/protocol, session, nonce, component identity/version, assigned port, owned
PID, and SHA-256 HMAC before probing readiness. The message is capped at 16 KiB.
Stdout and stderr are diagnostics only; they are drained and redacted, and
closing either pipe cannot determine readiness or fail an otherwise valid
control handshake.

Each launch generates 32 cryptographically random bytes with the operating
system secure random source and passes the base64url token through the child
environment. The token is held only in supervisor memory, is replaced on every
restart, and is never written to recovery metadata, status, diagnostics,
query strings, browser storage, or logs. The native API authenticates every
route except the existing `/live` liveness route. Readiness and capabilities
are always probed with the in-memory bearer token.

The WebView invokes `engine_api_request` with a relative path and request body
only. Rust inserts the bearer token, restricts methods and endpoint prefixes,
rejects absolute URLs/path traversal/credential queries, caps request and
response bodies, and returns a bounded response. Requests fail with
`ENGINE_NOT_READY` until the supervisor is in strict `ready` state. Browser/Vite
mode keeps its existing `http://localhost:8000/api/v1` path and does not use
the bridge.

Native imports and media/download helpers use the same bridge. Native resource
URLs are an internal `bridge:` marker handled by React; the WebView never
receives the dynamically assigned localhost port.

## Process ownership and lifecycle

On Windows, the child is assigned to a dedicated Job Object configured with
`JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`. Graceful stop first sends the
authenticated `/engine-control/shutdown` request, waits ten seconds, and then
terminates the owned job if needed. App/window destruction uses only the owned
process handle/job; no executable-name process kill is used. A cross-platform
direct-child handle fallback is retained for test platforms.

The supervisor owns stdout/stderr pipe readers, the child handle, the dynamic
port, and the session together. Sleep/resume, logout, and OS shutdown rely on
the app lifecycle plus the Windows job close guarantee; explicit window close
also performs immediate owned-tree cleanup. Stale or malformed recovery
metadata older than 24 hours is removed and is never treated as a live process.

## Diagnostics and remediation

Per-user logs are rotating, bounded to 1 MiB per file with three rotations.
Lines are tagged with stdout/stderr, capped, and redacted for the current
bearer token and common credential markers. Diagnostics expose only schema-
versioned status, owned-process presence, redacted recovery/log paths, a
bounded log tail, retry/rollback state, and safe remediation codes.

Typical remediation mapping is:

| Failure | Supervisor result | User action |
| --- | --- | --- |
| Missing activation | `repair-required` / `COMPONENT_NOT_ACTIVE` | Install or activate the signed component in the future Setup Center. |
| Bad/corrupt activation, inventory, entrypoint, or protocol | `repair-required` | Repair/retry the verified component; inspect diagnostics. |
| Elevation-required component | `repair-required` / `STORAGE_NOT_WRITABLE` | Run the authorized machine-level repair path. |
| Wrong bearer or readiness auth rejection | `repair-required` / `SESSION_AUTH_FAILED` | Restart/retry; no token is displayed. |
| Startup timeout or owned crash | `crashed-backoff` | Automatic bounded retry, then manual retry or rollback. |
| Retry budget exhausted | `fatal` / `ENGINE_CRASH_BUDGET_EXHAUSTED` | Manual restart or last-known-good component rollback. |
| User stop/restart/app close | `stopping` → `stopped` | No automatic restart after an intentional stop. |

The shell shows these states and actions directly. It does not show raw
`Failed to fetch` errors and does not mount editor/settings views until the
authenticated `ready` event arrives.

## Deterministic tests and verification

The test-only fixture at
`fixtures/desktop-v2/fake-engine/fake_engine.py` covers `ready`, `degraded`,
`wrong-protocol`, `wrong-host`, `malformed`, `oversized`, `timeout`, and
`crash`. It is not a component archive and is not referenced by installer
resources.

The final verification record for this worktree is:

| Check | Result |
| --- | --- |
| Phase 1 contract and frontend checks | PASS — 6 schemas and 11 fixtures |
| Phase 2 desktop tests | PASS — boot, routing, missing-component, path, and diagnostics invariants |
| Phase 3 component manager tests | PASS — included in 28 Rust library tests |
| Phase 4 native tests | PASS — 7 `test_desktop_native` tests |
| Phase 5 Rust supervisor tests | PASS — 11 supervisor tests covering handshake bounds/host/protocol, token rotation, bridge gating, argument safety, redaction, stale metadata, state machine, lifecycle guard, structured repair, and bounded budget |
| Phase 5 fake-engine tests | PASS — 3 tests covering dynamic port/auth/stop, handshake failure modes, timeout, and crash |
| Frontend test suite | PASS — contract, Phase 2, and Phase 5 tests |
| Frontend production build | PASS — 1,601 modules transformed |
| Native source integration smoke | PASS — authenticated native engine smoke and graceful shutdown, including handshake assertions |
| `cargo check` | PASS |
| Safety verifier | Recorded after final source staging; no protected profile/install used |
| Thin-installer inspection | `tauri.bundle.override.json` has `resources: []`; no runtime archive, FFmpeg binary, model, upload, database, secret, `dist`, `target`, or `node_modules` is commit content |

The first combined `npm test; npm run build` invocation encountered a Windows
`esbuild` child-process `EPERM` on its second spawn; the standalone build
rerun passed with the same 1,601-module output. This was not a source or
TypeScript failure.

No protected original/viva/standalone Desktop folder was modified. No Phase 6
work was started. The Phase 5 gate is **PASS** when the final safety scan and
clean source-only commit checks below remain green.
