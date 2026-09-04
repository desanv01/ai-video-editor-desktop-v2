# RC.6 Lecturer Uninstall and Data-Retention Guide

AI Video Editor Desktop V2 separates the installed shell/components from valuable user data. A normal uninstall is intentionally data-preserving.

## Before uninstalling

1. Finish or cancel active imports and exports, then close the app.
2. Back up any project or export that cannot be recreated.
3. If validating retention, record hashes or filenames under `%USERPROFILE%\Documents\AI Video Editor` before uninstalling.
4. Review the app's uninstall plan or dry-run report when available. It must name bounded targets and redact secrets.

## Normal uninstall

Open **Windows Settings > Apps > Installed apps**, find **AI Video Editor Desktop V2**, and choose **Uninstall**. Approve elevation if requested and reboot if Windows reports locked files.

The uninstaller acquires the same setup mutex, switches to a safe temporary working directory, and verifies its embedded package generation against the exact identity JSON, canonical install path, committed marker, main EXE, live uninstaller, and ARP registration before deleting owned files. A stale, mismatched, or reparse-point installation refuses with code `2109`. Normal NSIS temporary self-copy execution remains supported. Before deletion, the verified shell is atomically moved to a unique sibling tombstone and journaled, so delayed deletion can never target a later reinstall at the canonical path. Redacted output is written to `%ProgramData%\AI Video Editor\Installer\uninstall-rc6.log`.

The default path removes the shell, owned shortcuts, and component-owned machine runtime state. It preserves per-user settings/uploads/models/databases, projects, exports, provider credentials, and redacted installer logs so that a later reinstall can resume work. Unknown files and reparse points are preserved rather than traversed.

Expected preserved locations include:

- `%LocalAppData%\AI Video Editor` for per-user settings/runtime records that are not explicitly disposable.
- `%USERPROFILE%\Documents\AI Video Editor` for projects, uploads, exports, and models.
- AI Video Editor provider entries in Windows Credential Manager.

## Full wipe

Full wipe is destructive and is separate from normal uninstall. Use it only when the data owner explicitly requests deletion, has a backup, has reviewed the exact allowlisted plan, and types this exact confirmation in the application:

```text
REMOVE ALL AI VIDEO EDITOR USER DATA
```

The uninstall confirmation page also has an unchecked **Remove ALL AI Video Editor user data...** box. For authorized unattended uninstall, the exact installer token is `/FULLWIPE=REMOVE_ALL_AI_VIDEO_EDITOR_USER_DATA`. The application-side reviewed-plan confirmation phrase remains `REMOVE ALL AI VIDEO EDITOR USER DATA`.

The wipe may remove only known AI Video Editor user-data roots and the fixed provider/credential-name allowlist. It must never enumerate or clear unrelated credentials, arbitrary folders, repository checkouts, or Docker data. Do not reproduce full wipe with broad `Remove-Item`, registry cleaners, or manual recursive deletion.

## Validate the result

- Confirm the Desktop and Start menu shortcuts no longer launch the shell.
- Confirm the uninstall registration is gone after any required reboot.
- For normal uninstall, confirm the chosen project/export test files and provider credentials remain.
- For an authorized full wipe, compare the actual bounded removals with the reviewed plan and record any locked/reboot-pending item.

Source tests and the packaged-component operator smoke do not execute Windows uninstall. Only a recorded run against the actual installer on the intended Windows test PC is clean-PC uninstall/preservation evidence.
