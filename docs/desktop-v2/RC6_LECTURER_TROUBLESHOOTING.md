# RC.6 Lecturer Troubleshooting Guide

Start with **Diagnostics > Redacted recovery details**. Record the visible error code, component/version, readiness and capabilities status, and remediation text. Do not send API keys, raw Credential Manager contents, full user paths, videos, or project databases unless the owner explicitly authorizes that disclosure.

## Verification or Windows reputation warning

- **Checksum/signature verifier fails:** stop. Re-copy or re-download the complete RC.6 handoff from the expected channel. Never edit a manifest/catalog or combine it with RC.4/RC.5 files.
- **Unknown publisher / SmartScreen:** this RC.6 handoff honestly declares `authenticode.status = not-claimed`. Continue only for supervised evaluation after both included verifiers pass. The warning is not proof that verification passed.
- **Python verifier cannot start:** install Python 3 and `cryptography` for the independent verifier, or have the release operator run it. Python is not required by the installed application.

## Installation and first launch

- **Installer cannot write Program Files or ProgramData:** rerun the installer as an administrator. Do not grant broad write access to Program Files and do not manually take ownership of system folders.
- **Installer state/rollback issue:** retain `%ProgramData%\AI Video Editor\Installer\setup-rc6.log`, `transaction-rc6.json`, `uninstall-transaction-rc6.json`, `Shell.rc6-staging`, `Shell.rc6-rollback`, and any uniquely named `Shell.rc6-uninstall-*` tombstone. Rerun the same Setup after closing the app or restarting Windows. Do not delete recovery material when rollback is pending.
- **WebView2 unavailable:** install or repair the Microsoft Edge WebView2 Runtime, then relaunch.
- **Shortcut is missing or wrong:** launch the installed executable only from `%ProgramFiles%\AI Video Editor Desktop V2\Shell`; record the shortcut target and repair/reinstall the same RC.6 shell. Do not point a shortcut at a repository development build.

## Setup Center and components

- **Bundled catalog unavailable:** select **Browse** and choose `Catalog\offline-catalog.json` from the same verified handoff. Keep `Catalog` and `Components` in their original relative layout.
- **Unknown trust key, invalid signature, hash mismatch, expired or incompatible catalog:** stop and obtain a fresh coherent handoff. Retrying cannot make an invalid artifact trusted.
- **Storage not writable / activation needs elevation:** choose **Repair**, approve the scoped UAC prompt, and retry the exact check. Do not copy binaries directly into the active component folder.
- **Locked file or reboot required:** close the application, allow the recorded reboot action to complete, restart Windows, then reopen Setup Center. Preserve the diagnostics captured before reboot.

## Native engine not ready

Open Diagnostics and distinguish handshake, HTTP readiness, and capabilities failures. The engine uses an authenticated `127.0.0.1` control handshake with a fresh session/nonce; stdout is diagnostic only.

- Use Setup Center **Repair** for the native core, then retry.
- Check that endpoint security did not quarantine the verified engine or block loopback communication.
- Do not create a firewall exception that exposes the engine to the LAN and do not bind it to `0.0.0.0`.
- A component/version or protocol mismatch requires a coherent RC.6 catalog and shell, not a manual executable replacement.

## Import, processing, or export

- **Import stays copying/finalizing:** leave the app open while progress changes. After restart, let the app poll the durable operation. Retry or cancel through the UI; never promote a `.part` file manually.
- **Source rejected:** confirm the file is a local readable media file, has nonzero size, and plays outside the app. Try a small known-valid MP4.
- **FFmpeg unavailable or export fails:** repair **Media Tools**, then confirm Diagnostics reports the packaged FFmpeg capability. The app must not silently use a random FFmpeg from `PATH`.
- **Provider operation fails:** verify the selected provider from Settings and check network/account quota separately. Local ingest failure is not fixed by adding a provider key.
- **Output completes but does not play:** retain the project and export, record the preset/error, and test the file with an independent player or ffprobe. A completed JSON job alone is not playable-video evidence.

## What to collect

Collect the verifier output, Windows version, exact RC.6 installer filename/hash, the redacted Diagnostics snapshot, the user-visible step/error code, and whether repair/restart changed the result. Keep clean-PC installation, repair, and uninstall observations separate from source/unit/operator-smoke results.

## Stable Setup and uninstall codes

| Code | Stage | Meaning / action |
| ---: | --- | --- |
| 2101 | snapshot | External/registry/shortcut state could not be protected; no payload activation is allowed. |
| 2102 | registry | Registry discovery or restoration failed. Retain rollback state. |
| 2103 | shortcut | A required shortcut could not be created or verified. |
| 2104 | shell/staging rename | A same-volume staging, backup, or shell move failed. |
| 2105 | lock/reboot | Close the app and retry; if repeated, restart Windows. Interactive Setup offers Retry/Cancel. |
| 2106 | activation | The verified staged shell could not be atomically activated. |
| 2107 | handoff | Bundled-catalog origin could not be published atomically. |
| 2108 | registration | ARP/product registration could not be written or verified. |
| 2109 | identity | The uninstaller or committed identity could not be written/verified. |
| 2110 | rollback | Rollback is incomplete. Recovery material is intentionally retained. |
| 2111 | invariant | A canonical-path, test-override, or commit invariant was rejected. |
| 2112 | conflict | Unknown nonempty/reparse data was preserved; identify its owner before acting. |
| 2113 | mutex | Another Setup/uninstall instance owns the product mutex. |
| 3010 | committed cleanup | Installation succeeded; restart is required only for deferred old-version cleanup. |

Silent runs return these codes without an interactive retry dialog. A nonzero code is not success and must not be represented as a valid ARP installation.
