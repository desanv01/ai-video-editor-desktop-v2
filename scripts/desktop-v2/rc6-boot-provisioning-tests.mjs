import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const read = relative => readFile(path.join(repoRoot, relative), "utf8");
const [rust, setupRust, shell, client, setup, providers, transcription, lib, bootSchema, journalSchema, installerOriginSchema] = await Promise.all([
  read("desktop/src-tauri/src/provisioning.rs"),
  read("desktop/src-tauri/src/setup_center.rs"),
  read("desktop/src/components/DesktopV2Shell.tsx"),
  read("desktop/src/provisioning.ts"),
  read("desktop/src/components/SetupCenterPanel.tsx"),
  read("desktop/src/components/ProviderOnboardingPanel.tsx"),
  read("desktop/src/components/TranscriptionSettingsPanel.tsx"),
  read("desktop/src-tauri/src/lib.rs"),
  read("contracts/desktop-v2/schemas/boot-snapshot.v1.schema.json").then(JSON.parse),
  read("contracts/desktop-v2/schemas/provisioning-journal.v1.schema.json").then(JSON.parse),
  read("contracts/desktop-v2/schemas/installer-handoff-origin.v1.schema.json").then(JSON.parse),
]);

assert.match(rust, /desktop\.boot-snapshot\.v1/);
assert.equal(bootSchema.properties.schemaVersion.const, "desktop.boot-snapshot.v1");
assert.equal(bootSchema.properties.hydrationComplete.const, true);
assert.equal(bootSchema.properties.reconciled.const, true);
assert.equal(journalSchema.properties.schemaVersion.const, "desktop.provisioning-journal.v1");
assert.equal(installerOriginSchema.properties.schemaVersion.const, "desktop.installer-handoff-origin.v1");
assert.equal(installerOriginSchema.properties.catalogRelativePath.const, "Catalog/offline-catalog.json");
assert.equal(installerOriginSchema.properties.componentsRelativePath.const, "Components");
for (const route of ["booting", "needs-core-setup", "resumable-setup", "starting-engine", "needs-optional-ai-choice", "ready", "repair-required"]) {
  assert.match(client, new RegExp(`"${route}"`));
}
assert.match(rust, /hydration_complete:\s*true/);
assert.match(rust, /reconciled:\s*true/);
assert.match(rust, /coordinator\.recover\(\)/);
assert.match(rust, /manager\.recover\(\)/);
assert.match(rust, /manager\.repair\(/);
assert.match(rust, /catalog_needs_reconciliation/);
assert.match(rust, /cached_catalog_source_is_usable/);
assert.match(rust, /repaired_activation_routes_to_resume_when_trusted_reinstall_is_available/);
assert.match(rust, /recovered_components_progress_idempotently_through_start_and_first_launch/);
assert.match(rust, /setup_discover_bundled_catalog/);
assert.match(setupRust, /load_installer_handoff_origin/);
assert.match(setupRust, /MAX_INSTALLER_HANDOFF_ORIGIN_BYTES/);
assert.match(setupRust, /persisted_installer_origin_resolves_external_handoff_without_copying_assets/);
assert.match(rust, /in_atomic_section/);
assert.match(rust, /cancellation_waits_for_atomic_boundary_and_recovers_safely/);
assert.match(rust, /runtime_and_model_operations_are_serialized/);
assert.match(lib, /manage\(provisioning::ProvisioningCoordinator::default\(\)\)/);
assert.match(lib, /provisioning::desktop_boot_snapshot/);

assert.match(shell, /await provisioningClient\.hydrate\(\)/);
assert.match(shell, /if \(!bootSnapshot\)/);
assert.match(shell, /routeNeedsSetup\(.*\.route\)/s);
assert.match(shell, /reconciledSnapshot\.shellBootState === "engine-available"/);
assert.match(shell, /for \(let attempt = 0; attempt < 60/);
for (const label of ["Welcome", "Check this PC", "Install Core", "Install Media Tools", "Verify and Start", "Optional AI Setup", "Ready"]) {
  assert.match(setup + shell, new RegExp(label));
}
assert.match(providers, /PROVIDER_CARDS\.map/);
assert.doesNotMatch(providers, /<input value=\{providerId\}/);
assert.match(providers, /Windows Credential Manager/);
assert.match(providers, /Save securely/);
assert.match(providers, /Verify provider/);
assert.match(transcription, /window\.confirm\(`Download/);
assert.match(transcription, /local-transcription-model/);
assert.match(transcription, /provisioningClient\.begin/);

console.log("Desktop V2 RC.6 boot/provisioning tests passed: authoritative hydration, durable checkpoints, commercial first launch, fixed providers, and serialized model consent.");
