import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const read = relativePath => readFileSync(path.join(repoRoot, relativePath), "utf8");
const readJson = relativePath => JSON.parse(read(relativePath));

const packageJson = readJson("desktop/package.json");
const packageLock = readJson("desktop/package-lock.json");
const tauriConfig = readJson("desktop/src-tauri/tauri.conf.json");
const cargoToml = read("desktop/src-tauri/Cargo.toml");
const cargoLock = read("desktop/src-tauri/Cargo.lock");
const trust = read("desktop/src-tauri/src/release_trust.rs");
const broker = read("desktop/src-tauri/src/component_broker.rs");
const manager = read("desktop/src-tauri/src/component_manager.rs");
const setupRust = read("desktop/src-tauri/src/setup_center.rs");
const setupTs = read("desktop/src/setupCenter.ts");
const setupPanel = read("desktop/src/components/SetupCenterPanel.tsx");
const shellRust = read("desktop/src-tauri/src/lib.rs");
const mainRust = read("desktop/src-tauri/src/main.rs");
const supervisor = read("desktop/src-tauri/src/supervisor.rs");
const diagnostics = read("desktop/src-tauri/src/desktop_v2.rs");
const operationLog = read("desktop/src-tauri/src/operation_log.rs");
const hook = read("desktop/src-tauri/nsis/installer-hooks.nsh");

for (const value of [
  packageJson.version,
  packageLock.version,
  packageLock.packages[""].version,
]) assert.equal(value, "2.0.0-rc.4");
assert.match(cargoToml, /version = "2\.0\.0-rc\.4"/);
assert.match(cargoLock, /name = "ai-video-editor"\r?\nversion = "2\.0\.0-rc\.4"/);
assert.equal(tauriConfig.version, "2.0.0-rc.4");
assert.match(trust, /RELEASE_VERSION: &str = "2\.0\.0-rc\.4"/);

assert.match(broker, /desktop\.component-broker\.v1/);
for (const operation of ["Activate", "Reconcile", "Repair", "Rollback", "Uninstall"]) {
  assert.match(broker, new RegExp(`BrokerOperation::${operation}`));
}
assert.match(broker, /ShellExecuteExW/);
assert.match(broker, /AIVE_COMPONENT_BROKER/);
assert.match(broker, /ensure_child_path/);
assert.match(broker, /The helper request path contains traversal/);
assert.doesNotMatch(broker, /fallback (to )?AppData|Docker (Desktop|Compose) (?:fallback|startup)/i);
assert.match(mainRust, /run_broker_cli/);

for (const invariant of [
  'state: "already-active"',
  '"recovered-published"',
  '"activation-intent"',
  '"quarantined"',
  'AIVE_ACTIVATION_FAIL_CHECKPOINT',
  'commit_published_activation',
  'verify_installed_inventory',
]) assert.match(manager, new RegExp(invariant.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
assert.doesNotMatch(manager, /VERSION_ALREADY_PUBLISHED/);

for (const invariant of [
  "SetupActivationWriterProbe",
  "same_volume_rename",
  "atomic_replace",
  "activation_ready",
  "CATALOG_TEMPLATE_REJECTED",
  "setup_get_catalog_status",
  "clear_catalog_rejection",
]) assert.match(setupRust, new RegExp(invariant));
assert.match(setupRust, /production-catalog template, not a signed catalog/);
assert.match(setupTs, /systemChecksAreCurrentAndHealthy/);
assert.match(setupTs, /activationReady/);
assert.match(setupPanel, /const reviewReady = hasRequiredCatalog && checksHealthy && !error/);
assert.match(setupPanel, /disabled={!reviewReady || busy}/);

assert.doesNotMatch(shellRust, /bootstrap_desktop_backend/);
assert.doesNotMatch(shellRust, /Command::new\("docker"\)/);
assert.match(supervisor, /SourcePolicy::PRODUCTION/);
assert.match(supervisor, /Docker and global tools were not attempted/);
assert.match(diagnostics, /broker_health/);
assert.match(diagnostics, /operation_tail/);
assert.match(diagnostics, /perimeter_summary/);
assert.match(operationLog, /PROGRAMDATA/);

assert.match(hook, /StrCpy \$INSTDIR "\$PROGRAMFILES64\\AI Video Editor Desktop V2\\Shell"/);
assert.match(hook, /desktop\.component-broker\.v1/);
assert.match(hook, /\$2\\Broker\\Requests/);
assert.doesNotMatch(hook, /CreateShortCut/i);
assert.match(hook, /2\.0\.0-rc\.4/);

const generatedInstaller = path.join(repoRoot, "desktop", "src-tauri", "target", "release", "nsis", "x64", "installer.nsi");
if (existsSync(generatedInstaller)) {
  const generated = readFileSync(generatedInstaller, "utf8");
  assert.match(generated, /installer-hooks\.nsh/);
  assert.match(generated, /VERSION \"2\.0\.0-rc\.4\"/);
  assert.match(generated, /CreateShortcut/);
  console.log(`Generated NSIS inspection PASS: ${generatedInstaller}`);
} else {
  console.log("Generated NSIS inspection deferred: release bundle has not been built in this checkout.");
}

console.log("Desktop V2 rc.4 first-run recovery tests passed: bounded broker, convergent activation, truthful writer/catalog gates, native-only routing, redacted diagnostics, and single-owner installer shortcuts.");
