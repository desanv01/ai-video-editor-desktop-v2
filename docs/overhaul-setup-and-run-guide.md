# AI Video Editor Overhaul Setup And Run Guide

This guide is for running the completed overhaul locally with your own lecture videos, screen recordings, camera recordings, audio, slides, notes, and course materials.

It replaces the older pre-overhaul startup notes. The current app has a project dashboard, multi-source uploads, AI provider settings, guided editor workflow, rendering, and thesis evidence exports.

## 1. What You Need

Install these first:

- Docker Desktop
- Git
- Node.js 20 or newer
- Python 3.12
- FFmpeg, optional but useful for local fixture generation and debugging

You also need API keys for a full real-material run:

- `OPENAI_API_KEY`
- `DEEPSEEK_API_KEY`
- `MISTRAL_API_KEY`

The app can open without keys, but real transcription, embeddings, and LLM planning need configured providers unless you are only testing deterministic/local fixture paths.

## 2. Open The Project

```powershell
cd C:\Users\Dv\Desktop\ai-video-editor
git switch codex/system-overhaul
git status --short --branch
```

Expected branch:

```text
codex/system-overhaul
```

Do not run from `main` unless you intentionally merge the overhaul there later.

## 3. Configure Environment

If `.env` does not exist:

```powershell
Copy-Item .env.example .env
```

Edit `.env` and set:

```env
OPENAI_API_KEY=your_openai_key
DEEPSEEK_API_KEY=your_deepseek_key
MISTRAL_API_KEY=your_mistral_key

AI_PROCESSING_MODE=hybrid
AI_PROVIDER_FALLBACK_ENABLED=true

CORS_ORIGINS=["http://localhost:3000","http://localhost:5173","http://localhost:1420","http://127.0.0.1:1420","tauri://localhost"]
```

Keep `.env` private. Do not commit it.

## 4. Start Docker Backend Stack

Start Docker Desktop first, then run:

```powershell
docker compose up -d --build
```

Check containers:

```powershell
docker ps
```

Expected running containers:

- `aive-backend`
- `aive-db`
- `aive-qdrant`
- `aive-redis`
- `aive-n8n`

Check backend health:

```powershell
Invoke-RestMethod http://localhost:8000/health
```

Expected:

```json
{"status":"healthy"}
```

API docs:

```text
http://localhost:8000/docs
```

## 5. Important: Old Database Volumes

If you ran the old pre-overhaul project before, your local Docker Postgres volume may contain old tables without new columns such as `videos.project_id`.

Symptoms:

- project creation or upload gives `500 Internal Server Error`
- backend logs mention missing columns, for example `column videos.project_id does not exist`
- Alembic says tables already exist because the DB was created before migration tracking

For a clean local test database, stop and remove Docker volumes:

```powershell
docker compose down -v
docker compose up -d --build
```

Warning: `docker compose down -v` deletes local database, Qdrant, Redis, and n8n volumes for this Compose project. Export or back up anything you need first.

If you must preserve old data, do not reset volumes blindly. Back up Postgres first, then migrate/repair the schema carefully.

## 6. Start The Desktop Frontend In Browser Mode

Install frontend dependencies if needed:

```powershell
cd C:\Users\Dv\Desktop\ai-video-editor\desktop
npm install
```

Start Vite:

```powershell
npm run dev -- --host 127.0.0.1
```

Open the URL printed by Vite. It is usually:

```text
http://127.0.0.1:1420/
```

You can also use:

```text
http://localhost:1420/
```

Use browser mode for normal testing. Tauri packaging can come later after the web workflow is stable.

## 7. Verify The App Is Connected

In the app:

1. Open the Project Dashboard.
2. Confirm no red `Failed to fetch` error appears.
3. Open Settings.
4. Confirm AI Mode, Providers, Local Models, Export, Appearance, and Tours tabs load.
5. Confirm preferred mode is `Hybrid` unless you intentionally changed it.

If the UI says `Failed to fetch`:

- check `docker ps`
- check `http://localhost:8000/health`
- confirm `CORS_ORIGINS` includes the Vite URL
- restart backend after changing `.env`:

```powershell
docker compose restart backend
```

## 8. Run The Full Workflow With Your Own Materials

### Step 1: Create A Project

On the Project Dashboard:

1. Enter a project title.
2. Add optional notes.
3. Pick project type: Lecture, MOOC, Tutorial, or Workshop.
4. Choose `Single video` if you only have one mixed recording.
5. Choose `Multi-source` if you have separate screen/camera/audio/slides/notes.
6. Click `Create and Open`.

### Step 2: Upload Sources

For single-video testing:

- upload the main lecture MP4

For multi-source testing:

- upload screen recording
- upload camera or webcam recording
- upload separate microphone/audio file
- upload slides or PDFs if available
- upload notes/materials if available

Recommended formats:

- Video: `.mp4`, `.mov`, `.webm`, `.mkv`
- Audio: `.wav`, `.mp3`, `.m4a`
- Slides/notes/materials: `.pptx`, `.pdf`, `.docx`, `.txt`, `.md`

Keep first real tests short, ideally 1 to 5 minutes, so transcription, LLM calls, and rendering are quick.

### Step 3: Start Processing

After upload, start processing from the app. The backend will run:

1. transcription
2. transcript embedding/RAG
3. content analysis
4. fluency/filler/dead-air analysis
5. visual analysis
6. edit planning
7. teacher review preparation

Watch the progress/status area. The video should eventually reach `Ready to review` or `Awaiting review`.

### Step 4: Review The Guided Editor

Use the workflow tabs:

- `Transcribe`: inspect transcript timing and words
- `Clean`: review filler, dead-air, and bad-take suggestions
- `Sections`: inspect generated topic/section structure
- `Layout`: check screen/camera composition cues
- `Polish`: configure captions, callouts, labels, title cards, transitions, and end cards
- `Export`: choose output preset and render/download files

You can use the transcript/timeline tools to keep, cut, shorten, highlight, or add polish actions.

### Step 5: Export

In the Export step:

1. Choose a preset, such as `YouTube 1080p`, `LMS Compatible`, or `Podcast Audio-only`.
2. Approve and render.
3. Wait for render progress to reach complete.
4. Download outputs.

Expected export links include:

- Edited Video or Audio
- Subtitles SRT
- Subtitles VTT
- Chapter Markers
- Edit Plan JSON
- Quality Report JSON
- Academic Evidence JSON
- Evidence Summary Markdown
- Before/After Comparison JSON
- Timeline Decisions CSV
- Provider Mode Trace JSON
- Metrics Summary JSON
- Evidence Bundle ZIP

## 9. Test With Synthetic Fixtures First

Before using private/important recordings, generate safe test media:

```powershell
cd C:\Users\Dv\Desktop\ai-video-editor
python scripts\generate_synthetic_test_media.py --force
```

Generated files appear under:

```text
fixtures\synthetic_media\generated
```

Useful files:

- `media\lecture_video.mp4`
- `media\screen_recording.mp4`
- `media\webcam_recording.mp4`
- `media\separate_audio.wav`
- `transcripts\synthetic_lecture_transcript.json`
- `transcripts\synthetic_lecture.srt`
- `transcripts\synthetic_lecture.vtt`
- `slides\synthetic_lecture_slides.pptx`

This is the safest first full workflow test because it contains no private recordings.

## 10. Run Checks

Backend tests:

```powershell
cd C:\Users\Dv\Desktop\ai-video-editor
.\.venv\Scripts\python.exe -m unittest discover -s backend\tests -p "test_*.py"
```

Frontend build:

```powershell
cd C:\Users\Dv\Desktop\ai-video-editor\desktop
npm run build
```

Synthetic fixture generation:

```powershell
cd C:\Users\Dv\Desktop\ai-video-editor
python scripts\generate_synthetic_test_media.py --metadata-only --force
python scripts\generate_synthetic_test_media.py --force
```

## 11. Useful Backend Commands

View backend logs:

```powershell
docker logs aive-backend --tail 120
```

Restart backend after `.env` changes:

```powershell
docker compose restart backend
```

Restart everything:

```powershell
docker compose restart
```

Stop everything while keeping data:

```powershell
docker compose down
```

Stop everything and delete local volumes:

```powershell
docker compose down -v
```

Only use `down -v` when you are comfortable deleting local test DB/vector data.

## 12. Common Problems

### `TypeError: Failed to fetch` in the app

Check:

```powershell
docker ps
Invoke-RestMethod http://localhost:8000/health
```

Also confirm the frontend URL is included in `.env` `CORS_ORIGINS`, then restart backend.

### `500 Internal Server Error` during project/video upload

Check logs:

```powershell
docker logs aive-backend --tail 120
```

If logs mention missing columns on an old database, reset local volumes or migrate/repair the database.

### Processing fails during transcription or planning

Check:

- API keys exist in `.env`
- backend was restarted after `.env` edits
- uploaded video/audio is readable by FFmpeg
- video is short enough for provider limits

### Local model mode is not ready

Hybrid/API mode is the easiest for full real-material testing. Local transcription needs a configured Whisper.cpp binary and model path in Settings.

Use Settings -> Local Models to check local transcription model state.

## 13. Recommended First Real Test

Use a short lecture clip:

- 2 to 5 minutes
- clear audio
- one screen recording or one mixed MP4
- optional slides/PDF

Run this first with `Hybrid` mode. After one successful render, test a longer clip and then test separate screen/camera/audio sources.

## 14. What To Capture For Thesis Evidence

After a successful export, save:

- rendered MP4 or M4A
- edit plan JSON
- quality report JSON
- evidence summary Markdown
- before/after comparison JSON
- timeline decisions CSV
- provider mode trace JSON
- metrics summary JSON
- evidence bundle ZIP

These files are designed for report screenshots, appendix tables, methodology explanation, and supervisor/examiner demo evidence.
