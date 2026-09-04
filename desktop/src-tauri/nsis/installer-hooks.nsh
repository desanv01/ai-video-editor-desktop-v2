; AI Video Editor Desktop V2 RC.6 per-machine policy hooks.
; installer-template.nsi is the single owner of payload transaction state,
; shortcuts, committed identity, ARP registration, and Program Files cleanup.
; Program Files remains immutable at runtime; scoped machine writes use the
; exact ProgramData perimeter and per-user content remains preserve-by-default.

!macro AIVE_REPARSE_RESULT PATH RESULT
  StrCpy ${RESULT} 0
  System::Call 'kernel32::GetFileAttributesW(w "${PATH}") i .r0'
  IntCmp $0 -1 +3
  IntOp $0 $0 & 0x400
  StrCmp $0 0 +2
    StrCpy ${RESULT} 1
!macroend

!macro AIVE_CREATE_MACHINE_DIR PATH CREATED_FLAG LABEL
  IfFileExists "${PATH}\." ${LABEL}_exists ${LABEL}_create
  ${LABEL}_exists:
    StrCpy $4 "${PATH}"
    !insertmacro AIVE_REPARSE_RESULT "${PATH}" $7
    StrCmp $7 1 machine_perimeter_reparse
    Goto ${LABEL}_ready
  ${LABEL}_create:
    StrCpy ${CREATED_FLAG} 1
  ${LABEL}_ready:
  ClearErrors
  StrCpy $4 "${PATH}"
  CreateDirectory "$4"
  IfErrors machine_perimeter_failed
  Call WriteTransactionJournal
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

!macro AIVE_REMOVE_OWNED_TREE PATH LABEL
  Push "${PATH}"
  Call un.RemoveTreeNoReparse
!macroend

!macro NSIS_HOOK_PREINSTALL
  SetShellVarContext all
  SetRegView 64

  ; Resolve the machine perimeter exactly. Never fall back to a user profile.
  StrCpy $2 "$APPDATA\AI Video Editor"
  ReadEnvStr $3 "ProgramData"
  StrCmp $3 "" machine_data_resolution_failed
  StrCpy $4 "$3\AI Video Editor"
  StrCmp $2 $4 machine_data_resolved
  DetailPrint "Unexpected machine data root. Expected: $4"
  DetailPrint "Resolved NSIS machine data root: $2"
  machine_data_resolution_failed:
    StrCpy $FailureCode ${AIVE_E_INVARIANT}
    StrCpy $FailureStage "machine-perimeter"
    StrCpy $FailureMessage "Setup could not resolve its machine component perimeter to ProgramData."
    Call FailInstall
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
  machine_perimeter_reparse:
    DetailPrint "Refusing reparse-point machine perimeter directory: $4"
    StrCpy $FailureCode ${AIVE_E_CONFLICT}
    StrCpy $FailureStage "machine-perimeter-reparse"
    StrCpy $FailureMessage "Setup found a reparse point inside its machine component perimeter. Preserve it and resolve the conflict manually."
    Call FailInstall
  machine_perimeter_failed:
    DetailPrint "CreateDirectory failed for: $4"
    StrCpy $FailureCode ${AIVE_E_INVARIANT}
    StrCpy $FailureStage "machine-perimeter"
    StrCpy $FailureMessage "Setup could not prepare an owned machine component directory."
    Call FailInstall
  machine_perimeter_ready:

  ; Apply policy at the owned root without recursively rewriting ACLs or
  ; ownership on pre-existing component/user-created content.
  nsExec::ExecToStack /OEM '"$SYSDIR\icacls.exe" "$2" /inheritance:r /grant:r "*S-1-5-18:(OI)(CI)(F)" "*S-1-5-32-544:(OI)(CI)(F)" "*S-1-5-32-545:(OI)(CI)(M)"'
  Pop $0
  Pop $1
  DetailPrint "icacls perimeter policy exit code: $0"
  StrCmp $0 "0" acl_ready
    StrCpy $FailureCode ${AIVE_E_INVARIANT}
    StrCpy $FailureStage "machine-acl"
    StrCpy $FailureMessage "Setup could not secure its machine component perimeter."
    Call FailInstall
  acl_ready:
  nsExec::ExecToStack /OEM '"$SYSDIR\icacls.exe" "$2" /setowner "*S-1-5-32-544"'
  Pop $0
  Pop $1
  DetailPrint "icacls owner policy exit code: $0"
  StrCmp $0 "0" owner_ready
    StrCpy $FailureCode ${AIVE_E_INVARIANT}
    StrCpy $FailureStage "machine-owner"
    StrCpy $FailureMessage "Setup could not set the machine component perimeter owner."
    Call FailInstall
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
    StrCpy $FailureCode ${AIVE_E_IDENTITY}
    StrCpy $FailureStage "identity-component"
    StrCpy $FailureMessage "Setup could not write its component repair identity marker."
    Call FailInstall
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
    Call WriteTransactionJournal
  handoff_origin_no_prior:
  ${WordReplace} "$EXEDIR" "\" "/" "+*" $7
  Delete "$PROGRAMDATA\AI Video Editor\Installer\handoff-root.json.part"
  FileOpen $0 "$PROGRAMDATA\AI Video Editor\Installer\handoff-root.json.part" w
  IfErrors handoff_origin_failed
  FileWrite $0 '{"schemaVersion":"desktop.installer-handoff-origin.v1","handoffRoot":"$7","catalogRelativePath":"Catalog/offline-catalog.json","componentsRelativePath":"Components"}'
  FileClose $0
  StrCpy $TxnWroteInstallerOrigin 1
  Call WriteTransactionJournal
  System::Call 'kernel32::MoveFileExW(w "$PROGRAMDATA\AI Video Editor\Installer\handoff-root.json.part", w "$PROGRAMDATA\AI Video Editor\Installer\handoff-root.json", i 0x1) i .r0'
  StrCmp $0 0 handoff_origin_failed handoff_origin_done
  handoff_origin_failed:
    StrCpy $FailureCode ${AIVE_E_HANDOFF}
    StrCpy $FailureStage "handoff"
    StrCpy $FailureMessage "Setup could not atomically persist the installer handoff origin."
    Call FailInstall
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
    !insertmacro AIVE_REPARSE_RESULT "$2" $7
    StrCmp $7 1 0 machine_cleanup_not_reparse
      DetailPrint "Preserving reparse-point machine root: $2"
      Goto machine_cleanup_done
  machine_cleanup_not_reparse:
    Delete /REBOOTOK "$2\Installer\handoff-root.json"
    Delete /REBOOTOK "$2\Installer\handoff-root.json.part"
    Delete /REBOOTOK "$2\Installer\handoff-root.json.rc6-rollback"
    !insertmacro AIVE_REMOVE_OWNED_TREE "$2\Components" cleanup_components
    !insertmacro AIVE_REMOVE_OWNED_TREE "$2\Activation" cleanup_activation
    !insertmacro AIVE_REMOVE_OWNED_TREE "$2\Downloads\Staging" cleanup_staging
    !insertmacro AIVE_REMOVE_OWNED_TREE "$2\Catalog" cleanup_catalog
    !insertmacro AIVE_REMOVE_OWNED_TREE "$2\Broker\Requests" cleanup_requests
    !insertmacro AIVE_REMOVE_OWNED_TREE "$2\Provisioning" cleanup_provisioning
    ; Keep redacted installer/uninstaller logs for durable diagnostics.
    Delete /REBOOTOK "$2\Installer\transaction-rc6.json"
    Delete /REBOOTOK "$2\Installer\transaction-rc6.json.part"
    RMDir "$2\Installer"
    RMDir "$2\Broker"
    RMDir "$2\Downloads"
    RMDir "$2"
    !insertmacro AIVE_REPORT_MACHINE_LEFTOVER "$2\Components" report_components
    !insertmacro AIVE_REPORT_MACHINE_LEFTOVER "$2\Activation" report_activation
    !insertmacro AIVE_REPORT_MACHINE_LEFTOVER "$2\Downloads" report_downloads
    !insertmacro AIVE_REPORT_MACHINE_LEFTOVER "$2\Catalog" report_catalog
    !insertmacro AIVE_REPORT_MACHINE_LEFTOVER "$2\Broker" report_broker
    !insertmacro AIVE_REPORT_MACHINE_LEFTOVER "$2\Provisioning" report_provisioning
  machine_cleanup_done:
  !insertmacro AIVE_REPARSE_RESULT "$5" $7
  StrCmp $7 1 local_runtime_done
    !insertmacro AIVE_REMOVE_OWNED_TREE "$5\Cache" cleanup_user_cache
    !insertmacro AIVE_REMOVE_OWNED_TREE "$5\Temp" cleanup_user_temp
    !insertmacro AIVE_REMOVE_OWNED_TREE "$5\Logs" cleanup_user_logs
    !insertmacro AIVE_REMOVE_OWNED_TREE "$5\State" cleanup_user_state
    RMDir "$5"
  local_runtime_done:

  ; Full wipe is separately allowlisted and reachable only from the explicit,
  ; unchecked UI choice or the exact unattended token handled by the template.
  StrCmp $FullWipeCheckboxState 1 0 full_wipe_done
    !insertmacro AIVE_REPARSE_RESULT "$5" $7
    StrCmp $7 1 full_wipe_documents
    !insertmacro AIVE_REMOVE_OWNED_TREE "$5\Config" cleanup_user_config
    !insertmacro AIVE_REMOVE_OWNED_TREE "$5\uploads" cleanup_user_uploads
    !insertmacro AIVE_REMOVE_OWNED_TREE "$5\models" cleanup_user_models
    !insertmacro AIVE_REMOVE_OWNED_TREE "$5\database" cleanup_user_database
    !insertmacro AIVE_REMOVE_OWNED_TREE "$5\postgresql" cleanup_user_postgresql
    !insertmacro AIVE_REMOVE_OWNED_TREE "$5\qdrant" cleanup_user_qdrant
  full_wipe_documents:
    !insertmacro AIVE_REPARSE_RESULT "$6" $7
    StrCmp $7 1 full_wipe_credentials
    !insertmacro AIVE_REMOVE_OWNED_TREE "$6\Projects" cleanup_documents_projects
    !insertmacro AIVE_REMOVE_OWNED_TREE "$6\Exports" cleanup_documents_exports
    !insertmacro AIVE_REMOVE_OWNED_TREE "$6\Models" cleanup_documents_models
    RMDir "$6"
  full_wipe_credentials:
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
