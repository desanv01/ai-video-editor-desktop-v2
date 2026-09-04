import assert from "node:assert/strict";
import { access, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const candidates = process.env.AIVE_RENDERED_NSIS
  ? [path.resolve(process.env.AIVE_RENDERED_NSIS)]
  : [
      path.join(repoRoot, "desktop", "src-tauri", "target", "release", "nsis", "x64", "installer.nsi"),
      path.join(repoRoot, "desktop", "src-tauri", "target", "release", "bundle", "nsis", "installer.nsi"),
    ];

let renderedPath;
for (const candidate of candidates) {
  try {
    await access(candidate);
    renderedPath = candidate;
    break;
  } catch (error) {
    if (error?.code !== "ENOENT") throw error;
  }
}
assert.ok(
  renderedPath,
  `Rendered NSIS source is mandatory. Build it first with "npx tauri build --bundles nsis --no-sign" or set AIVE_RENDERED_NSIS. Checked: ${candidates.join(", ")}`,
);

const rendered = await readFile(renderedPath, "utf8");
const code = rendered.split(/\r?\n/).filter(line => !/^\s*;/.test(line)).join("\n");

function functionBody(name) {
  const start = code.indexOf(`Function ${name}`);
  const end = code.indexOf("FunctionEnd", start);
  assert.ok(start >= 0 && end > start, `rendered NSIS is missing ${name}`);
  return code.slice(start, end);
}

assert.doesNotMatch(rendered, /\{\{[#/]?[^}]+\}\}/, "rendered NSIS still contains a Handlebars placeholder");
assert.match(rendered, /tauri-v2\.11\.2 installer\.nsi/i);
assert.match(code, /Function RejectProductionTestOverrides[\s\S]*?\/AIVE_TEST_ROOT=[\s\S]*?\/AIVE_FAULT_PHASE=/);

const canonical = functionBody("SetCanonicalInstallDir");
assert.match(canonical, /StrCpy \$INSTDIR "\$PROGRAMFILES64\\AI Video Editor Desktop V2\\Shell"|StrCpy \$INSTDIR "\$\{AIVEINSTALLDIR\}"/);
assert.doesNotMatch(canonical, /\bSetOutPath\b/i, "path selection must not create or enter the live shell");

const safe = functionBody("SetSafeWorkingDir");
assert.match(safe, /InitPluginsDir[\s\S]*?SetOutPath "\$PLUGINSDIR"/);

const outputTargets = [...code.matchAll(/\bSetOutPath\s+([^\r\n]+)/gi)].map(match => match[1].trim());
assert.ok(outputTargets.length >= 2, "rendered NSIS must explicitly select safe and staging output paths");
for (const target of outputTargets) {
  assert.match(target, /^(?:"\$PLUGINSDIR"|"\$\{AIVESTAGINGDIR\}")$/, `unsafe rendered SetOutPath target: ${target}`);
}
assert.doesNotMatch(code, /\bSetOutPath\s+"?(?:\$INSTDIR|\$\{AIVEINSTALLDIR\}|\$\{AIVEBACKUPDIR\})"?/i);

const init = functionBody(".onInit");
assert.match(init, /Call SetCanonicalInstallDir[\s\S]*?Call SetSafeWorkingDir[\s\S]*?Call RejectProductionTestOverrides[\s\S]*?Call AcquireInstallerMutex[\s\S]*?Call RecoverInterruptedInstall/);

const protect = functionBody("ProtectAndActivateStaging");
assert.match(protect, /Call SetSafeWorkingDir[\s\S]*?Rename "\$\{AIVEINSTALLDIR\}" "\$\{AIVEBACKUPDIR\}"/);
assert.match(protect, /activate_retry:[\s\S]*?Call SetSafeWorkingDir[\s\S]*?Rename "\$\{AIVESTAGINGDIR\}" "\$\{AIVEINSTALLDIR\}"/);

const removal = functionBody("RemoveCurrentShellPayload");
assert.match(removal, /^Function RemoveCurrentShellPayload\s+Call SetSafeWorkingDir/);
assert.ok(removal.indexOf("Call SetSafeWorkingDir") < removal.search(/\b(?:Delete|RMDir)\b/), "removal must leave its target before deleting");

const rollback = functionBody("RollbackInstallTransaction");
assert.match(rollback, /Call SetSafeWorkingDir[\s\S]*?Rename "\$\{AIVEBACKUPDIR\}" "\$\{AIVEINSTALLDIR\}"/);
assert.match(code, /Section Install[\s\S]*?Call BeginInstallTransaction[\s\S]*?SetOutPath "\$\{AIVESTAGINGDIR\}"[\s\S]*?File /);
assert.match(code, /Function \.onInstFailed[\s\S]*?InstallStarted = 1[\s\S]*?InstallCommitted = 0[\s\S]*?Call RollbackInstallTransaction/);

console.log(JSON.stringify({ status: "pass", schemaVersion: "desktop.rendered-nsis-verification.v1", renderedPath }));
