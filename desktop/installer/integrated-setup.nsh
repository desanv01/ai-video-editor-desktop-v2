# Keep a registered custom installation directory when updating it interactively.
# The default callback still sanitizes every new or unregistered destination.
!macro customPageAfterChangeDir
  !ifdef allowToChangeInstallationDirectory
    Function AiveInstFilesPre
      Push $0
      ReadRegStr $0 SHELL_CONTEXT "${INSTALL_REGISTRY_KEY}" InstallLocation
      ${If} $0 != ""
      ${AndIf} $INSTDIR == $0
      ${AndIf} ${FileExists} "$INSTDIR\${APP_EXECUTABLE_FILENAME}"
        Pop $0
        Return
      ${EndIf}
      Call instFilesPre
      Pop $0
    FunctionEnd
    !undef MUI_PAGE_CUSTOMFUNCTION_PRE
    !define MUI_PAGE_CUSTOMFUNCTION_PRE AiveInstFilesPre
  !endif
!macroend

# Interactive finish-page handoff only. Silent/update launch macros remain owned
# by electron-builder and do not receive the acquisition flag.
!macro customFinishPage
  !ifndef HIDE_RUN_AFTER_FINISH
    Function AiveContinueSetup
      ${If} ${UAC_IsAdmin}
        MessageBox MB_OK|MB_ICONSTOP "Aivora setup was not started. Close this installer and run it without administrator privileges."
        Return
      ${EndIf}
      StrCpy $1 "--aive-complete-setup"
      ${if} ${isUpdated}
        StrCpy $1 "--updated --aive-complete-setup"
      ${endif}
      ClearErrors
      Exec '"$INSTDIR\${APP_EXECUTABLE_FILENAME}" $1'
      ${If} ${Errors}
        MessageBox MB_OK|MB_ICONSTOP "Aivora setup could not start. The installation is retained. Close this installer and retry setup."
      ${EndIf}
    FunctionEnd
    !define MUI_FINISHPAGE_RUN
    !define MUI_FINISHPAGE_RUN_TEXT "Continue Aivora setup (downloads tools)"
    !define MUI_FINISHPAGE_RUN_FUNCTION "AiveContinueSetup"
  !endif
  !insertmacro MUI_PAGE_FINISH
!macroend
