!macro NSIS_HOOK_PREINSTALL
  SetShellVarContext all
  StrCpy $INSTDIR "$PROGRAMFILES\AI Video Editor\Shell"

  ; Phase 6 permission decision: the per-machine installer creates only the
  ; scoped ProgramData component perimeter and grants the interactive Users
  ; group Modify access there. The shell itself stays non-elevated; every
  ; launch re-verifies the signed manifest and exact inventory before the
  ; supervisor can execute anything. Program Files remains immutable.
  CreateDirectory "$COMMONAPPDATA\AI Video Editor"
  CreateDirectory "$COMMONAPPDATA\AI Video Editor\Components"
  CreateDirectory "$COMMONAPPDATA\AI Video Editor\Activation"
  CreateDirectory "$COMMONAPPDATA\AI Video Editor\Downloads\Staging"
  CreateDirectory "$COMMONAPPDATA\AI Video Editor\Catalog"
  nsExec::ExecToLog '"$SYSDIR\icacls.exe" "$COMMONAPPDATA\AI Video Editor" /inheritance:r /grant:r "*S-1-5-18:(OI)(CI)(F)" "*S-1-5-32-544:(OI)(CI)(F)" "*S-1-5-32-545:(OI)(CI)(M)"'
!macroend
