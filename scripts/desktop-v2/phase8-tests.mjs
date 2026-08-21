import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const workflow = await import(pathToFileURL(path.join(repoRoot, "desktop", "src", "lib", "workflow.ts")).href);
const ingest = await import(pathToFileURL(path.join(repoRoot, "desktop", "src", "lib", "ingest.ts")).href);
const dashboard = await import(pathToFileURL(path.join(repoRoot, "desktop", "src", "lib", "dashboardModel.ts")).href);
const apiSource = await readFile(path.join(repoRoot, "desktop", "src", "lib", "api.ts"), "utf8");
const transcriptSource = await readFile(path.join(repoRoot, "desktop", "src", "components", "TranscriptPanel.tsx"), "utf8");
const workflowPanelSource = await readFile(path.join(repoRoot, "desktop", "src", "components", "GuidedWorkflow.tsx"), "utf8");

const project = (id, title, status, updated_at) => ({
  id,
  title,
  description: "",
  project_type: "lecture",
  status,
  created_at: updated_at,
  updated_at,
  settings: {},
});

function testWorkflowTransitionsAndActions() {
  assert.equal(workflow.legacyToWorkflowState(project("p1", "Draft", "draft", "2026-01-01")), "source_required");
  assert.equal(workflow.legacyToWorkflowState(project("p1", "Ready", "ready", "2026-01-01"), { status: "awaiting_review" }), "review_suggestions");
  assert.equal(workflow.workflowNextAction("failed"), "Repair or retry");
  assert.equal(workflow.workflowProgress({ status: "completed" }), 100);
  assert.equal(workflow.workflowProgress({ status: "processing" }, 112), 100);
  assert.equal(workflow.isWorkflowActive("exporting"), true);
}

function testIngestValidationAndDuplicateDetection() {
  const existing = [{ original_filename: "lecture.mp4", file_size_bytes: 1024 }];
  const valid = ingest.validateVideoFile({ name: "lecture.mp4", size: 1024, type: "video/mp4" }, existing);
  assert.equal(valid.valid, true);
  assert.equal(valid.duplicate, true);
  assert.match(valid.warnings.join(" "), /same name and size/i);
  const invalid = ingest.validateVideoFile({ name: "notes.txt", size: 0, type: "text/plain" });
  assert.equal(invalid.valid, false);
  assert.equal(invalid.errors.length, 2);
  assert.equal(ingest.formatBytes(1024 * 1024), "1.0 MB");
}

function testDashboardFiltersAndSort() {
  const projects = [
    project("p1", "Beta Lecture", "ready", "2026-01-02"),
    project("p2", "Alpha Lecture", "failed", "2026-01-03"),
  ];
  const videos = new Map([
    ["p1", [{ id: "v1", project_id: "p1", status: "processing" }]],
    ["p2", [{ id: "v2", project_id: "p2", status: "failed" }]],
  ]);
  assert.deepEqual(dashboard.filterAndSortProjects(projects, videos, "alpha", "all", "title").map(item => item.id), ["p2"]);
  assert.deepEqual(dashboard.filterAndSortProjects(projects, videos, "", "processing", "updated").map(item => item.id), ["p1"]);
  assert.deepEqual(dashboard.filterAndSortProjects(projects, videos, "", "failed", "updated").map(item => item.id), ["p2"]);
  assert.deepEqual(dashboard.filterAndSortProjects(projects, videos, "", "all", "title").map(item => item.id), ["p2", "p1"]);
}

function testMockedIngestToExportFlow() {
  const flow = ["source_required", "validating", "ready_for_analysis", "analyzing", "review_suggestions", "editing", "export_ready", "exporting", "completed"];
  assert.deepEqual(flow.map(state => workflow.workflowLabel(state)), [
    "Add a source", "Checking source", "Ready for analysis", "Analyzing", "Review suggestions",
    "Editing", "Ready to export", "Exporting", "Completed",
  ]);
  assert.equal(workflow.workflowNextAction(flow[0]), "Import a primary video");
  assert.equal(workflow.workflowNextAction(flow.at(-1)), "Continue editing");
}

function testRecoveryAndAccessibilityWiring() {
  assert.match(apiSource, /BACKEND_UNAVAILABLE/);
  assert.match(apiSource, /testProviderConnection/);
  assert.match(apiSource, /retryVideoProcessing/);
  assert.match(apiSource, /NATIVE_BRIDGE_ENABLED/);
  assert.match(transcriptSource, /Search transcript/);
  assert.match(transcriptSource, /role="button"/);
  assert.match(transcriptSource, /aria-current/);
  assert.match(workflowPanelSource, /exportBlocked/);
  assert.match(workflowPanelSource, /Export is blocked until prerequisites are fixed/);
}

testWorkflowTransitionsAndActions();
testIngestValidationAndDuplicateDetection();
testDashboardFiltersAndSort();
testMockedIngestToExportFlow();
testRecoveryAndAccessibilityWiring();
console.log("Desktop V2 Phase 8 tests passed: workflow mapping, ingest validation, dashboard filters, and mocked ingest-to-export flow");
