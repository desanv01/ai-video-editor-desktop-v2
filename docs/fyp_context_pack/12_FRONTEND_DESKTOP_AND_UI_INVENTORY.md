# Frontend, Desktop, and UI Inventory

## Hierarchy

```text
App
  ProjectDashboard
  UploadPanel / multi-source intake
  ProcessingView
  ReviewEditor
    GuidedWorkflow: Transcribe, Clean, Sections, Layout, Polish, Export
    TranscriptPanel / SegmentDetail / Timeline / StatsPanel
  MainSettingsPanel / TranscriptionSettingsPanel
```

Tauri 2 configuration is in `desktop/src-tauri/tauri.conf.json`; React 19 dependencies are in `desktop/package.json`. `App.tsx:25-213` restores hash-based project/video context, bootstraps the native backend, and selects dashboard/upload/processing/review views. API calls and native IPC wrappers live in `desktop/src/lib/api.ts`.

The UI includes project creation/loading, multi-source imports, native import progress, chunked browser upload, processing progress, teacher transcript/action review, semantic layout controls, annotations/polish, export presets, render progress/cancel, and artifact downloads. Backend URL selection differs by browser/desktop runtime. Projects stored in different Docker/PostgreSQL stacks will not appear across runtimes.

Potentially disconnected/unfinished features: Tauri local `save_project`/`load_project` is not the dashboard's primary persistence; hidden `{false && ...}` legacy layout panels remain in `GuidedWorkflow.tsx:1250,1356`; Redis has no UI-visible function; MCP has no UI; no frontend test suite was found.

## Screenshot checklist

1. Project dashboard with project summary and creation panel.
2. Multi-source intake with video, screen, camera, audio, and material options.
3. Processing progress showing five agents.
4. Transcribe/Clean transcript decision screen.
5. Sections view with topic blocks.
6. Layout view with page relation and teacher override.
7. Polish annotations/captions view.
8. Export preset and render progress view.
9. Settings provider/mode panel with all secrets masked.
10. Final exported artifacts/download panel.
