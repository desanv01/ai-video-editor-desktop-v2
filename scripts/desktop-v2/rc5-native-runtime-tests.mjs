import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const read = relativePath => readFileSync(path.join(repoRoot, relativePath), "utf8");
const readJson = relativePath => JSON.parse(read(relativePath));
// Kept as an RC5 regression suite, but release identity follows the current
// candidate and is additionally frozen by rc6-release-installer-tests.mjs.
const releaseVersion = "2.0.0-rc.6";

const packageJson = readJson("desktop/package.json");
const packageLock = readJson("desktop/package-lock.json");
const tauriConfig = readJson("desktop/src-tauri/tauri.conf.json");
const cargoToml = read("desktop/src-tauri/Cargo.toml");
const cargoLock = read("desktop/src-tauri/Cargo.lock");
const trust = read("desktop/src-tauri/src/release_trust.rs");
const manager = read("desktop/src-tauri/src/component_manager.rs");
const broker = read("desktop/src-tauri/src/component_broker.rs");
const supervisor = read("desktop/src-tauri/src/supervisor.rs");
const setupRust = read("desktop/src-tauri/src/setup_center.rs");
const diagnosticsRust = read("desktop/src-tauri/src/desktop_v2.rs");
const setupTs = read("desktop/src/setupCenter.ts");
const desktopV2 = read("desktop/src/desktopV2.ts");
const setupPanel = read("desktop/src/components/SetupCenterPanel.tsx");
const shellPanel = read("desktop/src/components/DesktopV2Shell.tsx");
const shellRust = read("desktop/src-tauri/src/lib.rs");
const hook = read("desktop/src-tauri/nsis/installer-hooks.nsh");
const installerTemplate = read("desktop/src-tauri/nsis/installer-template.nsi");

for (const value of [packageJson.version, packageLock.version, packageLock.packages[""].version]) {
  assert.equal(value, releaseVersion);
}
assert.equal(tauriConfig.version, releaseVersion);
assert.match(cargoToml, new RegExp(`version = "${releaseVersion.replaceAll(".", "\\.")}"`));
assert.match(cargoLock, new RegExp(`name = "ai-video-editor"\\r?\\nversion = "${releaseVersion.replaceAll(".", "\\.")}"`));
assert.match(trust, new RegExp(`RELEASE_VERSION: &str = "${releaseVersion.replaceAll(".", "\\.")}"`));
assert.match(packageJson.scripts["test:desktop-v2"], /rc5-native-runtime-tests\.mjs/);
assert.match(packageJson.scripts["test:desktop-v2"], /rc5-installer-uninstall-tests\.mjs/);

// Acquisition accepts only an explicitly selected production/offline policy;
// launch verification reads the signed installed payload and never replays
// the original artifact URL.
assert.match(manager, /pub const INSTALLED_RUNTIME: Self/);
assert.match(manager, /pub validate_artifact_source: bool/);
assert.match(manager, /fn ensure_artifact_source_policy/);
assert.match(manager, /SOURCE_POLICY_INVALID/);
assert.match(manager, /installed_runtime_verification_does_not_revalidate_offline_acquisition_source/);
assert.match(manager, /fn verify_installed_inventory/);
assert.doesNotMatch(manager, /VERSION_ALREADY_PUBLISHED/);
const managerRuntimeRead = manager.slice(manager.indexOf("pub fn verified_active_component"), manager.indexOf("pub fn status", manager.indexOf("pub fn verified_active_component")));
assert.match(managerRuntimeRead, /policy: SourcePolicy/);
assert.match(managerRuntimeRead, /verify_installed_inventory/);
assert.match(manager, /pub fn status[\s\S]*?SourcePolicy::INSTALLED_RUNTIME/);

const resolveLaunchBundle = supervisor.slice(supervisor.indexOf("fn resolve_launch_bundle"), supervisor.indexOf("fn component_failure"));
assert.match(resolveLaunchBundle, /SourcePolicy::INSTALLED_RUNTIME/);
assert.doesNotMatch(resolveLaunchBundle, /SourcePolicy::PRODUCTION/);
assert.match(broker, /BrokerOperation::Repair \| BrokerOperation::Rollback[\s\S]*?SourcePolicy::INSTALLED_RUNTIME/);
assert.match(broker, /allow_offline_sources: false/);

// Startup state is explicit enough to distinguish setup, storage, launch,
// protocol, authentication, retry, cancellation, and fatal shell failures.
for (const phase of [
  "ResolvingInstalledComponents",
  "Launching",
  "AwaitingHandshake",
  "ProbingReadiness",
  "DegradedUsable",
  "SetupRequired",
  "ComponentRepairRequired",
  "StorageBlocked",
  "LaunchBlocked",
  "EngineRetryableFailure",
  "ProtocolIncompatible",
  "SessionAuthFailed",
  "CancelledStopped",
  "FatalShellFailure",
]) assert.match(supervisor, new RegExp(`SupervisorPhase::${phase}|enum SupervisorPhase[\\s\\S]*?\\b${phase}\\b`));
for (const field of [
  "last_exit_code",
  "handshake_at_epoch_ms",
  "readiness_at_epoch_ms",
  "last_probe_status",
  "capabilities_at_epoch_ms",
  "last_capabilities_status",
  "verification_policy",
]) assert.match(supervisor, new RegExp(`\\b${field}\\b`));
assert.match(supervisor, /fn finish_cancelled/);
assert.match(supervisor, /Only the signed active component store was inspected; Docker and global tools were not attempted/);
assert.match(supervisor, /AIVE_ENGINE_BEARER_TOKEN/);
assert.match(supervisor, /redact_sensitive/);
assert.match(diagnosticsRust, /supervisor_diagnostics/);
assert.match(diagnosticsRust, /supervisor_readiness_summary/);
assert.match(diagnosticsRust, /lastError|last_error/);
assert.match(diagnosticsRust, /stderrTailLines|log_tail/);
assert.match(setupRust, /last_probe_status/);
assert.match(setupRust, /verification_policy/);

// The WebView launch gate accepts only authenticated ready/degraded-usable
// states, while setup cancellation stays pending until a safe boundary.
assert.match(desktopV2, /degraded-usable/);
assert.match(setupTs, /degraded-usable/);
assert.match(setupTs, /SETUP_CANCELLED/);
assert.match(setupPanel, /cancelRequestedRef/);
assert.match(setupPanel, /throwIfCancellationRequested/);
assert.match(setupPanel, /stopSupervisorForCancellation/);
assert.match(setupPanel, /SETUP_CANCELLED/);
assert.match(setupPanel, /Finishing safely/);
assert.match(setupPanel, /operationStageRef\.current !== "download"/);
assert.match(setupPanel, /stage === "download"/);
assert.match(setupPanel, /active version.*valid state|atomic safe checkpoint/is);
assert.match(shellPanel, /lastProbeStatus/);
assert.match(shellPanel, /verificationPolicy/);
assert.match(shellPanel, /redactDiagnosticText/);

// Native-only launch remains enforced at the shell boundary.
assert.doesNotMatch(shellRust, /bootstrap_desktop_backend/);
assert.doesNotMatch(shellRust, /Command::new\("docker"\)/);
assert.doesNotMatch(supervisor, /Command::new\("docker"\)/);

// The hook owns machine ACL/ancillary state; the pinned template owns the
// immutable payload transaction, committed identity, and two shortcuts.
assert.match(installerTemplate, /StrCpy \$INSTDIR "\$\{AIVEINSTALLDIR\}"/);
assert.doesNotMatch(hook, /SetOutPath\s+[^\r\n]*\$INSTDIR/i);
assert.match(installerTemplate, /!define AIVEPACKAGEID "rc6-sep4-installer-recovery-v1"/);
assert.doesNotMatch(hook.replace(/^\s*;.*/gm, ""), /CreateShortCut/i);
assert.equal((installerTemplate.match(/\bCreateShortcut\b/g) ?? []).length, 2);
assert.match(hook, /installer-template\.nsi is the single owner/i);
assert.doesNotMatch(hook, /SetOutPath\s+[^\r\n]*\$APPDATA/i);

const generatedInstaller = path.join(repoRoot, "desktop", "src-tauri", "target", "release", "nsis", "x64", "installer.nsi");
if (existsSync(generatedInstaller)) {
  const generated = readFileSync(generatedInstaller, "utf8");
  assert.match(generated, /installer-hooks\.nsh/);
  assert.match(generated, /VERSION \"2\.0\.0-rc\.6\"/);
  console.log(`Generated NSIS inspection PASS: ${generatedInstaller}`);
} else {
  console.log("Generated NSIS inspection deferred: release bundle has not been built in this checkout.");
}

console.log("Desktop V2 RC5 native-runtime tests passed: installed-runtime verification is source-independent, supervisor failures are typed, diagnostics are redacted and durable, cancellation is safe-boundary based, and the native launch gate remains enforced.");
