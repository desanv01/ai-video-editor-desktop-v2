import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const read = relative => readFile(path.join(repoRoot, relative), "utf8");
const [configText, template, hook] = await Promise.all([
  read("desktop/src-tauri/tauri.conf.json"), read("desktop/src-tauri/nsis/installer-template.nsi"), read("desktop/src-tauri/nsis/installer-hooks.nsh"),
]);
const config = JSON.parse(configText);
const executable = source => source.split(/\r?\n/).filter(line => !/^\s*;/.test(line)).join("\n");
const templateCode = executable(template);
const hookCode = executable(hook);

assert.equal(config.bundle.windows.nsis.template, "nsis/installer-template.nsi");
assert.match(template, /tauri-v2\.11\.2 installer\.nsi/i);
assert.doesNotMatch(templateCode, /MUI_PAGE_DIRECTORY|MUI_PAGE_STARTMENU|MUI_FINISHPAGE_SHOWREADME/);
assert.match(template, /InstallDir "\$\{AIVEINSTALLDIR\}"/);
assert.match(template, /Function \.onInit[\s\S]*?Call SetCanonicalInstallDir[\s\S]*?Call SetSafeWorkingDir[\s\S]*?Call ClassifyInstallState[\s\S]*?Call RecoverInterruptedInstall[\s\S]*?Call ResolveClassifiedInstallState/);
assert.match(template, /AIVEINSTALLDIR "\$\{AIVEINSTALLERPARENT\}\\Shell"/);
assert.match(template, /AIVESTAGINGDIR "\$\{AIVEINSTALLERPARENT\}\\Shell\.rc6-staging"/);

const functionBody = (source, name) => {
  const start = source.indexOf("Function " + name);
  const end = source.indexOf("FunctionEnd", start);
  assert.ok(start >= 0 && end > start, name + " must exist");
  return source.slice(start, end);
};
assert.doesNotMatch(functionBody(templateCode, "SetCanonicalInstallDir"), /\bSetOutPath\b/i);
assert.doesNotMatch(hookCode, /\bSetOutPath\b/i);
assert.doesNotMatch(templateCode + "\n" + hookCode, /\bSetOutPath\s+"?\$\{AIVEINSTALLDIR\}"?|\bSetOutPath\s+"?\$PROGRAMFILES64/i);
assert.equal((templateCode.match(/\bSetOutPath\s+"?\$\{AIVESTAGINGDIR\}"?/gi) ?? []).length, 2);
assert.match(functionBody(templateCode, "ProtectAndActivateStaging"), /Call SetSafeWorkingDir[\s\S]*?Rename "\$\{AIVEINSTALLDIR\}" "\$\{AIVEBACKUPDIR\}"[\s\S]*?Call SetSafeWorkingDir[\s\S]*?Rename "\$\{AIVESTAGINGDIR\}" "\$\{AIVEINSTALLDIR\}"/);

assert.equal((templateCode.match(/\bCreateShortcut\b/gi) ?? []).length, 2);
assert.doesNotMatch(hookCode, /\bCreateShortcut\b/i);
assert.match(template, /CreateShortcut "\$\{AIVESTARTMENULINK\}"[\s\S]*?CreateShortcut "\$\{AIVEDESKTOPLINK\}"/);
assert.equal((template.match(/!insertmacro IsShortcutTarget/g) ?? []).length, 6);

const install = template.slice(template.indexOf("Section Install"), template.indexOf("Function CreateAndVerifyRequiredShortcuts"));
const ordered = ["Call BeginInstallTransaction", 'SetOutPath "${AIVESTAGINGDIR}"', 'File "${MAINBINARYSRCPATH}"', "WriteUninstaller", "Call ValidateStagingPayload", "Call ProtectAndActivateStaging", "Call CreateAndVerifyRequiredShortcuts", "NSIS_HOOK_POSTINSTALL", "Call CommitInstallRegistration", "Call PublishCommittedIdentity"];
for (const marker of ordered) assert.ok(install.includes(marker), `install transaction is missing ${marker}`);
for (let i = 1; i < ordered.length; i += 1) assert.ok(install.indexOf(ordered[i - 1]) < install.indexOf(ordered[i]), `${ordered[i]} must follow ${ordered[i - 1]}`);
assert.match(template, /Function \.onInstFailed[\s\S]*?InstallStarted = 1[\s\S]*?InstallCommitted = 0[\s\S]*?Call RollbackInstallTransaction/);
assert.match(template, /StrCpy \$InstallStarted 1[\s\S]*?CreateDirectory "\$\{AIVESTAGINGDIR\}"/);
assert.match(template, /Function RollbackInstallTransaction[\s\S]*?Call SetSafeWorkingDir[\s\S]*?AIVESTAGINGDIR[\s\S]*?AIVEINSTALLDIR[\s\S]*?Rename "\$\{AIVEBACKUPDIR\}" "\$\{AIVEINSTALLDIR\}"/);
assert.match(template, /Function RecoverInterruptedInstall[\s\S]*?AIVESTAGINGDIR[\s\S]*?\.installing[\s\S]*?AIVEBACKUPDIR/);

assert.match(functionBody(template, "HasCoherentPayload"), /AIVEIDENTITY[\s\S]*?MAINBINARYNAME[\s\S]*?uninstall\.exe/);
assert.match(functionBody(template, "ClassifyInstallState"), /InstallCommitted[\s\S]*?InstallPath[\s\S]*?UNINSTKEY[\s\S]*?unknown-nonempty-or-reparse/);
assert.match(template, /Function ResolveClassifiedInstallState[\s\S]*?empty-owned-residue[\s\S]*?orphan-registration[\s\S]*?classification-conflict/);
assert.match(template, /WriteRegDWORD HKLM "\$\{AIVEPRODUCTKEY\}" "InstallCommitted" 1/);
assert.match(template, /Function PublishCommittedIdentity[\s\S]*?MoveFileExW[\s\S]*?WriteRegDWORD HKLM "\$\{AIVEPRODUCTKEY\}" "InstallCommitted" 1/);
assert.match(template, /AIVESETUPLOG[\s\S]*?AIVEJOURNAL[\s\S]*?AIVE_E_SNAPSHOT[\s\S]*?AIVE_E_INVARIANT/);
assert.match(template, /RejectProductionTestOverrides[\s\S]*?AIVE_TEST_ROOT[\s\S]*?AIVE_FAULT_PHASE/);
assert.match(template, /CreateMutexW[\s\S]*?183/);
const journal = functionBody(template, "WriteTransactionJournal");
assert.ok(journal.indexOf('"TransactionId"') < journal.indexOf('"Phase" "$TxnPhase"'), "phase must be the last authoritative registry commit field");
assert.match(journal, /ReadRegStr[\s\S]*?TransactionId[\s\S]*?ExpectedVersion[\s\S]*?PackageIdentity[\s\S]*?CanonicalPath[\s\S]*?journal_write_failed/);
assert.match(functionBody(template, "LoadTransactionState"), /ExpectedVersion[\s\S]*?PackageIdentity[\s\S]*?CanonicalPath[\s\S]*?StagingPath[\s\S]*?BackupPath[\s\S]*?load_transaction_invalid/);
assert.match(functionBody(template, "RecoverInterruptedInstall"), /uninstall-rename-intent[\s\S]*?recovery_uninstall[\s\S]*?committed[\s\S]*?recovery_committed/);
assert.match(functionBody(template, "FailInstall"), /RecoveryActive != 1[\s\S]*?Call WriteTransactionJournal/, "recovery failures must preserve the semantic retry phase");
assert.match(functionBody(template, "IsValidUninstallTombstone"), /GetParent[\s\S]*?GetFileName[\s\S]*?Shell\.rc6-uninstall-\$TxnId[\s\S]*?GetFullPathNameW[\s\S]*?valid_tombstone_char_loop/, "tombstones must be canonical numeric PID-tick sibling leaves");
assert.match(functionBody(template, "RecoverInterruptedInstall"), /recovery_committed:[\s\S]*?HasCurrentPayload[\s\S]*?recovery_committed_invalid[\s\S]*?AIVEBACKUPDIR/, "committed cleanup must validate the exact current live payload before deleting backup");
assert.match(functionBody(template, "un.WriteUninstallJournal"), /FullWipeRequested[\s\S]*?UninstallLocalRoot[\s\S]*?UninstallDocumentsRoot[\s\S]*?fullWipeRequested/, "uninstall policy and roots must be durable before rename");
assert.match(functionBody(template, "RecoverInterruptedInstall"), /recovery_uninstall_external:[\s\S]*?Call ResumeInterruptedUninstallCleanup[\s\S]*?DeleteRegKey HKLM "\$\{UNINSTKEY\}"/, "interrupted uninstall must resume policy cleanup before clearing registration");
assert.match(functionBody(template, "ResumeInterruptedUninstallCleanup"), /UninstallLocalRoot[\s\S]*?UninstallDocumentsRoot[\s\S]*?FullWipeCheckboxState[\s\S]*?AIVE_DELETE_KNOWN_CREDENTIAL/, "recovery cleanup must preserve default/full-wipe semantics");
assert.match(template, /Section Uninstall[\s\S]*?DeleteRegKey HKLM "\$\{AIVEPRODUCTKEY\}"/);
assert.match(functionBody(template, "un.ValidateInstalledIdentity"), /InstallCommitted[\s\S]*?AIVEPACKAGEID/);
assert.doesNotMatch(functionBody(templateCode, "un.ValidateInstalledIdentity"), /StrCmp\s+\$EXEPATH/, "normal NSIS TEMP self-copy uninstall must remain supported");
assert.match(template, /Shell\.rc6-uninstall-\$0-\$1[\s\S]*?uninstall-rename-intent[\s\S]*?Rename "\$\{AIVEINSTALLDIR\}" "\$UninstallTombstone"/);
assert.match(functionBody(template, "un.onInit"), /GetCurrentProcessId[\s\S]*?GetTickCount[\s\S]*?IntFmt \$0 "%u" \$0[\s\S]*?IntFmt \$1 "%u" \$1[\s\S]*?StrCpy \$TxnId "\$0-\$1"/, "PID and high-bit tick values must produce one numeric tombstone separator");
assert.match(template, /Call un\.WriteUninstallJournal\s+Call un\.SetSafeWorkingDir\s+ClearErrors\s+Rename "\$\{AIVEINSTALLDIR\}" "\$UninstallTombstone"/, "uninstall live rename must re-pin CWD immediately after journaling");
assert.match(template, /Function un\.RemoveTreeNoReparse[\s\S]*?0x400[\s\S]*?Call un\.RemoveTreeNoReparse/);
assert.doesNotMatch(hookCode, /RMDir \/r/, "hook cleanup must refuse nested reparse traversal");
assert.doesNotMatch(`${templateCode}\n${hookCode}`, /\bStrCmp\s+\/I\b/);

assert.match(hook, /Provisioning/);
assert.match(hook, /Installer/);
assert.match(hook, /handoff-root\.json\.part/);
assert.match(hook, /MoveFileExW/);
assert.match(hook, /desktop\.installer-handoff-origin\.v1/);
assert.match(hook, /catalogRelativePath.*Catalog\/offline-catalog\.json/);
assert.match(hook, /componentsRelativePath.*Components/);
assert.match(template, /handoff-root\.json\.rc6-rollback/);

const postUninstall = hook.slice(hook.indexOf("!macro NSIS_HOOK_POSTUNINSTALL"));
const fullWipeStart = postUninstall.indexOf("StrCmp $FullWipeCheckboxState 1");
assert.ok(fullWipeStart > 0);
const defaultCleanup = postUninstall.slice(0, fullWipeStart);
const fullWipe = postUninstall.slice(fullWipeStart);
assert.doesNotMatch(defaultCleanup, /\\(?:Config|uploads|models|database|postgresql|qdrant|Projects|Exports|Models)"|cmdkey/i);
for (const allowed of ["Config", "uploads", "models", "database", "postgresql", "qdrant", "Projects", "Exports", "Models"]) assert.ok(fullWipe.includes(`\\${allowed}\"`) || fullWipe.includes(`\\${allowed}"`));
assert.equal((fullWipe.match(/!insertmacro AIVE_DELETE_KNOWN_CREDENTIAL/g) ?? []).length, 20);
assert.match(template, /AIVEFULLWIPETOKEN "REMOVE_ALL_AI_VIDEO_EDITOR_USER_DATA"/);
assert.match(template, /Program Files cleanup is deferred until restart[\s\S]*?SetRebootFlag true/);
assert.match(template, /RMDir \/REBOOTOK "\$\{AIVEINSTALLERPARENT\}"[\s\S]*?product parent is not empty and was preserved/);
assert.match(hook, /machine-state cleanup is deferred until restart/);
for (const runtimeDir of ["Components", "Activation", "Downloads", "Catalog", "Broker", "Provisioning"]) assert.match(hook, new RegExp(`AIVE_REPORT_MACHINE_LEFTOVER "\\$2\\\\${runtimeDir}"`));
assert.match(hook, /Keep redacted installer\/uninstaller logs for durable diagnostics/);

const generated = "desktop/src-tauri/target/release/nsis/x64/installer.nsi";
try {
  await access(path.join(repoRoot, generated));
  assert.doesNotMatch(executable(await read(generated)), /\bStrCmp\s+\/I\b/);
} catch (error) {
  if (error?.code !== "ENOENT") throw error;
}

console.log("RC6 installer transaction tests passed: pinned single-owner template, fixed path, verified pre-commit shortcuts, bounded rollback/repair, handoff provenance, preserve-default uninstall, explicit allowlisted wipe, and cleanup reporting.");
