# Desktop V2 — Phase 8 Product Improvements

Status: compact implementation on `codex/desktop-v2-phase-8`. This phase
improves the existing AI Video Editor workflow while preserving the Docker /
browser API, the native desktop engine, and all Phase 0–7 installer,
component, supervisor, and migration behavior. It does not include Phase 9
release signing, distribution, or handoff.

## Before and after

| Area | Before | After |
| --- | --- | --- |
| Workflow language | Project and video screens exposed different legacy status values. | A shared product state vocabulary maps legacy values to source, analysis, review, editing, export, completed, failed, and cancelled states. |
| Readiness | Users discovered missing files, media tools, storage, or provider setup only after starting work. | `/api/v1/product-readiness`, `/projects/{id}/readiness`, and `/videos/{id}/readiness` report source validity, metadata, capabilities, storage, blockers, warnings, and next actions. |
| Jobs | Native SQLite and Docker render jobs had different response shapes. | The compatibility adapter exposes stable job id/type/state/progress/stage/message/timestamps/cancellable/retryable/error/remediation fields while keeping legacy fields and routes. |
| Dashboard | Projects were searchable but did not explain the next action or backend readiness. | The dashboard has a local system-readiness summary, state/progress cards, status filter, sort, last activity, retry action, safe active-job deletion rejection, and friendly offline errors. |
| Ingest | Browser ingest depended mostly on backend validation and did not clearly show duplicate or format feedback. | Picker/drop validation reports supported formats, empty/size errors, unusual MIME warnings, duplicate name+size, ordered sources, and project preflight. Native path imports retain backend canonical-path security. |
| Transcript review | Timed transcript segments were clickable, but there was no transcript search and segment containers were mouse-oriented. | Transcript search, match counts, keyboard-selectable segments, active-segment cues, and existing non-destructive cut restore/delete/undo paths are available. |
| Export | Export controls existed but were not gated by a common project preflight. | Export rechecks readiness immediately before approval, presents blockers/warnings and remediation, prevents duplicate approval while busy, and preserves existing preset/progress/cancel/retry/download behavior. |
| Provider readiness | Settings showed configured key state but there was no explicit authenticated health-test call. | The authenticated `POST /settings/ai/test-provider` boundary reports configured vs usable status without returning keys; manual editing remains available when AI providers are unavailable. |

## Shared workflow/status model

The canonical values live in `backend/app/services/product_workflow.py` and
are mirrored for display in `desktop/src/lib/workflow.ts`:

`source_required -> validating -> ready_for_analysis -> analyzing ->
review_suggestions -> editing -> export_ready -> exporting -> completed`

`failed` and `cancelled` are recoverable terminal states. Legacy persisted
`VideoStatus` and `ProjectStatus` values remain unchanged; the mapping is
response/UI compatibility only. Invalid transitions are rejected by the
shared transition guard used by deterministic tests. The current pipeline
continues to use its existing background-task implementation and maps its
status into a stable `analysis:{video_id}` job until a future phase can change
the underlying worker without a data migration.

## Readiness contract

Readiness responses use `phase8.product-readiness.v1` or
`phase8.project-readiness.v1` and include:

- `ready`, `required_actions`, `blockers`, and `warnings` with code, message,
  remediation, and severity;
- source path/format/size validity and supported extensions;
- duration, resolution, FPS, and available metadata when already recorded;
- configured versus usable API, local-runtime, model, and FFmpeg capabilities;
- storage root, writability, free/total bytes, and required free-space margin;
- mode (`docker` or `native`) and the mapped workflow state.

The readiness check is deterministic and does not make a provider network call
or expose secrets. Explicit provider testing remains user initiated.

## Job compatibility contract

`backend/app/services/job_adapter.py` normalizes native SQLite jobs and Docker
render jobs into:

`job_id`, `type`, `state`, `status`, `video_id`, `progress_percent`, `stage`,
`message`, `created_at`, `updated_at`, `started_at`, `completed_at`,
`cancellable`, `retryable`, `error_code`, `error`, and `remediation`.

Existing `/videos/{id}/status`, render routes, and native `/jobs` routes remain
available. Structured error normalization turns common provider, source,
storage, cancellation, and backend-availability failures into human-readable
recovery guidance. The frontend converts offline `Failed to fetch` variants to
local-backend guidance and never renders raw transport error copy.

## Implemented feature set

- Compact shared workflow mapping and stable job/readiness payloads for both
  browser and native bridge calls.
- Project/video readiness endpoints and export preflight gating.
- Dashboard readiness, progress polling for active videos, search/filter/sort,
  retry, and active-job deletion protection.
- Browser file validation and duplicate feedback; native path import remains
  constrained by the existing server/Tauri security boundary.
- Transcript search and keyboard activation while preserving timed word cuts,
  restore, autosave-through-existing-API, and undo/redo behavior.
- Provider-test API with configured/usable distinction and no secret values.
- Deterministic backend and frontend tests plus a mocked ingest-to-export state
  walk.

## Deliberately left out

This compact phase does not replace the editor layout, add a new AI model,
invent silence/scene data that is not present, or add a fake cloud processing
queue. Analysis cancellation remains limited by the existing background worker
contract; export cancellation uses the existing cooperative render job. The
browser keeps download-link behavior. Native open-folder/copy-path affordances
are not fabricated without an existing safe Tauri command, so completion uses
the existing authenticated download/export links. A full visual redesign,
provider network probing on page load, multi-user collaboration, and release
packaging belong outside this phase.

## Verification record

| Gate | Command/check | Result |
| --- | --- | --- |
| Focused backend product tests | `python -m unittest discover -s backend/tests -p test_phase8_product_workflow.py` | PASS — 4 tests |
| Existing backend regressions | Provider 26, project 14, render jobs 4, native imports 6, transcript 11, progress 2, export presets 3, edit-plan 11, export artifacts 3 | PASS — 80 tests |
| Frontend deterministic tests | `npm test` / `npm run test:desktop-v2` | PASS — contracts plus Phase 2, 5, 6, 7, and 8 suites |
| TypeScript/Vite build | `npm run build` | PASS — `tsc` and Vite production build; only existing chunk-size/dynamic-import warnings |
| Native Rust/backend checks | `cargo check --manifest-path desktop/src-tauri/Cargo.toml`; `cargo test --manifest-path desktop/src-tauri/Cargo.toml`; native app, compositor, PiP, fake-engine smoke | PASS — cargo check, 41 Rust tests, native app 7, compositor 2, PiP 38, fake engine 3 |
| Browser/Docker config | `docker compose config --quiet` and desktop compose with `.env.example` | BLOCKED HONESTLY — isolated root intentionally has no `.env` or host volume paths; no private env was supplied and no environment file was created |
| Safety/artifact audit | baseline verifier, `git diff --check`, staged-name audit | PASS — protected-root, secret, large-artifact, runtime/private-path, and whitespace scans are clean |
| Mocked E2E | ingest → analyze → review → edit → export state walk | Included in Phase 8 frontend test |

## Gate

The final gate is **PASS**: the verification record contains actual results,
the isolated worktree contains only Phase 8 source/docs/tests, and the commit
contains no media, exports, models, databases, keys, env files, runtimes,
installers, `node_modules`, `dist`, `target`, logs, or caches. Docker runtime
validation remains an environment limitation rather than a product failure;
the existing localhost configuration was not mutated to manufacture private
paths or credentials.
