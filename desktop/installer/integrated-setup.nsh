# Interactive finish-page handoff only. Silent/update launch macros remain owned
# by electron-builder and do not receive the acquisition flag.
!macro customFinishPage
  !ifndef HIDE_RUN_AFTER_FINISH
    Function AiveContinueSetup
      StrCpy $1 "--aive-complete-setup"
      ${if} ${isUpdated}
        StrCpy $1 "--updated --aive-complete-setup"
      ${endif}
      ${StdUtils.ExecShellAsUser} $0 "$launchLink" "open" "$1"
    FunctionEnd
    !define MUI_FINISHPAGE_RUN
    !define MUI_FINISHPAGE_RUN_TEXT "Continue Aivora setup (downloads tools)"
    !define MUI_FINISHPAGE_RUN_FUNCTION "AiveContinueSetup"
  !endif
  !insertmacro MUI_PAGE_FINISH
!macroend
