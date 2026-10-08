'use strict';
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const Module = require('node:module');
const args = process.argv.slice(2);
const repo = path.resolve(args[0]);
const output = path.resolve(args[1]);
const modules = path.resolve(args[2] || path.join(repo, 'desktop/node_modules'));
fs.mkdirSync(path.dirname(output), { recursive: true });
fs.mkdirSync(output, { recursive: false });
const requireDesktop = Module.createRequire(path.join(modules, '../package.json'));
const esbuild = requireDesktop('esbuild');
const source = path.join(repo, 'desktop/src/components/GuidedWorkflow.tsx').replaceAll('\\', '/');
const entry = `
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { GuidedWorkflowPanel, DEFAULT_LAYOUT_PREVIEW_SETTINGS } from ${JSON.stringify(source)};
export function renderEstimate(estimate) {
 const noop = () => {};
 const props = {
  activeStep: 'export', completedStepIds: new Set(), videoId: 'duration-regression', transcriptId: null,
  segments: [], selectedSegment: null, selectedAnnotationId: null, selectedEducationalOverlayId: null,
  plan: { original_duration: 6, estimated_duration: 6, is_approved: true, layout_cues: [], slide_cues: [], editorial_blocks: [], sections: [], polish_actions: [] },
  readiness: null, readinessLoading: false, currentTime: 0, layoutSettings: DEFAULT_LAYOUT_PREVIEW_SETTINGS,
  warnings: null, chapters: [], chaptersLoading: false, approving: false, renderStatus: null, renderCancelling: false,
  onLayoutSettingsChange: noop, onLayoutDraftDirtyChange: noop, onPolishPlanUpdated: noop,
  onSelectedAnnotationChange: noop, onSelectedEducationalOverlayChange: noop, onAcceptAll: noop,
  onCleanApplied: noop, onApprove: noop, onCancelRender: noop, onRefreshChapters: noop,
  onSeekToTime: noop, onUpdateAction: noop, onCompleteStep: noop, onNextStep: noop, onPreviousStep: noop, onStepChange: noop,
  synchronizedEstimatedDurationSeconds: estimate
 };
 return renderToStaticMarkup(React.createElement(GuidedWorkflowPanel, props));
}
`;
const compiled = esbuild.buildSync({ stdin: { contents: entry, resolveDir: repo, sourcefile: 'export-duration-regression.tsx', loader: 'tsx' }, bundle: true, write: false, platform: 'node', format: 'cjs', jsx: 'automatic', packages: 'external', nodePaths: [modules] }).outputFiles[0].text;
const filename = path.join(output, 'production-panel.cjs');
fs.writeFileSync(filename, compiled);
const runtime = new Module(filename, module);
runtime.filename = filename;
runtime.paths = [modules, ...Module._nodeModulePaths(output)];
runtime._compile(compiled, filename);
const cases = [];
for (const [name, estimate, expected, saved] of [
 ['teacher-cut-shared-estimate', 4, '0:04', '0:02'],
 ['all-cut-valid-zero', 0, '0:00', '0:06'],
 ['unsynchronized-plan-fallback', null, '0:06', '0:00']
]) {
 const html = runtime.exports.renderEstimate(estimate);
 fs.writeFileSync(path.join(output, name + '.html'), html);
 function metric(label) {
  const escaped = label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const match = html.match(new RegExp('<div[^>]*>([^<]+)</div><div[^>]*>' + escaped + '</div>'));
  assert.ok(match, 'Missing metric ' + label);
  return match[1];
 }
 try {
  assert.equal(metric('Estimated'), expected);
  assert.equal(metric('Saved'), saved);
  cases.push({ name, status: 'passed' });
 } catch (error) {
  cases.push({ name, status: 'failed', error: String(error) });
 }
}
const receipt = { status: cases.every(c => c.status === 'passed') ? 'passed' : 'failed', scope: 'Actual production export panel server render with stale agent-plan estimate and shared edit-decision estimates; no API mocks or provider calls', cases };
fs.writeFileSync(path.join(output, 'receipt.json'), JSON.stringify(receipt, null, 2));
console.log(JSON.stringify(receipt, null, 2));
process.exitCode = receipt.status === 'passed' ? 0 : 1;

