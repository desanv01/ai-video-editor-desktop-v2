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
assert.match(template, /Function \.onInit[\s\S]*?Call SetCanonicalInstallDir[\s\S]*?Call RecoverInterruptedInstall[\s\S]*?Call RepairStaleRc6Registration/);
assert.match(template, /AIVEINSTALLDIR "\$\{AIVEINSTALLERPARENT\}\\Shell"/);

assert.equal((templateCode.match(/\bCreateShortcut\b/gi) ?? []).length, 2);
assert.doesNotMatch(hookCode, /\bCreateShortcut\b/i);
assert.match(template, /CreateShortcut "\$\{AIVESTARTMENULINK\}"[\s\S]*?CreateShortcut "\$\{AIVEDESKTOPLINK\}"/);
assert.equal((template.match(/!insertmacro IsShortcutTarget/g) ?? []).length, 2);

const install = template.slice(template.indexOf("Section Install"), template.indexOf("Function CreateAndVerifyRequiredShortcuts"));
const ordered = ["Call BeginInstallTransaction", 'File "${MAINBINARYSRCPATH}"', "WriteUninstaller", "Call CreateAndVerifyRequiredShortcuts", "NSIS_HOOK_POSTINSTALL", "Call CommitInstallRegistration", "installCommitted", "StrCpy $InstallCommitted 1"];
for (const marker of ordered) assert.ok(install.includes(marker), `install transaction is missing ${marker}`);
for (let i = 1; i < ordered.length; i += 1) assert.ok(install.indexOf(ordered[i - 1]) < install.indexOf(ordered[i]), `${ordered[i]} must follow ${ordered[i - 1]}`);
assert.match(template, /Function \.onInstFailed[\s\S]*?InstallStarted = 1[\s\S]*?InstallCommitted = 0[\s\S]*?Call RollbackInstallTransaction/);
assert.match(template, /Only now can failure rollback safely[\s\S]*?StrCpy \$InstallStarted 1/);
assert.ok(template.indexOf("StrCpy $InstallStarted 1") > template.indexOf('Rename "$INSTDIR" "${AIVEBACKUPDIR}"'));
assert.match(template, /Function RollbackInstallTransaction[\s\S]*?Call RemoveCurrentShellPayload[\s\S]*?Rename "\$\{AIVEBACKUPDIR\}" "\$INSTDIR"/);
assert.match(template, /Function RecoverInterruptedInstall[\s\S]*?\.installing[\s\S]*?AIVEBACKUPDIR/);

assert.match(template, /Function RepairStaleRc6Registration[\s\S]*?desktop-v2\.identity\.json[\s\S]*?uninstall\.exe[\s\S]*?MAINBINARYNAME[\s\S]*?DeleteRegKey HKLM "\$\{AIVEPRODUCTKEY\}"/);
assert.match(template, /WriteRegDWORD HKLM "\$\{AIVEPRODUCTKEY\}" "InstallCommitted" 1/);
assert.match(template, /Section Uninstall[\s\S]*?DeleteRegKey HKLM "\$\{AIVEPRODUCTKEY\}"/);
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
for (const runtimeDir of ["Components", "Activation", "Downloads", "Catalog", "Broker", "Provisioning", "Installer"]) assert.match(hook, new RegExp(`AIVE_REPORT_MACHINE_LEFTOVER "\\$2\\\\${runtimeDir}"`));

const generated = "desktop/src-tauri/target/release/nsis/x64/installer.nsi";
try {
  await access(path.join(repoRoot, generated));
  assert.doesNotMatch(executable(await read(generated)), /\bStrCmp\s+\/I\b/);
} catch (error) {
  if (error?.code !== "ENOENT") throw error;
}

console.log("RC6 installer transaction tests passed: pinned single-owner template, fixed path, verified pre-commit shortcuts, bounded rollback/repair, handoff provenance, preserve-default uninstall, explicit allowlisted wipe, and cleanup reporting.");
