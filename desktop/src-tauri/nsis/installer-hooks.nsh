!macro NSIS_HOOK_PREINSTALL
  SetShellVarContext current
  StrCpy $INSTDIR "$LOCALAPPDATA\Programs\AI Video Editor"
!macroend
