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
!define AIVESTAGINGDIR "${AIVEINSTALLERPARENT}\Shell.rc6-staging"
!define AIVETXNBACKUPDIR "${AIVEINSTALLERPARENT}\.rc6-installer-rollback"
!define AIVEINSTALLERDIR "$PROGRAMDATA\AI Video Editor\Installer"
!define AIVESETUPLOG "${AIVEINSTALLERDIR}\setup-rc6.log"
!define AIVEJOURNAL "${AIVEINSTALLERDIR}\transaction-rc6.json"
!define AIVEUNINSTALLJOURNAL "${AIVEINSTALLERDIR}\uninstall-transaction-rc6.json"
!define AIVEIDENTITY "desktop-v2.identity.json"
!define AIVEIDENTIFIER "com.fyp.ai-video-editor.desktop-v2"
!define AIVEPACKAGEID "rc6-sep4-installer-recovery-v1"
!define AIVESTARTMENUDIR "$SMPROGRAMS\AI Video Editor Desktop V2"
!define AIVESTARTMENULINK "${AIVESTARTMENUDIR}\AI Video Editor Desktop V2.lnk"
!define AIVEDESKTOPLINK "$DESKTOP\AI Video Editor Desktop V2.lnk"
!define AIVEFULLWIPETOKEN "REMOVE_ALL_AI_VIDEO_EDITOR_USER_DATA"
!define AIVE_E_SNAPSHOT 2101
!define AIVE_E_REGISTRY 2102
!define AIVE_E_SHORTCUT 2103
!define AIVE_E_RENAME 2104
!define AIVE_E_LOCK 2105
!define AIVE_E_ACTIVATION 2106
!define AIVE_E_HANDOFF 2107
!define AIVE_E_REGISTRATION 2108
!define AIVE_E_IDENTITY 2109
!define AIVE_E_ROLLBACK 2110
!define AIVE_E_INVARIANT 2111
!define AIVE_E_CONFLICT 2112
!define AIVE_E_CONCURRENT 2113

Var PassiveMode
Var UpdateMode
Var InstallStarted
Var InstallCommitted
Var InstallState
Var FailureCode
Var FailureStage
Var FailureMessage
Var RollbackIncomplete
Var MutexHandle
Var DeferredCleanup
Var TxnId
Var TxnPhase
Var JournalOk
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
Var UninstallTombstone

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
    SetErrorLevel ${AIVE_E_INVARIANT}
    MessageBox MB_ICONSTOP|MB_OK "AI Video Editor Desktop V2 RC.6 requires 64-bit Windows."
    Abort
  ${EndIf}
  StrCpy $INSTDIR "${AIVEINSTALLDIR}"
FunctionEnd

; Never select the canonical or backup directory as NSIS's current/output
; directory while either path may be renamed or removed.
Function SetSafeWorkingDir
  InitPluginsDir
  SetOutPath "$PLUGINSDIR"
FunctionEnd

Function ValidateInstallerPerimeter
  ReadEnvStr $0 "ProgramData"
  StrCmp $0 "" installer_perimeter_failed
  StrCpy $3 "$0"
  Call IsReparsePoint
  StrCmp $1 1 installer_perimeter_failed
  StrCpy $0 "$3"
  StrCpy $1 "$0\AI Video Editor"
  StrCpy $2 "$1\Installer"
  IfFileExists "$1\." 0 installer_check_directory
    StrCpy $0 "$1"
    Call IsReparsePoint
    StrCmp $1 1 installer_perimeter_failed
  installer_check_directory:
  IfFileExists "$2\." 0 installer_create_directory
    StrCpy $0 "$2"
    Call IsReparsePoint
    StrCmp $1 1 installer_perimeter_failed
  installer_create_directory:
  ClearErrors
  CreateDirectory "$2"
  IfErrors installer_perimeter_failed
  StrCpy $0 "$2"
  Call IsReparsePoint
  StrCmp $1 1 installer_perimeter_failed
  nsExec::ExecToStack /OEM '"$SYSDIR\icacls.exe" "$2" /inheritance:r /grant:r "*S-1-5-18:(OI)(CI)(F)" "*S-1-5-32-544:(OI)(CI)(F)"'
  Pop $0
  Pop $1
  StrCmp $0 "0" installer_perimeter_valid
  installer_perimeter_failed:
    SetErrorLevel ${AIVE_E_CONFLICT}
    ${IfNot} ${Silent}
      MessageBox MB_ICONSTOP|MB_OK "Setup refused an unsafe or unavailable ProgramData installer perimeter. Reparse points were preserved."
    ${EndIf}
    Abort
  installer_perimeter_valid:
FunctionEnd

Function AppendSetupLog
  CreateDirectory "${AIVEINSTALLERDIR}"
  FileOpen $9 "${AIVESETUPLOG}" a
  IfErrors setup_log_done
  FileWrite $9 "stage=$FailureStage code=$FailureCode message=$FailureMessage$\r$\n"
  FileClose $9
  setup_log_done:
FunctionEnd

Function WriteTransactionJournal
  StrCpy $JournalOk 0
  CreateDirectory "${AIVEINSTALLERDIR}"
  StrCpy $TxnPhase "$FailureStage"
  ${If} $InstallStarted = 1
    ClearErrors
    DeleteRegValue HKLM "${AIVEROLLBACKKEY}" "Phase"
    WriteRegStr HKLM "${AIVEROLLBACKKEY}" "TransactionId" "$TxnId"
    WriteRegStr HKLM "${AIVEROLLBACKKEY}" "ExpectedVersion" "${VERSION}"
    WriteRegStr HKLM "${AIVEROLLBACKKEY}" "PackageIdentity" "${AIVEPACKAGEID}"
    WriteRegStr HKLM "${AIVEROLLBACKKEY}" "CanonicalPath" "${AIVEINSTALLDIR}"
    WriteRegStr HKLM "${AIVEROLLBACKKEY}" "StagingPath" "${AIVESTAGINGDIR}"
    WriteRegStr HKLM "${AIVEROLLBACKKEY}" "BackupPath" "${AIVEBACKUPDIR}"
    WriteRegDWORD HKLM "${AIVEROLLBACKKEY}" "HadArp" $TxnHadArp
    WriteRegDWORD HKLM "${AIVEROLLBACKKEY}" "HadTauriProduct" $TxnHadProductRegistration
    WriteRegDWORD HKLM "${AIVEROLLBACKKEY}" "HadProduct" $TxnHadAiveProductRegistration
    WriteRegDWORD HKLM "${AIVEROLLBACKKEY}" "HadPriorShell" $TxnHadPriorShell
    WriteRegDWORD HKLM "${AIVEROLLBACKKEY}" "HadDesktopShortcut" $TxnHadDesktopShortcut
    WriteRegDWORD HKLM "${AIVEROLLBACKKEY}" "HadStartMenuShortcut" $TxnHadStartMenuShortcut
    WriteRegDWORD HKLM "${AIVEROLLBACKKEY}" "HadInstallerOrigin" $TxnHadInstallerOrigin
    WriteRegDWORD HKLM "${AIVEROLLBACKKEY}" "WroteInstallerOrigin" $TxnWroteInstallerOrigin
    WriteRegDWORD HKLM "${AIVEROLLBACKKEY}" "CreatedMachineRoot" $TxnCreatedMachineRoot
    WriteRegDWORD HKLM "${AIVEROLLBACKKEY}" "CreatedComponents" $TxnCreatedComponents
    WriteRegDWORD HKLM "${AIVEROLLBACKKEY}" "CreatedActivation" $TxnCreatedActivation
    WriteRegDWORD HKLM "${AIVEROLLBACKKEY}" "CreatedDownloads" $TxnCreatedDownloads
    WriteRegDWORD HKLM "${AIVEROLLBACKKEY}" "CreatedStaging" $TxnCreatedStaging
    WriteRegDWORD HKLM "${AIVEROLLBACKKEY}" "CreatedCatalog" $TxnCreatedCatalog
    WriteRegDWORD HKLM "${AIVEROLLBACKKEY}" "CreatedBroker" $TxnCreatedBroker
    WriteRegDWORD HKLM "${AIVEROLLBACKKEY}" "CreatedRequests" $TxnCreatedRequests
    WriteRegDWORD HKLM "${AIVEROLLBACKKEY}" "CreatedProvisioning" $TxnCreatedProvisioning
    WriteRegDWORD HKLM "${AIVEROLLBACKKEY}" "CreatedInstaller" $TxnCreatedInstaller
    WriteRegStr HKLM "${AIVEROLLBACKKEY}" "Phase" "$TxnPhase"
    IfErrors journal_write_failed
    ReadRegStr $4 HKLM "${AIVEROLLBACKKEY}" "TransactionId"
    ReadRegStr $5 HKLM "${AIVEROLLBACKKEY}" "ExpectedVersion"
    ReadRegStr $6 HKLM "${AIVEROLLBACKKEY}" "PackageIdentity"
    ReadRegStr $7 HKLM "${AIVEROLLBACKKEY}" "CanonicalPath"
    ReadRegStr $8 HKLM "${AIVEROLLBACKKEY}" "StagingPath"
    ReadRegStr $R0 HKLM "${AIVEROLLBACKKEY}" "BackupPath"
    ReadRegStr $R1 HKLM "${AIVEROLLBACKKEY}" "Phase"
    StrCmp $4 "$TxnId" 0 journal_write_failed
    StrCmp $5 "${VERSION}" 0 journal_write_failed
    StrCmp $6 "${AIVEPACKAGEID}" 0 journal_write_failed
    StrCmp $7 "${AIVEINSTALLDIR}" 0 journal_write_failed
    StrCmp $8 "${AIVESTAGINGDIR}" 0 journal_write_failed
    StrCmp $R0 "${AIVEBACKUPDIR}" 0 journal_write_failed
    StrCmp $R1 "$TxnPhase" 0 journal_write_failed
  ${EndIf}
  Delete "${AIVEJOURNAL}.part"
  ClearErrors
  FileOpen $9 "${AIVEJOURNAL}.part" w
  IfErrors journal_write_failed
  FileWrite $9 '{$\"schemaVersion$\":$\"desktop.installer-transaction.v1$\",$\"transactionId$\":$\"$TxnId$\",$\"phase$\":$\"$TxnPhase$\",$\"state$\":$\"$InstallState$\",$\"expectedVersion$\":$\"${VERSION}$\",$\"packageIdentity$\":$\"${AIVEPACKAGEID}$\",$\"canonicalPath$\":$\"%ProgramFiles%/AI Video Editor Desktop V2/Shell$\",$\"stagingPath$\":$\"%ProgramFiles%/AI Video Editor Desktop V2/Shell.rc6-staging$\",$\"backupPath$\":$\"%ProgramFiles%/AI Video Editor Desktop V2/Shell.rc6-rollback$\",$\"hadPriorShell$\":$TxnHadPriorShell,$\"hadDesktopShortcut$\":$TxnHadDesktopShortcut,$\"hadStartMenuShortcut$\":$TxnHadStartMenuShortcut,$\"hadInstallerOrigin$\":$TxnHadInstallerOrigin,$\"wroteInstallerOrigin$\":$TxnWroteInstallerOrigin,$\"code$\":$FailureCode}'
  FileClose $9
  IfErrors journal_write_failed
  System::Call 'kernel32::MoveFileExW(w "${AIVEJOURNAL}.part", w "${AIVEJOURNAL}", i 0x1) i .r8'
  StrCmp $8 0 journal_write_failed
  StrCpy $JournalOk 1
  Return
  journal_write_failed:
  SetErrorLevel ${AIVE_E_SNAPSHOT}
  ${IfNot} ${Silent}
    MessageBox MB_ICONSTOP|MB_OK "Setup stopped because its durable transaction journal could not be published and verified. No further mutation is allowed."
  ${EndIf}
  Abort
  journal_write_done:
FunctionEnd

Function FailInstall
  Call AppendSetupLog
  Call WriteTransactionJournal
  SetErrorLevel $FailureCode
  ${IfNot} ${Silent}
    MessageBox MB_ICONSTOP|MB_OK "$FailureMessage$\r$\n$\r$\nSetup code: $FailureCode ($FailureStage)$\r$\nLog: ${AIVESETUPLOG}"
  ${EndIf}
  Abort
FunctionEnd

Function AcquireInstallerMutex
  System::Call 'kernel32::CreateMutexW(p0, i0, w "Global\AI-Video-Editor-Desktop-V2-RC6-Setup") p .rMutexHandle ?e'
  Pop $0
  ${If} $MutexHandle = 0
    StrCpy $FailureCode ${AIVE_E_CONCURRENT}
    StrCpy $FailureStage "mutex"
    StrCpy $FailureMessage "Setup could not acquire its installation mutex."
    Call FailInstall
  ${EndIf}
  ${If} $0 = 183
    StrCpy $FailureCode ${AIVE_E_CONCURRENT}
    StrCpy $FailureStage "mutex"
    StrCpy $FailureMessage "Another setup or uninstall is already running. Wait for it to finish, then retry."
    Call FailInstall
  ${EndIf}
FunctionEnd

Function RejectProductionTestOverrides
  ${GetOptions} $CMDLINE "/AIVE_TEST_ROOT=" $0
  ${IfNot} ${Errors}
    StrCpy $FailureCode ${AIVE_E_INVARIANT}
    StrCpy $FailureStage "invariant"
    StrCpy $FailureMessage "Production Setup rejects test-root overrides."
    Call FailInstall
  ${EndIf}
  ${GetOptions} $CMDLINE "/AIVE_FAULT_PHASE=" $0
  ${IfNot} ${Errors}
    StrCpy $FailureCode ${AIVE_E_INVARIANT}
    StrCpy $FailureStage "invariant"
    StrCpy $FailureMessage "Production Setup rejects fault-injection overrides."
    Call FailInstall
  ${EndIf}
FunctionEnd

; $0=input path, $1=1 only when the directory is exactly empty.
Function IsDirectoryEmpty
  StrCpy $1 1
  FindFirst $2 $3 "$0\*"
  IfErrors directory_empty_done
  directory_empty_loop:
    StrCmp $3 "." directory_empty_next
    StrCmp $3 ".." directory_empty_next
    StrCpy $1 0
    Goto directory_empty_close
  directory_empty_next:
    ClearErrors
    FindNext $2 $3
    IfErrors directory_empty_close directory_empty_loop
  directory_empty_close:
    FindClose $2
  directory_empty_done:
FunctionEnd

; $0=input path, $1=1 when it is a reparse point.
Function IsReparsePoint
  StrCpy $1 0
  System::Call 'kernel32::GetFileAttributesW(w r0) i .r2'
  IntCmp $2 -1 reparse_done
  IntOp $2 $2 & 0x400
  StrCmp $2 0 reparse_done
  StrCpy $1 1
  reparse_done:
FunctionEnd

Function ValidateCanonicalParent
  IfFileExists "${AIVEINSTALLERPARENT}\." 0 canonical_parent_valid
  StrCpy $0 "${AIVEINSTALLERPARENT}"
  Call IsReparsePoint
  StrCmp $1 0 canonical_parent_valid
    StrCpy $FailureCode ${AIVE_E_CONFLICT}
    StrCpy $FailureStage "parent-conflict"
    StrCpy $FailureMessage "The canonical Program Files product parent is a reparse point and was preserved."
    Call FailInstall
  canonical_parent_valid:
FunctionEnd

; A payload is genuine only when all three owned identity files exist.
; $0=input directory, $1=1 when the payload is coherent.
Function HasCoherentPayload
  StrCpy $1 0
  IfFileExists "$0\${AIVEIDENTITY}" 0 coherent_payload_done
  IfFileExists "$0\${MAINBINARYNAME}.exe" 0 coherent_payload_done
  IfFileExists "$0\uninstall.exe" 0 coherent_payload_done
  FileOpen $2 "$0\${AIVEIDENTITY}" r
  IfErrors coherent_payload_done
  FileRead $2 $3
  FileClose $2
  StrCmp $3 '{"schemaVersion":"desktop.install-identity.v1","productName":"AI Video Editor Desktop V2","identifier":"${AIVEIDENTIFIER}","packageIdentity":"${AIVEPACKAGEID}","version":"${VERSION}","channel":"beta","canonicalPath":"%ProgramFiles%/AI Video Editor Desktop V2/Shell","installCommitted":true}' coherent_payload_valid
  ; Exact legacy RC.6 identity emitted by the predecessor this recovery build
  ; upgrades. No other filename-only or arbitrary JSON identity is accepted.
  StrCmp $3 '{"productName":"AI Video Editor Desktop V2","identifier":"com.fyp.ai-video-editor.desktop-v2","version":"2.0.0-rc.6","channel":"beta","installCommitted":true}' 0 coherent_payload_done
  coherent_payload_valid:
  StrCpy $1 1
  coherent_payload_done:
FunctionEnd

Function LoadTransactionState
  ReadRegStr $TxnPhase HKLM "${AIVEROLLBACKKEY}" "Phase"
  StrCmp $TxnPhase "" load_transaction_done
  ReadRegStr $TxnId HKLM "${AIVEROLLBACKKEY}" "TransactionId"
  ReadRegStr $4 HKLM "${AIVEROLLBACKKEY}" "ExpectedVersion"
  ReadRegStr $5 HKLM "${AIVEROLLBACKKEY}" "PackageIdentity"
  ReadRegStr $6 HKLM "${AIVEROLLBACKKEY}" "CanonicalPath"
  ReadRegStr $7 HKLM "${AIVEROLLBACKKEY}" "StagingPath"
  ReadRegStr $8 HKLM "${AIVEROLLBACKKEY}" "BackupPath"
  StrCmp $TxnId "" load_transaction_invalid
  StrCmp $4 "${VERSION}" 0 load_transaction_invalid
  StrCmp $5 "${AIVEPACKAGEID}" 0 load_transaction_invalid
  StrCmp $6 "${AIVEINSTALLDIR}" 0 load_transaction_invalid
  StrCmp $7 "${AIVESTAGINGDIR}" 0 load_transaction_invalid
  StrCmp $8 "${AIVEBACKUPDIR}" 0 load_transaction_invalid
  ReadRegStr $UninstallTombstone HKLM "${AIVEROLLBACKKEY}" "UninstallTombstone"
  StrCpy $InstallStarted 1
  ReadRegDWORD $TxnHadArp HKLM "${AIVEROLLBACKKEY}" "HadArp"
  ReadRegDWORD $TxnHadProductRegistration HKLM "${AIVEROLLBACKKEY}" "HadTauriProduct"
  ReadRegDWORD $TxnHadAiveProductRegistration HKLM "${AIVEROLLBACKKEY}" "HadProduct"
  ReadRegDWORD $TxnHadPriorShell HKLM "${AIVEROLLBACKKEY}" "HadPriorShell"
  ReadRegDWORD $TxnHadDesktopShortcut HKLM "${AIVEROLLBACKKEY}" "HadDesktopShortcut"
  ReadRegDWORD $TxnHadStartMenuShortcut HKLM "${AIVEROLLBACKKEY}" "HadStartMenuShortcut"
  ReadRegDWORD $TxnHadInstallerOrigin HKLM "${AIVEROLLBACKKEY}" "HadInstallerOrigin"
  ReadRegDWORD $TxnWroteInstallerOrigin HKLM "${AIVEROLLBACKKEY}" "WroteInstallerOrigin"
  ReadRegDWORD $TxnCreatedMachineRoot HKLM "${AIVEROLLBACKKEY}" "CreatedMachineRoot"
  ReadRegDWORD $TxnCreatedComponents HKLM "${AIVEROLLBACKKEY}" "CreatedComponents"
  ReadRegDWORD $TxnCreatedActivation HKLM "${AIVEROLLBACKKEY}" "CreatedActivation"
  ReadRegDWORD $TxnCreatedDownloads HKLM "${AIVEROLLBACKKEY}" "CreatedDownloads"
  ReadRegDWORD $TxnCreatedStaging HKLM "${AIVEROLLBACKKEY}" "CreatedStaging"
  ReadRegDWORD $TxnCreatedCatalog HKLM "${AIVEROLLBACKKEY}" "CreatedCatalog"
  ReadRegDWORD $TxnCreatedBroker HKLM "${AIVEROLLBACKKEY}" "CreatedBroker"
  ReadRegDWORD $TxnCreatedRequests HKLM "${AIVEROLLBACKKEY}" "CreatedRequests"
  ReadRegDWORD $TxnCreatedProvisioning HKLM "${AIVEROLLBACKKEY}" "CreatedProvisioning"
  ReadRegDWORD $TxnCreatedInstaller HKLM "${AIVEROLLBACKKEY}" "CreatedInstaller"
  Goto load_transaction_done
  load_transaction_invalid:
    StrCpy $TxnPhase "invalid"
  load_transaction_done:
FunctionEnd

Function ClassifyInstallState
  StrCpy $InstallState "pristine"
  IfFileExists "${AIVEINSTALLDIR}\." canonical_present classify_registration
  canonical_present:
    StrCpy $0 "${AIVEINSTALLDIR}"
    Call IsReparsePoint
    StrCmp $1 1 classify_conflict
    StrCpy $0 "${AIVEINSTALLDIR}"
    Call IsDirectoryEmpty
    StrCmp $1 1 classify_empty_residue
    StrCpy $0 "${AIVEINSTALLDIR}"
    Call HasCoherentPayload
    StrCmp $1 1 classify_payload classify_conflict
  classify_empty_residue:
    StrCpy $InstallState "empty-owned-residue"
    Goto classify_done
  classify_payload:
    ReadRegDWORD $2 HKLM "${AIVEPRODUCTKEY}" "InstallCommitted"
    ReadRegStr $3 HKLM "${AIVEPRODUCTKEY}" "InstallPath"
    ReadRegStr $4 HKLM "${UNINSTKEY}" "DisplayName"
    ReadRegStr $5 HKLM "${UNINSTKEY}" "InstallLocation"
    ReadRegStr $6 HKLM "${UNINSTKEY}" "UninstallString"
    ReadRegStr $7 HKLM "${AIVEPRODUCTKEY}" "PackageIdentity"
    StrCmp $2 1 0 classify_repairable
    StrCmp $3 "${AIVEINSTALLDIR}" 0 classify_repairable
    StrCmp $4 "${PRODUCTNAME}" 0 classify_repairable
    StrCmp $5 "${AIVEINSTALLDIR}" 0 classify_repairable
    StrCmp $6 '$"${AIVEINSTALLDIR}\uninstall.exe$"' 0 classify_repairable
    StrCmp $7 "${AIVEPACKAGEID}" 0 classify_repairable
    StrCpy $InstallState "valid-committed"
    Goto classify_done
  classify_repairable:
    StrCpy $InstallState "repairable-registration"
    Goto classify_done
  classify_registration:
    ReadRegDWORD $2 HKLM "${AIVEPRODUCTKEY}" "InstallCommitted"
    ReadRegStr $3 HKLM "${AIVEPRODUCTKEY}" "InstallPath"
    ReadRegStr $4 HKLM "${UNINSTKEY}" "DisplayName"
    StrCmp $2 1 classify_orphan_registration
    StrCmp $3 "" 0 classify_orphan_registration
    StrCmp $4 "" 0 classify_orphan_registration
    Goto classify_done
  classify_orphan_registration:
    StrCpy $InstallState "orphan-registration"
    Goto classify_done
  classify_conflict:
    StrCpy $InstallState "unknown-nonempty-or-reparse"
  classify_done:
FunctionEnd

Function .onInit
  StrCpy $InstallStarted 0
  StrCpy $InstallCommitted 0
  StrCpy $TxnId ""
  StrCpy $TxnPhase ""
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
  StrCpy $RollbackIncomplete 0
  StrCpy $DeferredCleanup 0
  StrCpy $FailureCode 0
  StrCpy $FailureStage "initialization"
  StrCpy $FailureMessage "initializing"
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
  Call SetSafeWorkingDir
  Call ValidateInstallerPerimeter
  Call RejectProductionTestOverrides
  Call AcquireInstallerMutex
  Call ValidateCanonicalParent
  Call ClassifyInstallState
  Call RecoverInterruptedInstall
  Call ClassifyInstallState
  Call ResolveClassifiedInstallState
FunctionEnd

Function RecoverInterruptedInstall
  Call LoadTransactionState
  StrCmp $TxnPhase "invalid" recovery_invalid_record
  StrCmp $TxnPhase "uninstall-rename-intent" recovery_uninstall
  StrCmp $TxnPhase "uninstall-cleanup" recovery_uninstall
  ; A durable committed phase (or the final committed registry marker if the
  ; process stopped between those two writes) means retain the new external
  ; state and clean only prior-version recovery material.
  StrCmp $TxnPhase "committed" recovery_committed
  StrCmp $TxnPhase "cleanup-pending" recovery_committed
  ReadRegDWORD $6 HKLM "${AIVEPRODUCTKEY}" "InstallCommitted"
  ReadRegStr $7 HKLM "${AIVEPRODUCTKEY}" "PackageIdentity"
  StrCmp $6 1 0 recovery_check_snapshot_phase
  StrCmp $7 "${AIVEPACKAGEID}" 0 recovery_check_snapshot_phase
  StrCpy $0 "${AIVEINSTALLDIR}"
  Call HasCoherentPayload
  StrCmp $1 1 recovery_committed recovery_check_snapshot_phase
  recovery_check_snapshot_phase:
  ; Snapshotting never changes live/external state. A crash here abandons only
  ; exact transaction-owned copies, so a subsequent run starts cleanly.
  StrCmp $TxnPhase "snapshotting" recovery_abandon_snapshot
  StrCmp $TxnPhase "prepared" 0 recovery_infer_paths
    IfFileExists "${AIVESTAGINGDIR}\." recovery_infer_paths 0
    IfFileExists "${AIVEBACKUPDIR}\." recovery_infer_paths recovery_abandon_snapshot
  recovery_abandon_snapshot:
    Delete "${AIVETXNBACKUPDIR}\Desktop.lnk"
    Delete "${AIVETXNBACKUPDIR}\StartMenu.lnk"
    Call SetSafeWorkingDir
    RMDir "${AIVETXNBACKUPDIR}"
    DeleteRegKey HKLM "${AIVEROLLBACKKEY}"
    Delete "${AIVEJOURNAL}"
    StrCpy $InstallStarted 0
    Goto recovery_done
  recovery_uninstall:
    StrLen $0 "${AIVEINSTALLERPARENT}\Shell.rc6-uninstall-"
    StrCpy $1 "$UninstallTombstone" $0
    StrCmp $1 "${AIVEINSTALLERPARENT}\Shell.rc6-uninstall-" 0 recovery_invalid_record
    IfFileExists "${AIVEINSTALLDIR}\." 0 recovery_uninstall_no_live
      IfFileExists "$UninstallTombstone\." recovery_uninstall_conflict 0
      ; The intent was durable but the atomic rename never occurred.
      DeleteRegKey HKLM "${AIVEROLLBACKKEY}"
      Delete "${AIVEUNINSTALLJOURNAL}"
      StrCpy $InstallStarted 0
      Goto recovery_done
  recovery_uninstall_no_live:
    IfFileExists "$UninstallTombstone\." 0 recovery_uninstall_external
      StrCpy $0 "$UninstallTombstone"
      Call IsReparsePoint
      StrCmp $1 1 recovery_uninstall_conflict
      StrCpy $INSTDIR "$UninstallTombstone"
      Call RemoveCurrentShellPayload
      IfFileExists "$UninstallTombstone\." recovery_cleanup_locked 0
  recovery_uninstall_external:
    !insertmacro IsShortcutTarget "${AIVESTARTMENULINK}" "${AIVEINSTALLDIR}\${MAINBINARYNAME}.exe"
    Pop $0
    StrCmp $0 1 0 +2
      Delete "${AIVESTARTMENULINK}"
    RMDir "${AIVESTARTMENUDIR}"
    !insertmacro IsShortcutTarget "${AIVEDESKTOPLINK}" "${AIVEINSTALLDIR}\${MAINBINARYNAME}.exe"
    Pop $0
    StrCmp $0 1 0 +2
      Delete "${AIVEDESKTOPLINK}"
    DeleteRegKey HKLM "${UNINSTKEY}"
    DeleteRegKey HKLM "${MANUPRODUCTKEY}"
    DeleteRegKey HKLM "${AIVEPRODUCTKEY}"
    DeleteRegKey HKLM "${AIVEROLLBACKKEY}"
    Delete "${AIVEUNINSTALLJOURNAL}"
    StrCpy $InstallStarted 0
    Goto recovery_done
  recovery_uninstall_conflict:
    StrCpy $FailureCode ${AIVE_E_CONFLICT}
    StrCpy $FailureStage "uninstall-recovery-conflict"
    StrCpy $FailureMessage "Interrupted uninstall state is ambiguous or reparse-backed. Both paths were preserved."
    Call FailInstall
  recovery_committed:
    IfFileExists "${AIVEBACKUPDIR}\." 0 recovery_committed_external
      StrCpy $0 "${AIVEBACKUPDIR}"
      Call IsReparsePoint
      StrCmp $1 1 recovery_unknown_backup
      StrCpy $INSTDIR "${AIVEBACKUPDIR}"
      Call RemoveCurrentShellPayload
      IfFileExists "${AIVEBACKUPDIR}\." recovery_cleanup_locked 0
  recovery_committed_external:
    Delete "$PROGRAMDATA\AI Video Editor\Installer\handoff-root.json.rc6-rollback"
    Delete "${AIVETXNBACKUPDIR}\Desktop.lnk"
    Delete "${AIVETXNBACKUPDIR}\StartMenu.lnk"
    Call SetSafeWorkingDir
    RMDir "${AIVETXNBACKUPDIR}"
    DeleteRegKey HKLM "${AIVEROLLBACKKEY}"
    Delete "${AIVEJOURNAL}"
    StrCpy $InstallStarted 0
    StrCpy $InstallCommitted 1
    Goto recovery_done
  recovery_infer_paths:
  ; A staging directory is owned only when it carries our transaction marker.
  IfFileExists "${AIVESTAGINGDIR}\." 0 recovery_check_backup
    StrCpy $0 "${AIVESTAGINGDIR}"
    Call IsReparsePoint
    StrCmp $1 1 recovery_unknown_staging
    IfFileExists "${AIVESTAGINGDIR}\.installing" 0 +2
      Goto recovery_remove_staging
    StrCmp $TxnPhase "" recovery_unknown_staging
  recovery_remove_staging:
    StrCpy $INSTDIR "${AIVESTAGINGDIR}"
    Call RemoveCurrentShellPayload
    IfFileExists "${AIVESTAGINGDIR}\." recovery_cleanup_locked 0
  recovery_check_backup:
  IfFileExists "${AIVEINSTALLDIR}\.installing" recovery_partial_live recovery_check_backup_path
  recovery_partial_live:
    StrCpy $0 "${AIVEINSTALLDIR}"
    Call IsReparsePoint
    StrCmp $1 1 recovery_unknown_canonical
    StrCpy $INSTDIR "${AIVEINSTALLDIR}"
    Call RemoveCurrentShellPayload
    IfFileExists "${AIVEINSTALLDIR}\." recovery_cleanup_locked 0
    IfFileExists "${AIVEBACKUPDIR}\." recovery_restore_backup recovery_repaired
  recovery_check_backup_path:
  IfFileExists "${AIVEBACKUPDIR}\." 0 recovery_no_backup
    StrCpy $0 "${AIVEBACKUPDIR}"
    Call IsReparsePoint
    StrCmp $1 1 recovery_unknown_backup
    StrCpy $0 "${AIVEBACKUPDIR}"
    Call HasCoherentPayload
    StrCmp $1 1 recovery_backup_owned recovery_unknown_backup
  recovery_no_backup:
    StrCmp $TxnPhase "" recovery_done recovery_repaired
  recovery_backup_owned:
    IfFileExists "${AIVEINSTALLDIR}\." recovery_canonical_and_backup recovery_restore_backup
  recovery_restore_backup:
    Call SetSafeWorkingDir
    ClearErrors
    Rename "${AIVEBACKUPDIR}" "${AIVEINSTALLDIR}"
    IfErrors recovery_restore_failed recovery_repaired
  recovery_canonical_and_backup:
    IfFileExists "${AIVEINSTALLDIR}\.installing" recovery_remove_partial 0
    StrCpy $0 "${AIVEINSTALLDIR}"
    Call IsDirectoryEmpty
    StrCmp $1 1 recovery_remove_empty_canonical
    StrCpy $0 "${AIVEINSTALLDIR}"
    Call HasCoherentPayload
    StrCmp $1 1 recovery_remove_stale_backup recovery_unknown_canonical
  recovery_remove_empty_canonical:
    Call SetSafeWorkingDir
    RMDir "${AIVEINSTALLDIR}"
    IfFileExists "${AIVEINSTALLDIR}\." recovery_cleanup_locked recovery_restore_backup
  recovery_remove_partial:
    StrCpy $0 "${AIVEINSTALLDIR}"
    Call IsReparsePoint
    StrCmp $1 1 recovery_unknown_canonical
    StrCpy $INSTDIR "${AIVEINSTALLDIR}"
    Call RemoveCurrentShellPayload
    IfFileExists "${AIVEINSTALLDIR}\." recovery_cleanup_locked recovery_restore_backup
  recovery_remove_stale_backup:
    StrCpy $INSTDIR "${AIVEBACKUPDIR}"
    Call RemoveCurrentShellPayload
    IfFileExists "${AIVEBACKUPDIR}\." recovery_cleanup_locked recovery_repaired
  recovery_repaired:
    Call SetCanonicalInstallDir
    ReadRegStr $0 HKLM "${AIVEROLLBACKKEY}" "CanonicalPath"
    StrCmp $0 "${AIVEINSTALLDIR}" 0 recovery_external_done
      Call RestoreRegistrySnapshot
      ${If} $RollbackIncomplete = 1
        StrCpy $FailureCode ${AIVE_E_ROLLBACK}
        StrCpy $FailureStage "rollback-registry"
        StrCpy $FailureMessage "Filesystem recovery completed, but registry rollback is incomplete. Recovery material was retained."
        Call FailInstall
      ${EndIf}
      Call RecoverInterruptedInstallerOrigin
      IfFileExists "${AIVETXNBACKUPDIR}\." 0 recovery_external_check
        Call RecoverInterruptedShortcuts
      recovery_external_check:
      ${If} $RollbackIncomplete = 1
        StrCpy $FailureCode ${AIVE_E_ROLLBACK}
        StrCpy $FailureStage "rollback-external"
        StrCpy $FailureMessage "Shortcut or installer-origin recovery is incomplete. Recovery material was retained."
        Call FailInstall
      ${EndIf}
    recovery_external_done:
    ${If} $TxnCreatedRequests = 1
      RMDir "$PROGRAMDATA\AI Video Editor\Broker\Requests"
    ${EndIf}
    ${If} $TxnCreatedBroker = 1
      RMDir "$PROGRAMDATA\AI Video Editor\Broker"
    ${EndIf}
    ${If} $TxnCreatedStaging = 1
      RMDir "$PROGRAMDATA\AI Video Editor\Downloads\Staging"
    ${EndIf}
    ${If} $TxnCreatedDownloads = 1
      RMDir "$PROGRAMDATA\AI Video Editor\Downloads"
    ${EndIf}
    ${If} $TxnCreatedCatalog = 1
      RMDir "$PROGRAMDATA\AI Video Editor\Catalog"
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
    DeleteRegKey HKLM "${AIVEROLLBACKKEY}"
    Delete "${AIVEJOURNAL}"
    StrCpy $InstallStarted 0
    StrCpy $FailureCode 0
    StrCpy $FailureStage "recovery-complete"
    StrCpy $FailureMessage "interrupted transaction recovered"
    Call AppendSetupLog
    Goto recovery_done
  recovery_cleanup_locked:
    StrCpy $FailureCode ${AIVE_E_LOCK}
    StrCpy $FailureStage "lock-reboot"
    StrCpy $FailureMessage "Interrupted setup files are locked. Restart Windows, then retry Setup."
    Call FailInstall
  recovery_restore_failed:
    StrCpy $FailureCode ${AIVE_E_ROLLBACK}
    StrCpy $FailureStage "rollback"
    StrCpy $FailureMessage "The prior committed shell could not be restored. Recovery material was retained."
    Call FailInstall
  recovery_unknown_staging:
    StrCpy $FailureCode ${AIVE_E_CONFLICT}
    StrCpy $FailureStage "staging-conflict"
    StrCpy $FailureMessage "An unknown nonempty staging directory was preserved. Remove it only after identifying its owner."
    Call FailInstall
  recovery_unknown_backup:
    StrCpy $FailureCode ${AIVE_E_CONFLICT}
    StrCpy $FailureStage "backup-conflict"
    StrCpy $FailureMessage "An unknown or reparse-point rollback directory was preserved. Setup will not overwrite it."
    Call FailInstall
  recovery_unknown_canonical:
    StrCpy $FailureCode ${AIVE_E_CONFLICT}
    StrCpy $FailureStage "shell-conflict"
    StrCpy $FailureMessage "The canonical shell and rollback directory are not a coherent owned pair. Both were preserved."
    Call FailInstall
  recovery_invalid_record:
    StrCpy $FailureCode ${AIVE_E_CONFLICT}
    StrCpy $FailureStage "journal-conflict"
    StrCpy $FailureMessage "An invalid or foreign installer transaction record was preserved. Setup will not trust it for recovery."
    Call FailInstall
  recovery_done:
  Call SetCanonicalInstallDir
FunctionEnd

Function RecoverInterruptedInstallerOrigin
  StrCmp $TxnWroteInstallerOrigin 1 0 interrupted_origin_recovered
  StrCmp $TxnHadInstallerOrigin 1 0 interrupted_origin_was_new
  IfFileExists "$PROGRAMDATA\AI Video Editor\Installer\handoff-root.json.rc6-rollback" 0 interrupted_origin_already_restored
    ClearErrors
    Delete "$PROGRAMDATA\AI Video Editor\Installer\handoff-root.json"
    IfErrors interrupted_origin_failed
    ClearErrors
    Rename "$PROGRAMDATA\AI Video Editor\Installer\handoff-root.json.rc6-rollback" "$PROGRAMDATA\AI Video Editor\Installer\handoff-root.json"
    IfErrors interrupted_origin_failed
    Goto interrupted_origin_recovered
  interrupted_origin_already_restored:
    IfFileExists "$PROGRAMDATA\AI Video Editor\Installer\handoff-root.json" interrupted_origin_recovered interrupted_origin_failed
  interrupted_origin_was_new:
    ClearErrors
    Delete "$PROGRAMDATA\AI Video Editor\Installer\handoff-root.json"
    IfErrors interrupted_origin_failed
  interrupted_origin_recovered:
  Delete "$PROGRAMDATA\AI Video Editor\Installer\handoff-root.json.part"
  Return
  interrupted_origin_failed:
    StrCpy $RollbackIncomplete 1
FunctionEnd

Function RecoverInterruptedShortcuts
  StrCmp $TxnHadDesktopShortcut 1 interrupted_desktop_had_prior interrupted_desktop_was_new
  interrupted_desktop_had_prior:
  IfFileExists "${AIVETXNBACKUPDIR}\Desktop.lnk" 0 interrupted_desktop_already_restored
    ClearErrors
    Delete "${AIVEDESKTOPLINK}"
    IfErrors interrupted_shortcut_failed
    ClearErrors
    Rename "${AIVETXNBACKUPDIR}\Desktop.lnk" "${AIVEDESKTOPLINK}"
    IfErrors interrupted_shortcut_failed
    Goto interrupted_desktop_recovered
  interrupted_desktop_already_restored:
    IfFileExists "${AIVEDESKTOPLINK}" interrupted_desktop_recovered interrupted_shortcut_failed
  interrupted_desktop_was_new:
    ClearErrors
    Delete "${AIVEDESKTOPLINK}"
    IfErrors interrupted_shortcut_failed
  interrupted_desktop_recovered:
  StrCmp $TxnHadStartMenuShortcut 1 interrupted_start_had_prior interrupted_start_was_new
  interrupted_start_had_prior:
  IfFileExists "${AIVETXNBACKUPDIR}\StartMenu.lnk" 0 interrupted_start_already_restored
    ClearErrors
    Delete "${AIVESTARTMENULINK}"
    IfErrors interrupted_shortcut_failed
    ClearErrors
    Rename "${AIVETXNBACKUPDIR}\StartMenu.lnk" "${AIVESTARTMENULINK}"
    IfErrors interrupted_shortcut_failed
    Goto interrupted_start_recovered
  interrupted_start_already_restored:
    IfFileExists "${AIVESTARTMENULINK}" interrupted_start_recovered interrupted_shortcut_failed
  interrupted_start_was_new:
    ClearErrors
    Delete "${AIVESTARTMENULINK}"
    IfErrors interrupted_shortcut_failed
    RMDir "${AIVESTARTMENUDIR}"
  interrupted_start_recovered:
  Delete "${AIVETXNBACKUPDIR}\Desktop.lnk"
  Delete "${AIVETXNBACKUPDIR}\StartMenu.lnk"
  RMDir "${AIVETXNBACKUPDIR}"
  Return
  interrupted_shortcut_failed:
    StrCpy $RollbackIncomplete 1
FunctionEnd

Function ResolveClassifiedInstallState
  StrCmp $InstallState "unknown-nonempty-or-reparse" classified_conflict
  StrCmp $InstallState "empty-owned-residue" classified_remove_empty
  StrCmp $InstallState "orphan-registration" classified_remove_registration
  StrCmp $InstallState "repairable-registration" classified_ready
  StrCmp $InstallState "valid-committed" classified_ready
  StrCmp $InstallState "pristine" classified_ready classified_invariant
  classified_remove_empty:
    Call SetSafeWorkingDir
    ClearErrors
    RMDir "${AIVEINSTALLDIR}"
    IfErrors classified_lock
    StrCpy $InstallState "pristine"
    Goto classified_ready
  classified_remove_registration:
    DeleteRegKey HKLM "${UNINSTKEY}"
    DeleteRegKey HKLM "${MANUPRODUCTKEY}"
    DeleteRegKey HKLM "${AIVEPRODUCTKEY}"
    IfErrors classified_registry_failed
    StrCpy $InstallState "pristine"
    Goto classified_ready
  classified_conflict:
    StrCpy $FailureCode ${AIVE_E_CONFLICT}
    StrCpy $FailureStage "classification-conflict"
    StrCpy $FailureMessage "The canonical Shell contains unknown nonempty or reparse-point data. It was left unchanged."
    Call FailInstall
  classified_lock:
    StrCpy $FailureCode ${AIVE_E_LOCK}
    StrCpy $FailureStage "lock-reboot"
    StrCpy $FailureMessage "The exact empty installer-owned residue could not be removed. Restart Windows, then retry."
    Call FailInstall
  classified_registry_failed:
    StrCpy $FailureCode ${AIVE_E_REGISTRY}
    StrCpy $FailureStage "registry"
    StrCpy $FailureMessage "Stale registration could not be repaired before installation."
    Call FailInstall
  classified_invariant:
    StrCpy $FailureCode ${AIVE_E_INVARIANT}
    StrCpy $FailureStage "classification-invariant"
    StrCpy $FailureMessage "Setup reached an unknown installation state and made no payload changes."
    Call FailInstall
  classified_ready:
    StrCpy $FailureCode 0
    StrCpy $FailureStage "classified"
    StrCpy $FailureMessage "installation state accepted"
    Call AppendSetupLog
    Call WriteTransactionJournal
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
  StrCpy $FailureStage "snapshot"
  StrCpy $FailureCode ${AIVE_E_SNAPSHOT}
  StrCpy $FailureMessage "Setup could not prepare a recoverable transaction snapshot."
  !insertmacro CheckIfAppIsRunning "${MAINBINARYNAME}.exe" "${PRODUCTNAME}"
  IfFileExists "${AIVESTAGINGDIR}\." begin_staging_conflict 0
  IfFileExists "${AIVEBACKUPDIR}\." begin_backup_conflict 0
  IfFileExists "${AIVETXNBACKUPDIR}\." begin_snapshot_existing begin_snapshot_create
  begin_snapshot_existing:
    StrCpy $0 "${AIVETXNBACKUPDIR}"
    Call IsReparsePoint
    StrCmp $1 1 begin_snapshot_conflict
    StrCpy $0 "${AIVETXNBACKUPDIR}"
    Call IsDirectoryEmpty
    StrCmp $1 1 begin_snapshot_remove begin_snapshot_conflict
  begin_snapshot_remove:
    Call SetSafeWorkingDir
    RMDir "${AIVETXNBACKUPDIR}"
  begin_snapshot_create:
  DeleteRegKey HKLM "${AIVEROLLBACKKEY}"
  System::Call 'kernel32::GetCurrentProcessId() i .r0'
  System::Call 'kernel32::GetTickCount() i .r1'
  StrCpy $TxnId "$0-$1"
  StrCpy $InstallStarted 1
  StrCpy $FailureStage "snapshotting"
  StrCpy $FailureCode 0
  StrCpy $FailureMessage "transaction snapshot in progress"
  Call WriteTransactionJournal
  StrCpy $FailureCode ${AIVE_E_SNAPSHOT}
  ClearErrors
  CreateDirectory "${AIVETXNBACKUPDIR}"
  IfErrors begin_snapshot_failed
  IfFileExists "${AIVEDESKTOPLINK}" 0 desktop_shortcut_not_present
    ClearErrors
    CopyFiles /SILENT "${AIVEDESKTOPLINK}" "${AIVETXNBACKUPDIR}\Desktop.lnk"
    IfErrors begin_snapshot_failed
    StrCpy $TxnHadDesktopShortcut 1
  desktop_shortcut_not_present:
  IfFileExists "${AIVESTARTMENULINK}" 0 start_shortcut_not_present
    ClearErrors
    CopyFiles /SILENT "${AIVESTARTMENULINK}" "${AIVETXNBACKUPDIR}\StartMenu.lnk"
    IfErrors begin_snapshot_failed
    StrCpy $TxnHadStartMenuShortcut 1
  start_shortcut_not_present:
  nsExec::ExecToStack /OEM '"$SYSDIR\reg.exe" query "HKLM\${UNINSTKEY}" /reg:64'
  Pop $0
  Pop $1
  StrCmp $0 0 0 no_arp_backup
  StrCpy $TxnHadArp 1
  nsExec::ExecToStack /OEM '"$SYSDIR\reg.exe" copy "HKLM\${UNINSTKEY}" "HKLM\${AIVEROLLBACKKEY}\Arp" /s /f /reg:64'
  Pop $0
  Pop $1
  StrCmp $0 0 no_arp_backup
    Goto begin_snapshot_failed
  no_arp_backup:
  nsExec::ExecToStack /OEM '"$SYSDIR\reg.exe" query "HKLM\${MANUPRODUCTKEY}" /reg:64'
  Pop $0
  Pop $1
  StrCmp $0 0 0 no_product_backup
  StrCpy $TxnHadProductRegistration 1
  nsExec::ExecToStack /OEM '"$SYSDIR\reg.exe" copy "HKLM\${MANUPRODUCTKEY}" "HKLM\${AIVEROLLBACKKEY}\TauriProduct" /s /f /reg:64'
  Pop $0
  Pop $1
  StrCmp $0 0 no_product_backup
    Goto begin_snapshot_failed
  no_product_backup:
  nsExec::ExecToStack /OEM '"$SYSDIR\reg.exe" query "HKLM\${AIVEPRODUCTKEY}" /reg:64'
  Pop $0
  Pop $1
  StrCmp $0 0 0 no_aive_product_backup
  StrCpy $TxnHadAiveProductRegistration 1
  nsExec::ExecToStack /OEM '"$SYSDIR\reg.exe" copy "HKLM\${AIVEPRODUCTKEY}" "HKLM\${AIVEROLLBACKKEY}\Product" /s /f /reg:64'
  Pop $0
  Pop $1
  StrCmp $0 0 no_aive_product_backup
    Goto begin_snapshot_failed
  no_aive_product_backup:
  StrCmp $InstallState "valid-committed" prior_shell
  StrCmp $InstallState "repairable-registration" prior_shell no_prior_shell
  prior_shell:
    StrCpy $TxnHadPriorShell 1
  no_prior_shell:
  StrCpy $FailureStage "prepared"
  StrCpy $FailureCode 0
  StrCpy $FailureMessage "prior filesystem and external state snapshot prepared"
  Call WriteTransactionJournal
  ClearErrors
  CreateDirectory "${AIVESTAGINGDIR}"
  IfErrors begin_staging_failed
  FileOpen $0 "${AIVESTAGINGDIR}\.installing" w
  IfErrors begin_staging_failed
  FileWrite $0 "desktop-v2-rc6-installing$\r$\n"
  FileClose $0
  StrCpy $INSTDIR "${AIVESTAGINGDIR}"
  SetOutPath "${AIVESTAGINGDIR}"
  StrCpy $FailureCode 0
  StrCpy $FailureStage "staging"
  StrCpy $FailureMessage "owned sibling staging prepared"
  Call AppendSetupLog
  Call WriteTransactionJournal
  Goto transaction_begun
  begin_snapshot_failed:
    DeleteRegKey HKLM "${AIVEROLLBACKKEY}"
    Delete "${AIVETXNBACKUPDIR}\Desktop.lnk"
    Delete "${AIVETXNBACKUPDIR}\StartMenu.lnk"
    Call SetSafeWorkingDir
    RMDir "${AIVETXNBACKUPDIR}"
    Delete "${AIVEJOURNAL}"
    StrCpy $InstallStarted 0
    StrCpy $FailureCode ${AIVE_E_SNAPSHOT}
    StrCpy $FailureStage "snapshot"
    StrCpy $FailureMessage "Setup could not protect the existing installation. No application payload was changed."
    Call FailInstall
  begin_snapshot_conflict:
    StrCpy $FailureCode ${AIVE_E_CONFLICT}
    StrCpy $FailureStage "snapshot-conflict"
    StrCpy $FailureMessage "Unknown snapshot data was preserved; Setup will not reuse it."
    Call FailInstall
  begin_staging_conflict:
    StrCpy $FailureCode ${AIVE_E_CONFLICT}
    StrCpy $FailureStage "staging-conflict"
    StrCpy $FailureMessage "A staging path still exists after recovery and was preserved."
    Call FailInstall
  begin_backup_conflict:
    StrCpy $FailureCode ${AIVE_E_CONFLICT}
    StrCpy $FailureStage "backup-conflict"
    StrCpy $FailureMessage "A rollback path still exists after recovery and was preserved."
    Call FailInstall
  begin_staging_failed:
    StrCpy $FailureCode ${AIVE_E_RENAME}
    StrCpy $FailureStage "staging-create"
    StrCpy $FailureMessage "Setup could not create its owned sibling staging directory."
    Call FailInstall
  transaction_begun:
FunctionEnd

Function ValidateStagingPayload
  IfFileExists "${AIVESTAGINGDIR}\${MAINBINARYNAME}.exe" 0 staging_validation_failed
  IfFileExists "${AIVESTAGINGDIR}\uninstall.exe" 0 staging_validation_failed
  IfFileExists "${AIVESTAGINGDIR}\.installing" staging_validation_done 0
  staging_validation_failed:
    StrCpy $FailureCode ${AIVE_E_INVARIANT}
    StrCpy $FailureStage "staging-validation"
    StrCpy $FailureMessage "The staged shell failed executable, uninstaller, or ownership-marker validation."
    Call FailInstall
  staging_validation_done:
    StrCpy $FailureCode 0
    StrCpy $FailureStage "staging-validated"
    StrCpy $FailureMessage "staged payload validated"
    Call AppendSetupLog
    Call WriteTransactionJournal
FunctionEnd

Function ProtectAndActivateStaging
  Call SetSafeWorkingDir
  ${If} $TxnHadPriorShell = 1
    StrCpy $FailureCode 0
    StrCpy $FailureStage "prior-move-intent"
    StrCpy $FailureMessage "about to protect prior shell"
    Call WriteTransactionJournal
  protect_prior_retry:
    Call SetSafeWorkingDir
    ClearErrors
    Rename "${AIVEINSTALLDIR}" "${AIVEBACKUPDIR}"
    IfErrors 0 protect_prior_done
    ${IfNot} ${Silent}
      MessageBox MB_ICONEXCLAMATION|MB_RETRYCANCEL "The existing shell is locked. Close AI Video Editor and retry, or cancel without replacing it." IDRETRY protect_prior_retry
    ${EndIf}
    StrCpy $FailureCode ${AIVE_E_LOCK}
    StrCpy $FailureStage "shell-rename-lock"
    StrCpy $FailureMessage "The prior shell could not be moved to rollback protection."
    Call FailInstall
  protect_prior_done:
    StrCpy $FailureCode 0
    StrCpy $FailureStage "prior-moved"
    StrCpy $FailureMessage "prior shell protected"
    Call AppendSetupLog
    Call WriteTransactionJournal
  ${EndIf}
  StrCpy $FailureCode 0
  StrCpy $FailureStage "activation-intent"
  StrCpy $FailureMessage "about to activate verified staging"
  Call WriteTransactionJournal
  activate_retry:
    Call SetSafeWorkingDir
    ClearErrors
    Rename "${AIVESTAGINGDIR}" "${AIVEINSTALLDIR}"
    IfErrors 0 activation_done
    ${IfNot} ${Silent}
      MessageBox MB_ICONEXCLAMATION|MB_RETRYCANCEL "The staged shell could not be activated. Retry, or cancel to restore the prior installation." IDRETRY activate_retry
    ${EndIf}
    ${If} $TxnHadPriorShell = 1
      Call SetSafeWorkingDir
      ClearErrors
      Rename "${AIVEBACKUPDIR}" "${AIVEINSTALLDIR}"
      IfErrors 0 activation_failed
      StrCpy $RollbackIncomplete 1
      StrCpy $FailureCode ${AIVE_E_ROLLBACK}
      StrCpy $FailureStage "rollback"
      StrCpy $FailureMessage "Activation failed and the prior shell could not be restored. Recovery material was retained."
      Call FailInstall
    ${EndIf}
  activation_failed:
    StrCpy $FailureCode ${AIVE_E_ACTIVATION}
    StrCpy $FailureStage "activation"
    StrCpy $FailureMessage "The staged shell could not be atomically activated."
    Call FailInstall
  activation_done:
    Call SetCanonicalInstallDir
    StrCpy $FailureCode 0
    StrCpy $FailureStage "activated"
    StrCpy $FailureMessage "staging atomically activated"
    Call AppendSetupLog
    Call WriteTransactionJournal
FunctionEnd

Section Install
  Call BeginInstallTransaction

  !ifmacrodef NSIS_HOOK_PREINSTALL
    !insertmacro NSIS_HOOK_PREINSTALL
  !endif

  SetOutPath "${AIVESTAGINGDIR}"
  ClearErrors
  File "${MAINBINARYSRCPATH}"
  IfErrors payload_copy_failed

  {{#each resources_dirs}}
    CreateDirectory "$INSTDIR\\{{this}}"
  {{/each}}
  {{#each resources}}
    File /a "/oname={{this.[1]}}" "{{no-escape @key}}"
  {{/each}}
  {{#each binaries}}
    File /a "/oname={{this}}" "{{no-escape @key}}"
  {{/each}}
  IfErrors payload_copy_failed

  ClearErrors
  WriteUninstaller "$INSTDIR\uninstall.exe"
  IfErrors uninstaller_failed
  IfFileExists "$INSTDIR\uninstall.exe" uninstaller_ready uninstaller_failed
  uninstaller_ready:

  Call ValidateStagingPayload
  Call ProtectAndActivateStaging
  Call CreateAndVerifyRequiredShortcuts

  !ifmacrodef NSIS_HOOK_POSTINSTALL
    !insertmacro NSIS_HOOK_POSTINSTALL
  !endif

  Call CommitInstallRegistration
  Call PublishCommittedIdentity
  ${If} $TxnHadPriorShell = 1
    StrCpy $FailureCode 0
    StrCpy $FailureStage "cleanup-pending"
    StrCpy $FailureMessage "committed install is cleaning protected prior shell"
    Call WriteTransactionJournal
    StrCpy $INSTDIR "${AIVEBACKUPDIR}"
    Call RemoveCurrentShellPayload
    IfFileExists "${AIVEBACKUPDIR}\." 0 backup_cleanup_done
      StrCpy $DeferredCleanup 1
      StrCpy $FailureCode ${AIVE_E_LOCK}
      StrCpy $FailureStage "cleanup-pending"
      StrCpy $FailureMessage "The new install is committed; prior-version cleanup is deferred."
      Call AppendSetupLog
      Call WriteTransactionJournal
      Goto committed_cleanup_retained
    backup_cleanup_done:
    Call SetCanonicalInstallDir
  ${EndIf}
  Delete "$PROGRAMDATA\AI Video Editor\Installer\handoff-root.json.rc6-rollback"
  Delete "${AIVETXNBACKUPDIR}\Desktop.lnk"
  Delete "${AIVETXNBACKUPDIR}\StartMenu.lnk"
  Call SetSafeWorkingDir
  RMDir "${AIVETXNBACKUPDIR}"
  DeleteRegKey HKLM "${AIVEROLLBACKKEY}"
  Delete "${AIVEJOURNAL}"
  StrCpy $InstallStarted 0
  committed_cleanup_retained:
  DeleteRegKey HKLM "Software\Microsoft\Windows\CurrentVersion\Uninstall\AI Video Editor"
  DeleteRegKey HKCU "Software\Microsoft\Windows\CurrentVersion\Uninstall\AI Video Editor"

  ${If} $PassiveMode = 1
    SetAutoClose true
  ${EndIf}
  Goto install_section_done
  payload_copy_failed:
    StrCpy $FailureCode ${AIVE_E_INVARIANT}
    StrCpy $FailureStage "payload"
    StrCpy $FailureMessage "Failed to extract a required RC.6 payload file into staging."
    Call FailInstall
  uninstaller_failed:
    StrCpy $FailureCode ${AIVE_E_IDENTITY}
    StrCpy $FailureStage "uninstaller"
    StrCpy $FailureMessage "The staged uninstaller could not be written and verified."
    Call FailInstall
  install_section_done:
SectionEnd

Function CreateAndVerifyRequiredShortcuts
  ClearErrors
  CreateDirectory "${AIVESTARTMENUDIR}"
  CreateShortcut "${AIVESTARTMENULINK}" "$INSTDIR\${MAINBINARYNAME}.exe"
  CreateShortcut "${AIVEDESKTOPLINK}" "$INSTDIR\${MAINBINARYNAME}.exe"
  IfErrors shortcut_creation_failed
  !insertmacro SetLnkAppUserModelId "${AIVESTARTMENULINK}"
  !insertmacro SetLnkAppUserModelId "${AIVEDESKTOPLINK}"
  !insertmacro IsShortcutTarget "${AIVESTARTMENULINK}" "$INSTDIR\${MAINBINARYNAME}.exe"
  Pop $0
  StrCmp $0 1 0 shortcut_verification_failed
  !insertmacro IsShortcutTarget "${AIVEDESKTOPLINK}" "$INSTDIR\${MAINBINARYNAME}.exe"
  Pop $0
  StrCmp $0 1 shortcut_verification_done shortcut_verification_failed
  shortcut_verification_failed:
    StrCpy $FailureCode ${AIVE_E_SHORTCUT}
    StrCpy $FailureStage "shortcut"
    StrCpy $FailureMessage "A required shortcut did not target the canonical shell."
    Call FailInstall
  shortcut_creation_failed:
    StrCpy $FailureCode ${AIVE_E_SHORTCUT}
    StrCpy $FailureStage "shortcut"
    StrCpy $FailureMessage "The required Desktop and Start Menu shortcuts could not be created."
    Call FailInstall
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
  WriteRegStr HKLM "${AIVEPRODUCTKEY}" "Identifier" "${AIVEIDENTIFIER}"
  WriteRegStr HKLM "${AIVEPRODUCTKEY}" "InstallPath" "$INSTDIR"
  WriteRegStr HKLM "${AIVEPRODUCTKEY}" "InstalledVersion" "${VERSION}"
  WriteRegStr HKLM "${AIVEPRODUCTKEY}" "PackageIdentity" "${AIVEPACKAGEID}"
  WriteRegDWORD HKLM "${AIVEPRODUCTKEY}" "InstallCommitted" 0
  IfErrors registration_write_failed
  ReadRegStr $1 HKLM "${UNINSTKEY}" "UninstallString"
  StrCmp $1 '$"$INSTDIR\uninstall.exe$"' 0 registration_verification_failed
  ReadRegStr $1 HKLM "${UNINSTKEY}" "DisplayVersion"
  StrCmp $1 "${VERSION}" registration_verification_done registration_verification_failed
  registration_verification_failed:
    StrCpy $FailureCode ${AIVE_E_REGISTRATION}
    StrCpy $FailureStage "registration"
    StrCpy $FailureMessage "Add/Remove Programs registration verification failed."
    Call FailInstall
  registration_write_failed:
    StrCpy $FailureCode ${AIVE_E_REGISTRATION}
    StrCpy $FailureStage "registration"
    StrCpy $FailureMessage "Add/Remove Programs registration could not be written."
    Call FailInstall
  registration_verification_done:
FunctionEnd

Function PublishCommittedIdentity
  ; Publish the identity atomically, then flip InstallCommitted as the final
  ; externally visible commit operation.
  Delete "$INSTDIR\${AIVEIDENTITY}.part"
  FileOpen $0 "$INSTDIR\${AIVEIDENTITY}.part" w
  IfErrors identity_write_failed
  FileWrite $0 '{"schemaVersion":"desktop.install-identity.v1","productName":"AI Video Editor Desktop V2","identifier":"${AIVEIDENTIFIER}","packageIdentity":"${AIVEPACKAGEID}","version":"${VERSION}","channel":"beta","canonicalPath":"%ProgramFiles%/AI Video Editor Desktop V2/Shell","installCommitted":true}'
  FileClose $0
  System::Call 'kernel32::MoveFileExW(w "$INSTDIR\${AIVEIDENTITY}.part", w "$INSTDIR\${AIVEIDENTITY}", i 0x1) i .r0'
  StrCmp $0 0 identity_write_failed
  IfFileExists "$INSTDIR\${AIVEIDENTITY}" 0 identity_write_failed
  IfFileExists "$INSTDIR\${MAINBINARYNAME}.exe" 0 identity_invariant_failed
  IfFileExists "$INSTDIR\uninstall.exe" 0 identity_invariant_failed
  ClearErrors
  WriteRegDWORD HKLM "${AIVEPRODUCTKEY}" "InstallCommitted" 1
  IfErrors identity_registry_failed
  ReadRegDWORD $1 HKLM "${AIVEPRODUCTKEY}" "InstallCommitted"
  StrCmp $1 1 identity_committed identity_registry_failed
  identity_write_failed:
    StrCpy $FailureCode ${AIVE_E_IDENTITY}
    StrCpy $FailureStage "identity"
    StrCpy $FailureMessage "The committed installation identity could not be published atomically."
    Call FailInstall
  identity_registry_failed:
    StrCpy $FailureCode ${AIVE_E_REGISTRATION}
    StrCpy $FailureStage "registration-commit"
    StrCpy $FailureMessage "The final committed-registration marker could not be published."
    Call FailInstall
  identity_invariant_failed:
    StrCpy $FailureCode ${AIVE_E_INVARIANT}
    StrCpy $FailureStage "commit-invariant"
    StrCpy $FailureMessage "The activated shell lost a required owned file before commit."
    Call FailInstall
  identity_committed:
    Delete "$INSTDIR\.installing"
    StrCpy $InstallCommitted 1
    StrCpy $FailureCode 0
    StrCpy $FailureStage "committed"
    StrCpy $FailureMessage "installation committed"
    Call AppendSetupLog
    Call WriteTransactionJournal
FunctionEnd

Function RemoveCurrentShellPayload
  Call SetSafeWorkingDir
  ClearErrors
  Delete "$INSTDIR\${AIVEIDENTITY}.part"
  Delete "$INSTDIR\component-broker.json"
  {{#each resources}}
    Delete "$INSTDIR\\{{this.[1]}}"
  {{/each}}
  {{#each binaries}}
    Delete "$INSTDIR\\{{this}}"
  {{/each}}
  Delete "$INSTDIR\${MAINBINARYNAME}.exe"
  Delete "$INSTDIR\uninstall.exe"
  IfErrors remove_shell_keep_markers
  ; Keep both ownership/recovery markers until payload removal has completed.
  ; A crash can then safely resume the journal-authorized cleanup.
  Delete "$INSTDIR\${AIVEIDENTITY}"
  Delete "$INSTDIR\.installing"
  {{#each resources_ancestors}}
    RMDir "$INSTDIR\\{{this}}"
  {{/each}}
  RMDir "$INSTDIR"
  remove_shell_keep_markers:
FunctionEnd

Function RestoreRegistrySnapshot
  ReadRegDWORD $4 HKLM "${AIVEROLLBACKKEY}" "HadArp"
  ReadRegDWORD $5 HKLM "${AIVEROLLBACKKEY}" "HadTauriProduct"
  ReadRegDWORD $6 HKLM "${AIVEROLLBACKKEY}" "HadProduct"
  DeleteRegKey HKLM "${UNINSTKEY}"
  StrCmp $4 1 0 restore_registry_tauri
    nsExec::ExecToStack /OEM '"$SYSDIR\reg.exe" copy "HKLM\${AIVEROLLBACKKEY}\Arp" "HKLM\${UNINSTKEY}" /s /f /reg:64'
    Pop $0
    Pop $1
    StrCmp $0 0 restore_registry_tauri
      StrCpy $RollbackIncomplete 1
  restore_registry_tauri:
  DeleteRegKey HKLM "${MANUPRODUCTKEY}"
  StrCmp $5 1 0 restore_registry_product
    nsExec::ExecToStack /OEM '"$SYSDIR\reg.exe" copy "HKLM\${AIVEROLLBACKKEY}\TauriProduct" "HKLM\${MANUPRODUCTKEY}" /s /f /reg:64'
    Pop $0
    Pop $1
    StrCmp $0 0 restore_registry_product
      StrCpy $RollbackIncomplete 1
  restore_registry_product:
  DeleteRegKey HKLM "${AIVEPRODUCTKEY}"
  StrCmp $6 1 0 restore_registry_done
    nsExec::ExecToStack /OEM '"$SYSDIR\reg.exe" copy "HKLM\${AIVEROLLBACKKEY}\Product" "HKLM\${AIVEPRODUCTKEY}" /s /f /reg:64'
    Pop $0
    Pop $1
    StrCmp $0 0 restore_registry_done
      StrCpy $RollbackIncomplete 1
  restore_registry_done:
FunctionEnd

Function RollbackInstallTransaction
  DetailPrint "Rolling back the bounded RC.6 install transaction."
  StrCpy $FailureCode 0
  StrCpy $FailureStage "rollback-in-progress"
  StrCpy $FailureMessage "transaction rollback in progress"
  Call WriteTransactionJournal
  Call SetSafeWorkingDir
  IfFileExists "${AIVESTAGINGDIR}\.installing" 0 rollback_check_live
    StrCpy $INSTDIR "${AIVESTAGINGDIR}"
    Call RemoveCurrentShellPayload
    IfFileExists "${AIVESTAGINGDIR}\." 0 rollback_check_live
      StrCpy $RollbackIncomplete 1
  rollback_check_live:
  IfFileExists "${AIVEINSTALLDIR}\.installing" 0 rollback_restore_prior
    StrCpy $0 "${AIVEINSTALLDIR}"
    Call IsReparsePoint
    StrCmp $1 1 rollback_mark_incomplete
    StrCpy $INSTDIR "${AIVEINSTALLDIR}"
    Call RemoveCurrentShellPayload
    IfFileExists "${AIVEINSTALLDIR}\." 0 rollback_restore_prior
      StrCpy $RollbackIncomplete 1
  rollback_restore_prior:
  IfFileExists "${AIVEBACKUPDIR}\." 0 rollback_external_state
  IfFileExists "${AIVEINSTALLDIR}\." rollback_mark_incomplete 0
    Call SetSafeWorkingDir
    ClearErrors
    Rename "${AIVEBACKUPDIR}" "${AIVEINSTALLDIR}"
    IfErrors rollback_mark_incomplete rollback_external_state
  rollback_mark_incomplete:
    StrCpy $RollbackIncomplete 1
  rollback_external_state:
  Call RestoreRegistrySnapshot
  ${If} $RollbackIncomplete = 1
    StrCpy $FailureCode ${AIVE_E_ROLLBACK}
    StrCpy $FailureStage "rollback-pending"
    StrCpy $FailureMessage "Rollback is incomplete; shell and registry recovery material was retained."
    Call AppendSetupLog
    Call WriteTransactionJournal
    Call SetCanonicalInstallDir
    Return
  ${EndIf}
  Call RecoverInterruptedShortcuts
  Call RecoverInterruptedInstallerOrigin
  ${If} $RollbackIncomplete = 1
    StrCpy $FailureCode ${AIVE_E_ROLLBACK}
    StrCpy $FailureStage "rollback-pending"
    StrCpy $FailureMessage "Shortcut or installer-origin restoration is incomplete; recovery material was retained."
    Call AppendSetupLog
    Call WriteTransactionJournal
    Call SetCanonicalInstallDir
    Return
  ${EndIf}
  Delete "$PROGRAMDATA\AI Video Editor\Installer\handoff-root.json.part"
  Delete "$PROGRAMDATA\AI Video Editor\Installer\handoff-root.json.rc6-rollback"

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
    ; Persistent setup log/journal deliberately keep this directory nonempty.
  ${EndIf}
  ${If} $TxnCreatedMachineRoot = 1
    RMDir "$PROGRAMDATA\AI Video Editor"
  ${EndIf}
  Call SetCanonicalInstallDir
  StrCpy $FailureCode 0
  StrCpy $FailureStage "rolled-back"
  StrCpy $FailureMessage "transaction rolled back"
  Call AppendSetupLog
  DeleteRegKey HKLM "${AIVEROLLBACKKEY}"
  Delete "${AIVEJOURNAL}"
  StrCpy $InstallStarted 0
FunctionEnd

Function .onInstFailed
  Delete "$TEMP\MicrosoftEdgeWebview2Setup.exe"
  Delete "$TEMP\MicrosoftEdgeWebView2RuntimeInstaller.exe"
  ${If} $InstallStarted = 1
  ${AndIf} $InstallCommitted = 0
    Call RollbackInstallTransaction
  ${EndIf}
  ${If} $MutexHandle <> 0
    System::Call 'kernel32::CloseHandle(p rMutexHandle)'
  ${EndIf}
FunctionEnd

Function .onInstSuccess
  ${If} $InstallCommitted <> 1
    MessageBox MB_ICONSTOP|MB_OK "RC.6 Setup ended without a committed identity marker. Run Setup again to repair."
    SetErrorLevel ${AIVE_E_INVARIANT}
    ${If} $MutexHandle <> 0
      System::Call 'kernel32::CloseHandle(p rMutexHandle)'
    ${EndIf}
    Return
  ${EndIf}
  ${If} $DeferredCleanup = 1
    SetRebootFlag true
    SetErrorLevel 3010
  ${EndIf}
  ${If} $PassiveMode = 1
  ${OrIf} ${Silent}
    ${GetOptions} $CMDLINE "/R" $R0
    ${IfNot} ${Errors}
      nsis_tauri_utils::RunAsUser "$INSTDIR\${MAINBINARYNAME}.exe" ""
    ${EndIf}
  ${EndIf}
  ${If} $MutexHandle <> 0
    System::Call 'kernel32::CloseHandle(p rMutexHandle)'
  ${EndIf}
FunctionEnd

Function RunMainBinary
  nsis_tauri_utils::RunAsUser "$INSTDIR\${MAINBINARYNAME}.exe" ""
FunctionEnd

Function un.SetSafeWorkingDir
  InitPluginsDir
  SetOutPath "$PLUGINSDIR"
FunctionEnd

Function un.ValidateInstallerPerimeter
  ReadEnvStr $0 "ProgramData"
  StrCmp $0 "" un_installer_perimeter_failed
  System::Call 'kernel32::GetFileAttributesW(w r0) i .r3'
  IntOp $3 $3 & 0x400
  StrCmp $3 0 0 un_installer_perimeter_failed
  StrCpy $1 "$0\AI Video Editor"
  StrCpy $2 "$1\Installer"
  IfFileExists "$1\." 0 un_installer_check_directory
    System::Call 'kernel32::GetFileAttributesW(w r1) i .r3'
    IntOp $3 $3 & 0x400
    StrCmp $3 0 0 un_installer_perimeter_failed
  un_installer_check_directory:
  IfFileExists "$2\." 0 un_installer_create_directory
    System::Call 'kernel32::GetFileAttributesW(w r2) i .r3'
    IntOp $3 $3 & 0x400
    StrCmp $3 0 0 un_installer_perimeter_failed
  un_installer_create_directory:
  ClearErrors
  CreateDirectory "$2"
  IfErrors un_installer_perimeter_failed
  System::Call 'kernel32::GetFileAttributesW(w r2) i .r3'
  IntOp $3 $3 & 0x400
  StrCmp $3 0 0 un_installer_perimeter_failed
  nsExec::ExecToStack /OEM '"$SYSDIR\icacls.exe" "$2" /inheritance:r /grant:r "*S-1-5-18:(OI)(CI)(F)" "*S-1-5-32-544:(OI)(CI)(F)"'
  Pop $0
  Pop $1
  StrCmp $0 "0" un_installer_perimeter_valid
  un_installer_perimeter_failed:
    SetErrorLevel ${AIVE_E_CONFLICT}
    ${IfNot} ${Silent}
      MessageBox MB_ICONSTOP|MB_OK "Uninstall refused an unsafe or unavailable ProgramData installer perimeter. Reparse points were preserved."
    ${EndIf}
    Abort
  un_installer_perimeter_valid:
FunctionEnd

Function un.WriteUninstallJournal
  ClearErrors
  DeleteRegValue HKLM "${AIVEROLLBACKKEY}" "Phase"
  WriteRegStr HKLM "${AIVEROLLBACKKEY}" "TransactionId" "$TxnId"
  WriteRegStr HKLM "${AIVEROLLBACKKEY}" "ExpectedVersion" "${VERSION}"
  WriteRegStr HKLM "${AIVEROLLBACKKEY}" "PackageIdentity" "${AIVEPACKAGEID}"
  WriteRegStr HKLM "${AIVEROLLBACKKEY}" "CanonicalPath" "${AIVEINSTALLDIR}"
  WriteRegStr HKLM "${AIVEROLLBACKKEY}" "StagingPath" "${AIVESTAGINGDIR}"
  WriteRegStr HKLM "${AIVEROLLBACKKEY}" "BackupPath" "${AIVEBACKUPDIR}"
  WriteRegStr HKLM "${AIVEROLLBACKKEY}" "UninstallTombstone" "$UninstallTombstone"
  WriteRegStr HKLM "${AIVEROLLBACKKEY}" "Phase" "$FailureStage"
  IfErrors un_journal_failed
  ReadRegStr $4 HKLM "${AIVEROLLBACKKEY}" "Phase"
  ReadRegStr $5 HKLM "${AIVEROLLBACKKEY}" "UninstallTombstone"
  StrCmp $4 "$FailureStage" 0 un_journal_failed
  StrCmp $5 "$UninstallTombstone" 0 un_journal_failed
  Delete "${AIVEUNINSTALLJOURNAL}.part"
  FileOpen $9 "${AIVEUNINSTALLJOURNAL}.part" w
  IfErrors un_journal_failed
  FileWrite $9 '{$\"schemaVersion$\":$\"desktop.uninstall-transaction.v1$\",$\"transactionId$\":$\"$TxnId$\",$\"phase$\":$\"$FailureStage$\",$\"packageIdentity$\":$\"${AIVEPACKAGEID}$\",$\"canonicalPath$\":$\"%ProgramFiles%/AI Video Editor Desktop V2/Shell$\",$\"tombstone$\":$\"$UninstallTombstone$\"}'
  FileClose $9
  IfErrors un_journal_failed
  System::Call 'kernel32::MoveFileExW(w "${AIVEUNINSTALLJOURNAL}.part", w "${AIVEUNINSTALLJOURNAL}", i 0x1) i .r8'
  StrCmp $8 0 un_journal_failed
  Return
  un_journal_failed:
    StrCpy $FailureCode ${AIVE_E_SNAPSHOT}
    StrCpy $FailureStage "uninstall-journal"
    StrCpy $FailureMessage "Uninstall stopped because its recovery journal could not be published and verified."
    Call un.Fail
FunctionEnd

; Remove an allowlisted tree without ever traversing a junction/symlink.
; Reparse entries and their parents are deliberately preserved and reported.
Function un.RemoveTreeNoReparse
  Exch $0
  Push $1
  Push $2
  Push $3
  System::Call 'kernel32::GetFileAttributesW(w r0) i .r1'
  IntCmp $1 -1 un_tree_done
  IntOp $1 $1 & 0x400
  StrCmp $1 0 un_tree_scan
    DetailPrint "Preserving reparse-point cleanup target: $0"
    Goto un_tree_done
  un_tree_scan:
  FindFirst $1 $2 "$0\*"
  IfErrors un_tree_remove_root
  un_tree_loop:
    StrCmp $2 "." un_tree_next
    StrCmp $2 ".." un_tree_next
    IfFileExists "$0\$2\." un_tree_directory un_tree_file
  un_tree_directory:
    Push "$0\$2"
    Call un.RemoveTreeNoReparse
    Goto un_tree_next
  un_tree_file:
    Delete /REBOOTOK "$0\$2"
  un_tree_next:
    ClearErrors
    FindNext $1 $2
    IfErrors un_tree_close un_tree_loop
  un_tree_close:
    FindClose $1
  un_tree_remove_root:
    RMDir /REBOOTOK "$0"
  un_tree_done:
  Pop $3
  Pop $2
  Pop $1
  Pop $0
FunctionEnd

Function un.AppendSetupLog
  CreateDirectory "${AIVEINSTALLERDIR}"
  FileOpen $9 "${AIVEINSTALLERDIR}\uninstall-rc6.log" a
  IfErrors un_setup_log_done
  FileWrite $9 "stage=$FailureStage code=$FailureCode message=$FailureMessage$\r$\n"
  FileClose $9
  un_setup_log_done:
FunctionEnd

Function un.Fail
  Call un.AppendSetupLog
  SetErrorLevel $FailureCode
  ${IfNot} ${Silent}
    MessageBox MB_ICONSTOP|MB_OK "$FailureMessage$\r$\n$\r$\nUninstall code: $FailureCode ($FailureStage)$\r$\nLog: ${AIVEINSTALLERDIR}\uninstall-rc6.log"
  ${EndIf}
  Abort
FunctionEnd

Function un.AcquireInstallerMutex
  System::Call 'kernel32::CreateMutexW(p0, i0, w "Global\AI-Video-Editor-Desktop-V2-RC6-Setup") p .rMutexHandle ?e'
  Pop $0
  ${If} $MutexHandle = 0
    StrCpy $FailureCode ${AIVE_E_CONCURRENT}
    StrCpy $FailureStage "mutex"
    StrCpy $FailureMessage "Uninstall could not acquire the product mutex."
    Call un.Fail
  ${EndIf}
  ${If} $0 = 183
    StrCpy $FailureCode ${AIVE_E_CONCURRENT}
    StrCpy $FailureStage "mutex"
    StrCpy $FailureMessage "Another setup or uninstall is already running. Wait for it to finish, then retry."
    Call un.Fail
  ${EndIf}
FunctionEnd

Function un.ValidateInstalledIdentity
  ; NSIS normally executes uninstall from a temporary self-copy, so $EXEPATH
  ; is not the registered path. Authorize with the immutable package token,
  ; committed registry identity, canonical live path, and live uninstaller.
  System::Call 'kernel32::GetFileAttributesW(w "${AIVEINSTALLDIR}") i .r0'
  IntCmp $0 -1 un_identity_failed
  IntOp $0 $0 & 0x400
  StrCmp $0 0 0 un_identity_failed
  IfFileExists "${AIVEINSTALLDIR}\${AIVEIDENTITY}" 0 un_identity_failed
  IfFileExists "${AIVEINSTALLDIR}\${MAINBINARYNAME}.exe" 0 un_identity_failed
  IfFileExists "${AIVEINSTALLDIR}\uninstall.exe" 0 un_identity_failed
  FileOpen $5 "${AIVEINSTALLDIR}\${AIVEIDENTITY}" r
  IfErrors un_identity_failed
  FileRead $5 $6
  FileClose $5
  StrCmp $6 '{"schemaVersion":"desktop.install-identity.v1","productName":"AI Video Editor Desktop V2","identifier":"${AIVEIDENTIFIER}","packageIdentity":"${AIVEPACKAGEID}","version":"${VERSION}","channel":"beta","canonicalPath":"%ProgramFiles%/AI Video Editor Desktop V2/Shell","installCommitted":true}' 0 un_identity_failed
  ReadRegStr $0 HKLM "${AIVEPRODUCTKEY}" "Identifier"
  ReadRegStr $1 HKLM "${AIVEPRODUCTKEY}" "PackageIdentity"
  ReadRegStr $2 HKLM "${AIVEPRODUCTKEY}" "InstallPath"
  ReadRegDWORD $3 HKLM "${AIVEPRODUCTKEY}" "InstallCommitted"
  ReadRegStr $4 HKLM "${UNINSTKEY}" "UninstallString"
  StrCmp $0 "${AIVEIDENTIFIER}" 0 un_identity_failed
  StrCmp $1 "${AIVEPACKAGEID}" 0 un_identity_failed
  StrCmp $2 "${AIVEINSTALLDIR}" 0 un_identity_failed
  StrCmp $3 1 0 un_identity_failed
  StrCmp $4 '$"${AIVEINSTALLDIR}\uninstall.exe$"' un_identity_valid un_identity_failed
  un_identity_failed:
    StrCpy $FailureCode ${AIVE_E_IDENTITY}
    StrCpy $FailureStage "uninstall-identity"
    StrCpy $FailureMessage "Uninstall refused because its executable, canonical path, identity, and registration do not describe the same committed installation."
    Call un.Fail
  un_identity_valid:
FunctionEnd

Function un.onInit
  !insertmacro SetContext
  SetRegView 64
  StrCpy $INSTDIR "${AIVEINSTALLDIR}"
  StrCpy $FailureCode 0
  StrCpy $FailureStage "uninstall-init"
  StrCpy $FailureMessage "initializing uninstall"
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
  ${GetOptions} $CMDLINE "/AIVE_TEST_ROOT=" $0
  ${IfNot} ${Errors}
    StrCpy $FailureCode ${AIVE_E_INVARIANT}
    StrCpy $FailureStage "uninstall-invariant"
    StrCpy $FailureMessage "Production uninstall rejects test-root overrides."
    Call un.Fail
  ${EndIf}
  Call un.SetSafeWorkingDir
  Call un.ValidateInstallerPerimeter
  Call un.AcquireInstallerMutex
  Call un.ValidateInstalledIdentity
  System::Call 'kernel32::GetCurrentProcessId() i .r0'
  System::Call 'kernel32::GetTickCount() i .r1'
  StrCpy $TxnId "$0-$1"
  StrCpy $UninstallTombstone "${AIVEINSTALLERPARENT}\Shell.rc6-uninstall-$0-$1"
  StrCpy $FailureStage "uninstall-validated"
  StrCpy $FailureMessage "committed uninstall identity validated"
  Call un.AppendSetupLog
FunctionEnd

Section Uninstall
  !ifmacrodef NSIS_HOOK_PREUNINSTALL
    !insertmacro NSIS_HOOK_PREUNINSTALL
  !endif
  !insertmacro CheckIfAppIsRunning "${MAINBINARYNAME}.exe" "${PRODUCTNAME}"

  ; Move the verified live tree to a never-reused sibling before any delayed
  ; deletion. Reinstall can safely reuse the canonical path before reboot.
  Call un.SetSafeWorkingDir
  StrCpy $FailureStage "uninstall-rename-intent"
  StrCpy $FailureMessage "about to move verified live shell to unique uninstall cleanup path"
  Call un.WriteUninstallJournal
  ClearErrors
  Rename "${AIVEINSTALLDIR}" "$UninstallTombstone"
  IfErrors uninstall_live_rename_failed
  StrCpy $FailureStage "uninstall-cleanup"
  StrCpy $FailureMessage "verified live shell moved to unique uninstall cleanup path"
  Call un.WriteUninstallJournal
  StrCpy $INSTDIR "$UninstallTombstone"
  Delete /REBOOTOK "$INSTDIR\${MAINBINARYNAME}.exe"
  Delete /REBOOTOK "$INSTDIR\uninstall.exe"
  Delete /REBOOTOK "$INSTDIR\${AIVEIDENTITY}"
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

  !insertmacro IsShortcutTarget "${AIVESTARTMENULINK}" "${AIVEINSTALLDIR}\${MAINBINARYNAME}.exe"
  Pop $0
  StrCmp $0 1 0 +2
    Delete "${AIVESTARTMENULINK}"
  RMDir "${AIVESTARTMENUDIR}"
  !insertmacro IsShortcutTarget "${AIVEDESKTOPLINK}" "${AIVEINSTALLDIR}\${MAINBINARYNAME}.exe"
  Pop $0
  StrCmp $0 1 0 +2
    Delete "${AIVEDESKTOPLINK}"
  DeleteRegKey HKLM "${UNINSTKEY}"
  DeleteRegKey HKLM "${MANUPRODUCTKEY}"
  DeleteRegKey HKLM "${AIVEPRODUCTKEY}"

  !ifmacrodef NSIS_HOOK_POSTUNINSTALL
    !insertmacro NSIS_HOOK_POSTUNINSTALL
  !endif

  ; Report locked Program Files leftovers and remove the parent only when empty.
  IfFileExists "$UninstallTombstone\*.*" program_files_leftover shell_empty
  program_files_leftover:
    DetailPrint "RC.6 Program Files cleanup is deferred until restart: $UninstallTombstone"
    SetRebootFlag true
    Goto program_files_report_done
  shell_empty:
    Call un.SetSafeWorkingDir
    RMDir /REBOOTOK "$UninstallTombstone"
    RMDir /REBOOTOK "${AIVEINSTALLERPARENT}"
    IfFileExists "${AIVEINSTALLERPARENT}\*.*" 0 program_files_report_done
      DetailPrint "The Program Files product parent is not empty and was preserved: ${AIVEINSTALLERPARENT}"
  program_files_report_done:

  ${If} $PassiveMode = 1
  ${OrIf} $UpdateMode = 1
    SetAutoClose true
  ${EndIf}
  StrCpy $FailureCode 0
  StrCpy $FailureStage "uninstall-complete"
  StrCpy $FailureMessage "owned application files removed; user data retention policy applied"
  Call un.AppendSetupLog
  DeleteRegKey HKLM "${AIVEROLLBACKKEY}"
  Delete "${AIVEUNINSTALLJOURNAL}"
  Delete "${AIVEUNINSTALLJOURNAL}.part"
  Goto uninstall_done
  uninstall_live_rename_failed:
    StrCpy $FailureCode ${AIVE_E_LOCK}
    StrCpy $FailureStage "uninstall-rename-lock"
    StrCpy $FailureMessage "Uninstall could not move the verified live shell to its unique cleanup path. Close the app, restart Windows if needed, and retry."
    Call un.Fail
  uninstall_done:
  ${If} $MutexHandle <> 0
    System::Call 'kernel32::CloseHandle(p rMutexHandle)'
  ${EndIf}
SectionEnd

Function SkipIfPassive
  ${IfThen} $PassiveMode = 1 ${|} Abort ${|}
FunctionEnd
Function un.SkipIfPassive
  ${IfThen} $PassiveMode = 1 ${|} Abort ${|}
FunctionEnd
