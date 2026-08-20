import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const shell = await import(pathToFileURL(path.join(repoRoot, "desktop", "src", "desktopV2.ts")).href);
const supervisorSource = await readFile(path.join(repoRoot, "desktop", "src-tauri", "src", "supervisor.rs"), "utf8");
const fixtureSource = await readFile(path.join(repoRoot, "fixtures", "desktop-v2", "fake-engine", "fake_engine.py"), "utf8");

function testSupervisorReadinessGate() {
  assert.equal(shell.supervisorViewsEnabled(null), false);
  assert.equal(shell.supervisorViewsEnabled({ state: "starting", engineReady: false }), false);
  assert.equal(shell.supervisorViewsEnabled({ state: "degraded", engineReady: false }), false);
  assert.equal(shell.supervisorViewsEnabled({ state: "repair-required", engineReady: false }), false);
  assert.equal(shell.supervisorViewsEnabled({ state: "ready", engineReady: true }), true);
}

function testStatusLabelsAndFailureCopy() {
  assert.equal(shell.supervisorStateLabel({ state: "waiting-for-handshake", engineReady: false }), "Waiting for engine");
  assert.equal(shell.supervisorStateLabel({ state: "crashed-backoff", engineReady: false }), "Recovering engine");
  assert.equal(shell.supervisorStateLabel({ state: "repair-required", engineReady: false }), "Repair required");
}

function testBridgeSourceSafetyInvariants() {
  assert.match(supervisorSource, /AIVE_ENGINE_BEARER_TOKEN/);
  assert.match(supervisorSource, /engine_api_request/);
  assert.match(supervisorSource, /ENGINE_NOT_READY/);
  assert.match(supervisorSource, /127\.0\.0\.1/);
  assert.match(supervisorSource, /JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE|0x0000_2000/);
  assert.match(supervisorSource, /kill_owned/);
  assert.match(supervisorSource, /engine-control\/shutdown/);
  assert.match(supervisorSource, /STOP_GRACE_PERIOD/);
  assert.doesNotMatch(supervisorSource, /localStorage/);
  assert.doesNotMatch(supervisorSource, /bearer_token.*Serialize/);
  assert.doesNotMatch(supervisorSource, /taskkill|Get-Process/);
}

function testFakeEngineModes() {
  for (const mode of ["ready", "degraded", "wrong-protocol", "wrong-host", "malformed", "oversized", "timeout", "crash"]) {
    assert.match(fixtureSource, new RegExp(`"${mode}"|${mode}`), `fixture mode ${mode}`);
  }
  assert.match(fixtureSource, /127\.0\.0\.1/);
  assert.match(fixtureSource, /protocolVersion/);
  assert.doesNotMatch(fixtureSource, /--bearer-token/);
}

testSupervisorReadinessGate();
testStatusLabelsAndFailureCopy();
testBridgeSourceSafetyInvariants();
testFakeEngineModes();
console.log("Desktop V2 Phase 5 tests passed: readiness gating, bridge source safety, and deterministic fake-engine modes");
