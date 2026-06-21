# AI-Agent Assisted Video Editing Framework

Final Year Project implementation for producing reviewable educational-video edits from lecture recordings and uploaded course material.

The application is a teacher-supervised system. AI-generated transcript evidence, curriculum-grounded content labels, fluency findings, slide/page decisions, and edit recommendations remain reviewable before the approved plan is rendered.

## Implemented workflow

```text
Project and asset upload
        |
        v
Agent 1: transcription
        |
        v
Transcript embedding and course-material retrieval
        |
        v
Agent 2: curriculum-grounded content analysis
        |
        +-------------------------+
        |                         |
        v                         v
Agent 3: fluency analysis   Agent 4: semantic visual planning
        |                         |
        +------------+------------+
                     |
                     v
             Agent 5: edit planning
                     |
                     v
          Teacher review and overrides
                     |
                     v
       Semantic render plan and final export
```

The processing pipeline pauses after edit planning. Rendering is started only after teacher approval.

## Main components

| Layer | Implementation |
|---|---|
| Desktop interface | React 19, TypeScript, Tailwind CSS, Tauri 2 |
| Backend API | FastAPI and Pydantic |
| Persistence | PostgreSQL, SQLAlchemy and Alembic |
| Retrieval | Qdrant with configurable embeddings |
| Orchestration | Asynchronous five-agent pipeline with stage progress |
| Speech recognition | Configurable hosted, local and hybrid routes |
| Language models | Provider-routed structured generation |
| Course materials | PDF, PPTX and DOCX extraction with page/slide metadata |
| Rendering | FFmpeg native compositor and Revideo integration |
| Evidence | JSON, CSV, Markdown, subtitle and chapter artefacts |

## Repository structure

```text
backend/
  app/
    agents/                 Five processing agents and orchestrator
    api/routes/             Project, video, review and settings endpoints
    db/                     SQLAlchemy database configuration and models
    models/                 Pydantic request and response schemas
    providers/              Speech/LLM provider adapters and defaults
    rag/                    Qdrant vector-store integration
    services/               Rendering, planning, export and support services
    alembic/versions/       Database migrations
  tests/                    Canonical automated test suite
  revideo/                  Backend Revideo project support
desktop/
  src/                      React teacher-facing desktop interface
  src-tauri/                Tauri desktop shell and backend bootstrap
  revideo/                  Revideo scene and render entry points
docs/
  reproducibility/          Source-package and thesis reproduction guidance
scripts/                    Verification and source-package utilities
```

## Development setup

### Requirements

- Docker Desktop with Docker Compose
- FFmpeg and FFprobe
- Node.js compatible with the lockfile
- Rust toolchain for Tauri builds
- Provider credentials for the selected hosted AI routes

Copy the configuration template and provide local values:

```powershell
Copy-Item .env.example .env
```

Never commit `.env`; it is intentionally ignored.

### Backend services

```powershell
docker compose up -d --build
```

The API is available at `http://localhost:8000`, with interactive documentation at `/docs`.

### Desktop development

```powershell
Set-Location desktop
npm install
npm run dev
```

For the native desktop application:

```powershell
npx tauri dev
```

## Verification

Run the canonical backend tests from the repository root:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s backend\tests -p "test_*.py"
```

Build the frontend:

```powershell
npm run build --prefix desktop
```

Validate Rust integration:

```powershell
cargo check --manifest-path desktop\src-tauri\Cargo.toml
```

## Reproducible source package

The thesis source package is generated with:

```powershell
.\.venv\Scripts\python.exe scripts\generate_thesis_source_package.py
```

The generator creates a sanitised archive, source manifest, summary and SHA-256 checksum under `output/thesis_source_package/`. Dependencies, credentials, media, caches, generated outputs and local analysis folders are excluded.

See [docs/reproducibility/REPRODUCIBILITY_GUIDE.md](docs/reproducibility/REPRODUCIBILITY_GUIDE.md) for the final-freeze and appendix workflow.

## Security and privacy

Do not include the following in a source release or thesis submission:

- `.env` or API keys
- uploaded recordings or course material without permission
- database dumps containing personal data
- provider logs containing credentials
- generated media unless explicitly required as evaluation evidence

Use `.env.example` to document configuration fields safely.

## Project status

This repository is an academic prototype developed for a Final Year Project. Reported evaluation findings must be tied to a specific Git commit, source-package checksum, provider/model configuration, and evaluation date.
