import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

async function text(relativePath) {
  return readFile(path.join(repoRoot, relativePath), "utf8");
}

const capability = JSON.parse(await text("desktop/src-tauri/capabilities/main.json"));
const tauriConfig = JSON.parse(await text("desktop/src-tauri/tauri.conf.json"));
const setupPanel = await text("desktop/src/components/SetupCenterPanel.tsx");
const setupClient = await text("desktop/src/setupCenter.ts");
const setupRust = await text("desktop/src-tauri/src/setup_center.rs");
const shellRust = await text("desktop/src-tauri/src/lib.rs");
const desktopV2Rust = await text("desktop/src-tauri/src/desktop_v2.rs");
const migrationRust = await text("desktop/src-tauri/src/migration.rs");
const contractsRust = await text("desktop/src-tauri/src/contracts.rs");
const contractsTs = await text("desktop/src/contracts/desktopV2.ts");
const storageSchema = JSON.parse(await text("contracts/desktop-v2/schemas/storage-layout.v1.schema.json"));
const storageFixture = JSON.parse(await text("fixtures/desktop-v2/contracts/valid-storage-layout.json"));
const installerHook = await text("desktop/src-tauri/nsis/installer-hooks.nsh");
const handoffReadme = await text("desktop/src-tauri/resources/lecturer-handoff/README.txt");

assert.equal(capability.identifier, "main-capability");
assert.ok(capability.permissions.includes("core:default"));
assert.ok(capability.permissions.includes("core:event:default"));
assert.ok(capability.permissions.includes("dialog:allow-open"));
assert.ok(!capability.permissions.includes("event:default"), "Tauri event permission must use the core namespace");
assert.deepEqual(tauriConfig.app.security.capabilities, ["main-capability"]);
assert.equal(tauriConfig.bundle.resources[0], "resources/lecturer-handoff");

assert.match(setupPanel, /await import\("@tauri-apps\/plugin-dialog"\)/);
assert.match(setupPanel, /multiple:\s*false/);
assert.match(setupPanel, /directory:\s*false/);
assert.match(setupPanel, /extensions:\s*\["json"\]/);
assert.match(setupPanel, /DIALOG_OPEN_FAILED/);
assert.match(setupPanel, /role="alert"/);
assert.match(setupPanel, /Use bundled lecturer catalog/);
assert.match(setupPanel, /setupClient\.importBundledCatalog/);
assert.match(setupPanel, /setupClient\.discoverBundledCatalog/);
const dialogImportOffset = setupPanel.indexOf('await import("@tauri-apps/plugin-dialog")');
const importHandlerOffset = setupPanel.indexOf("const importCatalog = async () =>");
assert.ok(importHandlerOffset >= 0 && dialogImportOffset > importHandlerOffset);
assert.match(setupPanel.slice(importHandlerOffset, dialogImportOffset), /try\s*\{/s);
assert.match(setupPanel.slice(dialogImportOffset), /catch\s*\(dialogError\)/s);

assert.match(setupClient, /discoverBundledCatalog: \(\) => transport\.invoke<BundledCatalogDiscovery>\("setup_discover_bundled_catalog"\)/);
assert.match(setupClient, /importBundledCatalog: \(\) => transport\.invoke<SetupImportResult>\("setup_import_bundled_catalog"\)/);
assert.match(setupClient, /friendlySetupMessage/);
assert.match(setupClient, /CATALOG_FILE_INVALID/);

for (const invariant of [
  "MAX_BUNDLED_CATALOG_CANDIDATES",
  "path_is_same_or_child",
  "read_bounded_catalog_file",
  "offline_catalog_handoff_root",
  "setup_discover_bundled_catalog",
  "setup_import_bundled_catalog",
  "CATALOG_TOO_LARGE",
]) {
  assert.match(setupRust, new RegExp(invariant));
}
assert.match(setupRust, /Components/);
assert.match(setupRust, /canonicalize/);
assert.match(setupRust, /verify_and_intake_catalog/);

const singleInstanceOffset = shellRust.indexOf("tauri_plugin_single_instance::init");
const dialogPluginOffset = shellRust.indexOf("tauri_plugin_dialog::init");
assert.ok(singleInstanceOffset >= 0 && dialogPluginOffset > singleInstanceOffset, "single-instance must be registered before dialog");
assert.match(shellRust, /window\.set_focus\(\)/);
assert.match(shellRust, /desktop-v2-handoff-args/);
assert.match(shellRust, /Path::new\(&cwd\)/);

for (const invariant of [
  "PROGRAM_FILES_DIRECTORY",
  "USER_DATA_DIRECTORY",
  "MAX_SINGLE_INSTANCE_ARGUMENTS",
  "approved_catalog_path",
  "approved_handoff_root",
  "approved_single_instance_args",
]) {
  assert.match(desktopV2Rust, new RegExp(invariant));
}
assert.match(desktopV2Rust, /AI Video Editor Desktop V2\\Shell/);
assert.match(desktopV2Rust, /MAX_SINGLE_INSTANCE_ARGUMENT_BYTES/);

assert.match(migrationRust, /V2_PROGRAM_FILES_DIRECTORY: &str = "AI Video Editor Desktop V2"/);
assert.match(migrationRust, /CURRENT_V2_MARKER_FILES/);
assert.match(migrationRust, /journal\.status == "committed"/);
assert.match(migrationRust, /if current_v2 \{/);
assert.match(migrationRust, /user data—not legacy migration candidates/);
assert.match(migrationRust, /legacy-program-files/);

assert.match(contractsRust, /%ProgramFiles%\\\\AI Video Editor Desktop V2\\\\Shell/);
assert.match(contractsTs, /%ProgramFiles%\\\\AI Video Editor Desktop V2\\\\Shell/);
assert.match(storageSchema.properties.paths.properties.shellInstall.$ref, /pathDescriptor/);
assert.match(storageSchema.$defs.pathDescriptor.properties.pathTemplate.pattern, /AI Video Editor Desktop V2/);
assert.equal(storageFixture.paths.shellInstall.pathTemplate, "%ProgramFiles%\\AI Video Editor Desktop V2\\Shell");
assert.match(installerHook, /\$PROGRAMFILES64\\AI Video Editor Desktop V2/);

assert.match(handoffReadme, /Catalog\/offline-catalog\.json/);
assert.match(handoffReadme, /Components/);
assert.match(handoffReadme, /bounded|containment|signature/i);

console.log("Desktop V2 rc.3 hardening tests passed: dialog capability and guarded JSON intake, bundled handoff trust boundary, single-instance forwarding, current-data migration exclusion, and canonical shell identity.");
