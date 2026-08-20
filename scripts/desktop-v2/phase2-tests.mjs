import assert from "node:assert/strict";
import { pathToFileURL, fileURLToPath } from "node:url";
import path from "node:path";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const shell = await import(pathToFileURL(path.join(repoRoot, "desktop", "src", "desktopV2.ts")).href);
const contracts = await import(pathToFileURL(path.join(repoRoot, "desktop", "src", "contracts", "desktopV2.ts")).href);

function testBootTransitions() {
  let state = shell.initialBootState();
  assert.equal(state, "starting");
  state = shell.transitionBootState(state, { type: "shell-ready" });
  assert.equal(state, "shell-ready");
  assert.equal(shell.transitionBootState(state, { type: "component-scan", componentState: "not-installed" }), "setup-required");
  assert.equal(shell.transitionBootState(state, { type: "component-scan", componentState: "available" }), "engine-available");
  assert.equal(shell.transitionBootState(state, { type: "component-scan", componentState: "invalid" }), "recoverable-error");
  assert.equal(shell.transitionBootState("engine-available", { type: "supervisor-ready" }), "engine-available");
}

function testMissingComponentStartup() {
  assert.equal(shell.deriveBootState("not-installed"), "setup-required");
  assert.equal(shell.deriveBootState("unavailable"), "recoverable-error");
  assert.equal(shell.deriveBootState("available"), "engine-available");
  assert.equal(shell.engineViewsEnabled({ bootState: "setup-required", engineReady: false }), false);
  assert.equal(shell.engineViewsEnabled({ bootState: "engine-available", engineReady: false }), false);
  assert.equal(shell.engineViewsEnabled({ bootState: "engine-available", engineReady: true }), true);
}

function testStoragePathInvariants() {
  assert.equal(shell.storagePathInvariantsHold(), true);
  const invalid = structuredClone(contracts.canonicalWindowsStorageLayout());
  // The pure invariant helper must reject a shell path that is writable.
  invalid.programFilesRuntimeWritable = true;
  assert.equal(shell.storagePathInvariantsHold(invalid), false);
}

function testDiagnosticsRedaction() {
  const redacted = shell.redactDiagnosticText("password=secret token=abc Bearer very-secret sk-abcdefghijkl");
  assert.equal(redacted.includes("secret"), false);
  assert.equal(redacted.includes("very-secret"), false);
  assert.equal(redacted.includes("sk-abcdefghijkl"), false);
  assert.equal(redacted.includes("[REDACTED]"), true);
}

function testRuntimeRouting() {
  assert.equal(shell.resolveAppRoute(false), "browser-editor");
  assert.equal(shell.resolveAppRoute(true), "desktop-v2-shell");
}

testBootTransitions();
testMissingComponentStartup();
testStoragePathInvariants();
testDiagnosticsRedaction();
testRuntimeRouting();
console.log("Desktop V2 Phase 2 tests passed: boot transitions, missing-component startup, path invariants, diagnostics redaction, and runtime routing");
