; AI Video Editor Desktop V2 RC.6 pinned NSIS template.
; Derived from @tauri-apps/cli 2.11.2 / tauri-v2.11.2 installer.nsi.
; Intentional policy changes: fixed per-machine path, no directory/start-menu
; chooser, one shortcut owner, verified shortcuts before ARP commit, and a
; bounded recoverable install transaction.

Unicode true
ManifestDPIAware true
ManifestDPIAwareness PerMonitorV2

!if "{{compression}}" == "none"
  SetCompress off
!else
  SetCompressor /SOLID "{{compression}}"
!endif

!include MUI2.nsh
!include FileFunc.nsh
!include x64.nsh
!include WordFunc.nsh
!include LogicLib.nsh
!include "utils.nsh"
!include "FileAssociation.nsh"
!include "Win\COM.nsh"
!include "Win\Propkey.nsh"

{{#if installer_hooks}}
!include "{{installer_hooks}}"
{{/if}}

!define WEBVIEW2APPGUID "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
!define MANUFACTURER "{{manufacturer}}"
!define PRODUCTNAME "{{product_name}}"
!define VERSION "{{version}}"
!define VERSIONWITHBUILD "{{version_with_build}}"
!define HOMEPAGE "{{homepage}}"
!define INSTALLMODE "{{install_mode}}"
!define LICENSE "{{license}}"
!define INSTALLERICON "{{installer_icon}}"
!define SIDEBARIMAGE "{{sidebar_image}}"
!define HEADERIMAGE "{{header_image}}"
!define UNINSTALLERICON "{{uninstaller_icon}}"
!define UNINSTALLERHEADERIMAGE "{{uninstaller_header_image}}"
!define MAINBINARYNAME "{{main_binary_name}}"
!define MAINBINARYSRCPATH "{{main_binary_path}}"
!define BUNDLEID "{{bundle_id}}"
!define COPYRIGHT "{{copyright}}"
!define OUTFILE "{{out_file}}"
!define ARCH "{{arch}}"
!define ADDITIONALPLUGINSPATH "{{additional_plugins_path}}"
!define DISPLAYLANGUAGESELECTOR "{{display_language_selector}}"
!define INSTALLWEBVIEW2MODE "{{install_webview2_mode}}"
!define WEBVIEW2INSTALLERARGS "{{webview2_installer_args}}"
!define WEBVIEW2BOOTSTRAPPERPATH "{{webview2_bootstrapper_path}}"
!define WEBVIEW2INSTALLERPATH "{{webview2_installer_path}}"
!define MINIMUMWEBVIEW2VERSION "{{minimum_webview2_version}}"
!define UNINSTALLERSIGNCOMMAND "{{uninstaller_sign_cmd}}"
!define ESTIMATEDSIZE "{{estimated_size}}"
!define UNINSTKEY "Software\Microsoft\Windows\CurrentVersion\Uninstall\${PRODUCTNAME}"
!define MANUKEY "Software\${MANUFACTURER}"
!define MANUPRODUCTKEY "${MANUKEY}\${PRODUCTNAME}"
!define AIVEPRODUCTKEY "Software\AI Video Editor Desktop V2"
!define AIVEROLLBACKKEY "Software\AI Video Editor Desktop V2 RC6 Installer Rollback"
!define AIVEINSTALLERPARENT "$PROGRAMFILES64\AI Video Editor Desktop V2"
!define AIVEINSTALLDIR "${AIVEINSTALLERPARENT}\Shell"
!define AIVEBACKUPDIR "${AIVEINSTALLERPARENT}\Shell.rc6-rollback"
!define AIVETXNBACKUPDIR "${AIVEINSTALLERPARENT}\.rc6-installer-rollback"
!define AIVESTARTMENUDIR "$SMPROGRAMS\AI Video Editor Desktop V2"
!define AIVESTARTMENULINK "${AIVESTARTMENUDIR}\AI Video Editor Desktop V2.lnk"
!define AIVEDESKTOPLINK "$DESKTOP\AI Video Editor Desktop V2.lnk"
!define AIVEFULLWIPETOKEN "REMOVE_ALL_AI_VIDEO_EDITOR_USER_DATA"

Var PassiveMode
Var UpdateMode
Var InstallStarted
Var InstallCommitted
Var TxnHadPriorShell
Var TxnHadDesktopShortcut
Var TxnHadStartMenuShortcut
Var TxnHadArp
Var TxnHadProductRegistration
Var TxnHadAiveProductRegistration
Var TxnCreatedMachineRoot
Var TxnCreatedComponents
Var TxnCreatedActivation
Var TxnCreatedDownloads
Var TxnCreatedStaging
Var TxnCreatedCatalog
Var TxnCreatedBroker
Var TxnCreatedRequests
Var TxnCreatedProvisioning
Var TxnCreatedInstaller
Var TxnHadInstallerOrigin
Var TxnWroteInstallerOrigin
Var FullWipeCheckbox
Var FullWipeCheckboxState

Name "${PRODUCTNAME}"
BrandingText "${COPYRIGHT}"
OutFile "${OUTFILE}"
InstallDir "${AIVEINSTALLDIR}"
VIProductVersion "${VERSIONWITHBUILD}"
VIAddVersionKey "ProductName" "${PRODUCTNAME}"
VIAddVersionKey "FileDescription" "${PRODUCTNAME}"
VIAddVersionKey "LegalCopyright" "${COPYRIGHT}"
VIAddVersionKey "FileVersion" "${VERSION}"
VIAddVersionKey "ProductVersion" "${VERSION}"
!addplugindir "${ADDITIONALPLUGINSPATH}"

!if "${UNINSTALLERSIGNCOMMAND}" != ""
  !uninstfinalize '${UNINSTALLERSIGNCOMMAND}'
!endif

RequestExecutionLevel admin
!if "${INSTALLERICON}" != ""
  !define MUI_ICON "${INSTALLERICON}"
!endif
!if "${SIDEBARIMAGE}" != ""
  !define MUI_WELCOMEFINISHPAGE_BITMAP "${SIDEBARIMAGE}"
!endif
!if "${HEADERIMAGE}" != ""
  !define MUI_HEADERIMAGE
  !define MUI_HEADERIMAGE_BITMAP "${HEADERIMAGE}"
!endif
!if "${UNINSTALLERICON}" != ""
  !define MUI_UNICON "${UNINSTALLERICON}"
!endif

!define MUI_LANGDLL_REGISTRY_ROOT "HKCU"
!define MUI_LANGDLL_REGISTRY_KEY "${MANUPRODUCTKEY}"
!define MUI_LANGDLL_REGISTRY_VALUENAME "Installer Language"

; The install path and shortcut locations are policy, not user choices.
!define MUI_PAGE_CUSTOMFUNCTION_PRE SkipIfPassive
!insertmacro MUI_PAGE_WELCOME
!if "${LICENSE}" != ""
  !define MUI_PAGE_CUSTOMFUNCTION_PRE SkipIfPassive
  !insertmacro MUI_PAGE_LICENSE "${LICENSE}"
!endif
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_NOAUTOCLOSE
!define MUI_FINISHPAGE_RUN
!define MUI_FINISHPAGE_RUN_FUNCTION RunMainBinary
!define MUI_PAGE_CUSTOMFUNCTION_PRE SkipIfPassive
!insertmacro MUI_PAGE_FINISH

; One explicit destructive choice. It is unchecked by default and is ignored
; for updater/passive flows unless the exact command-line token is supplied.
!define /ifndef WS_EX_LAYOUTRTL 0x00400000
!define MUI_PAGE_CUSTOMFUNCTION_SHOW un.ConfirmShow
Function un.ConfirmShow
  FindWindow $1 "#32770" "" $HWNDPARENT
  System::Call "user32::GetDpiForWindow(p r1) i .r2"
  ${If} $(^RTL) = 1
    StrCpy $3 "${__NSD_CheckBox_EXSTYLE} | ${WS_EX_LAYOUTRTL}"
    IntOp $4 50 * $2
  ${Else}
    StrCpy $3 "${__NSD_CheckBox_EXSTYLE}"
    IntOp $4 0 * $2
  ${EndIf}
  IntOp $5 100 * $2
  IntOp $6 440 * $2
  IntOp $7 40 * $2
  IntOp $4 $4 / 96
  IntOp $5 $5 / 96
  IntOp $6 $6 / 96
  IntOp $7 $7 / 96
  System::Call 'user32::CreateWindowEx(i r3, w "${__NSD_CheckBox_CLASS}", w "Remove ALL AI Video Editor user data, projects, settings, and known credentials", i ${__NSD_CheckBox_STYLE}, i r4, i r5, i r6, i r7, p r1, i0, i0, i0) i .s'
  Pop $FullWipeCheckbox
  SendMessage $HWNDPARENT ${WM_GETFONT} 0 0 $1
  SendMessage $FullWipeCheckbox ${WM_SETFONT} $1 1
  ${If} $FullWipeCheckboxState = 1
    SendMessage $FullWipeCheckbox ${BM_SETCHECK} ${BST_CHECKED} 0
  ${EndIf}
FunctionEnd
!define MUI_PAGE_CUSTOMFUNCTION_LEAVE un.ConfirmLeave
Function un.ConfirmLeave
  SendMessage $FullWipeCheckbox ${BM_GETCHECK} 0 0 $FullWipeCheckboxState
FunctionEnd
!define MUI_PAGE_CUSTOMFUNCTION_PRE un.SkipIfPassive
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

{{#each languages}}
!insertmacro MUI_LANGUAGE "{{this}}"
{{/each}}
!insertmacro MUI_RESERVEFILE_LANGDLL
{{#each language_files}}
  !include "{{this}}"
{{/each}}

Function SetCanonicalInstallDir
  ${IfNot} ${RunningX64}
    MessageBox MB_ICONSTOP|MB_OK "AI Video Editor Desktop V2 RC.6 requires 64-bit Windows."
    Abort
  ${EndIf}
  StrCpy $INSTDIR "${AIVEINSTALLDIR}"
  SetOutPath "$INSTDIR"
FunctionEnd

Function .onInit
  StrCpy $InstallStarted 0
  StrCpy $InstallCommitted 0
  StrCpy $TxnHadPriorShell 0
  StrCpy $TxnHadDesktopShortcut 0
  StrCpy $TxnHadStartMenuShortcut 0
  StrCpy $TxnHadArp 0
  StrCpy $TxnHadProductRegistration 0
  StrCpy $TxnHadAiveProductRegistration 0
  StrCpy $TxnHadInstallerOrigin 0
  StrCpy $TxnWroteInstallerOrigin 0
  StrCpy $TxnCreatedMachineRoot 0
  StrCpy $TxnCreatedComponents 0
  StrCpy $TxnCreatedActivation 0
  StrCpy $TxnCreatedDownloads 0
  StrCpy $TxnCreatedStaging 0
  StrCpy $TxnCreatedCatalog 0
  StrCpy $TxnCreatedBroker 0
  StrCpy $TxnCreatedRequests 0
  StrCpy $TxnCreatedProvisioning 0
  StrCpy $TxnCreatedInstaller 0
  StrCpy $FullWipeCheckboxState 0
  ${GetOptions} $CMDLINE "/P" $PassiveMode
  ${IfNot} ${Errors}
    StrCpy $PassiveMode 1
  ${EndIf}
  ${GetOptions} $CMDLINE "/UPDATE" $UpdateMode
  ${IfNot} ${Errors}
    StrCpy $UpdateMode 1
  ${EndIf}
  !if "${DISPLAYLANGUAGESELECTOR}" == "true"
    !insertmacro MUI_LANGDLL_DISPLAY
  !endif
  !insertmacro SetContext
  Call SetCanonicalInstallDir
  Call RecoverInterruptedInstall
  Call RepairStaleRc6Registration
FunctionEnd

Function RecoverInterruptedInstall
  IfFileExists "${AIVEBACKUPDIR}\." backup_present no_shell_backup
  no_shell_backup:
    IfFileExists "$INSTDIR\.installing" fresh_interrupted_partial recovery_done
  fresh_interrupted_partial:
    DetailPrint "Removing an interrupted fresh RC.6 install transaction."
    Call RecoverInterruptedInstallerOrigin
    Call RecoverInterruptedShortcuts
    Call RemoveCurrentShellPayload
    RMDir /REBOOTOK "${AIVEINSTALLERPARENT}"
    Goto recovery_done
  backup_present:
    IfFileExists "$INSTDIR\.installing" interrupted_partial backup_without_partial
  interrupted_partial:
    DetailPrint "Recovering interrupted RC.6 install transaction."
    Call RecoverInterruptedInstallerOrigin
    Call RecoverInterruptedShortcuts
    Call RemoveCurrentShellPayload
    ClearErrors
    Rename "${AIVEBACKUPDIR}" "$INSTDIR"
    IfErrors 0 recovery_done
      MessageBox MB_ICONSTOP|MB_OK "RC.6 could not restore the previous shell. Restart Windows, then run Setup again."
      Abort
  backup_without_partial:
    IfFileExists "$INSTDIR\." stale_backup_after_commit restore_backup_only
  stale_backup_after_commit:
    DetailPrint "Removing a stale committed RC.6 backup."
    Delete "$PROGRAMDATA\AI Video Editor\Installer\handoff-root.json.rc6-rollback"
    RMDir /r "${AIVETXNBACKUPDIR}"
    RMDir /r /REBOOTOK "${AIVEBACKUPDIR}"
    Goto recovery_done
  restore_backup_only:
    ClearErrors
    Rename "${AIVEBACKUPDIR}" "$INSTDIR"
    IfErrors 0 recovery_done
      MessageBox MB_ICONSTOP|MB_OK "RC.6 found an interrupted backup that could not be restored. Restart Windows, then retry."
      Abort
  recovery_done:
FunctionEnd

Function RecoverInterruptedInstallerOrigin
  IfFileExists "$PROGRAMDATA\AI Video Editor\Installer\handoff-root.json.rc6-rollback" 0 interrupted_origin_was_new
    Delete "$PROGRAMDATA\AI Video Editor\Installer\handoff-root.json"
    Rename "$PROGRAMDATA\AI Video Editor\Installer\handoff-root.json.rc6-rollback" "$PROGRAMDATA\AI Video Editor\Installer\handoff-root.json"
    Goto interrupted_origin_recovered
  interrupted_origin_was_new:
    Delete "$PROGRAMDATA\AI Video Editor\Installer\handoff-root.json"
  interrupted_origin_recovered:
  Delete "$PROGRAMDATA\AI Video Editor\Installer\handoff-root.json.part"
FunctionEnd

Function RecoverInterruptedShortcuts
  IfFileExists "${AIVETXNBACKUPDIR}\Desktop.lnk" 0 interrupted_desktop_was_new
    Delete "${AIVEDESKTOPLINK}"
    Rename "${AIVETXNBACKUPDIR}\Desktop.lnk" "${AIVEDESKTOPLINK}"
    Goto interrupted_desktop_recovered
  interrupted_desktop_was_new:
    Delete "${AIVEDESKTOPLINK}"
  interrupted_desktop_recovered:
  IfFileExists "${AIVETXNBACKUPDIR}\StartMenu.lnk" 0 interrupted_start_was_new
    Delete "${AIVESTARTMENULINK}"
    Rename "${AIVETXNBACKUPDIR}\StartMenu.lnk" "${AIVESTARTMENULINK}"
    Goto interrupted_start_recovered
  interrupted_start_was_new:
    Delete "${AIVESTARTMENULINK}"
    RMDir "${AIVESTARTMENUDIR}"
  interrupted_start_recovered:
  RMDir /r "${AIVETXNBACKUPDIR}"
FunctionEnd

Function RepairStaleRc6Registration
  ReadRegStr $0 HKLM "${UNINSTKEY}" "DisplayName"
  ReadRegDWORD $3 HKLM "${AIVEPRODUCTKEY}" "InstallCommitted"
  StrCmp $0 "${PRODUCTNAME}" 0 stale_registration_check_product
  ReadRegStr $1 HKLM "${UNINSTKEY}" "InstallLocation"
  StrCmp $1 "$INSTDIR" 0 stale_registration
  StrCmp $3 1 0 stale_registration
  IfFileExists "$INSTDIR\desktop-v2.identity.json" 0 stale_registration
  IfFileExists "$INSTDIR\uninstall.exe" 0 stale_registration
  IfFileExists "$INSTDIR\${MAINBINARYNAME}.exe" stale_registration_done stale_registration
  stale_registration_check_product:
    StrCmp $3 1 stale_registration 0
    ReadRegStr $2 HKLM "${AIVEPRODUCTKEY}" "InstallPath"
    StrCmp $2 "" stale_registration_done stale_registration
  stale_registration:
    DetailPrint "Repairing stale or broken RC.6 Add/Remove Programs registration."
    DeleteRegKey HKLM "${UNINSTKEY}"
    DeleteRegKey HKLM "${MANUPRODUCTKEY}"
    DeleteRegKey HKLM "${AIVEPRODUCTKEY}"
  stale_registration_done:
FunctionEnd

Section WebView2
  ${If} ${RunningX64}
    ReadRegStr $4 HKLM "SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\${WEBVIEW2APPGUID}" "pv"
  ${Else}
    ReadRegStr $4 HKLM "SOFTWARE\Microsoft\EdgeUpdate\Clients\${WEBVIEW2APPGUID}" "pv"
  ${EndIf}
  ${If} $4 == ""
    ReadRegStr $4 HKCU "SOFTWARE\Microsoft\EdgeUpdate\Clients\${WEBVIEW2APPGUID}" "pv"
  ${EndIf}
  ${If} $4 == ""
  ${AndIf} $UpdateMode <> 1
    !if "${INSTALLWEBVIEW2MODE}" == "downloadBootstrapper"
      Delete "$TEMP\MicrosoftEdgeWebview2Setup.exe"
      NSISdl::download "https://go.microsoft.com/fwlink/p/?LinkId=2124703" "$TEMP\MicrosoftEdgeWebview2Setup.exe"
      Pop $0
      StrCmp $0 "success" 0 webview2_failed
      ExecWait '"$TEMP\MicrosoftEdgeWebview2Setup.exe" ${WEBVIEW2INSTALLERARGS} /install' $1
      StrCmp $1 0 webview2_done webview2_failed
    !endif
    !if "${INSTALLWEBVIEW2MODE}" == "embedBootstrapper"
      File "/oname=$TEMP\MicrosoftEdgeWebview2Setup.exe" "${WEBVIEW2BOOTSTRAPPERPATH}"
      ExecWait '"$TEMP\MicrosoftEdgeWebview2Setup.exe" ${WEBVIEW2INSTALLERARGS} /install' $1
      StrCmp $1 0 webview2_done webview2_failed
    !endif
    !if "${INSTALLWEBVIEW2MODE}" == "offlineInstaller"
      File "/oname=$TEMP\MicrosoftEdgeWebView2RuntimeInstaller.exe" "${WEBVIEW2INSTALLERPATH}"
      ExecWait '"$TEMP\MicrosoftEdgeWebView2RuntimeInstaller.exe" ${WEBVIEW2INSTALLERARGS} /install' $1
      StrCmp $1 0 webview2_done webview2_failed
    !endif
    Goto webview2_done
    webview2_failed:
      Delete "$TEMP\MicrosoftEdgeWebview2Setup.exe"
      Delete "$TEMP\MicrosoftEdgeWebView2RuntimeInstaller.exe"
      Abort "WebView2 installation failed before the RC.6 application transaction began."
    webview2_done:
  ${EndIf}
SectionEnd

Function BeginInstallTransaction
  Call SetCanonicalInstallDir
  !insertmacro CheckIfAppIsRunning "${MAINBINARYNAME}.exe" "${PRODUCTNAME}"
  ClearErrors
  CreateDirectory "${AIVETXNBACKUPDIR}"
  IfErrors 0 +2
    Abort "Could not prepare the bounded RC.6 rollback directory. No files were changed."
  IfFileExists "${AIVEDESKTOPLINK}" 0 desktop_shortcut_not_present
    ClearErrors
    CopyFiles /SILENT "${AIVEDESKTOPLINK}" "${AIVETXNBACKUPDIR}\Desktop.lnk"
    IfErrors pre_transaction_failed
    StrCpy $TxnHadDesktopShortcut 1
  desktop_shortcut_not_present:
  IfFileExists "${AIVESTARTMENULINK}" 0 start_shortcut_not_present
    ClearErrors
    CopyFiles /SILENT "${AIVESTARTMENULINK}" "${AIVETXNBACKUPDIR}\StartMenu.lnk"
    IfErrors pre_transaction_failed
    StrCpy $TxnHadStartMenuShortcut 1
  start_shortcut_not_present:
  ReadRegStr $0 HKLM "${UNINSTKEY}" "DisplayName"
  StrCmp $0 "" no_arp_backup 0
  StrCpy $TxnHadArp 1
  nsExec::ExecToStack /OEM '"$SYSDIR\reg.exe" copy "HKLM\${UNINSTKEY}" "HKLM\${AIVEROLLBACKKEY}\Arp" /s /f /reg:64'
  Pop $0
  Pop $1
  StrCmp $0 0 no_arp_backup
    Goto pre_transaction_failed
  no_arp_backup:
  ReadRegStr $0 HKLM "${MANUPRODUCTKEY}" ""
  StrCmp $0 "" no_product_backup 0
  StrCpy $TxnHadProductRegistration 1
  nsExec::ExecToStack /OEM '"$SYSDIR\reg.exe" copy "HKLM\${MANUPRODUCTKEY}" "HKLM\${AIVEROLLBACKKEY}\TauriProduct" /s /f /reg:64'
  Pop $0
  Pop $1
  StrCmp $0 0 no_product_backup
    Goto pre_transaction_failed
  no_product_backup:
  ReadRegStr $0 HKLM "${AIVEPRODUCTKEY}" "InstallPath"
  StrCmp $0 "" no_aive_product_backup 0
  StrCpy $TxnHadAiveProductRegistration 1
  nsExec::ExecToStack /OEM '"$SYSDIR\reg.exe" copy "HKLM\${AIVEPRODUCTKEY}" "HKLM\${AIVEROLLBACKKEY}\Product" /s /f /reg:64'
  Pop $0
  Pop $1
  StrCmp $0 0 no_aive_product_backup
    Goto pre_transaction_failed
  no_aive_product_backup:
  IfFileExists "$INSTDIR\." prior_shell no_prior_shell
  prior_shell:
    StrCpy $TxnHadPriorShell 1
    ClearErrors
    Rename "$INSTDIR" "${AIVEBACKUPDIR}"
    IfErrors 0 no_prior_shell
      Goto pre_transaction_failed
  no_prior_shell:
  ; Only now can failure rollback safely: registry backups are complete and an
  ; existing shell, if any, is protected outside the new payload directory.
  StrCpy $InstallStarted 1
  ClearErrors
  CreateDirectory "$INSTDIR"
  IfErrors 0 +2
    Abort "Could not create the canonical Program Files shell directory."
  FileOpen $0 "$INSTDIR\.installing" w
  IfErrors 0 +2
    Abort "Could not create the RC.6 transaction marker."
  FileWrite $0 "desktop-v2-rc6-installing$\r$\n"
  FileClose $0
  Goto transaction_begun
  pre_transaction_failed:
    DeleteRegKey HKLM "${AIVEROLLBACKKEY}"
    RMDir /r "${AIVETXNBACKUPDIR}"
    Abort "RC.6 could not protect the existing installation before update. No application payload was changed."
  transaction_begun:
FunctionEnd

Section Install
  Call BeginInstallTransaction

  !ifmacrodef NSIS_HOOK_PREINSTALL
    !insertmacro NSIS_HOOK_PREINSTALL
  !endif

  ClearErrors
  File "${MAINBINARYSRCPATH}"
  IfErrors 0 +2
    Abort "Failed to copy the RC.6 shell executable."

  {{#each resources_dirs}}
    CreateDirectory "$INSTDIR\\{{this}}"
  {{/each}}
  {{#each resources}}
    File /a "/oname={{this.[1]}}" "{{no-escape @key}}"
  {{/each}}
  {{#each binaries}}
    File /a "/oname={{this}}" "{{no-escape @key}}"
  {{/each}}
  IfErrors 0 +2
    Abort "Failed to copy an RC.6 resource or sidecar binary."

  ClearErrors
  WriteUninstaller "$INSTDIR\uninstall.exe"
  IfErrors 0 +2
    Abort "Failed to create the RC.6 uninstaller."
  IfFileExists "$INSTDIR\uninstall.exe" uninstaller_ready 0
    Abort "The RC.6 uninstaller could not be verified after creation."
  uninstaller_ready:

  Call CreateAndVerifyRequiredShortcuts

  !ifmacrodef NSIS_HOOK_POSTINSTALL
    !insertmacro NSIS_HOOK_POSTINSTALL
  !endif

  Call CommitInstallRegistration

  ; The committed marker is deliberately last. Stale ARP with no marker is
  ; repaired on the next run; every earlier Abort is rolled back.
  FileOpen $0 "$INSTDIR\desktop-v2.identity.json" w
  IfErrors 0 +2
    Abort "Failed to write the RC.6 committed identity marker."
  FileWrite $0 '{"productName":"AI Video Editor Desktop V2","identifier":"com.fyp.ai-video-editor.desktop-v2","version":"2.0.0-rc.6","channel":"beta","installCommitted":true}'
  FileClose $0
  Delete "$INSTDIR\.installing"
  StrCpy $InstallCommitted 1
  DeleteRegKey HKLM "${AIVEROLLBACKKEY}"
  Delete "$PROGRAMDATA\AI Video Editor\Installer\handoff-root.json.rc6-rollback"
  RMDir /r "${AIVETXNBACKUPDIR}"
  RMDir /r /REBOOTOK "${AIVEBACKUPDIR}"
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\AI Video Editor"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AI Video Editor"

  ${If} $PassiveMode = 1
    SetAutoClose true
  ${EndIf}
SectionEnd

Function CreateAndVerifyRequiredShortcuts
  ClearErrors
  CreateDirectory "${AIVESTARTMENUDIR}"
  CreateShortcut "${AIVESTARTMENULINK}" "$INSTDIR\${MAINBINARYNAME}.exe"
  CreateShortcut "${AIVEDESKTOPLINK}" "$INSTDIR\${MAINBINARYNAME}.exe"
  IfErrors 0 +2
    Abort "Failed to create the required RC.6 shortcuts."
  !insertmacro SetLnkAppUserModelId "${AIVESTARTMENULINK}"
  !insertmacro SetLnkAppUserModelId "${AIVEDESKTOPLINK}"
  !insertmacro IsShortcutTarget "${AIVESTARTMENULINK}" "$INSTDIR\${MAINBINARYNAME}.exe"
  Pop $0
  StrCmp $0 1 0 shortcut_verification_failed
  !insertmacro IsShortcutTarget "${AIVEDESKTOPLINK}" "$INSTDIR\${MAINBINARYNAME}.exe"
  Pop $0
  StrCmp $0 1 shortcut_verification_done shortcut_verification_failed
  shortcut_verification_failed:
    Abort "A required RC.6 shortcut did not target the canonical shell."
  shortcut_verification_done:
FunctionEnd

Function CommitInstallRegistration
  ClearErrors
  WriteRegStr HKLM "${MANUPRODUCTKEY}" "" "$INSTDIR"
  WriteRegStr HKLM "${UNINSTKEY}" "DisplayName" "${PRODUCTNAME}"
  WriteRegStr HKLM "${UNINSTKEY}" "DisplayIcon" '$"$INSTDIR\${MAINBINARYNAME}.exe$"'
  WriteRegStr HKLM "${UNINSTKEY}" "DisplayVersion" "${VERSION}"
  WriteRegStr HKLM "${UNINSTKEY}" "Publisher" "${MANUFACTURER}"
  WriteRegStr HKLM "${UNINSTKEY}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKLM "${UNINSTKEY}" "UninstallString" '$"$INSTDIR\uninstall.exe$"'
  WriteRegStr HKLM "${UNINSTKEY}" "MainBinaryName" "${MAINBINARYNAME}.exe"
  WriteRegDWORD HKLM "${UNINSTKEY}" "NoModify" 1
  WriteRegDWORD HKLM "${UNINSTKEY}" "NoRepair" 1
  ${GetSize} "$INSTDIR" "/M=uninstall.exe /S=0K /G=0" $0 $1 $2
  IntOp $0 $0 + ${ESTIMATEDSIZE}
  IntFmt $0 "0x%08X" $0
  WriteRegDWORD HKLM "${UNINSTKEY}" "EstimatedSize" "$0"
  WriteRegStr HKLM "${AIVEPRODUCTKEY}" "Identifier" "com.fyp.ai-video-editor.desktop-v2"
  WriteRegStr HKLM "${AIVEPRODUCTKEY}" "InstallPath" "$INSTDIR"
  WriteRegDWORD HKLM "${AIVEPRODUCTKEY}" "InstallCommitted" 1
  IfErrors 0 +2
    Abort "Failed to commit the RC.6 Add/Remove Programs registration."
  ReadRegStr $1 HKLM "${UNINSTKEY}" "UninstallString"
  StrCmp $1 '$"$INSTDIR\uninstall.exe$"' 0 registration_verification_failed
  ReadRegStr $1 HKLM "${UNINSTKEY}" "DisplayVersion"
  StrCmp $1 "${VERSION}" registration_verification_done registration_verification_failed
  registration_verification_failed:
    Abort "RC.6 Add/Remove Programs registration verification failed."
  registration_verification_done:
FunctionEnd

Function RemoveCurrentShellPayload
  Delete /REBOOTOK "$INSTDIR\desktop-v2.identity.json"
  Delete /REBOOTOK "$INSTDIR\component-broker.json"
  Delete /REBOOTOK "$INSTDIR\.installing"
  Delete /REBOOTOK "$INSTDIR\${MAINBINARYNAME}.exe"
  Delete /REBOOTOK "$INSTDIR\uninstall.exe"
  {{#each resources}}
    Delete /REBOOTOK "$INSTDIR\\{{this.[1]}}"
  {{/each}}
  {{#each binaries}}
    Delete /REBOOTOK "$INSTDIR\\{{this}}"
  {{/each}}
  {{#each resources_ancestors}}
    RMDir /REBOOTOK "$INSTDIR\\{{this}}"
  {{/each}}
  RMDir /REBOOTOK "$INSTDIR"
FunctionEnd

Function RollbackInstallTransaction
  DetailPrint "Rolling back the bounded RC.6 install transaction."
  Call RemoveCurrentShellPayload
  ${If} $TxnHadPriorShell = 1
    ClearErrors
    Rename "${AIVEBACKUPDIR}" "$INSTDIR"
    IfErrors 0 +3
      DetailPrint "Previous shell restore is deferred; restart Windows and rerun Setup."
      SetRebootFlag true
  ${Else}
    RMDir /REBOOTOK "${AIVEINSTALLERPARENT}"
  ${EndIf}
  Call RecoverInterruptedShortcuts
  ${If} $TxnWroteInstallerOrigin = 1
    Delete "$PROGRAMDATA\AI Video Editor\Installer\handoff-root.json"
    ${If} $TxnHadInstallerOrigin = 1
      Rename "$PROGRAMDATA\AI Video Editor\Installer\handoff-root.json.rc6-rollback" "$PROGRAMDATA\AI Video Editor\Installer\handoff-root.json"
    ${EndIf}
  ${EndIf}
  Delete "$PROGRAMDATA\AI Video Editor\Installer\handoff-root.json.part"
  Delete "$PROGRAMDATA\AI Video Editor\Installer\handoff-root.json.rc6-rollback"
  DeleteRegKey HKLM "${UNINSTKEY}"
  ${If} $TxnHadArp = 1
    nsExec::ExecToStack /OEM '"$SYSDIR\reg.exe" copy "HKLM\${AIVEROLLBACKKEY}\Arp" "HKLM\${UNINSTKEY}" /s /f /reg:64'
    Pop $0
    Pop $1
    StrCmp $0 0 +2
      DetailPrint "WARNING: RC.6 could not restore the prior ARP registration (reg.exe exit $0)."
  ${EndIf}
  DeleteRegKey HKLM "${MANUPRODUCTKEY}"
  ${If} $TxnHadProductRegistration = 1
    nsExec::ExecToStack /OEM '"$SYSDIR\reg.exe" copy "HKLM\${AIVEROLLBACKKEY}\TauriProduct" "HKLM\${MANUPRODUCTKEY}" /s /f /reg:64'
    Pop $0
    Pop $1
    StrCmp $0 0 +2
      DetailPrint "WARNING: RC.6 could not restore the prior Tauri product registration (reg.exe exit $0)."
  ${EndIf}
  DeleteRegKey HKLM "${AIVEPRODUCTKEY}"
  ${If} $TxnHadAiveProductRegistration = 1
    nsExec::ExecToStack /OEM '"$SYSDIR\reg.exe" copy "HKLM\${AIVEROLLBACKKEY}\Product" "HKLM\${AIVEPRODUCTKEY}" /s /f /reg:64'
    Pop $0
    Pop $1
    StrCmp $0 0 +2
      DetailPrint "WARNING: RC.6 could not restore the prior committed product marker (reg.exe exit $0)."
  ${EndIf}
  DeleteRegKey HKLM "${AIVEROLLBACKKEY}"

  ${If} $TxnCreatedRequests = 1
    RMDir "$PROGRAMDATA\AI Video Editor\Broker\Requests"
  ${EndIf}
  ${If} $TxnCreatedBroker = 1
    RMDir "$PROGRAMDATA\AI Video Editor\Broker"
  ${EndIf}
  ${If} $TxnCreatedCatalog = 1
    RMDir "$PROGRAMDATA\AI Video Editor\Catalog"
  ${EndIf}
  ${If} $TxnCreatedStaging = 1
    RMDir "$PROGRAMDATA\AI Video Editor\Downloads\Staging"
  ${EndIf}
  ${If} $TxnCreatedDownloads = 1
    RMDir "$PROGRAMDATA\AI Video Editor\Downloads"
  ${EndIf}
  ${If} $TxnCreatedComponents = 1
    RMDir "$PROGRAMDATA\AI Video Editor\Components"
  ${EndIf}
  ${If} $TxnCreatedActivation = 1
    RMDir "$PROGRAMDATA\AI Video Editor\Activation"
  ${EndIf}
  ${If} $TxnCreatedProvisioning = 1
    RMDir "$PROGRAMDATA\AI Video Editor\Provisioning"
  ${EndIf}
  ${If} $TxnCreatedInstaller = 1
    RMDir "$PROGRAMDATA\AI Video Editor\Installer"
  ${EndIf}
  ${If} $TxnCreatedMachineRoot = 1
    RMDir "$PROGRAMDATA\AI Video Editor"
  ${EndIf}
FunctionEnd

Function .onInstFailed
  Delete "$TEMP\MicrosoftEdgeWebview2Setup.exe"
  Delete "$TEMP\MicrosoftEdgeWebView2RuntimeInstaller.exe"
  ${If} $InstallStarted = 1
  ${AndIf} $InstallCommitted = 0
    Call RollbackInstallTransaction
  ${EndIf}
FunctionEnd

Function .onInstSuccess
  ${If} $InstallCommitted <> 1
    MessageBox MB_ICONSTOP|MB_OK "RC.6 Setup ended without a committed identity marker. Run Setup again to repair."
    SetErrorLevel 5
    Return
  ${EndIf}
  ${If} $PassiveMode = 1
  ${OrIf} ${Silent}
    ${GetOptions} $CMDLINE "/R" $R0
    ${IfNot} ${Errors}
      nsis_tauri_utils::RunAsUser "$INSTDIR\${MAINBINARYNAME}.exe" ""
    ${EndIf}
  ${EndIf}
FunctionEnd

Function RunMainBinary
  nsis_tauri_utils::RunAsUser "$INSTDIR\${MAINBINARYNAME}.exe" ""
FunctionEnd

Function un.onInit
  !insertmacro SetContext
  SetRegView 64
  StrCpy $INSTDIR "${AIVEINSTALLDIR}"
  StrCpy $FullWipeCheckboxState 0
  !insertmacro MUI_UNGETLANGUAGE
  ${GetOptions} $CMDLINE "/P" $PassiveMode
  ${IfNot} ${Errors}
    StrCpy $PassiveMode 1
  ${EndIf}
  ${GetOptions} $CMDLINE "/UPDATE" $UpdateMode
  ${IfNot} ${Errors}
    StrCpy $UpdateMode 1
  ${EndIf}
  ${GetOptions} $CMDLINE "/FULLWIPE=" $0
  ${IfNot} ${Errors}
    StrCmp $0 "${AIVEFULLWIPETOKEN}" 0 +2
      StrCpy $FullWipeCheckboxState 1
  ${EndIf}
FunctionEnd

Section Uninstall
  !ifmacrodef NSIS_HOOK_PREUNINSTALL
    !insertmacro NSIS_HOOK_PREUNINSTALL
  !endif
  !insertmacro CheckIfAppIsRunning "${MAINBINARYNAME}.exe" "${PRODUCTNAME}"

  Delete /REBOOTOK "$INSTDIR\${MAINBINARYNAME}.exe"
  Delete /REBOOTOK "$INSTDIR\uninstall.exe"
  Delete /REBOOTOK "$INSTDIR\desktop-v2.identity.json"
  Delete /REBOOTOK "$INSTDIR\component-broker.json"
  {{#each resources}}
    Delete /REBOOTOK "$INSTDIR\\{{this.[1]}}"
  {{/each}}
  {{#each binaries}}
    Delete /REBOOTOK "$INSTDIR\\{{this}}"
  {{/each}}
  {{#each resources_ancestors}}
    RMDir /REBOOTOK "$INSTDIR\\{{this}}"
  {{/each}}
  RMDir /REBOOTOK "$INSTDIR"

  Delete "${AIVESTARTMENULINK}"
  RMDir "${AIVESTARTMENUDIR}"
  Delete "${AIVEDESKTOPLINK}"
  DeleteRegKey HKLM "${UNINSTKEY}"
  DeleteRegKey HKLM "${MANUPRODUCTKEY}"
  DeleteRegKey HKLM "${AIVEPRODUCTKEY}"
  DeleteRegKey HKLM "${AIVEROLLBACKKEY}"

  !ifmacrodef NSIS_HOOK_POSTUNINSTALL
    !insertmacro NSIS_HOOK_POSTUNINSTALL
  !endif

  ; Report locked Program Files leftovers and remove the parent only when empty.
  IfFileExists "$INSTDIR\*.*" program_files_leftover shell_empty
  program_files_leftover:
    DetailPrint "RC.6 Program Files cleanup is deferred until restart: $INSTDIR"
    SetRebootFlag true
    Goto program_files_report_done
  shell_empty:
    RMDir /REBOOTOK "$INSTDIR"
    RMDir /REBOOTOK "${AIVEINSTALLERPARENT}"
    IfFileExists "${AIVEINSTALLERPARENT}\*.*" 0 program_files_report_done
      DetailPrint "The Program Files product parent is not empty and was preserved: ${AIVEINSTALLERPARENT}"
  program_files_report_done:

  ${If} $PassiveMode = 1
  ${OrIf} $UpdateMode = 1
    SetAutoClose true
  ${EndIf}
SectionEnd

Function SkipIfPassive
  ${IfThen} $PassiveMode = 1 ${|} Abort ${|}
FunctionEnd
Function un.SkipIfPassive
  ${IfThen} $PassiveMode = 1 ${|} Abort ${|}
FunctionEnd
