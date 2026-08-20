# Desktop V2 — Phase 7 Migration, Repair, Cleanup, and Uninstall

Status: implementation complete on `codex/desktop-v2-phase-7` after the
redirected-root Rust engine, synthetic flows, wizard, NSIS hooks, and focused
verification are complete. This phase does not redesign the editor (Phase 8)
or sign/distribute a release (Phase 9).

## Purpose and user promise

Phase 7 addresses the old Desktop/Tauri installation problem: an old
`%LocalAppData%` runtime can be several gigabytes, a split installation can
leave files in both Program Files and AppData, and a stale shortcut or
installer identity can make a partial install look successful. The V2 shell
therefore performs a bounded, read-only discovery first and shows Migration &
Cleanup when legacy state is present.

Detection never deletes. The wizard distinguishes application runtime,
rebuildable diagnostics state, settings, and valuable user content. The
recommended choice is backup/export, transactional migration of supported
data, and keeping the old copy until the user explicitly approves disposable
cleanup.

## Versioned contracts and report format

The Rust module `desktop/src-tauri/src/migration.rs` owns these stable
machine-readable versions:

| Contract | Purpose |
| --- | --- |
| `desktop.migration-inventory.v1` | Read-only legacy identity, path, size, safety, database, secret-key, shortcut, registry, PID/port, conflict, and recommendation inventory. |
| `desktop.migration-report.v1` | Preflight result, deterministic plan, target roots, conflict strategy, journal handoff, completion checkpoints, and redacted warnings. |
| `desktop.migration-journal.v1` | Atomic copy/validate/switch phase, entries, staged paths, created destinations, digests, status, and recoverable error. |
| `desktop.cleanup-report.v1` | Approved cleanup results, preserved paths, locked leftovers, unsafe paths, and reboot requirement. |
| `desktop.repair-report.v1` | Installer identity, component-store, activation, shortcut, cache-reset, and self-test actions. |
| `desktop.uninstall-plan.v1` / `desktop.uninstall-report.v1` | Default-preserve versus full-wipe choices, owned-process candidates, exact allowlisted paths, and locked-leftover reporting. |

The JSON Schema files are under
`contracts/desktop-v2/schemas/`. Reports contain paths and safe metadata but
never provider secret values. Secret key names may be reported so the user can
understand what needs protected-store migration or re-entry.

## Path classification

The scanner accepts `MigrationRoots`, so tests pass synthetic LocalAppData,
Program Files, ProgramData, Documents, Desktop, Start Menu, and redirected
registry roots. Without redirected roots, the Tauri command resolves only the
known Windows roots; it does not walk drives or perform an arbitrary disk
search.

Known old product roots are:

- `%LocalAppData%\AI Video Editor` — `runtime`, `runtime.zip`, partial ZIPs,
  `venv`, `backend`, `database`, `postgresql`, `qdrant`, `uploads`, `projects`,
  `exports`, `models`, `config`, root settings files, `logs`, `cache`, `temp`,
  staging, activation records, `backend.pid`, `backend.port`, and old installer
  markers.
- `%ProgramFiles%\AI Video Editor` and `%ProgramFiles(x86)%\AI Video Editor` —
  old executable/resource/runtime bundles and identity/uninstaller records.
- `%ProgramData%\AI Video Editor` — legacy machine payload/activation/staging
  evidence. The current V2 `Shell`, `Components`, and activation perimeter is
  never adopted as legacy merely because it exists.
- `%USERPROFILE%\Documents\AI Video Editor` — inspected only as this explicit
  content root when a bounded old identity was found; Projects, Exports, and
  Models are valuable and preserved by default.
- Known Desktop/Start Menu shortcut names and a redirected registry fixture
  root. The NSIS upgrade path retires the old product uninstall key only after
  V2 succeeds; synthetic scanner/cleanup tests use JSON registry records and
  never touch the real Windows registry.

Each item records size, file count, reparse/locked state, identity/version,
database kind, SQLite compatibility, export/import requirement, secret-key
presence, conflict status, and a recommended action.

| Classification | Default treatment |
| --- | --- |
| Runtime, runtime ZIP/partial ZIP, old Program Files payload, cache, temp, logs, stale PID/port, obsolete shortcut/installer record | Remove only after explicit cleanup approval and safe-boundary validation. |
| Settings/config | Migrate supported non-secret settings. Provider secrets go to Windows Credential Manager or a DPAPI-protected backup; otherwise the wizard requires re-entry. |
| Projects, uploads/media, exports | Migrate with staging, digest validation, conflict naming, and rollback. Preserve if the user chooses keep-old-copy. |
| SQLite | Migrate only when the `SQLite format 3` header is compatible. |
| PostgreSQL/Qdrant | Never copy raw files into V2. Report export/import-required with honest remediation. |
| Models and unknown databases | Keep old copy by default; no silent deletion or compatibility claim. |

## Migration and rollback

1. `scan_legacy_roots` builds the inventory without mutation.
2. `preview_migration` computes supported destinations, conflict names,
   backup bytes, available-space preflight, lock/reparse findings, and a
   redacted report.
3. `execute_migration` writes `State\migration-journal.json` atomically,
   optionally copies a sanitized backup, copies to a V2 `.migration` staging
   directory, validates a SHA-256 digest, and switches by rename. A journal
   checkpoint is written after every item.
4. A critical failure returns an error and rolls back destinations created by
   that journal. A changed destination, locked path, or reparse point refuses
   rollback rather than deleting an unexpected object.
5. `migration_recover` re-reads an incomplete journal after restart. An
   explicit rollback command can safely remove only journal-created paths.
   Re-running a committed migration skips identical destinations and uses a
   deterministic `.legacy-<migration-id>` conflict name for different content.

Supported secrets are recognized by key name only. Values are held in memory
long enough to write Credential Manager entries; when that is unavailable,
Windows DPAPI protects the backup envelope. The synthetic non-Windows harness
uses a sealed digest and proves that plaintext never appears in reports or
backups; it is not the Windows production secret store.

## Cleanup and exact old-folder treatment

Cleanup requires `approved=true`. It removes only inventory items classified as
disposable and safe: old runtime bundles, staging ZIPs, cache/temp/logs, stale
PID/port markers, old shortcuts, and old installer records. It may remove an
empty old product directory afterward, but it never recursively removes a
product root containing valuable content by default.

Projects, uploads, exports, models, SQLite/PostgreSQL/Qdrant data, settings,
and unknown content are preserved. Locked paths and anything that crosses a
symlink/junction/reparse point are reported, never forced, and can be retried
after the old process closes or after a safe reboot.

Full wipe is a separate operation. It requires the exact phrase
`REMOVE ALL AI VIDEO EDITOR USER DATA`, is limited to the resolved allowlisted
product/content roots, and is never implied by detection, migration, cleanup,
or uninstall.

## Repair

Repair verifies the V2 shell identity and exact Program Files shell path,
checks the ProgramData component perimeter without trusting a writable
AppData runtime fallback, re-reads activation journals, and can request the
existing signed component self-tests. It can recreate V2 Desktop/Start Menu
shortcuts and reset only Cache/Temp/Logs. Projects, Exports, uploads, models,
databases, and settings are listed as preserved data.

## Upgrade/install and uninstall choices

The NSIS hooks keep one V2 product identity and per-machine install mode. The
installer creates the ProgramData perimeter, applies the scoped ACL, writes a
non-secret identity marker, creates Start Menu/Desktop shortcuts, and aborts on
critical directory/ACL/shell/identity/shortcut failures. Obsolete uninstall
records are retired only after those steps succeed. Heavy components are not
bundled into initial setup; Setup Center handles signed component delivery.

The default uninstall removes the Program Files V2 shell, V2 shortcuts,
ProgramData Components/Activation/Catalog/Staging, and LocalAppData Cache/
Temp/Logs/State. It preserves LocalAppData Config/uploads/models/database and
Documents Projects/Exports. The Rust uninstall plan is the authoritative
choice/report surface for a separate full wipe. Only an exact V2 ownership
marker can make a supervisor/job a stop candidate; generic process termination
is not used. Locked leftovers produce a reboot/close recommendation.

## Lecturer guidance

For a safe demonstration, create a synthetic redirected root (the Rust tests
do this automatically) containing an old runtime, `backend.pid`/`backend.port`,
one media file, a SQLite header, a Qdrant directory, a provider-secret config,
an old shortcut, and an old uninstall JSON record. Show the read-only report,
point out that valuable paths are preserved, run the recommended migration,
inspect the journal/report, and then approve disposable cleanup. Do not point
the test roots at the real `%LOCALAPPDATA%`, Program Files, ProgramData,
registry, Docker volumes, models, uploads, or project directories.

## Results and gate

The Phase 7 gate is **PASS** when the final verification record confirms:

- Phase 1–6 tests and frontend build remain green;
- focused/full Rust tests and `cargo check` pass;
- all synthetic inventory, migration, rollback, recovery, conflict, disk,
  secret-redaction, unsupported-DB, shortcut, cleanup, repair, uninstall, and
  idempotence flows pass;
- browser/Docker mode remains isolated;
- NSIS identity, per-machine ACL, shortcut, abort/rollback, and uninstall
  script inspection pass;
- the safety verifier finds no real product paths, protected data, secrets,
  installers, runtimes, models, databases, uploads, `target`, `dist`, or
  `node_modules` in the commit.

### Verification record

| Gate | Command/check | Result |
| --- | --- | --- |
| Redirected-root synthetic flows | `cargo test migration::tests` and full `cargo test` | PASS — 7 focused / 41 full Rust tests, 0 failures |
| Rust compile | `cargo check --manifest-path desktop/src-tauri/Cargo.toml` | PASS |
| Phase 1–6 regression plus Phase 7 bridge/UI checks | `npm run test:desktop-v2` | PASS — Phase 2, 5, 6, and 7 suites |
| TypeScript/frontend build | `npx tsc --noEmit`; `npm run build` | PASS — contract checks and Vite production build |
| NSIS policy inspection | Stable identity, per-machine perimeter, shortcut target, abort-on-critical-failure, and preserve-by-default hook assertions | PASS |
| NSIS bundle build | `npx tauri build --bundles nsis` | PASS — x64 setup bundle produced; no installer was installed or executed |
| Safety/artifact audit | scoped Phase 7 `git diff --check`, staged-name audit, and tracked artifact inspection | PASS — no real machine data or generated artifacts staged; the legacy baseline verifier is line-ending-limited by unrelated pre-existing CRLF worktree changes |

No Phase 8 work is included in this gate.
