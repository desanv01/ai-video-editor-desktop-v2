# RC.7 Lecturer Setup Guide

AI Video Editor Desktop V2 `2.0.0-rc.7` is a Windows x64 release candidate for supervised evaluation. The default handoff is labeled **DEVELOPER/TEST — NOT PRODUCTION-TRUSTED**. It is not Authenticode-signed, and its public Ed25519 test key proves internal component consistency rather than a commercial publisher identity.

Do not install a handoff that lacks `START-HERE.md`, `release-manifest.json`, `SHA256SUMS.txt`, `Verify-RC7Release.ps1`, or the two signed component archives. Do not use RC.4/RC.5 files to fill gaps in an RC.7 folder.

The distributed ZIP must have an adjacent `.sha256` file. Hash the downloaded ZIP before extraction and compare the complete 64-character value. After extraction, run both bundled verifiers below; a ZIP hash does not replace the internal exact-file and signature checks.

## What the test PC needs

- Windows 10 or 11 x64 and an administrator available for the per-machine installer and component activation prompts.
- Enough free space for the shell, native engine, FFmpeg, imported videos, and exports. Setup Center reports the current requirement before activation.
- Microsoft Edge WebView2 Runtime. The shell diagnoses a missing runtime rather than bundling an undocumented replacement.
- A local copy of the entire RC.7 handoff. Keep `Catalog` and `Components` together; signed `offline:Components/...` references are resolved relative to the selected catalog.
- Python 3 plus the `cryptography` package only if you will run the independent Python signature verifier or smoke harness. The installed application itself does not require system Python.
- Lecturer-owned provider credentials only for provider-backed AI features. No API keys, models, user projects, or Docker environment are included.

## Verify before installation

Open PowerShell in the extracted handoff folder and run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Verify-RC7Release.ps1 -HandoffRoot .
```

The release verifier is read-only and must pass. It confirms the RC.7 identity, checksums, pinned FFmpeg `8.1.1` provenance, absence of private signing material, and the honest `authenticode.status = not-claimed` declaration. The release operator separately runs the included `verify-handoff-signatures.py` against the signed catalog and component manifests before distributing the ZIP; that optional independent check requires Python with `cryptography`.

Stop if a verifier fails, if Windows reports that the files changed after download, or if the folder is a mixture of release candidates. Do not bypass a checksum or signature error by editing the catalog or granting broad filesystem permissions.

## Expected storage boundaries

| Purpose | Default location |
| --- | --- |
| Per-machine shell | `%ProgramFiles%\AI Video Editor Desktop V2\Shell` |
| Signed components and machine state | `%ProgramData%\AI Video Editor` |
| Per-user settings, logs, and disposable runtime state | `%LocalAppData%\AI Video Editor` |
| Projects, uploads, exports, and models | `%USERPROFILE%\Documents\AI Video Editor` |
| Provider secrets | Windows Credential Manager |
| Redacted Setup/uninstall diagnostics | `%ProgramData%\AI Video Editor\Installer\*-rc6.log` (stable RC.6 transaction namespace retained by RC.7) |

The installer and repair helper may request elevation only for the bounded Program Files and ProgramData areas. Never grant `Everyone` write access to Program Files or move user projects into the component directory.

## Optional operator smoke

After assembling real RC.7 component archives, an operator can run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\SMOKE\Run-DesktopV2Smoke.ps1 `
  -HandoffRoot . `
  -EvidencePath .\operator-smoke.json
```

This extracts the actual archives into disposable temporary storage and tests a valid MP4 through project creation, durable native import, provider-free process/export, playable-output probing, engine restart, and redirected-root persistence. It does **not** install the shell and is not evidence of a clean-PC install, UAC, shortcuts, repair, or uninstall.

Continue with `RC7_LECTURER_INSTALL.md` and `RC7_LECTURER_CONFIGURATION.md` in the source tree, or `INSTALL.md` and `CONFIGURATION.md` in an assembled handoff.
