import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const setup = await import(pathToFileURL(path.join(repoRoot, "desktop", "src", "setupCenter.ts")).href);
const shell = await import(pathToFileURL(path.join(repoRoot, "desktop", "src", "desktopV2.ts")).href);
const appSource = await readFile(path.join(repoRoot, "desktop", "src", "App.tsx"), "utf8");
const managerSource = await readFile(path.join(repoRoot, "desktop", "src", "componentManager.ts"), "utf8");
const setupPanelSource = await readFile(path.join(repoRoot, "desktop", "src", "components", "SetupCenterPanel.tsx"), "utf8");
const installerSource = await readFile(path.join(repoRoot, "desktop", "src-tauri", "nsis", "installer-hooks.nsh"), "utf8");
const catalogSchema = JSON.parse(await readFile(path.join(repoRoot, "contracts", "desktop-v2", "schemas", "setup-catalog.v1.schema.json"), "utf8"));
const stateSchema = JSON.parse(await readFile(path.join(repoRoot, "contracts", "desktop-v2", "schemas", "setup-state.v1.schema.json"), "utf8"));

function testStateAndHealthyBypass() {
  const state = setup.defaultSetupState(1234);
  assert.equal(state.schemaVersion, "desktop.setup-state.v1");
  assert.deepEqual(state.selectedOptionalPacks, []);
  assert.equal(setup.requiredComponentsReady([
    { id: "aive-engine", state: "active" },
    { id: "ffmpeg", state: "active" },
  ]), true);
  assert.equal(setup.requiredComponentsReady([{ id: "aive-engine", state: "active" }]), false);
  assert.equal(setup.canLaunchEditor({ state: "ready", engineReady: true }), true);
  assert.equal(setup.canLaunchEditor({ state: "degraded", engineReady: true }), true);
  assert.equal(setup.canLaunchEditor({ state: "ready", engineReady: false }), false);
}

function testSelectionAndCatalogTruthfulness() {
  const optional = {
    componentId: "model-pack",
    displayName: "Model pack",
    required: false,
    availability: "catalog-only",
    description: "Not released",
    artifactBytes: 0,
    licenseVersion: "",
    licenseName: "",
    sourceUrl: null,
    unavailableReason: "No signed artifact",
    manifest: null,
  };
  assert.equal(setup.catalogEntryIsInstallable(optional), false);
  assert.equal(setup.catalogEntryIsInstallable({ ...optional, availability: "available", manifest: { component: {} } }), true);
  assert.equal(setup.optionalComponentIsSelected({ ...setup.defaultSetupState(), selectedOptionalPacks: ["model-pack"] }, "model-pack"), true);
}

function testProgressAndErrorCopy() {
  const progress = setup.aggregateProgress(["ffmpeg", "aive-engine"], {
    first: { operationId: "first", componentId: "ffmpeg", componentVersion: "1.0.0", operation: "download", state: "downloading", bytesDownloaded: 50, totalBytes: 100, percent: 50, message: "Downloading FFmpeg" },
    second: { operationId: "second", componentId: "aive-engine", componentVersion: "1.0.0", operation: "download", state: "downloaded", bytesDownloaded: 100, totalBytes: 100, percent: 100, message: "Downloaded engine" },
  });
  assert.equal(progress.percent, 75);
  assert.equal(progress.bytesDownloaded, 150);
  assert.equal(setup.normalizeSetupError({ code: "SIGNATURE_INVALID", message: "token=private-value" }).message.includes("signature"), true);
  assert.equal(setup.normalizeSetupError({ code: "SIGNATURE_INVALID", message: "token=private-value" }).technicalDetail.includes("private-value"), false);
  for (const code of ["DISK_SPACE_LOW", "UAC_CANCELLED", "DOWNLOAD_CANCELLED", "SELF_TEST_FAILED", "ENGINE_CRASHED", "OPERATION_RETRY_EXHAUSTED"]) {
    assert.notEqual(setup.friendlySetupMessage(code), setup.friendlySetupMessage("UNRECOGNIZED_CODE"));
  }
  assert.match(managerSource, /component_pause/);
  assert.match(managerSource, /component_cancel/);
  assert.match(managerSource, /component_retry/);
  assert.match(managerSource, /component_rollback/);
  assert.match(managerSource, /component_repair/);
  assert.match(setupPanelSource, /incompleteOperationIds/);
  assert.match(setupPanelSource, /Resume download/);
}

function testCatalogValidationAndOfflineMockBridge() {
  assert.equal(catalogSchema.$id, "https://schemas.aive.dev/desktop-v2/setup-catalog.v1.schema.json");
  assert.equal(stateSchema.$id, "https://schemas.aive.dev/desktop-v2/setup-state.v1.schema.json");
  assert.equal(catalogSchema.additionalProperties, false);
  assert.equal(stateSchema.additionalProperties, false);
  assert.deepEqual(catalogSchema.required, ["schemaVersion", "catalogId", "channel", "generatedAt", "expiresAt", "entries", "signature"]);
  assert.deepEqual(stateSchema.required, ["schemaVersion", "selectedOptionalPacks", "acceptedLicenseVersions", "catalogChannel", "lastSuccessfulSetup", "incompleteOperationIds", "onboardingCompleted", "updatedAtEpochMs"]);
  assert.equal(setup.validateCatalogEnvelope(null).valid, false);
  assert.equal(setup.validateCatalogEnvelope({ schemaVersion: "desktop.setup-catalog.v1", entries: [], signature: { algorithm: "ed25519", keyId: "test" } }).valid, false);
  const calls = [];
  const mock = setup.createSetupClient({
    async invoke(command, args) {
      calls.push({ command, args });
      if (command === "setup_get_state") return setup.defaultSetupState(99);
      if (command === "setup_run_system_checks") return { supported: true, checks: [] };
      return null;
    },
  });
  return mock.getState().then(state => {
    assert.equal(state.updatedAtEpochMs, 99);
    return mock.runSystemChecks(false);
  }).then(() => {
    assert.deepEqual(calls.map(call => call.command), ["setup_get_state", "setup_run_system_checks"]);
    assert.deepEqual(calls[1].args, { probeNetwork: false });
  });
}

function testBrowserIsolationAndAclDecision() {
  assert.equal(shell.resolveAppRoute(false), "browser-editor");
  assert.equal(shell.resolveAppRoute(true), "desktop-v2-shell");
  assert.match(appSource, /resolveAppRoute\(isTauriRuntime\)/);
  assert.doesNotMatch(appSource, /setup_get_state.*browser/i);
  assert.match(installerSource, /icacls\.exe/);
  assert.match(installerSource, /ProgramData|COMMONAPPDATA/);
  assert.match(installerSource, /Program Files remains immutable/);
}

testStateAndHealthyBypass();
testSelectionAndCatalogTruthfulness();
testProgressAndErrorCopy();
await testCatalogValidationAndOfflineMockBridge();
testBrowserIsolationAndAclDecision();
console.log("Desktop V2 Phase 6 tests passed: setup state, selection truthfulness, catalog validation, mock bridge, progress/error recovery, browser isolation, and ACL policy");
