; Desktop V2 Phase 7 NSIS policy.
; The identity remains stable across upgrades:
;   product: AI Video Editor Desktop V2
;   id:      com.fyp.ai-video-editor.desktop-v2
;   layout:  per-machine Program Files shell + ProgramData components
; Program Files remains immutable at runtime; user writes go to the scoped
; ProgramData component perimeter and per-user LocalAppData/content roots.
; User projects, uploads, exports, models, databases, and settings are not
; deleted by the default installer/uninstaller hooks.

!macro NSIS_HOOK_PREINSTALL
  SetShellVarContext all
  StrCpy $INSTDIR "$PROGRAMFILES\AI Video Editor\Shell"

  ; Critical directory/ACL failures abort.  There is no Ignore/continue path
  ; that could report a partial installation as success.
  ClearErrors
  CreateDirectory "$COMMONAPPDATA\AI Video Editor"
  CreateDirectory "$COMMONAPPDATA\AI Video Editor\Components"
  CreateDirectory "$COMMONAPPDATA\AI Video Editor\Activation"
  CreateDirectory "$COMMONAPPDATA\AI Video Editor\Downloads"
  CreateDirectory "$COMMONAPPDATA\AI Video Editor\Downloads\Staging"
  CreateDirectory "$COMMONAPPDATA\AI Video Editor\Catalog"
  IfErrors machine_perimeter_failed
  Goto machine_perimeter_ready
  machine_perimeter_failed:
    MessageBox MB_ICONSTOP|MB_OK "AI Video Editor Desktop V2 could not prepare its machine component perimeter. No partial installation will be accepted."
    Abort
  machine_perimeter_ready:

  ClearErrors
  nsExec::ExecToStack '"$SYSDIR\icacls.exe" "$COMMONAPPDATA\AI Video Editor" /inheritance:r /grant:r "*S-1-5-18:(OI)(CI)(F)" "*S-1-5-32-544:(OI)(CI)(F)" "*S-1-5-32-545:(OI)(CI)(M)"'
  Pop $0
  StrCmp $0 "0" acl_ready
    MessageBox MB_ICONSTOP|MB_OK "AI Video Editor Desktop V2 could not secure its machine component perimeter. Ask an administrator to repair the ACL, then retry."
    Abort
  acl_ready:
!macroend

!macro NSIS_HOOK_POSTINSTALL
  SetShellVarContext all
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
  FileWrite $0 '{"productName":"AI Video Editor Desktop V2","identifier":"com.fyp.ai-video-editor.desktop-v2","version":"2.0.0-rc.1","channel":"beta"}'
  FileClose $0
  Goto identity_done
  identity_failed:
    MessageBox MB_ICONSTOP|MB_OK "AI Video Editor Desktop V2 could not write its installer identity marker. Setup was aborted."
    Abort
  identity_done:

  CreateDirectory "$SMPROGRAMS\AI Video Editor Desktop V2"
  ClearErrors
  CreateShortCut "$DESKTOP\AI Video Editor Desktop V2.lnk" "$1"
  CreateShortCut "$SMPROGRAMS\AI Video Editor Desktop V2\AI Video Editor Desktop V2.lnk" "$1"
  IfErrors shortcut_failed
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\AI Video Editor Desktop V2" "DisplayName" "AI Video Editor Desktop V2"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\AI Video Editor Desktop V2" "DisplayVersion" "2.0.0-rc.1"
  WriteRegStr HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\AI Video Editor Desktop V2" "Publisher" "AI Video Editor"
  WriteRegStr HKLM "Software\AI Video Editor Desktop V2" "Identifier" "com.fyp.ai-video-editor.desktop-v2"
  WriteRegStr HKLM "Software\AI Video Editor Desktop V2" "InstallPath" "$INSTDIR"
  ; Retire obsolete installer records only after the new identity succeeded.
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\AI Video Editor"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AI Video Editor"
  Goto postinstall_done
  shortcut_failed:
    MessageBox MB_ICONSTOP|MB_OK "AI Video Editor Desktop V2 could not create its shortcuts. Setup was aborted; run Repair after fixing the shell profile."
    Abort
  postinstall_done:
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  SetShellVarContext all
  ; The app must close its owned supervisor/job before uninstall.  No generic
  ; forced process termination is used; Rust recognizes only an exact V2 ownership marker and
  ; reports locked leftovers for safe reboot cleanup.
  Delete "$DESKTOP\AI Video Editor Desktop V2.lnk"
  Delete "$SMPROGRAMS\AI Video Editor Desktop V2\AI Video Editor Desktop V2.lnk"
  RMDir "$SMPROGRAMS\AI Video Editor Desktop V2"
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  SetShellVarContext all
  ; Default uninstall removes only machine-scoped application/runtime state.
  ClearErrors
  RMDir /r "$COMMONAPPDATA\AI Video Editor\Components"
  RMDir /r "$COMMONAPPDATA\AI Video Editor\Activation"
  RMDir /r "$COMMONAPPDATA\AI Video Editor\Downloads\Staging"
  RMDir /r "$COMMONAPPDATA\AI Video Editor\Catalog"
  RMDir "$COMMONAPPDATA\AI Video Editor\Downloads"
  RMDir "$COMMONAPPDATA\AI Video Editor"
  ; Per-user disposable setup state only. Config, uploads, models, database,
  ; projects, and exports are deliberately preserved for a future reinstall.
  RMDir /r "$LOCALAPPDATA\AI Video Editor\Cache"
  RMDir /r "$LOCALAPPDATA\AI Video Editor\Temp"
  RMDir /r "$LOCALAPPDATA\AI Video Editor\Logs"
  RMDir /r "$LOCALAPPDATA\AI Video Editor\State"
  RMDir "$LOCALAPPDATA\AI Video Editor"
!macroend
