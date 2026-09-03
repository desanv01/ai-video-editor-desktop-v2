; AI Video Editor Desktop V2 RC.6 per-machine policy hooks.
; installer-template.nsi is the single owner of payload transaction state,
; shortcuts, committed identity, ARP registration, and Program Files cleanup.
; Program Files remains immutable at runtime; scoped machine writes use the
; exact ProgramData perimeter and per-user content remains preserve-by-default.

!macro AIVE_CREATE_MACHINE_DIR PATH CREATED_FLAG LABEL
  IfFileExists "${PATH}\." ${LABEL}_exists 0
    StrCpy ${CREATED_FLAG} 1
  ${LABEL}_exists:
  ClearErrors
  StrCpy $4 "${PATH}"
  CreateDirectory "$4"
  IfErrors machine_perimeter_failed
!macroend

!macro AIVE_DELETE_KNOWN_CREDENTIAL PROVIDER KEY
  nsExec::ExecToLog '"$SYSDIR\cmdkey.exe" /delete:"AI Video Editor Desktop V2/provider/${PROVIDER}/${KEY}"'
!macroend

!macro AIVE_REPORT_MACHINE_LEFTOVER PATH LABEL
  IfFileExists "${PATH}\." ${LABEL}_leftover ${LABEL}_done
  ${LABEL}_leftover:
    DetailPrint "RC.6 machine-state cleanup is deferred until restart: ${PATH}"
    SetRebootFlag true
  ${LABEL}_done:
!macroend

!macro NSIS_HOOK_PREINSTALL
  SetShellVarContext all
  SetRegView 64
  StrCpy $INSTDIR "$PROGRAMFILES64\AI Video Editor Desktop V2\Shell"
  SetOutPath $INSTDIR

  ; Resolve the machine perimeter exactly. Never fall back to a user profile.
  StrCpy $2 "$APPDATA\AI Video Editor"
  ReadEnvStr $3 "ProgramData"
  StrCmp $3 "" machine_data_resolution_failed
  StrCpy $4 "$3\AI Video Editor"
  StrCmp $2 $4 machine_data_resolved
  DetailPrint "Unexpected machine data root. Expected: $4"
  DetailPrint "Resolved NSIS machine data root: $2"
  machine_data_resolution_failed:
    MessageBox MB_ICONSTOP|MB_OK "AI Video Editor Desktop V2 could not resolve its machine component perimeter to %ProgramData%. No partial installation will be accepted."
    Abort
  machine_data_resolved:

  ; Track only directories this transaction created. Rollback removes only
  ; those paths and only while empty, preserving all pre-existing state.
  !insertmacro AIVE_CREATE_MACHINE_DIR "$2" $TxnCreatedMachineRoot machine_root
  !insertmacro AIVE_CREATE_MACHINE_DIR "$2\Components" $TxnCreatedComponents machine_components
  !insertmacro AIVE_CREATE_MACHINE_DIR "$2\Activation" $TxnCreatedActivation machine_activation
  !insertmacro AIVE_CREATE_MACHINE_DIR "$2\Downloads" $TxnCreatedDownloads machine_downloads
  !insertmacro AIVE_CREATE_MACHINE_DIR "$2\Downloads\Staging" $TxnCreatedStaging machine_staging
  !insertmacro AIVE_CREATE_MACHINE_DIR "$2\Catalog" $TxnCreatedCatalog machine_catalog
  !insertmacro AIVE_CREATE_MACHINE_DIR "$2\Broker" $TxnCreatedBroker machine_broker
  !insertmacro AIVE_CREATE_MACHINE_DIR "$2\Broker\Requests" $TxnCreatedRequests machine_requests
  !insertmacro AIVE_CREATE_MACHINE_DIR "$2\Provisioning" $TxnCreatedProvisioning machine_provisioning
  !insertmacro AIVE_CREATE_MACHINE_DIR "$2\Installer" $TxnCreatedInstaller machine_installer
  Goto machine_perimeter_ready
  machine_perimeter_failed:
    DetailPrint "CreateDirectory failed for: $4"
    MessageBox MB_ICONSTOP|MB_OK "AI Video Editor Desktop V2 could not prepare its machine component perimeter. Failed path: $4. No partial installation will be accepted."
    Abort
  machine_perimeter_ready:

  nsExec::ExecToStack /OEM '"$SYSDIR\icacls.exe" "$2" /reset /T'
  Pop $0
  Pop $1
  DetailPrint "icacls reset exit code: $0"
  StrCmp $0 "0" acl_reset_ready
    MessageBox MB_ICONSTOP|MB_OK "AI Video Editor Desktop V2 could not reset the machine component perimeter ACL. icacls exit code: $0."
    Abort
  acl_reset_ready:
  nsExec::ExecToStack /OEM '"$SYSDIR\icacls.exe" "$2" /inheritance:r /grant:r "*S-1-5-18:(OI)(CI)(F)" "*S-1-5-32-544:(OI)(CI)(F)" "*S-1-5-32-545:(OI)(CI)(M)" /T'
  Pop $0
  Pop $1
  DetailPrint "icacls perimeter policy exit code: $0"
  StrCmp $0 "0" acl_ready
    MessageBox MB_ICONSTOP|MB_OK "AI Video Editor Desktop V2 could not secure its machine component perimeter. icacls exit code: $0."
    Abort
  acl_ready:
  nsExec::ExecToStack /OEM '"$SYSDIR\icacls.exe" "$2" /setowner "*S-1-5-32-544" /T'
  Pop $0
  Pop $1
  DetailPrint "icacls owner policy exit code: $0"
  StrCmp $0 "0" owner_ready
    MessageBox MB_ICONSTOP|MB_OK "AI Video Editor Desktop V2 could not set the machine component perimeter owner. icacls exit code: $0."
    Abort
  owner_ready:
!macroend

!macro NSIS_HOOK_POSTINSTALL
  SetShellVarContext all
  SetRegView 64

  ; This hook owns only ancillary shell state. The pinned template verifies
  ; both shortcuts and commits ARP/identity after this hook succeeds.
  FileOpen $0 "$INSTDIR\component-broker.json" w
  IfErrors broker_marker_failed
  FileWrite $0 '{"schemaVersion":"desktop.component-broker.v1","identifier":"aive-component-broker","scope":"per-machine","productIdentifier":"com.fyp.ai-video-editor.desktop-v2"}'
  FileClose $0
  Goto broker_marker_done
  broker_marker_failed:
    MessageBox MB_ICONSTOP|MB_OK "AI Video Editor Desktop V2 could not write its component repair marker. Setup was aborted."
    Abort
  broker_marker_done:

  ; Persist handoff provenance only for the bounded portable handoff layout.
  ; A .part file and MoveFileEx(REPLACE_EXISTING) make publication atomic.
  IfFileExists "$EXEDIR\Catalog\offline-catalog.json" 0 handoff_origin_done
  IfFileExists "$EXEDIR\Components\." 0 handoff_origin_done
  IfFileExists "$PROGRAMDATA\AI Video Editor\Installer\handoff-root.json" 0 handoff_origin_no_prior
    ClearErrors
    CopyFiles /SILENT "$PROGRAMDATA\AI Video Editor\Installer\handoff-root.json" "$PROGRAMDATA\AI Video Editor\Installer\handoff-root.json.rc6-rollback"
    IfErrors handoff_origin_failed
    StrCpy $TxnHadInstallerOrigin 1
  handoff_origin_no_prior:
  ${WordReplace} "$EXEDIR" "\" "/" "+*" $7
  Delete "$PROGRAMDATA\AI Video Editor\Installer\handoff-root.json.part"
  FileOpen $0 "$PROGRAMDATA\AI Video Editor\Installer\handoff-root.json.part" w
  IfErrors handoff_origin_failed
  FileWrite $0 '{"schemaVersion":"desktop.installer-handoff-origin.v1","handoffRoot":"$7","catalogRelativePath":"Catalog/offline-catalog.json","componentsRelativePath":"Components"}'
  FileClose $0
  StrCpy $TxnWroteInstallerOrigin 1
  System::Call 'kernel32::MoveFileExW(w "$PROGRAMDATA\AI Video Editor\Installer\handoff-root.json.part", w "$PROGRAMDATA\AI Video Editor\Installer\handoff-root.json", i 0x1) i .r0'
  StrCmp $0 0 handoff_origin_failed handoff_origin_done
  handoff_origin_failed:
    MessageBox MB_ICONSTOP|MB_OK "AI Video Editor Desktop V2 could not atomically persist the installer handoff origin. Setup was aborted."
    Abort
  handoff_origin_done:
!macroend

!macro NSIS_HOOK_PREUNINSTALL
  SetShellVarContext all
!macroend

!macro NSIS_HOOK_POSTUNINSTALL
  ; Capture per-user roots before switching to the all-users shell context.
  SetShellVarContext current
  StrCpy $5 "$LOCALAPPDATA\AI Video Editor"
  StrCpy $6 "$DOCUMENTS\AI Video Editor"
  SetShellVarContext all
  SetRegView 64

  ; Default uninstall removes application/runtime state, including installer
  ; provenance, but preserves settings, content, databases, models, projects,
  ; exports, and every Credential Manager entry.
  StrCpy $2 "$APPDATA\AI Video Editor"
  ReadEnvStr $3 "ProgramData"
  StrCpy $4 "$3\AI Video Editor"
  StrCmp $2 $4 machine_cleanup_resolved
    DetailPrint "Skipping machine cleanup because NSIS resolved an unexpected root: $2"
    Goto machine_cleanup_done
  machine_cleanup_resolved:
    Delete /REBOOTOK "$2\Installer\handoff-root.json"
    Delete /REBOOTOK "$2\Installer\handoff-root.json.part"
    Delete /REBOOTOK "$2\Installer\handoff-root.json.rc6-rollback"
    RMDir /r "$2\Components"
    RMDir /r "$2\Activation"
    RMDir /r "$2\Downloads\Staging"
    RMDir /r "$2\Catalog"
    RMDir /r "$2\Broker\Requests"
    RMDir /r "$2\Provisioning"
    RMDir /r "$2\Installer"
    RMDir "$2\Broker"
    RMDir "$2\Downloads"
    RMDir "$2"
    !insertmacro AIVE_REPORT_MACHINE_LEFTOVER "$2\Components" report_components
    !insertmacro AIVE_REPORT_MACHINE_LEFTOVER "$2\Activation" report_activation
    !insertmacro AIVE_REPORT_MACHINE_LEFTOVER "$2\Downloads" report_downloads
    !insertmacro AIVE_REPORT_MACHINE_LEFTOVER "$2\Catalog" report_catalog
    !insertmacro AIVE_REPORT_MACHINE_LEFTOVER "$2\Broker" report_broker
    !insertmacro AIVE_REPORT_MACHINE_LEFTOVER "$2\Provisioning" report_provisioning
    !insertmacro AIVE_REPORT_MACHINE_LEFTOVER "$2\Installer" report_installer
    !insertmacro AIVE_REPORT_MACHINE_LEFTOVER "$2" report_machine_root
  machine_cleanup_done:
  RMDir /r "$5\Cache"
  RMDir /r "$5\Temp"
  RMDir /r "$5\Logs"
  RMDir /r "$5\State"
  RMDir "$5"

  ; Full wipe is separately allowlisted and reachable only from the explicit,
  ; unchecked UI choice or the exact unattended token handled by the template.
  StrCmp $FullWipeCheckboxState 1 0 full_wipe_done
    RMDir /r "$5\Config"
    RMDir /r "$5\uploads"
    RMDir /r "$5\models"
    RMDir /r "$5\database"
    RMDir /r "$5\postgresql"
    RMDir /r "$5\qdrant"
    RMDir /r "$6\Projects"
    RMDir /r "$6\Exports"
    RMDir /r "$6\Models"
    RMDir "$6"
    !insertmacro AIVE_DELETE_KNOWN_CREDENTIAL mistral api_key
    !insertmacro AIVE_DELETE_KNOWN_CREDENTIAL mistral access_token
    !insertmacro AIVE_DELETE_KNOWN_CREDENTIAL mistral password
    !insertmacro AIVE_DELETE_KNOWN_CREDENTIAL mistral hf_token
    !insertmacro AIVE_DELETE_KNOWN_CREDENTIAL mistral custom_endpoint_key
    !insertmacro AIVE_DELETE_KNOWN_CREDENTIAL openai api_key
    !insertmacro AIVE_DELETE_KNOWN_CREDENTIAL openai access_token
    !insertmacro AIVE_DELETE_KNOWN_CREDENTIAL openai password
    !insertmacro AIVE_DELETE_KNOWN_CREDENTIAL openai hf_token
    !insertmacro AIVE_DELETE_KNOWN_CREDENTIAL openai custom_endpoint_key
    !insertmacro AIVE_DELETE_KNOWN_CREDENTIAL deepseek api_key
    !insertmacro AIVE_DELETE_KNOWN_CREDENTIAL deepseek access_token
    !insertmacro AIVE_DELETE_KNOWN_CREDENTIAL deepseek password
    !insertmacro AIVE_DELETE_KNOWN_CREDENTIAL deepseek hf_token
    !insertmacro AIVE_DELETE_KNOWN_CREDENTIAL deepseek custom_endpoint_key
    !insertmacro AIVE_DELETE_KNOWN_CREDENTIAL alibaba api_key
    !insertmacro AIVE_DELETE_KNOWN_CREDENTIAL alibaba access_token
    !insertmacro AIVE_DELETE_KNOWN_CREDENTIAL alibaba password
    !insertmacro AIVE_DELETE_KNOWN_CREDENTIAL alibaba hf_token
    !insertmacro AIVE_DELETE_KNOWN_CREDENTIAL alibaba custom_endpoint_key
  full_wipe_done:
!macroend
