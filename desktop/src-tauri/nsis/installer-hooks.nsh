!macro NSIS_HOOK_PREINSTALL
  SetShellVarContext all
  StrCpy $INSTDIR "$PROGRAMFILES\AI Video Editor\Shell"
!macroend
