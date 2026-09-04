Unicode true
SilentInstall silent
RequestExecutionLevel user
!include FileFunc.nsh
!include LogicLib.nsh

Name "AIVE RC6 Installer State Matrix"
OutFile "nsis-state-matrix-harness.exe"

Var Root
Var Case
Var RunId
Var Result
Var Shell
Var Stage
Var Backup
Var Safe
Var RegKey
Var CredKey
Var State
Var Code
Var PriorReg
Var PriorInstallPath
Var PriorArp
Var PriorCommitted
Var PriorDesktop
Var PriorStartMenu

Function WriteResult
  FileOpen $0 "$Result" w
  FileWrite $0 "case=$Case$\r$\nstate=$State$\r$\ncode=$Code$\r$\noutdir=$OUTDIR$\r$\n"
  FileClose $0
FunctionEnd

Function Fail
  Call WriteResult
  SetErrorLevel $Code
  Quit
FunctionEnd

Function SafeCwd
  InitPluginsDir
  SetOutPath "$PLUGINSDIR"
  StrCpy $Safe "$PLUGINSDIR"
FunctionEnd

Function ValidateRoot
  StrCmp $Root "" root_invalid_empty
  GetFullPathName $Root "$Root"
  StrCpy $0 "$TEMP\AIVE-Installer-StateMatrix\"
  GetFullPathName $0 "$0"
  StrLen $1 $0
  StrCpy $2 $Root $1
  StrCmp $2 $0 0 root_invalid_prefix
  ${GetParent} "$Result" $2
  GetFullPathName $2 "$2"
  StrCmp $2 $Root 0 root_invalid_result
  StrCmp $RunId "" root_invalid_runid root_valid
  root_invalid_empty:
    StrCpy $Code 2111
    Goto root_invalid
  root_invalid_prefix:
    StrCpy $Code 2111
    Goto root_invalid
  root_invalid_result:
    StrCpy $Code 2111
    Goto root_invalid
  root_invalid_runid:
    StrCpy $Code 2111
  root_invalid:
    StrCpy $State "rejected-root"
    SetErrorLevel $Code
    Quit
  root_valid:
FunctionEnd

Function AssertSafeCwd
  StrCmp $OUTDIR "$Shell" cwd_unsafe
  StrCmp $OUTDIR "$Stage" cwd_unsafe
  StrCmp $OUTDIR "$Backup" cwd_unsafe cwd_safe
  cwd_unsafe:
    StrCpy $State "unsafe-cwd"
    StrCpy $Code 2114
    Call Fail
  cwd_safe:
FunctionEnd

Function IsEmpty
  StrCpy $1 1
  FindFirst $2 $3 "$0\*"
  IfErrors empty_done
  empty_loop:
    StrCmp $3 "." empty_next
    StrCmp $3 ".." empty_next
    StrCpy $1 0
    Goto empty_close
  empty_next:
    ClearErrors
    FindNext $2 $3
    IfErrors empty_close empty_loop
  empty_close:
    FindClose $2
  empty_done:
FunctionEnd

Function HasPayload
  StrCpy $1 0
  IfFileExists "$0\desktop-v2.identity.json" 0 payload_done
  IfFileExists "$0\ai-video-editor.exe" 0 payload_done
  IfFileExists "$0\uninstall.exe" 0 payload_done
  StrCpy $1 1
  payload_done:
FunctionEnd

Function RemoveOwned
  Call SafeCwd
  Call AssertSafeCwd
  Delete "$0\.installing"
  Delete "$0\desktop-v2.identity.json"
  Delete "$0\desktop-v2.identity.json.part"
  Delete "$0\ai-video-editor.exe"
  Delete "$0\uninstall.exe"
  Delete "$0\payload.dat"
  RMDir "$0"
FunctionEnd

Function SnapshotPrior
  StrCpy $PriorReg 0
  StrCpy $PriorDesktop 0
  StrCpy $PriorStartMenu 0
  ClearErrors
  ReadRegStr $PriorInstallPath HKCU "$RegKey" "InstallPath"
  IfErrors snapshot_shortcuts
  StrCpy $PriorReg 1
  ReadRegStr $PriorArp HKCU "$RegKey" "Arp"
  ClearErrors
  ReadRegDWORD $PriorCommitted HKCU "$RegKey" "InstallCommitted"
  IfErrors 0 snapshot_shortcuts
    StrCpy $PriorCommitted 0
  snapshot_shortcuts:
  CreateDirectory "$Root\Txn"
  IfFileExists "$Root\Shortcuts\Desktop.lnk" 0 snapshot_start
    CopyFiles /SILENT "$Root\Shortcuts\Desktop.lnk" "$Root\Txn\Desktop.lnk"
    StrCpy $PriorDesktop 1
  snapshot_start:
  IfFileExists "$Root\Shortcuts\StartMenu.lnk" 0 snapshot_done
    CopyFiles /SILENT "$Root\Shortcuts\StartMenu.lnk" "$Root\Txn\StartMenu.lnk"
    StrCpy $PriorStartMenu 1
  snapshot_done:
FunctionEnd

Function RestorePrior
  DeleteRegKey HKCU "$RegKey"
  StrCmp $PriorReg 1 0 restore_shortcuts
    WriteRegStr HKCU "$RegKey" "InstallPath" "$PriorInstallPath"
    WriteRegStr HKCU "$RegKey" "Arp" "$PriorArp"
    WriteRegDWORD HKCU "$RegKey" "InstallCommitted" $PriorCommitted
  restore_shortcuts:
  Delete "$Root\Shortcuts\Desktop.lnk"
  Delete "$Root\Shortcuts\StartMenu.lnk"
  StrCmp $PriorDesktop 1 0 +2
    CopyFiles /SILENT "$Root\Txn\Desktop.lnk" "$Root\Shortcuts\Desktop.lnk"
  StrCmp $PriorStartMenu 1 0 +2
    CopyFiles /SILENT "$Root\Txn\StartMenu.lnk" "$Root\Shortcuts\StartMenu.lnk"
  Delete "$Root\Txn\Desktop.lnk"
  Delete "$Root\Txn\StartMenu.lnk"
  RMDir "$Root\Txn"
FunctionEnd

Function Classify
  StrCpy $State "pristine"
  IfFileExists "$Shell\." classify_shell classify_registry
  classify_shell:
    StrCpy $0 "$Shell"
    Call IsEmpty
    StrCmp $1 1 classify_empty
    StrCpy $0 "$Shell"
    Call HasPayload
    StrCmp $1 1 classify_payload classify_conflict
  classify_empty:
    StrCpy $State "empty-owned-residue"
    Return
  classify_payload:
    ReadRegDWORD $0 HKCU "$RegKey" "InstallCommitted"
    ReadRegStr $1 HKCU "$RegKey" "InstallPath"
    ReadRegStr $2 HKCU "$RegKey" "Arp"
    StrCmp $0 1 0 classify_repair
    StrCmp $1 "$Shell" 0 classify_repair
    StrCmp $2 "present" 0 classify_repair
    StrCpy $State "valid-committed"
    Return
  classify_repair:
    StrCpy $State "repairable-registration"
    Return
  classify_registry:
    ReadRegStr $0 HKCU "$RegKey" "InstallPath"
    StrCmp $0 "" classify_done
    StrCpy $State "orphan-registration"
    Return
  classify_conflict:
    StrCpy $State "unknown-nonempty-or-reparse"
  classify_done:
FunctionEnd

Function Recover
  IfFileExists "$Stage\." 0 recover_backup
    IfFileExists "$Stage\.installing" 0 recover_conflict
    StrCpy $0 "$Stage"
    Call RemoveOwned
  recover_backup:
  IfFileExists "$Backup\." 0 recover_partial_live
    StrCpy $0 "$Backup"
    Call HasPayload
    StrCmp $1 1 recover_owned_backup recover_conflict
  recover_owned_backup:
    IfFileExists "$Shell\." recover_both recover_restore
  recover_both:
    IfFileExists "$Shell\.installing" recover_remove_live 0
    StrCpy $0 "$Shell"
    Call HasPayload
    StrCmp $1 1 recover_remove_backup recover_conflict
  recover_remove_live:
    StrCpy $0 "$Shell"
    Call RemoveOwned
    Goto recover_restore
  recover_remove_backup:
    StrCpy $0 "$Backup"
    Call RemoveOwned
    Return
  recover_restore:
    Call SafeCwd
    Call AssertSafeCwd
    Rename "$Backup" "$Shell"
    IfErrors recover_rollback_failed
    Return
  recover_partial_live:
    IfFileExists "$Shell\.installing" 0 recover_done
    StrCpy $0 "$Shell"
    Call RemoveOwned
    Return
  recover_conflict:
    StrCpy $State "conflict-preserved"
    StrCpy $Code 2112
    Call Fail
  recover_rollback_failed:
    StrCpy $State "rollback-pending"
    StrCpy $Code 2110
    Call Fail
  recover_done:
FunctionEnd

Function StagePayload
  CreateDirectory "$Stage"
  FileOpen $0 "$Stage\.installing" w
  FileWrite $0 "owned"
  FileClose $0
  FileOpen $0 "$Stage\ai-video-editor.exe" w
  FileWrite $0 "new"
  FileClose $0
  FileOpen $0 "$Stage\uninstall.exe" w
  FileWrite $0 "new"
  FileClose $0
  FileOpen $0 "$Stage\payload.dat" w
  FileWrite $0 "new"
  FileClose $0
  SetOutPath "$Stage"
FunctionEnd

Function Rollback
  IfFileExists "$Stage\.installing" 0 rollback_live
    StrCpy $0 "$Stage"
    Call RemoveOwned
  rollback_live:
  IfFileExists "$Shell\.installing" 0 rollback_prior
    StrCpy $0 "$Shell"
    Call RemoveOwned
  rollback_prior:
  IfFileExists "$Backup\." 0 rollback_registry
    Call SafeCwd
    Call AssertSafeCwd
    Rename "$Backup" "$Shell"
    IfErrors rollback_incomplete
  rollback_registry:
    Call RestorePrior
    Return
  rollback_incomplete:
    StrCpy $State "rollback-pending"
    StrCpy $Code 2110
    Call Fail
FunctionEnd

Section
  ${GetOptions} $CMDLINE "/AIVE_TEST_ROOT=" $Root
  ${GetOptions} $CMDLINE "/CASE=" $Case
  ${GetOptions} $CMDLINE "/RUNID=" $RunId
  ${GetOptions} $CMDLINE "/RESULT=" $Result
  StrCpy $Code 0
  StrCpy $State "initial"
  Call ValidateRoot
  StrCpy $Shell "$Root\ProgramFiles\AI Video Editor Desktop V2\Shell"
  StrCpy $Stage "$Root\ProgramFiles\AI Video Editor Desktop V2\Shell.rc6-staging"
  StrCpy $Backup "$Root\ProgramFiles\AI Video Editor Desktop V2\Shell.rc6-rollback"
  StrCpy $RegKey "Software\AIVE Installer State Matrix\$RunId"
  StrCpy $CredKey "Software\AIVE Installer State Matrix Credentials\$RunId"
  Call SafeCwd
  System::Call 'kernel32::CreateMutexW(p0, i0, w "Local\AIVE-RC6-StateMatrix-$RunId") p .rMutex ?e'
  Pop $0
  StrCmp $0 183 concurrent_failed
  StrCmp $Case "hold-mutex" 0 after_hold
    Sleep 3000
    StrCpy $State "mutex-held"
    Call WriteResult
    Goto done
  after_hold:
  StrCmp $Case "classify-only" 0 after_classify
    Call Classify
    Call WriteResult
    Goto done
  after_classify:
  StrCmp $Case "recover-only" 0 after_recover
    Call Recover
    Call Classify
    Call WriteResult
    Goto done
  after_recover:
  StrCmp $Case "uninstall-locked" 0 after_locked_uninstall
    StrCpy $0 "$Shell"
    Call RemoveOwned
    IfFileExists "$Shell\." 0 unlocked_unexpected
      StrCpy $State "uninstall-lock-preserved"
      StrCpy $Code 2105
      Call Fail
    unlocked_unexpected:
      StrCpy $State "uninstall-lock-missing"
      StrCpy $Code 2114
      Call Fail
  after_locked_uninstall:
  StrCmp $Case "uninstall-default" 0 after_default_uninstall
    StrCpy $0 "$Shell"
    Call RemoveOwned
    RMDir /r "$Root\Runtime"
    DeleteRegKey HKCU "$RegKey"
    StrCpy $State "uninstalled-preserve-data"
    Call WriteResult
    Goto done
  after_default_uninstall:
  StrCmp $Case "uninstall-full-wipe" 0 install_case
    StrCpy $0 "$Shell"
    Call RemoveOwned
    RMDir /r "$Root\Runtime"
    RMDir /r "$Root\UserData\Config"
    RMDir /r "$Root\UserData\uploads"
    RMDir /r "$Root\UserData\models"
    RMDir /r "$Root\UserData\database"
    RMDir /r "$Root\Documents\Projects"
    RMDir /r "$Root\Documents\Exports"
    DeleteRegKey HKCU "$RegKey"
    DeleteRegKey HKCU "$CredKey"
    StrCpy $State "uninstalled-full-wipe"
    Call WriteResult
    Goto done
  install_case:
    Call Recover
    Call Classify
    StrCmp $State "unknown-nonempty-or-reparse" conflict_failed
    StrCmp $State "empty-owned-residue" 0 +4
      Call SafeCwd
      RMDir "$Shell"
      StrCpy $State "pristine"
    StrCmp $State "orphan-registration" 0 +2
      DeleteRegKey HKCU "$RegKey"
    Call SnapshotPrior
    Call StagePayload
    StrCmp $Case "lock-install" lock_install_case after_lock_install
    lock_install_case:
      StrCpy $State "lock-refused"
      StrCpy $Code 2105
      Call Rollback
      Call Fail
    after_lock_install:
    StrCmp $Case "fail-staging" fail_staging_case after_fail_staging
    fail_staging_case:
      StrCpy $State "fault-staging"
      StrCpy $Code 2104
      Call Rollback
      Call Fail
    after_fail_staging:
    StrCmp $State "valid-committed" move_prior
    StrCmp $State "repairable-registration" move_prior activate
  move_prior:
    Call SafeCwd
    Call AssertSafeCwd
    Rename "$Shell" "$Backup"
    IfErrors lock_failed
    StrCmp $Case "fail-prior-move" fail_prior_move_case activate
    fail_prior_move_case:
      StrCpy $State "fault-prior-move"
      StrCpy $Code 2104
      Call Rollback
      Call Fail
  activate:
    Call SafeCwd
    Call AssertSafeCwd
    Rename "$Stage" "$Shell"
    IfErrors activation_failed
    StrCmp $Case "fail-activation" fail_activation_case commit
    fail_activation_case:
      StrCpy $State "fault-activation"
      StrCpy $Code 2106
      Call Rollback
      Call Fail
  commit:
    CreateDirectory "$Root\Shortcuts"
    FileOpen $0 "$Root\Shortcuts\Desktop.lnk" w
    FileWrite $0 "$Shell\ai-video-editor.exe"
    FileClose $0
    FileOpen $0 "$Root\Shortcuts\StartMenu.lnk" w
    FileWrite $0 "$Shell\ai-video-editor.exe"
    FileClose $0
    StrCmp $Case "fail-shortcut" fail_shortcut_case commit_registry
    fail_shortcut_case:
      StrCpy $State "fault-shortcut"
      StrCpy $Code 2103
      Call Rollback
      Call Fail
  commit_registry:
    WriteRegStr HKCU "$RegKey" "InstallPath" "$Shell"
    WriteRegStr HKCU "$RegKey" "Arp" "present"
    WriteRegDWORD HKCU "$RegKey" "InstallCommitted" 0
    StrCmp $Case "fail-registration" fail_registration_case commit_identity
    fail_registration_case:
      StrCpy $State "fault-registration"
      StrCpy $Code 2108
      Call Rollback
      Call Fail
  commit_identity:
    FileOpen $0 "$Shell\desktop-v2.identity.json.part" w
    FileWrite $0 "owned"
    FileClose $0
    Rename "$Shell\desktop-v2.identity.json.part" "$Shell\desktop-v2.identity.json"
    StrCmp $Case "fail-identity" fail_identity_case publish_commit
    fail_identity_case:
      StrCpy $State "fault-identity"
      StrCpy $Code 2109
      Call Rollback
      Call Fail
  publish_commit:
    WriteRegDWORD HKCU "$RegKey" "InstallCommitted" 1
    Delete "$Shell\.installing"
    StrCpy $0 "$Backup"
    Call RemoveOwned
    Delete "$Root\Txn\Desktop.lnk"
    Delete "$Root\Txn\StartMenu.lnk"
    RMDir "$Root\Txn"
    StrCpy $State "committed"
    Call WriteResult
    Goto done
  concurrent_failed:
    StrCpy $State "concurrent-refused"
    StrCpy $Code 2113
    Call Fail
  conflict_failed:
    StrCpy $State "conflict-preserved"
    StrCpy $Code 2112
    Call Fail
  lock_failed:
    StrCpy $State "lock-refused"
    StrCpy $Code 2105
    Call Rollback
    Call Fail
  activation_failed:
    StrCpy $State "activation-refused"
    StrCpy $Code 2106
    Call Rollback
    Call Fail
  done:
  System::Call 'kernel32::CloseHandle(p rMutex)'
SectionEnd
