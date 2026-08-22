# Desktop V2 installer ACL hotfix — rc.2

## Incident and evidence

The shipped rc.1 installer failed during its preinstall hook. The NSIS detail log displayed a literal machine-data path beginning with the unresolved shell token `${COMMONAPPDATA}`, then aborted with “could not secure its machine component perimeter.” Read-only inspection of the shipped handoff found no literal placeholder directory on disk, no completed machine perimeter, no Desktop V2 uninstall registry record, and no shortcuts; the only remaining install residue was an empty `C:\Program Files\AI Video Editor Desktop V2` directory.

The old source was `desktop/src-tauri/nsis/installer-hooks.nsh` at the rc.1 release commit. The affected operations were:

- lines 18–23: preinstall creation of the machine root and `Components`, `Activation`, `Downloads`, `Downloads\Staging`, and `Catalog`;
- line 32: preinstall `icacls.exe` invocation;
- lines 104–109: postuninstall deletion of the machine perimeter.

The token was not a valid NSIS shell variable. NSIS therefore preserved it as literal text in the generated installer instead of resolving it to Windows common application data. The same defect affected both setup and cleanup paths. The old hook also assigned the shell to the legacy `AI Video Editor\Shell` directory, despite the release handoff claiming `C:\Program Files\AI Video Editor Desktop V2`.

## Corrected policy

rc.2 keeps the stable product identity `com.fyp.ai-video-editor.desktop-v2` and uses this layout:

| Scope | Path | Policy |
| --- | --- | --- |
| Shell | `C:\Program Files\AI Video Editor Desktop V2` | Per-machine, immutable at runtime |
| Components | `C:\ProgramData\AI Video Editor\Components` | Signed, versioned component perimeter |
| Activation | `C:\ProgramData\AI Video Editor\Activation` | Machine activation metadata and journals |
| Staging | `C:\ProgramData\AI Video Editor\Downloads\Staging` | Machine download staging |
| User state | `%LOCALAPPDATA%\AI Video Editor` | Per-user settings, logs, cache, projects, and exports |

The hook sets `SetShellVarContext all`, resolves `$APPDATA\AI Video Editor`, reads the Windows `ProgramData` environment root, and aborts unless the two paths match. It creates each required directory with a checked `CreateDirectory` result. It then runs a quoted `icacls.exe` command and checks both reset and final-policy exit codes; `error`, `timeout`, and every nonzero exit result abort setup with diagnostics. No Ignore/continue path exists.

The final ACL policy is applied recursively with inheritance removed and the Administrators group as owner: SYSTEM and Administrators receive full control, and the local Users group receives Modify only within the scoped component perimeter. The uninstaller resolves the same machine root before deleting only machine runtime state. It captures the invoking user’s `%LOCALAPPDATA%` path before switching to all-users context, so disposable per-user state is cleaned without touching user projects, uploads, models, databases, configuration, or exports.

The installer does not create WebView2 state for the administrator who approves UAC. At process start, the shell resolves the *actual launching user’s* `%LOCALAPPDATA%\com.fyp.ai-video-editor.desktop-v2`, creates it, performs a write/remove probe, and only then lets Tauri construct the first WebView2 window. This keeps a per-machine install usable by another Windows account and turns profile-permission failures into an actionable startup diagnostic rather than a generic WebView2 access-denied panic.

## Regression coverage

`scripts/desktop-v2/installer-acl-tests.mjs` fails if the invalid token or any unresolved path placeholder returns, verifies the Program Files identity and ProgramData resolution guard, checks the quoted recursive ACL command/SIDs/owner/exit-code gates, checks the current-user uninstall capture, and scans any generated NSIS source or supplied compiled artifact. `scripts/desktop-v2/webview-user-data-tests.mjs` verifies the launch-user WebView2 preflight runs before Tauri startup and that NSIS never creates that per-user directory for the installing administrator. Phase 6 and Phase 7 tests now require `$APPDATA` and explicitly reject the invalid token.

The final rc.2 handoff must also pass the read-only handoff verifier, copied-to-different-directory catalog/component lifecycle test, real installer install/launch/shortcut/ACL checks, authenticated engine readiness, real FFmpeg encode/probe/decode, restart/repair, and controlled uninstall preservation checks. Final sizes, hashes, and the exact source commit are generated into the handoff `release-manifest.json` after those gates pass.
