import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const migration = await import(pathToFileURL(path.join(repoRoot, "desktop", "src", "migration.ts")).href);
const migrationSource = await readFile(path.join(repoRoot, "desktop", "src-tauri", "src", "migration.rs"), "utf8");
const wizardSource = await readFile(path.join(repoRoot, "desktop", "src", "components", "MigrationCleanupWizard.tsx"), "utf8");
const shellSource = await readFile(path.join(repoRoot, "desktop", "src", "components", "DesktopV2Shell.tsx"), "utf8");
const installerSource = await readFile(path.join(repoRoot, "desktop", "src-tauri", "nsis", "installer-hooks.nsh"), "utf8");
const inventorySchema = JSON.parse(await readFile(path.join(repoRoot, "contracts", "desktop-v2", "schemas", "migration-inventory.v1.schema.json"), "utf8"));
const reportSchema = JSON.parse(await readFile(path.join(repoRoot, "contracts", "desktop-v2", "schemas", "migration-report.v1.schema.json"), "utf8"));
const uninstallSchema = JSON.parse(await readFile(path.join(repoRoot, "contracts", "desktop-v2", "schemas", "uninstall-plan.v1.schema.json"), "utf8"));

function testContractsAndRedaction() {
  assert.equal(inventorySchema.$id, "https://schemas.aive.dev/desktop-v2/migration-inventory.v1.schema.json");
  assert.equal(reportSchema.$id, "https://schemas.aive.dev/desktop-v2/migration-report.v1.schema.json");
  assert.equal(uninstallSchema.$id, "https://schemas.aive.dev/desktop-v2/uninstall-plan.v1.schema.json");
  for (const schema of [inventorySchema, reportSchema, uninstallSchema]) {
    assert.equal(schema.additionalProperties, false);
    assert.ok(schema.required.includes("schemaVersion"));
  }
  const redacted = migration.redactMigrationText("api_key=super-secret token=private-value");
  assert.doesNotMatch(redacted, /super-secret|private-value/);
  assert.equal(migration.migrationCategoryLabel({ category: "projects", classification: "projects" }), "Projects (valuable user data)");
  assert.equal(migration.migrationCategoryLabel({ category: "database", classification: "qdrant" }), "Export/import required");
}

async function testMockBridgeCommandSurface() {
  const calls = [];
  const client = migration.createMigrationClient({
    async invoke(command, args) {
      calls.push({ command, args });
      return { command };
    },
  });
  await client.scan();
  await client.preview(undefined, {});
  await client.execute({ migrationId: "synthetic" }, {});
  await client.rollback({ migrationId: "synthetic" });
  await client.recover();
  await client.cleanup({ schemaVersion: "desktop.migration-inventory.v1" }, {});
  await client.repair(undefined, {});
  await client.uninstallPlan();
  await client.uninstall({ schemaVersion: "desktop.uninstall-plan.v1" }, { dryRun: true });
  assert.deepEqual(calls.map(call => call.command), [
    "migration_scan_legacy",
    "migration_preview",
    "migration_execute",
    "migration_rollback",
    "migration_recover",
    "migration_cleanup",
    "migration_repair",
    "migration_uninstall_plan",
    "migration_uninstall_execute",
  ]);
}

function testRustSafetyAndUiWiring() {
  for (const text of [migrationSource, wizardSource]) {
    assert.match(text, /reparse|reparsePoint/i);
    assert.match(text, /locked|lockedLeftovers/i);
    assert.match(text, /secret|redact/i);
  }
  assert.match(migrationSource, /MIGRATION_JOURNAL_SCHEMA/);
  assert.match(migrationSource, /rollback_journal/);
  assert.match(migrationSource, /FULL_WIPE_CONFIRMATION/);
  assert.match(migrationSource, /export_import_required/);
  assert.match(migrationSource, /safe_join/);
  assert.match(wizardSource, /Nothing is deleted/);
  assert.match(wizardSource, /Keep the old copy/);
  assert.match(wizardSource, /Migrate supported data/);
  assert.match(wizardSource, /Clean approved disposable state/);
  assert.match(shellSource, /MigrationCleanupWizard/);
  assert.match(shellSource, /migrationClient\.scan/);
  assert.match(installerSource, /installMode|per-machine/i);
  assert.match(installerSource, /Abort/);
  assert.match(installerSource, /CreateShortCut/);
  assert.match(installerSource, /AI Video Editor Desktop V2/);
  assert.match(installerSource, /\$APPDATA\\AI Video Editor/);
  assert.doesNotMatch(installerSource, /COMMONAPPDATA/);
  assert.match(installerSource, /projects|uploads|models|database/i);
  assert.doesNotMatch(installerSource, /taskkill/i);
}

testContractsAndRedaction();
await testMockBridgeCommandSurface();
testRustSafetyAndUiWiring();
console.log("Desktop V2 Phase 7 tests passed: contract versions, mock command surface, redaction, migration safety invariants, wizard wiring, and NSIS policy");
