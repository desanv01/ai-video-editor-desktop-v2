# Phase 10 Demo Script And Presentation Narrative

Branch: `codex/phase-10-demo-script`
Base branch: `codex/phase-10-evaluation-demo`
Audience: supervisor, examiner, and project evaluators
Target duration: 12 to 15 minutes, with a 5 minute fallback path

## Demo Thesis

This demo presents the overhaul as a production-quality academic prototype for AI-assisted lecture and MOOC video editing. The key claim is:

> The system turns raw teaching sources into an editable, reviewable, and evidence-backed lecture export while keeping the teacher in control.

The demonstration should prove five things:

- The app now works as a project-first editor, not just a single upload script.
- The workflow is guided around real editing stages: Transcribe, Clean, Sections, Layout, Polish, and Export.
- AI suggestions remain reviewable and explainable through transcript cuts, segment decisions, layout cues, and teacher overrides.
- Local, API, and hybrid processing modes can be compared as an academic evaluation dimension.
- The final export produces reproducible evidence: video/audio output, captions, chapters, edit plan JSON, quality report, mode comparison, and academic evidence bundle.

## Demo Scenario

Use the privacy-safe synthetic lecture fixture:

- Fixture: `fixtures/synthetic_media/source/synthetic_lecture_manifest.json`
- Title: `Synthetic MOOC Lecture: Building a Tiny AI Video Editor`
- Duration: 72 seconds
- Sources: mixed video, screen recording, webcam recording, separate audio, slide deck, and word-level transcript
- Expected signals: filler words, a false start, dead air, chapter markers, and layout changes

Narrative framing:

> Imagine a lecturer has recorded a short MOOC lesson with separate screen, camera, audio, and slides. Instead of manually cutting pauses, checking captions, choosing layouts, and collecting evaluation proof, the system prepares an editable plan. The teacher reviews the plan, adjusts what matters, and exports both the polished video and the evidence needed for thesis evaluation.

## Pre-Demo Setup

Run these from the repository root before the presentation:

```powershell
python scripts/generate_synthetic_test_media.py --metadata-only --force
```

For a full visual demo with generated MP4/WAV outputs, run this when FFmpeg is available:

```powershell
python scripts/generate_synthetic_test_media.py --force
```

Recommended checks before opening the app:

```powershell
.venv\Scripts\python.exe -m unittest backend.tests.test_synthetic_media_fixtures backend.tests.test_evaluation_metrics backend.tests.test_mode_comparison backend.tests.test_export_artifacts
cd desktop
npm run build
```

Demo environment checklist:

- Backend API is running and the desktop app can reach it.
- Synthetic media has been generated or metadata fixtures are available.
- Hybrid mode is selected in AI settings if provider credentials/local models are configured.
- If external providers are unavailable, use the synthetic transcript and existing reports as the deterministic fallback path.
- Browser zoom is set so the workflow stepper, preview, transcript, and right-side controls fit on screen.

## Presentation Opening

Say:

> My original system already had a five-agent pipeline for transcription, content understanding, fluency analysis, visual structure, and edit planning. The overhaul turns that backend into a more complete editor: project assets, provider modes, transcript-based cuts, guided workflow steps, layout planning, polish tools, rendering presets, and evaluation exports. I will show the journey from raw teaching sources to final evidence.

Show briefly:

- Project dashboard and create-project surface.
- AI settings with API, Local, and Hybrid options.
- The guided editor steps across the top or side of the workspace.

Do not spend time on implementation internals yet. Keep the first minute product-focused.

## Live Demo Flow

### 1. Project And Source Import (1 minute)

Action:

- Create or open the synthetic MOOC lecture project.
- Point out multi-source assets: screen, camera, audio, slides, transcript, and mixed fallback video.
- If using the generated files, upload `lecture_video.mp4` first, then mention the separate-source workflow supported by the project asset APIs.

Talk track:

> This is the first shift from the old prototype. The editor is project-first. A lecture is not only one video file; it can include screen capture, camera, separate audio, slides, notes, and transcript references.

Evidence to mention:

- Project and asset APIs preserve the legacy single-video upload route.
- Sync metadata records offsets for camera and audio sources.

### 2. AI Mode And Local Model Readiness (1 minute)

Action:

- Open Settings.
- Show preferred processing mode: API, Local, Hybrid.
- Show local transcription model catalog and provider settings.

Talk track:

> Hybrid mode is the default academic story: deterministic local passes handle privacy-sensitive and low-cost work, while API reasoning can be used for high-accuracy planning when configured. The evaluation report later compares the tradeoffs rather than hiding them.

Examiner point:

- API mode favors quality and setup simplicity.
- Local mode favors privacy and zero external cost after model download.
- Hybrid mode balances both and demonstrates fallback behavior.

### 3. Transcribe And Process (1 to 2 minutes)

Action:

- Start processing or open a pre-processed synthetic fixture.
- Show the processing status labels and completed steps.
- Open transcript timeline when available.

Talk track:

> The transcript is no longer only segment-level text. The editor stores word-level timing so text selections can become real edit decisions. This is important because teachers think in words and sentences, while renderers need exact time ranges.

Fallback if processing takes too long:

- Use the committed synthetic transcript JSON.
- Explain that the 72 second fixture contains known timestamps, filler words, a false start, and dead air so evaluation is reproducible.

### 4. Clean Step Review (2 minutes)

Action:

- Open the Clean step.
- Select conservative and aggressive profiles if both are visible.
- Highlight filler, false start, dead air, repeated phrase, or bad-take suggestions.
- Apply a small set of suggestions or explain the apply path.

Talk track:

> The system does not blindly remove content. It proposes reviewable cleaning suggestions with reasons. The teacher can accept, ignore, or override them. For education videos this matters because a pause may be a mistake, but it may also be useful thinking time.

Specific synthetic signals:

- Filler word: `um`
- False start: `actually let me restart that`
- Dead air: approximately 44.4 to 48.2 seconds
- Cut candidate: `Review Decision` segment

### 5. Sections And Chapter Structure (1 minute)

Action:

- Open Sections or chapter analysis.
- Show chapter labels from transcript and slide-aware structure.

Talk track:

> The system creates lecture structure, not only cuts. For MOOC and LMS content, chapters make the output easier to navigate and easier to evaluate.

Expected chapters:

- Learning Goal
- Import Sources
- Clean Transcript
- Review Decision
- Export Evidence

### 6. Layout Step (2 minutes)

Action:

- Open Layout step.
- Show full screen, picture-in-picture, side-by-side, and full camera options.
- Show camera corner/shape/aspect controls if available.
- Point to layout cues in the plan.

Talk track:

> This is where the overhaul becomes a video editor rather than only a trimmer. Layout cues decide when to show slides, screen, camera, or picture-in-picture. The renderer can use those cues to produce a more polished teaching video.

Synthetic layout sequence:

- 0 to 12 seconds: side-by-side for presenter and goal
- 12 to 42 seconds: full screen for the walkthrough
- 42 to 60 seconds: picture-in-picture while reviewing decisions
- 60 to 72 seconds: full camera for the closing summary

### 7. Polish Step (1 to 2 minutes)

Action:

- Show caption policy, annotations/callouts, educational overlays, title cards, transitions, or end card controls depending on the current processed plan.
- Mention selective captions rather than always-on subtitles.

Talk track:

> Polish tools are stored as structured actions. That means captions, callouts, labels, transitions, and end cards are not just UI decoration; they become part of the edit plan and export metadata.

### 8. Export And Evidence (2 minutes)

Action:

- Open Export step.
- Show preset catalog: YouTube, LMS, social, professional, and audio-only options.
- Select an education or YouTube preset.
- Show available export links after render: edited video, captions, chapters, edit plan JSON, quality report, mode comparison, academic evidence, and evidence bundle.

Talk track:

> The final output is not only an MP4. For an academic project, I also need to prove what happened: what AI suggested, what the teacher changed, what provider mode was used, how much duration was reduced, what captions and chapters were generated, and what artifacts can reproduce the result.

Evidence endpoints to mention:

- `/api/v1/videos/{video_id}/plan/export`
- `/api/v1/videos/{video_id}/report/export`
- `/api/v1/videos/{video_id}/mode-comparison/export`
- `/api/v1/videos/{video_id}/mode-comparison/summary`
- `/api/v1/videos/{video_id}/evidence/export`
- `/api/v1/videos/{video_id}/evidence/summary`
- `/api/v1/videos/{video_id}/evidence/bundle`

## Five Minute Fallback Demo

Use this if live processing, rendering, or provider credentials are unavailable.

1. Show the Project Dashboard and explain project-first multi-source import.
2. Open Settings and show API, Local, and Hybrid mode configuration.
3. Open the synthetic transcript fixture and explain the known evaluation signals.
4. Show the guided workflow in the editor: Clean, Sections, Layout, Polish, Export.
5. Open or describe the generated evidence artifacts: quality report, mode comparison, academic evidence Markdown, and ZIP bundle.

Fallback sentence:

> The live provider path depends on local model files or API credentials, but the evaluation path remains deterministic because the synthetic fixture and report builders are committed and tested.

## Slide Narrative

Use this as the presentation spine around the live demo.

1. Problem: Lecturers record imperfect teaching videos, but manual cleanup is slow and repetitive.
2. Goal: Build an AI-assisted editor that prepares a plan while preserving teacher control.
3. Architecture: Project assets, provider routing, guided editor, edit decisions, renderer, evidence exports.
4. AI workflow: Transcribe, understand, clean, segment, layout, polish, export.
5. Human-in-the-loop: Teacher reviews transcript cuts, segment actions, layout choices, and final presets.
6. Evaluation: Measure accuracy proxy, time, cost, duration reduction, filler/dead-air removal, segment quality, layout correctness, and override rate.
7. Result: A polished lecture export plus reproducible artifacts for supervisor review and thesis writing.
8. Limitation: True ASR accuracy still needs ground-truth transcripts; current metrics include a proxy when ground truth is absent.
9. Future work: Broader real lecture dataset, stronger local model benchmarking, richer visual reasoning, and user study with lecturers.

## Examiner Q And A Anchors

If asked why this is different from a normal video editor:

> The contribution is not manual editing tools alone. It is the structured AI edit plan, provider-mode routing, education-specific workflow, teacher review loop, and reproducible evaluation evidence.

If asked how the system avoids unsafe automatic edits:

> AI actions are suggestions with confidence, reasons, and teacher override fields. Transcript selections and clean suggestions are synchronized into edit decisions before export.

If asked how privacy is handled:

> The architecture supports Local, API, and Hybrid modes. Local mode keeps transcription and reasoning on-device when models are available. Hybrid mode can use local-first transcription and API fallback.

If asked how evaluation is measured:

> Phase 10 records processing time, estimated cost, duration reduction, filler/dead-air removal, segment quality, layout correctness, transcription accuracy proxy, and teacher override rate. It also exports JSON and Markdown evidence.

If asked what is still incomplete:

> Real-world evaluation still needs more lecture samples and ground-truth transcripts. The prototype is production-quality for a final academic demo, but the next research step is broader validation with real lecturers and course material.

## Closing Statement

Say:

> The overhaul changes the project from an automatic trimming pipeline into an AI-assisted lecture editor. It can ingest teaching sources, create an editable plan, guide the teacher through review, render platform-ready outputs, and export the evidence needed to defend the result academically.

