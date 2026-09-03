# RC.6 Lecturer Uninstall and Data-Retention Guide

AI Video Editor Desktop V2 separates the installed shell/components from valuable user data. A normal uninstall is intentionally data-preserving.

## Before uninstalling

1. Finish or cancel active imports and exports, then close the app.
2. Back up any project or export that cannot be recreated.
3. If validating retention, record hashes or filenames under `%USERPROFILE%\Documents\AI Video Editor` before uninstalling.
4. Review the app's uninstall plan or dry-run report when available. It must name bounded targets and redact secrets.

## Normal uninstall

Open **Windows Settings > Apps > Installed apps**, find **AI Video Editor Desktop V2**, and choose **Uninstall**. Approve elevation if requested and reboot if Windows reports locked files.

The default path removes the shell, shortcuts, and component-owned machine runtime state. It preserves per-user settings/uploads/models/databases, projects, exports, and provider credentials so that a later reinstall can resume work. Valuable user data is not an installer cleanup target.

Expected preserved locations include:

- `%LocalAppData%\AI Video Editor` for per-user settings/runtime records that are not explicitly disposable.
- `%USERPROFILE%\Documents\AI Video Editor` for projects, uploads, exports, and models.
- AI Video Editor provider entries in Windows Credential Manager.

## Full wipe

Full wipe is destructive and is separate from normal uninstall. Use it only when the data owner explicitly requests deletion, has a backup, has reviewed the exact allowlisted plan, and types this exact confirmation in the application:

```text
REMOVE ALL AI VIDEO EDITOR USER DATA
```

The wipe may remove known AI Video Editor user-data roots and known provider credential targets. It must never enumerate or clear unrelated credentials, arbitrary folders, repository checkouts, or Docker data. Do not reproduce full wipe with broad `Remove-Item`, registry cleaners, or manual recursive deletion.

## Validate the result

- Confirm the Desktop and Start menu shortcuts no longer launch the shell.
- Confirm the uninstall registration is gone after any required reboot.
- For normal uninstall, confirm the chosen project/export test files and provider credentials remain.
- For an authorized full wipe, compare the actual bounded removals with the reviewed plan and record any locked/reboot-pending item.

Source tests and the packaged-component operator smoke do not execute Windows uninstall. Only a recorded run against the actual installer on the intended Windows test PC is clean-PC uninstall/preservation evidence.
