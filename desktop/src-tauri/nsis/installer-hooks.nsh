; Desktop V2 installer ACL hotfix policy.
; The identity remains stable across upgrades:
;   product: AI Video Editor Desktop V2
;   id:      com.fyp.ai-video-editor.desktop-v2
;   layout:  per-machine Program Files\Shell + ProgramData components
; Program Files remains immutable at runtime; user writes go to the scoped
; ProgramData component perimeter and per-user LocalAppData/content roots.
; User projects, uploads, exports, models, databases, and settings are not
; deleted by the default installer/uninstaller hooks.

!macro NSIS_HOOK_PREINSTALL
  SetShellVarContext all
  SetRegView 64
  StrCpy $INSTDIR "$PROGRAMFILES64\AI Video Editor Desktop V2\Shell"
  ; Tauri's generated section sets an output directory before this hook.  Set
  ; it again after enforcing the x64 path so every payload file and uninstaller
  ; resource lands under the same Program Files perimeter.
  SetOutPath $INSTDIR

  ; With the all-users shell context, NSIS resolves $APPDATA to the common
  ; application-data directory (%ProgramData%).  Verify that resolution before
  ; using it so a shell-variable fallback can never redirect machine state to a
  ; user profile or an unresolved literal token.
  StrCpy $2 "$APPDATA\AI Video Editor"
  ReadEnvStr $3 "ProgramData"
  StrCmp $3 "" machine_data_resolution_failed
  StrCpy $4 "$3\AI Video Editor"
  StrCmp /I $2 $4 machine_data_resolved
  DetailPrint "Unexpected machine data root. Expected: $4"
  DetailPrint "Resolved NSIS machine data root: $2"
  Goto machine_data_resolution_failed
  machine_data_resolution_failed:
    MessageBox MB_ICONSTOP|MB_OK "AI Video Editor Desktop V2 could not resolve its machine component perimeter to %ProgramData%. No partial installation will be accepted."
    Abort
  machine_data_resolved:

  ; Critical directory/ACL failures abort.  There is no bypass path
  ; that could report a partial installation as success.
  ClearErrors
  StrCpy $4 "$2"
  CreateDirectory "$4"
  IfErrors machine_perimeter_failed
  StrCpy $4 "$2\Components"
  CreateDirectory "$4"
  IfErrors machine_perimeter_failed
  StrCpy $4 "$2\Activation"
  CreateDirectory "$4"
  IfErrors machine_perimeter_failed
  StrCpy $4 "$2\Downloads"
  CreateDirectory "$4"
  IfErrors machine_perimeter_failed
  StrCpy $4 "$2\Downloads\Staging"
  CreateDirectory "$4"
  IfErrors machine_perimeter_failed
  StrCpy $4 "$2\Catalog"
  CreateDirectory "$4"
  IfErrors machine_perimeter_failed
  StrCpy $4 "$2\Broker"
  CreateDirectory "$4"
  IfErrors machine_perimeter_failed
  StrCpy $4 "$2\Broker\Requests"
  CreateDirectory "$4"
  IfErrors machine_perimeter_failed
  Goto machine_perimeter_ready
  machine_perimeter_failed:
    DetailPrint "CreateDirectory failed for: $4"
    MessageBox MB_ICONSTOP|MB_OK "AI Video Editor Desktop V2 could not prepare its machine component perimeter. Failed path: $4. No partial installation will be accepted."
    Abort
  machine_perimeter_ready:

  ; Reset the newly-created perimeter, remove inheritance, then apply the
  ; exact scoped policy: Administrators own the tree; SYSTEM and Administrators
  ; have full control; authenticated local Users have Modify only here.  The
  ; quoted executable and quoted variable path are intentional: both remain
  ; safe when the Windows installation path contains spaces.
  nsExec::ExecToStack /OEM '"$SYSDIR\icacls.exe" "$2" /reset /T'
  Pop $0
  Pop $1
  DetailPrint "icacls reset exit code: $0"
  DetailPrint "icacls reset output: $1"
  StrCmp $0 "0" acl_reset_ready
    DetailPrint "icacls reset failed; no ACL fallback is permitted."
    MessageBox MB_ICONSTOP|MB_OK "AI Video Editor Desktop V2 could not reset the machine component perimeter ACL. icacls exit code: $0. Ask an administrator to repair the ACL, then retry."
    Abort
  acl_reset_ready:

  nsExec::ExecToStack /OEM '"$SYSDIR\icacls.exe" "$2" /inheritance:r /grant:r "*S-1-5-18:(OI)(CI)(F)" "*S-1-5-32-544:(OI)(CI)(F)" "*S-1-5-32-545:(OI)(CI)(M)" /T'
  Pop $0
  Pop $1
  DetailPrint "icacls perimeter policy exit code: $0"
  DetailPrint "icacls perimeter policy output: $1"
  StrCmp $0 "0" acl_ready
    DetailPrint "icacls perimeter policy failed; no bypass path is available."
    MessageBox MB_ICONSTOP|MB_OK "AI Video Editor Desktop V2 could not secure its machine component perimeter. icacls exit code: $0. Ask an administrator to repair the ACL, then retry."
    Abort
  acl_ready:

  ; icacls does not accept /setowner in the same invocation as /grant.  Keep
  ; ownership as a separately checked operation so a successful grant cannot
  ; hide an owner-assignment failure.
  nsExec::ExecToStack /OEM '"$SYSDIR\icacls.exe" "$2" /setowner "*S-1-5-32-544" /T'
  Pop $0
  Pop $1
  DetailPrint "icacls owner policy exit code: $0"
  DetailPrint "icacls owner policy output: $1"
  StrCmp $0 "0" owner_ready
    DetailPrint "icacls owner policy failed; no bypass path is available."
    MessageBox MB_ICONSTOP|MB_OK "AI Video Editor Desktop V2 could not set the machine component perimeter owner. icacls exit code: $0. Ask an administrator to repair the ACL, then retry."
    Abort
  owner_ready:
!macroend

!macro NSIS_HOOK_POSTINSTALL
  SetShellVarContext all
  SetRegView 64
  ClearErrors

  ; Tauri may use the display name or the Cargo binary name.  A missing shell
  ; binary is a critical post-install failure.
  IfFileExists "$INSTDIR\AI Video Editor Desktop V2.exe" shell_display
  IfFileExists "$INSTDIR\ai-video-editor.exe" shell_cargo
  Goto shell_failed
  shell_display:
    StrCpy $1 "$INSTDIR\AI Video Editor Desktop V2.exe"
    Goto shell_verified
  shell_cargo:
    StrCpy $1 "$INSTDIR\ai-video-editor.exe"
    Goto shell_verified
  shell_failed:
    MessageBox MB_ICONSTOP|MB_OK "AI Video Editor Desktop V2 installed without its shell executable. Setup was aborted and must be repaired before launch."
    Abort
  shell_verified:

  FileOpen $0 "$INSTDIR\desktop-v2.identity.json" w
  IfErrors identity_failed
  FileWrite $0 '{"productName":"AI Video Editor Desktop V2","identifier":"com.fyp.ai-video-editor.desktop-v2","version":"2.0.0-rc.5","channel":"beta"}'
  FileClose $0
  Goto identity_done
  identity_failed:
    MessageBox MB_ICONSTOP|MB_OK "AI Video Editor Desktop V2 could not write its installer identity marker. Setup was aborted."
    Abort
  identity_done:

  ; The generated Tauri NSIS section is the sole shortcut owner.  This hook
  ; intentionally creates no .lnk files, preventing the duplicate desktop
  ; shortcut observed in the rc.3 clean-laptop evidence.
  FileOpen $0 "$INSTDIR\component-broker.json" w
  IfErrors broker_marker_failed
  FileWrite $0 '{"schemaVersion":"desktop.component-broker.v1","identifier":"aive-component-broker","scope":"per-machine","productIdentifier":"com.fyp.ai-video-editor.desktop-v2"}'
  FileClose $0
  Goto broker_marker_done
  broker_marker_failed:
    MessageBox MB_ICONSTOP|MB_OK "AI Video Editor Desktop V2 could not write its component repair marker. Setup was aborted."
    Abort
  broker_marker_done:
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\AI Video Editor Desktop V2" "DisplayName" "AI Video Editor Desktop V2"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\AI Video Editor Desktop V2" "DisplayVersion" "2.0.0-rc.5"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\AI Video Editor Desktop V2" "Publisher" "AI Video Editor"
  WriteRegStr HKLM "Software\AI Video Editor Desktop V2" "Identifier" "com.fyp.ai-video-editor.desktop-v2"
  WriteRegStr HKLM "Software\AI Video Editor Desktop V2" "InstallPath" "$INSTDIR"
  ; Retire obsolete installer records only after the new identity succeeded.
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\AI Video Editor"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AI Video Editor"
  Goto postinstall_done
  postinstall_done:
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  SetShellVarContext all
  ; The generated Tauri NSIS uninstall section owns the shortcuts.  The app
  ; must be closed before uninstall; locked runtime files are left for the
  ; standard Windows restart/retry path rather than force-killing processes.
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  ; Capture the invoking user's LocalAppData before switching to the all-users
  ; shell context.  $LOCALAPPDATA is context-sensitive too; using it while
  ; context=all would incorrectly target ProgramData and could violate the
  ; data-preserving uninstall contract.
  SetShellVarContext current
  StrCpy $5 "$LOCALAPPDATA\AI Video Editor"
  SetShellVarContext all
  SetRegView 64
  Delete "$INSTDIR\desktop-v2.identity.json"
  Delete "$INSTDIR\component-broker.json"
  RMDir "$INSTDIR"
  RMDir "$PROGRAMFILES64\AI Video Editor Desktop V2"
  ; Default uninstall removes only machine-scoped application/runtime state.
  StrCpy $2 "$APPDATA\AI Video Editor"
  ReadEnvStr $3 "ProgramData"
  StrCpy $4 "$3\AI Video Editor"
  StrCmp /I $2 $4 machine_cleanup_resolved
  DetailPrint "Skipping machine cleanup because NSIS resolved an unexpected root: $2"
  Goto machine_cleanup_done
  machine_cleanup_resolved:
  ClearErrors
  RMDir /r "$2\Components"
  RMDir /r "$2\Activation"
  RMDir /r "$2\Downloads\Staging"
  RMDir /r "$2\Catalog"
  RMDir /r "$2\Broker\Requests"
  RMDir "$2\Broker"
  RMDir "$2\Downloads"
  RMDir "$2"
  machine_cleanup_done:
  ; Per-user disposable setup state only. Config, uploads, models, database,
  ; projects, and exports are deliberately preserved for a future reinstall.
  RMDir /r "$5\Cache"
  RMDir /r "$5\Temp"
  RMDir /r "$5\Logs"
  RMDir /r "$5\State"
  RMDir "$5"
!macroend
