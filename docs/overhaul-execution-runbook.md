# AI Video Editor Overhaul Execution Runbook

This file is the single source of truth for how to execute the complete FYP AI video editor overhaul across separate chats, task branches, phase branches, commits, merges, GitHub pushes, and final integration testing.

Use this file whenever you feel unsure about where to start, what to paste into a new chat, when to commit, when to merge, or how all branches eventually come together.

## 1. Big Picture

The overhaul should be built in phases.

Each phase has:

- One phase branch.
- Multiple task branches.
- Usually one separate chat/window per task branch.

The safest rule is:

```text
one task branch = one chat/window
```

Each task branch is merged back into its phase branch. The next phase starts from the completed previous phase branch.

The branch chain should look like this:

```text
codex/system-overhaul
   ↓
codex/phase-0-overhaul-blueprint
   ↓
codex/phase-1-ai-provider-foundation
   ↓
codex/phase-2-local-transcription
   ↓
codex/phase-3-project-assets
   ↓
codex/phase-4-guided-editor-shell
   ↓
codex/phase-5-transcript-editor
   ↓
codex/phase-6-clean-sections
   ↓
codex/phase-7-layout-engine
   ↓
codex/phase-8-polish-tools
   ↓
codex/phase-9-export-render
   ↓
codex/phase-10-evaluation-demo
```

If this chain is followed correctly, the final phase branch already contains all previous phase work.

## 2. What Is Manual And What Codex Can Do

Git does not automatically commit, merge, push, or create integration branches.

But you do not need to do everything manually. You can ask Codex to do it by pasting the right command in the chat.

Codex can usually handle:

- Creating task branches.
- Creating phase branches.
- Implementing the task.
- Running tests/checks.
- Committing the task branch.
- Merging the task branch into its phase branch.
- Creating the next phase branch.
- Preparing the final integration branch.
- Pushing branches to GitHub if GitHub remote/authentication is available.

You should still review the final summary after each task.

## 3. The Universal Starting Prompt

Paste this at the top of every new task chat, then add the specific phase/task prompt below it.

```text
Continue the AI video editor overhaul project.

Repo path: C:\Users\Dv\Desktop\ai-video-editor
Read this first: docs/phase-0-overhaul-blueprint.md
Also read this execution guide if needed: docs/overhaul-execution-runbook.md

Important rules:
- Do not touch main.
- Do not revert unrelated existing changes.
- Create/switch to the task branch I specify.
- Implement only the task for this chat.
- Keep the app working after the change.
- At the end, give me a handoff summary: branch, files changed, what was implemented, tests/checks run, known issues, and the next recommended task branch.
```

## 4. Normal Task Workflow

For each task:

1. Open a new chat/window.
2. Paste the universal starting prompt.
3. Paste the specific task prompt from this file.
4. Let Codex implement the task.
5. Review the result.
6. Ask Codex to commit and merge the task branch into its phase branch.
7. Open the next chat for the next task.

The rhythm is:

```text
start task prompt
↓
Codex implements task
↓
commit/merge prompt
↓
Codex merges task into phase branch
↓
next task chat
```

## 5. After Each Task: Commit And Merge Prompt

At the end of each completed task chat, paste this:

```text
Commit this task branch, merge it into its phase branch, run the relevant checks, and tell me the next task branch.
```

This generic version should work because the chat already knows the phase branch and task branch from the starting prompt.

If you want to be explicit, use the phase-specific prompts below.

### After Any Phase 1 Task

```text
Commit this task branch, merge it into codex/phase-1-ai-provider-foundation, run the relevant checks, and tell me the next task branch.
```

### After Any Phase 2 Task

```text
Commit this task branch, merge it into codex/phase-2-local-transcription, run the relevant checks, and tell me the next task branch.
```

### After Any Phase 3 Task

```text
Commit this task branch, merge it into codex/phase-3-project-assets, run the relevant checks, and tell me the next task branch.
```

### After Any Phase 4 Task

```text
Commit this task branch, merge it into codex/phase-4-guided-editor-shell, run the relevant checks, and tell me the next task branch.
```

### After Any Phase 5 Task

```text
Commit this task branch, merge it into codex/phase-5-transcript-editor, run the relevant checks, and tell me the next task branch.
```

### After Any Phase 6 Task

```text
Commit this task branch, merge it into codex/phase-6-clean-sections, run the relevant checks, and tell me the next task branch.
```

### After Any Phase 7 Task

```text
Commit this task branch, merge it into codex/phase-7-layout-engine, run the relevant checks, and tell me the next task branch.
```

### After Any Phase 8 Task

```text
Commit this task branch, merge it into codex/phase-8-polish-tools, run the relevant checks, and tell me the next task branch.
```

### After Any Phase 9 Task

```text
Commit this task branch, merge it into codex/phase-9-export-render, run the relevant checks, and tell me the next task branch.
```

### After Any Phase 10 Task

```text
Commit this task branch, merge it into codex/phase-10-evaluation-demo, run the relevant checks, and tell me the next task branch.
```

## 6. After Each Phase Is Complete

After all tasks inside a phase are committed and merged into the phase branch, paste this:

```text
This phase is completed. Create the next phase branch from this completed phase branch, confirm the branch chain is correct, and give me the first task prompt for the next phase.
```

Example:

If Phase 1 is complete, Codex should create Phase 2 from:

```text
codex/phase-1-ai-provider-foundation
```

The new phase branch should be:

```text
codex/phase-2-local-transcription
```

## 7. Local Commits Vs GitHub Pushes

Use this rule:

```text
commit often locally, push to GitHub at stable checkpoints
```

Recommended strategy:

- Commit locally after every completed task branch.
- Merge each completed task branch into its phase branch.
- Push to GitHub after every completed phase.
- Push earlier if the task is very big or risky and you want a backup.

Do not wait until the whole overhaul is done before committing. That is risky because you lose clean restore points.

Do not push broken code unless you specifically want a backup branch.

## 8. Prompt To Push A Completed Phase To GitHub

After a phase branch is complete and checks pass, paste:

```text
Push this completed phase branch to GitHub. If there are uncommitted changes or failed checks, stop and explain what needs to be fixed first.
```

If you want a safer backup push for a task branch before merging, paste:

```text
Push this task branch to GitHub as a backup branch, but do not merge it yet. Tell me the branch name and current status after pushing.
```

## 9. Final Integration Testing

At the end, if the branch chain was followed properly, this branch should contain the whole overhaul:

```text
codex/phase-10-evaluation-demo
```

For final testing, create an integration branch from Phase 10:

```text
codex/full-overhaul-integration
```

Prompt to paste:

```text
Create a final integration branch from codex/phase-10-evaluation-demo named codex/full-overhaul-integration. Run full backend/frontend checks, start the app if appropriate, and test the complete overhaul workflow end to end.
```

If bugs appear during integration, fix them on:

```text
codex/full-overhaul-integration
```

After integration is stable, merge into:

```text
codex/system-overhaul
```

Prompt to paste:

```text
The full integration branch is stable. Merge codex/full-overhaul-integration into codex/system-overhaul, run the relevant checks again, and summarize the final merged state.
```

Only merge into `main` later when you are fully satisfied.

## 10. Phase 1: AI Provider Foundation

### Phase 1 Chat 1

```text
Use the universal rules.

Base branch: codex/phase-0-overhaul-blueprint
Create phase branch if needed: codex/phase-1-ai-provider-foundation
Create task branch: codex/phase-1-provider-interfaces

Task: Design and implement the backend AI provider interfaces and registry skeleton for transcription, chat/reasoning, embeddings, vision, and local model runtimes. Keep existing behavior working.
```

### Phase 1 Chat 2

```text
Use the universal rules.

Base branch: codex/phase-1-ai-provider-foundation
Create task branch: codex/phase-1-processing-modes

Task: Add processing modes: API, Local, and Hybrid. Add backend configuration structures for choosing provider mode per capability, without changing the current pipeline behavior yet.
```

### Phase 1 Chat 3

```text
Use the universal rules.

Base branch: codex/phase-1-ai-provider-foundation
Create task branch: codex/phase-1-settings-schema

Task: Add persistent app/settings schema for AI providers, API keys, local model paths, preferred processing mode, and fallback behavior. Keep secrets handled safely.
```

### Phase 1 Chat 4

```text
Use the universal rules.

Base branch: codex/phase-1-ai-provider-foundation
Create task branch: codex/phase-1-provider-routing

Task: Route the existing transcription, DeepSeek chat, and embeddings calls through the new provider abstraction with minimal behavior change.
```

### Phase 1 Chat 5

```text
Use the universal rules.

Base branch: codex/phase-1-ai-provider-foundation
Create task branch: codex/phase-1-provider-tests

Task: Add focused backend tests for provider registry, mode selection, fallback behavior, and existing pipeline compatibility.
```

## 11. Phase 2: Local Transcription

### Phase 2 Chat 1

```text
Use the universal rules.

Base branch: codex/phase-1-ai-provider-foundation
Create phase branch if needed: codex/phase-2-local-transcription
Create task branch: codex/phase-2-whisper-cpp-adapter

Task: Add local Whisper transcription adapter support, model selection structure, and backend integration point without requiring real model download yet.
```

### Phase 2 Chat 2

```text
Use the universal rules.

Base branch: codex/phase-2-local-transcription
Create task branch: codex/phase-2-model-catalog

Task: Add local transcription model catalog: small, medium, large-v3, size, speed, quality, active/downloaded status.
```

### Phase 2 Chat 3

```text
Use the universal rules.

Base branch: codex/phase-2-local-transcription
Create task branch: codex/phase-2-model-downloads

Task: Add backend service and UI-ready API shape for downloading/removing local transcription models.
```

### Phase 2 Chat 4

```text
Use the universal rules.

Base branch: codex/phase-2-local-transcription
Create task branch: codex/phase-2-transcription-routing

Task: Add local/API/hybrid transcription routing with fallback.
```

### Phase 2 Chat 5

```text
Use the universal rules.

Base branch: codex/phase-2-local-transcription
Create task branch: codex/phase-2-transcription-settings-ui

Task: Add frontend settings UI for transcription mode and model choice.
```

## 12. Phase 3: Project Assets And Multi-Source Input

### Phase 3 Chat 1

```text
Use the universal rules.

Base branch: codex/phase-2-local-transcription
Create phase branch if needed: codex/phase-3-project-assets
Create task branch: codex/phase-3-project-model

Task: Implement the project-first backend data model while preserving the existing legacy video flow. Add Project and ProjectAsset style structures so future uploads can belong to a project instead of only a single video.
```

### Phase 3 Chat 2

```text
Use the universal rules.

Base branch: codex/phase-3-project-assets
Create task branch: codex/phase-3-asset-upload-api

Task: Add project asset upload APIs for video, audio, slides, notes, and supporting materials. Keep existing /videos upload route working for backward compatibility.
```

### Phase 3 Chat 3

```text
Use the universal rules.

Base branch: codex/phase-3-project-assets
Create task branch: codex/phase-3-screen-camera-audio-sources

Task: Add support for separate screen recording, camera/webcam/phone recording, and separate audio recording as different project media sources. Store source type, duration, metadata, and intended sync role.
```

### Phase 3 Chat 4

```text
Use the universal rules.

Base branch: codex/phase-3-project-assets
Create task branch: codex/phase-3-slide-note-assets

Task: Add slide deck, PDF, and notes asset support so lecture structure can later be inferred from uploaded teaching material. Include backend models/API fields and frontend upload affordances if appropriate.
```

### Phase 3 Chat 5

```text
Use the universal rules.

Base branch: codex/phase-3-project-assets
Create task branch: codex/phase-3-source-sync

Task: Add initial source synchronization logic for separate screen, camera, and audio files. Start with metadata-based and user-adjustable sync offsets, preparing for waveform/audio-based sync later.
```

## 13. Phase 4: Guided Editor Shell And Pro UI

### Phase 4 Chat 1

```text
Use the universal rules.

Base branch: codex/phase-3-project-assets
Create phase branch if needed: codex/phase-4-guided-editor-shell
Create task branch: codex/phase-4-project-dashboard

Task: Build a project dashboard inspired by professional editor workflows: project list, create project, project type, recent projects, status, and continue editing entry point.
```

### Phase 4 Chat 2

```text
Use the universal rules.

Base branch: codex/phase-4-guided-editor-shell
Create task branch: codex/phase-4-guided-workflow

Task: Implement the guided editor workflow steps: Transcribe, Clean, Sections, Layout, Polish, Export. The UI should clearly show progress and allow moving between steps.
```

### Phase 4 Chat 3

```text
Use the universal rules.

Base branch: codex/phase-4-guided-editor-shell
Create task branch: codex/phase-4-settings-ui

Task: Build the main settings UI for AI mode, API/local provider choices, export folder, appearance, local model settings, and future guided tours.
```

### Phase 4 Chat 4

```text
Use the universal rules.

Base branch: codex/phase-4-guided-editor-shell
Create task branch: codex/phase-4-editor-layout

Task: Redesign the editor layout into a professional workspace: left transcript/assets panel, center preview, right contextual controls, bottom status/timeline area. Preserve existing review functionality where possible.
```

### Phase 4 Chat 5

```text
Use the universal rules.

Base branch: codex/phase-4-guided-editor-shell
Create task branch: codex/phase-4-shortcuts-command-palette

Task: Add keyboard shortcut structure and command palette foundation for editor actions such as play/pause, undo, redo, seek, cut selection, export, and open settings.
```

## 14. Phase 5: Transcript-Based Editing

### Phase 5 Chat 1

```text
Use the universal rules.

Base branch: codex/phase-4-guided-editor-shell
Create phase branch if needed: codex/phase-5-transcript-editor
Create task branch: codex/phase-5-word-timeline-model

Task: Add word-level transcript timeline structures so words can map accurately to video/audio time ranges. Preserve existing segment-level transcript behavior.
```

### Phase 5 Chat 2

```text
Use the universal rules.

Base branch: codex/phase-5-transcript-editor
Create task branch: codex/phase-5-select-text-to-cut

Task: Implement transcript text selection to create cut/edit decisions. User should be able to select words or phrases and mark them for removal from the video.
```

### Phase 5 Chat 3

```text
Use the universal rules.

Base branch: codex/phase-5-transcript-editor
Create task branch: codex/phase-5-undo-redo

Task: Add undo/redo support for transcript edits, cut decisions, and manual changes.
```

### Phase 5 Chat 4

```text
Use the universal rules.

Base branch: codex/phase-5-transcript-editor
Create task branch: codex/phase-5-edit-decision-sync

Task: Synchronize transcript edits with edit decisions, timeline display, preview playback, and export planning.
```

### Phase 5 Chat 5

```text
Use the universal rules.

Base branch: codex/phase-5-transcript-editor
Create task branch: codex/phase-5-manual-trim-controls

Task: Add manual trim controls for precise timing adjustment around transcript-based cuts, including pre-roll/post-roll tolerance.
```

## 15. Phase 6: Clean And Sections Intelligence

### Phase 6 Chat 1

```text
Use the universal rules.

Base branch: codex/phase-5-transcript-editor
Create phase branch if needed: codex/phase-6-clean-sections
Create task branch: codex/phase-6-clean-tools

Task: Implement Clean step tools: auto-clean, filler word removal, dead-air trimming, bad-take detection, and conservative/aggressive cleaning profiles.
```

### Phase 6 Chat 2

```text
Use the universal rules.

Base branch: codex/phase-6-clean-sections
Create task branch: codex/phase-6-false-starts-repetition

Task: Add detection for false starts, repeated explanations, restarted sentences, and repeated phrases. Convert detections into reviewable edit suggestions.
```

### Phase 6 Chat 3

```text
Use the universal rules.

Base branch: codex/phase-6-clean-sections
Create task branch: codex/phase-6-topic-segmentation

Task: Add automatic topic/section segmentation from transcript content and pauses. Generate suggested lecture chapters or sections.
```

### Phase 6 Chat 4

```text
Use the universal rules.

Base branch: codex/phase-6-clean-sections
Create task branch: codex/phase-6-slide-aware-sectioning

Task: Use uploaded slides/PDF titles and slide changes to improve lecture section detection and chapter labeling.
```

### Phase 6 Chat 5

```text
Use the universal rules.

Base branch: codex/phase-6-clean-sections
Create task branch: codex/phase-6-edit-plan-v2

Task: Upgrade the edit plan format to support transcript cuts, cleaning suggestions, sections, layout cues, polish actions, and export metadata while keeping old edit plans compatible.
```

## 16. Phase 7: Layout Engine

### Phase 7 Chat 1

```text
Use the universal rules.

Base branch: codex/phase-6-clean-sections
Create phase branch if needed: codex/phase-7-layout-engine
Create task branch: codex/phase-7-layout-data-model

Task: Add layout data model for screen, camera, audio, picture-in-picture, side-by-side, full-screen source, full-camera source, aspect ratio, shape, corner, and timing cues.
```

### Phase 7 Chat 2

```text
Use the universal rules.

Base branch: codex/phase-7-layout-engine
Create task branch: codex/phase-7-layout-rules

Task: Implement rule-based layout planning for lecture videos using available sources. Choose sensible defaults for single-source and multi-source projects.
```

### Phase 7 Chat 3

```text
Use the universal rules.

Base branch: codex/phase-7-layout-engine
Create task branch: codex/phase-7-layout-ui

Task: Build the Layout step UI with layout style selection, camera position, aspect ratio, camera shape, and preview-ready settings.
```

### Phase 7 Chat 4

```text
Use the universal rules.

Base branch: codex/phase-7-layout-engine
Create task branch: codex/phase-7-picture-in-picture

Task: Implement picture-in-picture layout rendering support for screen plus camera sources.
```

### Phase 7 Chat 5

```text
Use the universal rules.

Base branch: codex/phase-7-layout-engine
Create task branch: codex/phase-7-side-by-side-fullscreen

Task: Implement side-by-side, full-screen source, and full-camera layout rendering support.
```

## 17. Phase 8: Polish Tools

### Phase 8 Chat 1

```text
Use the universal rules.

Base branch: codex/phase-7-layout-engine
Create phase branch if needed: codex/phase-8-polish-tools
Create task branch: codex/phase-8-selective-captions

Task: Add selective caption/subtitle styling tools, including when captions appear, caption placement, and export/burn-in behavior.
```

### Phase 8 Chat 2

```text
Use the universal rules.

Base branch: codex/phase-8-polish-tools
Create task branch: codex/phase-8-annotations-callouts

Task: Add annotations and callouts that can be placed on the timeline, previewed, edited, and included in export.
```

### Phase 8 Chat 3

```text
Use the universal rules.

Base branch: codex/phase-8-polish-tools
Create task branch: codex/phase-8-step-labels-title-cards

Task: Add step labels, section title cards, intro cards, and chapter labels for educational video polish.
```

### Phase 8 Chat 4

```text
Use the universal rules.

Base branch: codex/phase-8-polish-tools
Create task branch: codex/phase-8-transitions-animations

Task: Add basic transitions and animations for layout changes, section starts, callouts, and title cards.
```

### Phase 8 Chat 5

```text
Use the universal rules.

Base branch: codex/phase-8-polish-tools
Create task branch: codex/phase-8-end-card-cta

Task: Add end card/CTA support for lecture summary, next topic, course link, or custom closing message.
```

## 18. Phase 9: Export And Rendering

### Phase 9 Chat 1

```text
Use the universal rules.

Base branch: codex/phase-8-polish-tools
Create phase branch if needed: codex/phase-9-export-render
Create task branch: codex/phase-9-export-presets

Task: Add export presets grouped by Social, Professional, and Education. Include YouTube 1080p, YouTube 4K, TikTok/Reels, Instagram, LinkedIn, MP4 1080p/720p, LMS compatible, and podcast audio-only.
```

### Phase 9 Chat 2

```text
Use the universal rules.

Base branch: codex/phase-9-export-render
Create task branch: codex/phase-9-multitrack-renderer

Task: Upgrade the renderer to support multi-source timelines, separate audio/video sources, layout cues, captions, annotations, transitions, and polish elements.
```

### Phase 9 Chat 3

```text
Use the universal rules.

Base branch: codex/phase-9-export-render
Create task branch: codex/phase-9-render-progress

Task: Add render job progress tracking, error reporting, cancel support where possible, and frontend progress display.
```

### Phase 9 Chat 4

```text
Use the universal rules.

Base branch: codex/phase-9-export-render
Create task branch: codex/phase-9-audio-only-export

Task: Add audio-only export for podcast/lecture audio output using cleaned transcript/edit decisions.
```

### Phase 9 Chat 5

```text
Use the universal rules.

Base branch: codex/phase-9-export-render
Create task branch: codex/phase-9-edit-plan-export

Task: Add export of edit plan JSON, captions, chapters, quality report, and academic evidence artifacts for evaluation/demo purposes.
```

## 19. Phase 10: Evaluation, Demo, And Academic Evidence

### Phase 10 Chat 1

```text
Use the universal rules.

Base branch: codex/phase-9-export-render
Create phase branch if needed: codex/phase-10-evaluation-demo
Create task branch: codex/phase-10-synthetic-test-media

Task: Create synthetic test media fixtures and scripts for lecture video, screen recording, webcam/camera recording, separate audio, slides, and transcript data so the overhaul can be tested without private real recordings.
```

### Phase 10 Chat 2

```text
Use the universal rules.

Base branch: codex/phase-10-evaluation-demo
Create task branch: codex/phase-10-evaluation-metrics

Task: Add evaluation metrics for transcription accuracy proxy, processing time, cost, duration reduction, filler/dead-air removal, segment quality, layout correctness, and user override rate.
```

### Phase 10 Chat 3

```text
Use the universal rules.

Base branch: codex/phase-10-evaluation-demo
Create task branch: codex/phase-10-api-vs-local-vs-hybrid

Task: Add comparison workflow and reporting for API mode, local mode, and hybrid mode across transcription, analysis, edit planning, and rendering.
```

### Phase 10 Chat 4

```text
Use the universal rules.

Base branch: codex/phase-10-evaluation-demo
Create task branch: codex/phase-10-demo-script

Task: Create the final demo flow and presentation narrative for showing the production-quality AI video editor overhaul to supervisor/examiner.
```

### Phase 10 Chat 5

```text
Use the universal rules.

Base branch: codex/phase-10-evaluation-demo
Create task branch: codex/phase-10-thesis-evidence-exports

Task: Add export/report artifacts useful for thesis writing: before/after comparison, timeline decisions, AI provider mode used, metrics summary, and generated evidence files.
```

## 20. If A Chat Gets Too Long

If a chat becomes too long or confusing:

1. Stop after the current task is at a clean point.
2. Ask Codex to commit or summarize the current state.
3. Open a new chat.
4. Paste the universal starting prompt.
5. Add this continuation note:

```text
Previous chat became too long. Continue from the current repository state. First check git status and current branch, then continue the same task if it is not finished. Do not restart from scratch.
```

## 21. If There Are Merge Conflicts

Merge conflicts are normal in a large overhaul.

If Codex reports a conflict, paste:

```text
Resolve the merge conflicts carefully. Preserve both the completed task behavior and the phase branch behavior where possible. Do not discard unrelated changes. After resolving, run the relevant checks and summarize every conflicted file and how it was resolved.
```

## 22. If Tests Fail

If checks fail after a task or merge, paste:

```text
Fix the failing checks on this branch. Do not start the next task yet. Explain the failure, apply the smallest safe fix, rerun the relevant checks, and then update the handoff summary.
```

## 23. If You Are Unsure What Comes Next

Paste:

```text
Check the current git branch and docs/overhaul-execution-runbook.md. Tell me exactly where we are in the overhaul workflow, whether this task is committed and merged, and what the next chat prompt should be.
```

## 24. Recommended Current Starting Point

The first production task after Phase 0 is:

```text
codex/phase-1-provider-interfaces
```

This task belongs to:

```text
codex/phase-1-ai-provider-foundation
```

Do not start Phase 2 until all Phase 1 task branches have been committed and merged into:

```text
codex/phase-1-ai-provider-foundation
```

Do not start Phase 3 until all Phase 2 task branches have been committed and merged into:

```text
codex/phase-2-local-transcription
```

## 25. Simple Mental Model

Use this mental model:

```text
Task branch = small focused work
Phase branch = completed group of related tasks
Integration branch = final whole-system testing
GitHub push = backup and sharing checkpoint
Main branch = only after you are fully satisfied
```

The main thing to remember:

```text
Start one task in one chat.
Finish it.
Commit it.
Merge it into its phase.
Then move to the next task.
```
