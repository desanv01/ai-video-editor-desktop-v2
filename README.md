# 🎬 AI-Agent Assisted Video Editing Framework

> Automated Generation of Educational Content using Multi-Agent AI

A multi-agent system that automatically processes raw lecture recordings into polished educational videos. Uses 5 specialized AI agents orchestrated by LangGraph with a teacher-in-the-loop review interface.

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     LangGraph Orchestrator                    │
│                                                              │
│  ┌─────────┐   ┌──────────────┐   ┌────────────────────┐   │
│  │ Agent 1  │   │   Agent 2     │   │    Agent 5         │   │
│  │ Whisper  │──▶│ Content + RAG │──▶│  Edit Planner      │   │
│  │ ASR      │   │ (DeepSeek)   │   │  (DeepSeek)        │   │
│  └─────────┘   └──────────────┘   └─────────┬──────────┘   │
│                 ┌──────────────┐              │              │
│                 │   Agent 3     │──────────────┤              │
│                 │ Fluency/Filler│              │              │
│                 │ (DeepSeek)   │              ▼              │
│                 └──────────────┘   ┌────────────────────┐   │
│                 ┌──────────────┐   │ Teacher Review UI   │   │
│                 │   Agent 4     │──▶│ (React + Tailwind) │   │
│                 │ PySceneDetect│   └─────────┬──────────┘   │
│                 └──────────────┘              │              │
│                                               ▼              │
│                                    ┌────────────────────┐   │
│                                    │  FFmpeg Renderer    │   │
│                                    │  MP4 + SRT Output   │   │
│                                    └────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

## Tech Stack

| Component        | Technology                              |
|------------------|-----------------------------------------|
| Backend          | FastAPI (Python 3.12)                   |
| Orchestration    | LangGraph                               |
| ASR              | OpenAI Whisper API                      |
| LLM              | DeepSeek V3 (reasoning + JSON output)   |
| Embeddings       | OpenAI text-embedding-3-small           |
| Vector DB        | Qdrant                                  |
| Database         | PostgreSQL 16                           |
| Task Queue       | Redis + Celery                          |
| Video Processing | FFmpeg                                  |
| Scene Detection  | PySceneDetect                           |
| Frontend         | React + Tailwind CSS (planned)          |
| Deployment       | Docker Compose                          |

## Quick Start

### Prerequisites
- Docker & Docker Compose
- OpenAI API key
- DeepSeek API key

### 1. Clone & Configure

```bash
git clone <your-repo-url>
cd ai-video-editor
cp .env.example .env
# Edit .env with your API keys
```

### 2. Start Services

```bash
docker-compose up -d
```

### 3. Access

- **API Docs:** http://localhost:8000/docs
- **Qdrant Dashboard:** http://localhost:6333/dashboard

### 4. Upload a Video

```bash
curl -X POST http://localhost:8000/api/v1/videos/upload \
  -F "file=@lecture.mp4"
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/v1/videos/upload` | Upload video & start processing |
| GET | `/api/v1/videos` | List all videos |
| GET | `/api/v1/videos/{id}` | Get video details |
| GET | `/api/v1/videos/{id}/status` | Get processing status |
| GET | `/api/v1/videos/{id}/segments` | Get analyzed segments |
| PUT | `/api/v1/videos/{id}/segments/{sid}` | Teacher overrides segment |
| PUT | `/api/v1/videos/{id}/segments/bulk` | Bulk update segments |
| GET | `/api/v1/videos/{id}/plan` | Get edit plan |
| POST | `/api/v1/videos/{id}/plan/approve` | Approve & trigger render |
| GET | `/api/v1/videos/{id}/report` | Quality metrics report |
| POST | `/api/v1/materials/upload` | Upload course materials for RAG |

## Project Structure

```
ai-video-editor/
├── docker-compose.yml
├── .env.example
├── .gitignore
├── README.md
└── backend/
    ├── Dockerfile
    ├── requirements.txt
    └── app/
        ├── main.py                    # FastAPI entry point
        ├── config.py                  # Settings (env vars)
        ├── api/routes/
        │   └── videos.py             # All API endpoints
        ├── agents/
        │   ├── orchestrator.py        # LangGraph pipeline
        │   ├── transcription.py       # Agent 1: Whisper ASR
        │   ├── content_understanding.py # Agent 2: LLM + RAG
        │   ├── fluency.py            # Agent 3: Filler detection
        │   ├── visual_structure.py    # Agent 4: PySceneDetect
        │   └── edit_planner.py        # Agent 5: Decision maker
        ├── services/
        │   ├── ffmpeg.py              # FFmpeg operations
        │   ├── whisper.py             # Whisper API client
        │   ├── llm.py                 # DeepSeek/OpenAI client
        │   └── renderer.py           # Final video assembly
        ├── rag/
        │   └── vector_store.py        # Qdrant operations
        ├── db/
        │   ├── database.py            # SQLAlchemy setup
        │   └── models.py             # ORM models
        └── models/
            └── schemas.py             # Pydantic schemas
```

## Pipeline Flow

1. **Upload** → Video saved, metadata extracted via ffprobe
2. **Transcribe** → Audio extracted (ffmpeg) → Whisper API → time-aligned transcript
3. **Embed** → Transcript chunks embedded into Qdrant for RAG
4. **Analyze** (parallel):
   - Agent 2: Content importance scoring with RAG context
   - Agent 3: Filler word + silence detection
   - Agent 4: Scene/slide boundary detection
5. **Plan** → Agent 5 fuses all signals → KEEP/CUT/SHORTEN/HIGHLIGHT per segment
6. **Review** → Teacher reviews in UI, accepts/overrides suggestions
7. **Render** → ffmpeg trims + concatenates + burns subtitles → final MP4

## License

This project is developed as a Final Year Project (FYP).
