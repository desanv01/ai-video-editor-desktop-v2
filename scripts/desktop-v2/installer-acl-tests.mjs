import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptRoot = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptRoot, "../..");
const hookPath = path.join(repoRoot, "desktop", "src-tauri", "nsis", "installer-hooks.nsh");
const hook = readFileSync(hookPath, "utf8");

assert.doesNotMatch(hook, /COMMONAPPDATA/, "the invalid NSIS shell token must never reach the hook source");
assert.doesNotMatch(hook, /\$\{[^}]+\}\\AI Video Editor/, "machine paths must not contain an unresolved placeholder");
assert.match(hook, /SetShellVarContext all/);
assert.match(hook, /SetRegView 64/);
assert.match(hook, /StrCpy \$INSTDIR "\$PROGRAMFILES64\\AI Video Editor Desktop V2"/);
assert.match(hook, /SetOutPath \$INSTDIR/);
assert.match(hook, /StrCpy \$2 "\$APPDATA\\AI Video Editor"/);
assert.match(hook, /ReadEnvStr \$3 "ProgramData"/);
assert.match(hook, /StrCmp \/I \$2 \$4/);
assert.match(hook, /nsExec::ExecToStack \/OEM '\"\$SYSDIR\\icacls\.exe\" \"\$2\"/);
assert.match(hook, /\/inheritance:r/);
assert.match(hook, /\*S-1-5-18:\(OI\)\(CI\)\(F\)/);
assert.match(hook, /\*S-1-5-32-544:\(OI\)\(CI\)\(F\)/);
assert.match(hook, /\*S-1-5-32-545:\(OI\)\(CI\)\(M\)/);
assert.match(hook, /\/setowner "\*S-1-5-32-544"/);
assert.doesNotMatch(hook, /\/grant:r[^']*\/setowner/, "icacls owner assignment must be a separate invocation");
assert.match(hook, /\/T['\"]?/);
assert.doesNotMatch(hook, /\/T \/C/);
assert.ok((hook.match(/nsExec::ExecToStack/g) ?? []).length >= 3, "reset, grant, and owner ACL commands must all be present");
assert.ok((hook.match(/StrCmp \$0 "0"/g) ?? []).length >= 3, "every icacls command must gate success on exit code 0");
assert.match(hook, /Pop \$0\s+Pop \$1/);
assert.match(hook, /SetShellVarContext current\s+StrCpy \$5 "\$LOCALAPPDATA\\AI Video Editor"/);
assert.match(hook, /Delete "\$INSTDIR\\desktop-v2\.identity\.json"/);
assert.match(hook, /RMDir "\$INSTDIR"/);
assert.match(hook, /RMDir \/r "\$2\\Components"/);
assert.match(hook, /RMDir \/r "\$5\\Cache"/);
assert.doesNotMatch(hook, /Ignore|ignore|continue path/i);
assert.match(hook, /2\.0\.0-rc\.2/);
assert.match(hook, /com\.fyp\.ai-video-editor\.desktop-v2/);

const generatedCandidates = [
  path.join(repoRoot, "desktop", "src-tauri", "target", "release", "bundle", "nsis", "installer.nsi"),
  path.join(repoRoot, "desktop", "src-tauri", "target", "release", "bundle", "nsis", "AI Video Editor Desktop V2_2.0.0-rc.2_x64.nsi"),
].filter(existsSync);
for (const generatedPath of generatedCandidates) {
  const generated = readFileSync(generatedPath, "utf8");
  assert.doesNotMatch(generated, /COMMONAPPDATA|\$\{COMMONAPPDATA\}/);
  assert.match(generated, /AI Video Editor Desktop V2/);
}

const artifact = process.env.AIVE_NSIS_ARTIFACT;
if (artifact && existsSync(artifact)) {
  const bytes = readFileSync(artifact);
  const ascii = bytes.toString("ascii");
  const utf16 = bytes.toString("utf16le");
  assert.doesNotMatch(ascii, /\$\{COMMONAPPDATA\}/);
  assert.doesNotMatch(utf16, /\$\{COMMONAPPDATA\}/);
  assert.match(path.basename(artifact), /2\.0\.0-rc\.2/);
  console.log(`Installer artifact ACL scan PASS: ${artifact}`);
} else {
  console.log("Installer artifact ACL scan deferred: set AIVE_NSIS_ARTIFACT after the NSIS build.");
}

console.log("Desktop V2 installer ACL tests passed: no invalid shell token, verified ProgramData resolution, quote-safe icacls policy, exact exit-code gates, Program Files identity, and data-preserving uninstall paths.");
