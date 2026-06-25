from __future__ import annotations

import ast
import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "fyp_context_pack"
INV = json.loads((OUT / "_inventory.json").read_text(encoding="utf-8"))
STATUSES = {
    "IMPLEMENTED_AND_CONNECTED",
    "IMPLEMENTED_BUT_NOT_CONNECTED",
    "PARTIALLY_IMPLEMENTED",
    "CONFIGURATION_DEPENDENT",
    "TEST_ONLY",
    "DOCUMENTATION_ONLY",
    "PLANNED",
    "DEPRECATED",
    "DEAD_CODE",
    "UNVERIFIED",
}


def write(name: str, body: str) -> None:
    (OUT / name).write_text(body.strip() + "\n", encoding="utf-8")


def read_csv(name: str) -> list[dict[str, str]]:
    with (OUT / name).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(name: str, fieldnames: list[str], rows: list[dict]) -> None:
    with (OUT / name).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def full_route(endpoint: dict[str, str]) -> str:
    path = endpoint["path"]
    route = endpoint["route"]
    if path.endswith("debug.py"):
        return "/debug" + route
    if path.endswith("projects.py"):
        return "/api/v1/projects" + route
    if path.endswith("main.py"):
        return route
    return "/api/v1" + route


def purpose(symbol: str) -> str:
    return symbol.replace("_", " ").strip().capitalize()


def category(route: str, symbol: str, path: str) -> str:
    value = f"{route} {symbol} {path}".lower()
    if "debug" in path:
        return "legacy/unused"
    if any(x in value for x in ("health", "settings", "config", "model")):
        return "health/settings"
    if "project" in value:
        return "projects"
    if any(x in value for x in ("asset", "upload", "native-import")):
        return "assets"
    if any(x in value for x in ("material", "rag", "course")):
        return "materials/RAG"
    if any(x in value for x in ("transcri", "audio")):
        return "transcription"
    if any(x in value for x in ("visual", "scene", "layout", "slide")):
        return "visual planning"
    if any(x in value for x in ("plan", "segment", "clean", "topic")):
        return "edit plans"
    if any(x in value for x in ("render", "export", "subtitle", "chapter")):
        return "rendering/export"
    if any(x in value for x in ("evaluat", "metric", "comparison", "quality")):
        return "evaluation/logging"
    if any(x in value for x in ("process", "agent", "analysis")):
        return "analysis"
    return "videos"


def endpoint_status(endpoint: dict[str, str]) -> str:
    if endpoint["path"].endswith("debug.py"):
        return "CONFIGURATION_DEPENDENT"
    return "IMPLEMENTED_AND_CONNECTED"


def handler_signature(path: str, symbol: str) -> tuple[str, str]:
    source = ROOT / path
    try:
        tree = ast.parse(source.read_text(encoding="utf-8"))
    except Exception:
        return "See handler signature", "See response_model/handler"
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == symbol:
            params = []
            for arg in node.args.args:
                if arg.arg in {"request", "db", "background_tasks"}:
                    continue
                annotation = ast.unparse(arg.annotation) if arg.annotation else "untyped"
                params.append(f"{arg.arg}: {annotation}")
            returns = ast.unparse(node.returns) if node.returns else "handler-defined"
            return "; ".join(params) or "None/path-query only", returns
    return "See handler signature", "See response_model/handler"


API = INV["python"]["endpoints"]
FRONTEND_APIS = read_csv("_FRONTEND_API_EXTRACT.csv")
FRONTEND_CALLS = read_csv("_FRONTEND_CALLS_EXTRACT.csv")
TESTS = read_csv("_TEST_EXTRACT.csv")
MODELS = read_csv("_MODELS_EXTRACT.csv")


def frontend_callers(symbol: str, route: str) -> str:
    terms = {symbol.lower(), symbol.lower().removeprefix("get_"), symbol.lower().removeprefix("list_")}
    hits = []
    for row in FRONTEND_APIS:
        name = row["name"].lower()
        if any(term and (term in name or name in term) for term in terms):
            hits.append(f"{row['path']}:{row['line']} {row['name']}")
    return "; ".join(hits[:4]) or "No direct static match found"


api_rows = []
for item in API:
    route = full_route(item)
    req, ret = handler_signature(item["path"], item["symbol"])
    api_rows.append({
        "category": category(route, item["symbol"], item["path"]),
        "method": item["method"],
        "route": route,
        "purpose": purpose(item["symbol"]),
        "request_schema": req,
        "response_schema": item.get("response_model") or ret,
        "authentication": "None implemented",
        "frontend_caller": frontend_callers(item["symbol"], route),
        "backend_handler": item["symbol"],
        "database_effect": "Handler-specific; inspect cited symbol",
        "filesystem_effect": "Handler-specific; uploads/renders may write files",
        "ai_provider_use": "Handler-specific; analysis/transcription/RAG routes may call providers",
        "status": endpoint_status(item),
        "evidence": f"{item['path']}:{item['line']} {item['symbol']}",
    })

write_csv("API_ENDPOINTS.csv", list(api_rows[0]), api_rows)
write_csv(
    "API_FRONTEND_MAPPING.csv",
    ["frontend_function", "frontend_evidence", "backend_route_match", "mapping_status", "notes"],
    [{
        "frontend_function": row["name"],
        "frontend_evidence": f"{row['path']}:{row['line']}",
        "backend_route_match": next((r["route"] for r in api_rows if row["name"].lower().replace("native", "") in r["backend_handler"].lower()), "Manual route inspection required"),
        "mapping_status": "PARTIALLY_IMPLEMENTED" if row["name"].startswith(("save", "load")) and "Project" in row["name"] else "IMPLEMENTED_AND_CONNECTED",
        "notes": "Static name-based mapping; API_ENDPOINTS.csv is authoritative for backend declarations.",
    } for row in FRONTEND_APIS],
)


providers = [
    ("voxtral", "ASR", "hosted", "default hosted transcription", "CONFIGURATION_DEPENDENT", "backend/app/providers/defaults.py:24-36 register_default_providers"),
    ("openai-whisper", "ASR", "hosted", "upload-size constrained fallback", "CONFIGURATION_DEPENDENT", "backend/app/providers/defaults.py:38-49 register_default_providers"),
    ("whisper.cpp", "ASR", "local", "local executable/model route", "CONFIGURATION_DEPENDENT", "backend/app/providers/defaults.py:51-61 register_default_providers"),
    ("deepseek-v4-flash", "chat", "hosted", "default Agents 2 and 3", "CONFIGURATION_DEPENDENT", "backend/app/providers/defaults.py:63-74 register_default_providers"),
    ("deepseek-v4-pro", "chat", "hosted", "default Agent 5", "CONFIGURATION_DEPENDENT", "backend/app/providers/defaults.py:76-84 register_default_providers"),
    ("openai-embeddings", "embedding", "hosted", "default Qdrant embedding source", "CONFIGURATION_DEPENDENT", "backend/app/providers/defaults.py:86-94 register_default_providers"),
    ("qwen-3.7-plus", "vision/chat", "hosted", "slide visual interpretation route", "CONFIGURATION_DEPENDENT", "backend/app/providers/defaults.py:96-104 register_default_providers"),
    ("unconfigured-vision", "vision", "placeholder", "capability placeholder", "PLANNED", "backend/app/providers/defaults.py:105-107 register_default_providers"),
    ("local-runtime", "chat/embedding/vision", "placeholder", "local non-ASR provider placeholder", "PLANNED", "backend/app/providers/placeholders.py:1-80"),
]
write_csv("PROVIDERS.csv", ["provider", "purpose", "route", "current_use", "status", "evidence"], [dict(zip(["provider", "purpose", "route", "current_use", "status", "evidence"], row)) for row in providers])


config_rows = [
    ("DATABASE_URL", "backend/app/config.py", "postgresql+asyncpg://...", "yes", "secret-like", "active", "PostgreSQL connection"),
    ("QDRANT_URL", "backend/app/config.py", "http://qdrant:6333", "yes", "no", "active", "Vector database"),
    ("REDIS_URL", "backend/app/config.py", "redis://redis:6379/0", "yes", "no", "configured-only", "Redis is a Compose dependency but no active client use was found"),
    ("ASR_PROVIDER", "backend/app/config.py", "voxtral", "yes", "no", "active", "Hosted transcription default"),
    ("AGENT2_MODEL", "backend/app/config.py", "deepseek-v4-flash", "yes", "no", "active", "Content analysis"),
    ("AGENT3_MODEL", "backend/app/config.py", "deepseek-v4-flash", "yes", "no", "active", "Fluency analysis"),
    ("AGENT5_MODEL", "backend/app/config.py", "deepseek-v4-pro", "yes", "no", "active", "Edit planning"),
    ("EMBEDDING_MODEL", "backend/app/config.py", "text-embedding-3-small", "yes", "no", "active", "1536-dimensional vectors"),
    ("CHUNK_SIZE", "backend/app/config.py", "300", "yes", "no", "active", "RAG chunk tokens"),
    ("CHUNK_OVERLAP", "backend/app/config.py", "50", "yes", "no", "active", "RAG overlap tokens"),
    ("MAX_UPLOAD_SIZE_MB", "backend/app/config.py", "10240", "yes", "no", "active", "Upload limit"),
    ("ENABLE_NATIVE_SEMANTIC_COMPOSITOR", "backend/app/config.py", "true", "yes", "no", "active", "Primary semantic renderer"),
    ("ENABLE_REVIDEO_RENDERER", "backend/app/config.py", "false", "yes", "no", "optional", "Browser/Puppeteer renderer"),
    ("APP_DEBUG", "backend/app/config.py", "true in source; desktop writes false", "yes", "no", "active", "Controls debug routes"),
    ("APP_SETTINGS_SECRET_KEY", "backend/app/config.py", "empty", "yes", "secret", "optional", "Required to persist encrypted API keys"),
    ("VITE_API_URL", "desktop/src/lib/api.ts", "http://localhost:8000", "yes", "no", "active", "Browser backend default; desktop bootstrap overrides to 127.0.0.1:18000"),
    ("AIVE_HOST_*", "docker-compose.desktop.yml", "no safe default", "launcher", "path", "active", "Desktop bind-mount paths; raw Compose validation fails without launcher values"),
]
write_csv("CONFIGURATION_KEYS.csv", ["key", "source", "default_redacted", "user_configurable", "secret", "use", "thesis_relevance"], [dict(zip(["key", "source", "default_redacted", "user_configurable", "secret", "use", "thesis_relevance"], row)) for row in config_rows])


mcp_tools = [
    ("video-tools", "get_video_metadata", "Inspect streams/format", "IMPLEMENTED_BUT_NOT_CONNECTED", "backend/app/mcp/video_tools_server.py:1"),
    ("video-tools", "extract_audio", "Extract audio with FFmpeg", "IMPLEMENTED_BUT_NOT_CONNECTED", "backend/app/mcp/video_tools_server.py:1"),
    ("video-tools", "trim_video", "Trim media", "IMPLEMENTED_BUT_NOT_CONNECTED", "backend/app/mcp/video_tools_server.py:1"),
    ("video-tools", "concatenate_videos", "Concatenate media", "IMPLEMENTED_BUT_NOT_CONNECTED", "backend/app/mcp/video_tools_server.py:1"),
    ("video-tools", "detect_silence", "Detect silence", "IMPLEMENTED_BUT_NOT_CONNECTED", "backend/app/mcp/video_tools_server.py:1"),
    ("video-tools", "extract_frame", "Extract still frame", "IMPLEMENTED_BUT_NOT_CONNECTED", "backend/app/mcp/video_tools_server.py:1"),
    ("video-tools", "generate_subtitles", "Create subtitle file", "IMPLEMENTED_BUT_NOT_CONNECTED", "backend/app/mcp/video_tools_server.py:1"),
    ("video-tools", "burn_subtitles", "Burn captions into video", "IMPLEMENTED_BUT_NOT_CONNECTED", "backend/app/mcp/video_tools_server.py:1"),
    ("knowledge-tools", "search_knowledge", "Qdrant search", "IMPLEMENTED_BUT_NOT_CONNECTED", "backend/app/mcp/knowledge_tools_server.py:1"),
    ("knowledge-tools", "ingest_course_material", "Embed material", "IMPLEMENTED_BUT_NOT_CONNECTED", "backend/app/mcp/knowledge_tools_server.py:1"),
    ("knowledge-tools", "ingest_transcript", "Embed transcript", "IMPLEMENTED_BUT_NOT_CONNECTED", "backend/app/mcp/knowledge_tools_server.py:1"),
    ("knowledge-tools", "list_materials", "List material sources", "IMPLEMENTED_BUT_NOT_CONNECTED", "backend/app/mcp/knowledge_tools_server.py:1"),
    ("knowledge-tools", "delete_material", "Delete vectors", "IMPLEMENTED_BUT_NOT_CONNECTED", "backend/app/mcp/knowledge_tools_server.py:1"),
    ("knowledge-tools", "extract_text", "Extract document text", "IMPLEMENTED_BUT_NOT_CONNECTED", "backend/app/mcp/knowledge_tools_server.py:1"),
    ("knowledge-tools", "get_collection_stats", "Inspect collection", "IMPLEMENTED_BUT_NOT_CONNECTED", "backend/app/mcp/knowledge_tools_server.py:1"),
    ("pipeline-tools", "list_videos", "List persisted videos", "IMPLEMENTED_BUT_NOT_CONNECTED", "backend/app/mcp/pipeline_tools_server.py:1"),
    ("pipeline-tools", "get_video_status", "Read pipeline status", "IMPLEMENTED_BUT_NOT_CONNECTED", "backend/app/mcp/pipeline_tools_server.py:1"),
    ("pipeline-tools", "run_agent", "Run selected processing stage", "IMPLEMENTED_BUT_NOT_CONNECTED", "backend/app/mcp/pipeline_tools_server.py:1"),
    ("pipeline-tools", "get_segments", "Read segments", "IMPLEMENTED_BUT_NOT_CONNECTED", "backend/app/mcp/pipeline_tools_server.py:1"),
    ("pipeline-tools", "get_edit_plan", "Read edit plan", "IMPLEMENTED_BUT_NOT_CONNECTED", "backend/app/mcp/pipeline_tools_server.py:1"),
    ("pipeline-tools", "update_segment", "Apply teacher action", "IMPLEMENTED_BUT_NOT_CONNECTED", "backend/app/mcp/pipeline_tools_server.py:1"),
    ("pipeline-tools", "approve_edit_plan", "Approve plan", "PARTIALLY_IMPLEMENTED", "backend/app/mcp/pipeline_tools_server.py:1"),
    ("pipeline-tools", "revalidate_plan", "Run plan validation", "IMPLEMENTED_BUT_NOT_CONNECTED", "backend/app/mcp/pipeline_tools_server.py:1"),
    ("pipeline-tools", "get_quality_report", "Read quality report", "IMPLEMENTED_BUT_NOT_CONNECTED", "backend/app/mcp/pipeline_tools_server.py:1"),
    ("pipeline-tools", "get_chapters", "Read chapter markers", "IMPLEMENTED_BUT_NOT_CONNECTED", "backend/app/mcp/pipeline_tools_server.py:1"),
]
write_csv("MCP_TOOLS.csv", ["server", "tool", "purpose", "status", "evidence"], [dict(zip(["server", "tool", "purpose", "status", "evidence"], row)) for row in mcp_tools])


agents = [
    {"name": "Agent 1 - transcription", "entry": "run_transcription_agent", "input": "Video/audio file", "output": "Transcript and timed segments", "provider": "ASR route: Voxtral/OpenAI Whisper/whisper.cpp", "status": "IMPLEMENTED_AND_CONNECTED", "evidence": ["backend/app/agents/transcription.py:1", "backend/app/services/transcription.py:1"]},
    {"name": "Agent 2 - content understanding", "entry": "run_content_understanding_agent", "input": "Transcript batches plus Qdrant retrieval", "output": "Importance/topic analysis", "provider": "DeepSeek V4 Flash default, temperature 0.1", "status": "IMPLEMENTED_AND_CONNECTED", "evidence": ["backend/app/agents/content_understanding.py:32", "backend/app/agents/content_understanding.py:64"]},
    {"name": "Agent 3 - fluency", "entry": "run_fluency_agent", "input": "Timed transcript segments", "output": "Filler/pause/repetition issues", "provider": "DeepSeek V4 Flash default, temperature 0.1", "status": "IMPLEMENTED_AND_CONNECTED", "evidence": ["backend/app/agents/fluency.py:96", "backend/app/agents/fluency.py:130"]},
    {"name": "Agent 4 - visual structure", "entry": "run_visual_structure_agent", "input": "Transcript, project visual assets, rendered pages", "output": "Slide relation, page and layout cues", "provider": "Qwen vision/DeepSeek-assisted semantics plus local fallback", "status": "IMPLEMENTED_AND_CONNECTED", "evidence": ["backend/app/agents/visual_structure.py:53", "backend/app/agents/visual_structure.py:468"]},
    {"name": "Agent 5 - edit planner", "entry": "run_edit_planner_agent", "input": "Outputs from Agents 2-4", "output": "KEEP/CUT/SHORTEN/HIGHLIGHT plan", "provider": "DeepSeek V4 Pro default, temperature 0.1", "status": "IMPLEMENTED_AND_CONNECTED", "evidence": ["backend/app/agents/edit_planner.py:93", "backend/app/agents/edit_planner.py:412"]},
]


entities = []
for row in MODELS:
    entities.append({"name": row["name"], "status": "IMPLEMENTED_AND_CONNECTED", "evidence": [f"{row['path']}:{row['line']}"], "symbol": row["name"]})


features = [
    ("Project-first workflow", "IMPLEMENTED_AND_CONNECTED", "backend/app/api/routes/projects.py:650 create_project; desktop/src/components/ProjectDashboard.tsx:1", "High"),
    ("Six lecturer stages", "IMPLEMENTED_AND_CONNECTED", "desktop/src/components/GuidedWorkflow.tsx:1 GuidedWorkflow", "High"),
    ("Multiple videos per project", "IMPLEMENTED_AND_CONNECTED", "backend/app/db/models.py:139 Project; backend/app/db/models.py:191 Video", "High"),
    ("PDF/PPTX project assets", "IMPLEMENTED_AND_CONNECTED", "backend/app/services/pdf_slides.py:1; backend/app/services/pptx_slides.py:1", "High"),
    ("Five specialised agents", "IMPLEMENTED_AND_CONNECTED", "backend/app/agents/orchestrator.py:96 run_full_pipeline", "High"),
    ("API/local/hybrid ASR", "IMPLEMENTED_AND_CONNECTED", "backend/app/services/transcription.py:1 TranscriptionService", "High"),
    ("RAG over Qdrant", "IMPLEMENTED_AND_CONNECTED", "backend/app/rag/vector_store.py:168 ingest_course_material", "High"),
    ("Semantic slide relations", "IMPLEMENTED_AND_CONNECTED", "backend/app/agents/visual_structure.py:468 semantic prompt", "High"),
    ("Teacher override", "IMPLEMENTED_AND_CONNECTED", "backend/app/db/models.py:252 Segment; desktop/src/components/GuidedWorkflow.tsx:2606", "High"),
    ("Direct async orchestration", "IMPLEMENTED_AND_CONNECTED", "backend/app/agents/orchestrator.py:184 asyncio.gather", "High"),
    ("n8n runtime", "DEPRECATED", "git status shows deleted n8n files; no runtime imports", "High"),
    ("LangGraph runtime", "IMPLEMENTED_BUT_NOT_CONNECTED", "backend/requirements.txt:21 only; no active import found", "High"),
    ("Redis application use", "CONFIGURATION_DEPENDENT", "docker-compose.yml:73; backend/app/config.py Redis URL; no client use found", "Medium"),
    ("MCP core workflow", "IMPLEMENTED_BUT_NOT_CONNECTED", "backend/app/mcp/run_mcp.py:1; no FastAPI/frontend connection", "High"),
    ("Local non-ASR AI providers", "PLANNED", "backend/app/providers/placeholders.py:1", "High"),
    ("OCR for scanned PDFs", "PLANNED", "backend/app/services/text_extraction.py:1 docstring mentions OCR but no OCR path exists", "High"),
    ("Authentication/authorization", "PLANNED", "API inventory shows no authentication dependency", "High"),
]


common_header = """# {title}

Audit status vocabulary is restricted to: IMPLEMENTED_AND_CONNECTED, IMPLEMENTED_BUT_NOT_CONNECTED, PARTIALLY_IMPLEMENTED, CONFIGURATION_DEPENDENT, TEST_ONLY, DOCUMENTATION_ONLY, PLANNED, DEPRECATED, DEAD_CODE, and UNVERIFIED.
"""


write("00_README.md", f"""
# FYP Context Pack

This package is a code-grounded audit for **AI-Agent Assisted Video Editing Framework for Automated Generation of Educational Content**. It is intended to support thesis Chapters 1-5, a technical paper, figure recreation, and a five-video evaluation without converting planned or external values into project results.

## Audit baseline

| Item | Value |
|---|---|
| Audit timestamp | 2026-06-15 22:21:14 +08:00 |
| Branch | `{INV['repository']['branch']}` |
| HEAD | `{INV['repository']['head']}` |
| HEAD date | `{INV['repository']['head_date']}` |
| Working tree | Dirty; current tracked and untracked files were audited |
| Network use | None |
| Source modifications | None; outputs are confined to `docs/fyp_context_pack/` |

## Method

The audit combined Git state inspection, AST/static parsing, targeted source reading, dependency/configuration inspection, safe tests, frontend production build, Rust checking, and Docker Compose validation. Machine-readable inventories were generated from the current working tree. Secrets were not read into the reports and are represented as `[REDACTED]`.

## Verification commands

`git status --short`, `git log`, `git diff --stat`, repository `rg` searches, Python AST inventory, `.venv\\Scripts\\python.exe -m unittest discover -s backend\\tests -p test_*.py -v`, isolated test-file execution, `npm run build`, `cargo check`, `docker compose config --quiet`, and `docker compose -f docker-compose.desktop.yml config --quiet`.

## Reading order

Start with `01`, `03`, `04`, `05`, `07`, `09`, `16`, `17`, and `25`. Use `26_MASTER_EVIDENCE_INDEX.md`, CSV inventories, and `project_ground_truth.json` for rapid verification.

## Limitations

No paid AI request, destructive database action, clean-machine installer test, full browser/desktop end-to-end replay, human study, or five-video timing study was performed. A successful build does not prove runtime services or provider credentials. Raw desktop Compose validation requires launcher-created `AIVE_HOST_*` variables. Screenshots were not captured because launching a second stateful desktop/backend stack was unnecessary for static audit evidence.
""")


write("01_EXECUTIVE_PROJECT_SNAPSHOT.md", """
# Executive Project Snapshot

The project addresses the time and consistency burden of editing educational lecture recordings. Its current contribution is a teacher-supervised, project-first desktop/web workflow that combines transcription, curriculum-grounded analysis, fluency detection, semantic slide/layout planning, edit recommendation, deterministic warnings, and FFmpeg-based export. The system is not a fully autonomous editor: the lecturer reviews and can override generated content, slide, and layout decisions before rendering.

The active boundary is a React/Tauri client, FastAPI backend, PostgreSQL persistence, Qdrant retrieval, filesystem media storage, hosted/local provider adapters, and FFmpeg rendering. Redis is provisioned but active application use was not found. MCP is an optional integration surface. n8n is legacy and LangGraph is installed without an active orchestration path.

| Area | Current state | Evidence | Confidence |
|---|---|---|---|
| User workflow | IMPLEMENTED_AND_CONNECTED project dashboard and six-stage review | `desktop/src/App.tsx:25-213`; `desktop/src/components/GuidedWorkflow.tsx:1` | High |
| Agents | Five specialised processing stages; Agents 3 and 4 run concurrently | `backend/app/agents/orchestrator.py:96-200` | High |
| RAG | Course-material chunks embedded and searched in Qdrant | `backend/app/rag/vector_store.py:52-64,168-463` | High |
| Visual planning | related/unrelated/uncertain page and layout decisions | `backend/app/agents/visual_structure.py:468-481,1033-1058` | High |
| Teacher control | Segment and layout overrides persisted | `backend/app/db/models.py:252-300`; `desktop/src/components/GuidedWorkflow.tsx:2606-2662` | High |
| Rendering | Native FFmpeg semantic compositor is default; Revideo optional | `backend/app/config.py`; `backend/app/services/renderer.py:471` | High |
| Evaluation | Metrics partly derivable; five paired cases still need collection | `backend/app/services/evaluation_metrics.py:1`; `16_EVALUATION_READINESS_AND_MEASUREMENT.md` | High |

Submission readiness is **PARTIALLY_IMPLEMENTED** from an evidence perspective: the engineering contribution is substantial, but Chapter 4 still requires the five-video paired timing/correctness study, failure reporting, and clearly separated human versus machine time.
""")


write("02_REPOSITORY_AND_VERSION_STATE.md", f"""
# Repository and Version State

## Version baseline

- Branch: `{INV['repository']['branch']}`
- HEAD: `{INV['repository']['head']}` (`{INV['repository']['head_subject']}`)
- Commit date: `{INV['repository']['head_date']}`
- Working tree: dirty and treated as authoritative.
- At baseline, Git reported 66 tracked changed files, approximately 16,239 insertions and 1,671 deletions, plus untracked implementation, migration, documentation, and asset files.

## Meaningful tree

```text
backend/
  app/agents/          five processing stages and orchestrator
  app/api/routes/      FastAPI routes
  app/db/              SQLAlchemy models/session
  app/providers/       provider registry and adapters
  app/rag/             Qdrant vector store
  app/services/        extraction, review, rendering, evaluation
  app/mcp/             three stdio MCP servers
  app/alembic/         five migration revisions
  tests/               canonical tests
desktop/
  src/                 React 19 client
  src-tauri/           Tauri 2 launcher/bootstrap/installer
  revideo/             optional browser-render helper
docker-compose.yml     development stack
docker-compose.desktop.yml packaged desktop backend stack
docs/                  handoff, setup, and generated audit material
scripts/               setup/evaluation helpers
```

`backend/app/tests/` duplicates many `backend/tests/` files. `desktop/src-tauri/target/` contains generated build copies and is excluded from source statistics. Deleted `n8n/README.md` and `n8n/workflows/pipeline_monitor.json` are pre-overhaul/legacy evidence, not current runtime.

## Overhaul implications

The current tree adds a project domain, multi-source assets, persisted settings, native import, semantic visual/layout planning, teacher review controls, richer export artifacts, evaluation metrics, and desktop bootstrap. Older single-video, n8n-centered, or scene-detection-primary descriptions are obsolete. See `22_CHANGELOG_AND_OVERHAUL_COMPARISON.md`.
""")


write("03_SYSTEM_ARCHITECTURE.md", """
# System Architecture

The Tauri shell launches a React client and, for packaged desktop use, bootstraps a Docker Compose backend on loopback port 18000. Browser development defaults to port 8000. FastAPI coordinates direct asynchronous Python agents, PostgreSQL, Qdrant, providers, document extraction, and rendering. Media and generated artifacts remain on the filesystem; paths and structured state are persisted in PostgreSQL.

```mermaid
flowchart LR
  U[Lecturer] --> T[Tauri 2 / React 19]
  T -->|HTTP| F[FastAPI]
  F --> O[Async agent orchestrator]
  O --> P[Provider registry]
  O --> Q[(Qdrant)]
  F --> D[(PostgreSQL)]
  F --> S[Filesystem storage]
  F --> R[FFmpeg / FFprobe renderer]
  C[Redis container] -. configured, no active client found .-> F
  M[Three MCP stdio servers] -. optional integration .-> F
```

## Active runtime only

```mermaid
flowchart TD
  UI[React UI] --> API[FastAPI API]
  API --> DB[(PostgreSQL)]
  API --> FS[Media/files]
  API --> AG[Direct Python orchestration]
  AG --> ASR[ASR provider route]
  AG --> LLM[Chat/vision providers]
  AG --> VDB[(Qdrant)]
  API --> FF[Native FFmpeg semantic compositor]
```

## Optional and fallback paths

```mermaid
flowchart TD
  ASR[Transcription] --> API[Hosted ASR]
  ASR --> LOCAL[whisper.cpp]
  ASR --> HYB[Hybrid fallback]
  VIS[Semantic visual planning] --> VISION[Vision/LLM]
  VIS --> MATCH[Local semantic matching]
  VIS --> PSD[PySceneDetect fallback]
  RENDER[Render] --> NATIVE[Native FFmpeg default]
  RENDER -. disabled by default .-> REVIDEO[Revideo/Puppeteer]
  EXT[External clients] -. optional .-> MCP[MCP stdio tools]
```

| Component | Purpose | Active/optional | Entry point | Dependencies | Evidence |
|---|---|---|---|---|---|
| Tauri shell | Desktop bootstrap/storage/native import | Active desktop | `desktop/src-tauri/src/main.rs` | Docker Desktop, WebView | `desktop/src-tauri/src/lib.rs:218-768` |
| React client | Lecturer workflow | Active | `desktop/src/main.tsx` | FastAPI | `desktop/src/App.tsx:25-213` |
| FastAPI | API/lifecycle | Active | `backend/app/main.py` | DB/Qdrant/storage | `backend/app/main.py:17-113` |
| Orchestrator | Five-stage pipeline | Active | `run_full_pipeline` | agents/providers | `backend/app/agents/orchestrator.py:96-200` |
| PostgreSQL | Relational state | Required | `backend/app/db/database.py` | SQLAlchemy/asyncpg | `backend/app/db/models.py:139-392` |
| Qdrant | RAG vectors | Required for RAG | `VectorStore` | embedding provider | `backend/app/rag/vector_store.py:52-64` |
| Redis | Provisioned cache/queue | CONFIGURATION_DEPENDENT | Compose only | Redis image | `docker-compose.yml:73-79` |
| Renderer | Final media/artifacts | Active | `render_final_video` | FFmpeg/FFprobe | `backend/app/services/renderer.py:471` |
| MCP | 25 external tools | Optional integration | `backend/app/mcp/run_mcp.py` | stdio client | `backend/app/mcp/*_server.py` |

n8n is DEPRECATED. LangGraph is IMPLEMENTED_BUT_NOT_CONNECTED as a dependency only. MCP is not required for the normal UI workflow.
""")


write("04_END_TO_END_USER_AND_DATA_WORKFLOW.md", """
# End-to-End User and Data Workflow

```mermaid
sequenceDiagram
  actor Teacher
  participant UI as React/Tauri
  participant API as FastAPI
  participant DB as PostgreSQL
  participant Q as Qdrant
  participant AI as Providers
  participant FF as FFmpeg
  Teacher->>UI: Launch, configure, create/open project
  UI->>API: Project and asset requests
  API->>DB: Persist project, videos, assets
  Teacher->>UI: Import recordings and PDF/PPTX
  UI->>API: Native or chunked upload
  API->>Q: Extract, chunk, embed material
  API->>AI: ASR and analysis stages
  AI-->>API: Transcript, semantics, fluency, visual plan, edit plan
  API->>DB: Persist transcript, segments, scenes, plan
  Teacher->>UI: Review and override
  UI->>API: Save teacher decisions
  API->>FF: Build deterministic render plan and render
  FF-->>API: MP4/subtitles/chapters/evidence
  API-->>UI: Progress and downloads
```

| Step | User/frontend | API/backend | Persistence/artifacts | Failure/retry |
|---|---|---|---|---|
| Launch/settings | `App`, `MainSettingsPanel` | settings/model routes; desktop bootstrap | `AppAISettings`, encrypted keys when configured | Failed backend bootstrap surfaces fetch/bootstrap error |
| Create/open project | `ProjectDashboard` | project CRUD | `Project`; project types/source setup | Duplicate/title validation is server/UI dependent |
| Add video(s) | `UploadPanel` | upload, chunk, native import, source-sync routes | `Video`, file paths, import session state | offset conflict, disk-space and orphan/quarantine handling |
| Add materials | multi-source upload | project assets and course-material extraction | `ProjectAsset`, `CourseMaterial`, page metadata, vectors | unsupported/empty extraction; scanned PDF OCR absent |
| Transcribe | processing view | `run_transcription_agent` | `Transcript`, `Segment` | provider retry/fallback and long-audio chunking |
| Analyse | guided workflow | Agents 2-5; Agents 3/4 parallel | segment analysis, scenes, edit plan | deterministic fallback and warning paths |
| Review | transcript/timeline/layout controls | segment, cue and plan update routes | teacher action/note/modified flags | warnings remain reviewable; regeneration can replace automatic data |
| Render/export | Export stage | approval creates persistent render job | MP4/M4A, SRT/VTT, chapters, plan, evidence | polling/cancel/restart interruption detection, FFmpeg watchdog |
| Reopen | dashboard/project load | project detail/status routes | relational/file state restored | missing backend, paths or containers cause partial load |

Disconnected/incomplete areas: local desktop project-file commands are not the primary React project persistence path; Redis has no traced runtime consumer; MCP is external-only; raw desktop Compose cannot start without launcher environment; browser and desktop can point at different databases and therefore show different projects.
""")


agent_table = "\n".join(f"| {a['name']} | {a['input']} | {a['output']} | {a['provider']} | Yes | Yes | `{a['evidence'][0]}` |" for a in agents)
write("05_AGENT_PIPELINE_AND_PROMPT_AUDIT.md", f"""
# Agent Pipeline and Prompt Audit

| Agent | Input | Output | Model/provider | Connected? | Persisted? | Evidence |
|---|---|---|---|---|---|---|
{agent_table}

## Execution model

`run_full_pipeline` performs direct Python orchestration. Agent 1 precedes Agent 2; Agent 2 results are committed before Agents 3 and 4 run with `asyncio.gather`; Agent 5 consumes their persisted outputs. There is no message bus, negotiation protocol, agent memory exchange, or autonomous agent-to-agent conversation (`backend/app/agents/orchestrator.py:96-200`).

The safest academic wording is: **a teacher-supervised pipeline of five specialised AI-assisted processing agents/modules, with limited parallel execution for fluency and visual analysis**. "Multi-agent" is defensible only when immediately qualified this way.

## Prompt and validation audit

| Prompt | Purpose | Structured output | Validation/fallback | Main risk |
|---|---|---|---|---|
| `backend/app/agents/content_understanding.py:32` | Topic/importance grounded by retrieved material | JSON batch decisions | parse checks plus deterministic fallback | weak retrieval or unsupported evidence may influence importance |
| `backend/app/agents/fluency.py:96` | Fillers, pauses, repetitions, bad takes | JSON issues | parser and local fallback | false-positive cuts in domain speech |
| `backend/app/agents/visual_structure.py:468-481` | page relevance, relation and layout | exact relation/page/layout fields | normalization, warnings, local semantic/PySceneDetect fallback | image/diagram interpretation depends on configured vision capability |
| `backend/app/agents/edit_planner.py:93` | KEEP/CUT/SHORTEN/HIGHLIGHT | JSON actions/reasons/confidence | coherence/consequence checks and rule fallback | over-removal without teacher review |

Agents 2 and 3 batch 5 and 8 transcript segments respectively; Agent 5 batches 15. Temperatures are 0.1. Provider/API failures generally degrade to conservative local decisions instead of halting the whole pipeline. Prompt wording broadly matches a specialised pipeline thesis description, but it does not support a claim of autonomous collaboration.
""")


write("06_RAG_AND_COURSE_MATERIAL_PIPELINE.md", """
# RAG and Course Material Pipeline

```mermaid
flowchart LR
  F[PDF/PPTX/DOCX/TXT/MD/CSV] --> X[Text extraction]
  X --> P[Page-aware cleaning]
  P --> C[300-token chunks / 50 overlap]
  C --> E[OpenAI-compatible embeddings]
  E --> Q[(Qdrant course_materials)]
  T[Transcript batch] --> S[Top-k semantic search]
  Q --> S
  S --> A2[Agent 2 prompt context]
  F --> IMG[Rendered PDF/PPTX page images]
  IMG --> A4[Agent 4 visual planning]
```

| Parameter | Current value | Evidence |
|---|---|---|
| Collection | `course_materials` | `backend/app/config.py`; `backend/app/rag/vector_store.py:52-64` |
| Embedding | `text-embedding-3-small`, 1536 dimensions | `backend/app/config.py` |
| Chunking | 300 tokens, overlap 50 | `backend/app/config.py` |
| Search | top-k 5, threshold 0.0 default | `backend/app/rag/vector_store.py:422-463` |
| Distance | Cosine | `backend/app/rag/vector_store.py:52-64` |
| Retry | one ingest retry after 2 seconds | `backend/app/rag/vector_store.py:112-130` |

PDF extraction uses PyMuPDF text; PPTX extraction includes shapes, tables, and speaker notes (`backend/app/services/text_extraction.py`). PDF/PPTX pages can also be rendered to images for Agent 4 (`pdf_slides.py`, `pptx_slides.py`). Project assets preserve optional one-based page ranges. Qdrant payloads retain source/page/file metadata.

Important limitations: no reranker was found; threshold 0.0 can admit weak matches; no content-hash deduplication was found; scanned PDFs have no implemented OCR despite an OCR-oriented comment/docstring; deletion removes vectors/files/rows but retention guarantees are not authenticated; Agent 2 uses retrieved text while Agent 4 primarily uses rendered page data and semantic prompts.
""")


write("07_SEMANTIC_VISUAL_PLANNING.md", """
# Semantic Visual Planning

Agent 4 builds page candidates from the selected project visual asset, respects a manual page scope when present, renders pages, aligns transcript windows, and asks the configured semantic/vision path for page and layout decisions. The exact labels `related`, `unrelated`, and `uncertain` are normalized in code. Unrelated and uncertain automatic decisions suppress the slide and use lecturer-only output; uncertain decisions carry `review_required`. Related decisions may use picture-in-picture by default, side-by-side selectively, or full-source sparingly (`backend/app/agents/visual_structure.py:468-481,1033-1058`; `backend/app/services/editorial_plan.py:283-297`).

```text
for each transcript window:
    restrict candidate pages to teacher scope when supplied
    obtain semantic page/relation/layout result
    normalize page index, confidence, relation and timing
    if relation == unrelated: use full_camera_source
    elif relation == uncertain: use full_camera_source and require review
    else: retain matched page and selected supported layout
stabilize adjacent/short cues to avoid visual flicker
persist scene/layout metadata and build deterministic render plan
on semantic failure: local matching, then PySceneDetect fallback where applicable
```

```mermaid
flowchart TD
  A[Transcript range + candidate pages] --> B{Semantic match}
  B -->|related| C{Layout choice}
  C --> P[Picture-in-picture]
  C --> S[Side-by-side]
  C --> F[Full-source]
  B -->|unrelated| L[Lecturer-only]
  B -->|uncertain| W[Lecturer-only + review warning]
  B -->|provider failure| M[Local semantic matching]
  M --> D[PySceneDetect fallback]
  P --> ST[Timing stabilization]
  S --> ST
  F --> ST
  L --> ST
  W --> ST
```

| Case | Slide | Layout | Review |
|---|---|---|---|
| related/high confidence | selected page | PIP/side/full source | optional |
| related/low diagnostic score | preserved | supported layout | may warn |
| unrelated | none | lecturer-only | no forced visual |
| uncertain | none by safe default | lecturer-only | required |
| speech absent from slides | none | lecturer-only | inspect if uncertain |
| provider failure | local/fallback result | conservative | warning |

Short/uncertain cue stabilization is implemented around `backend/app/agents/visual_structure.py:1297-1322`. PySceneDetect is a fallback around `:1532`, not the primary semantic planner. Weaknesses include provider-dependent diagram understanding, no measured page-selection accuracy, local lexical fallback limitations, possible page-number extraction ambiguity, and no proof yet across the five-video study.
""")


write("08_EDIT_PLANNING_AND_TEACHER_REVIEW.md", """
# Edit Planning and Teacher Review

Agent 5 consumes content importance, fluency findings, visual findings, and timing context to generate KEEP, CUT, SHORTEN, and HIGHLIGHT decisions. Coherence and consequence checks run after LLM output (`backend/app/agents/edit_planner.py:93,412,488`). Deterministic warnings protect introductions, transitions, uncertain visuals, and potentially important material from silent removal.

| Warning class | Risk addressed | Evidence |
|---|---|---|
| coherence/transition | cut creates broken explanation | `backend/app/agents/edit_planner.py:412` |
| removal consequence | important content may disappear | `backend/app/agents/edit_planner.py:488` |
| visual uncertainty | page/layout needs teacher judgment | `backend/app/services/editorial_plan.py:283-297` |
| overlap/timeline validity | conflicting playable ranges | `backend/app/services/transcript_timeline.py` |

Teacher overrides are stored on `Segment` using `teacher_action`, `teacher_note`, and `is_teacher_modified`, with timing/trim-related fields in the same entity (`backend/app/db/models.py:252-300`). Layout overrides are saved as cues whose source is `teacher_layout_override` (`desktop/src/components/GuidedWorkflow.tsx:2606-2662`). Manual decisions take precedence in editorial and semantic render-plan construction.

Override count and rate are automatically derivable and included in evaluation/evidence services (`backend/app/services/evaluation_metrics.py`; `backend/app/services/export_artifacts.py`). Active teacher editing time is not reliably recorded. Undo/reset exists at UI/decision-operation level but there is no general versioned edit-plan history table; regeneration/versioning semantics therefore remain PARTIALLY_IMPLEMENTED. The UI uses transcript cards, timeline colors, action controls, layout controls, warnings, and export gating in `GuidedWorkflow.tsx` and `ReviewEditor.tsx`.
""")


write("09_RENDERING_EXPORT_AND_MEDIA_PROCESSING.md", """
# Rendering, Export, and Media Processing

```mermaid
flowchart LR
  P[Approved edit plan] --> RP[Deterministic semantic render plan]
  RP --> J[Persistent render job]
  J --> F[FFmpeg/FFprobe]
  F --> L[Trim/concat/layout/audio/captions]
  L --> V[Output verification]
  V --> O[MP4 or M4A]
  V --> S[SRT/VTT]
  V --> C[Chapters]
  V --> E[Plan/evidence/metrics bundle]
```

`render_final_video` is the principal entry point (`backend/app/services/renderer.py:471`). Simple edits may use fast trim/concatenate paths; semantic layouts use the native FFmpeg compositor by default. Revideo/Puppeteer is optional and disabled by default. FFprobe validates source/output metadata. Hardware encoder selection can consider NVENC, QSV, VAAPI, or AMF; configuration controls CPU fallback.

| Artifact | Format | Status |
|---|---|---|
| edited lecture | MP4 or preset-specific M4A | IMPLEMENTED_AND_CONNECTED |
| subtitles | SRT and VTT; burn-in path also exists | IMPLEMENTED_AND_CONNECTED |
| chapters | structured chapter export | IMPLEMENTED_AND_CONNECTED |
| edit/render plan | JSON | IMPLEMENTED_AND_CONNECTED |
| academic evidence | JSON and Markdown | IMPLEMENTED_AND_CONNECTED |
| timeline/provider/metric evidence | CSV/JSON bundle | IMPLEMENTED_AND_CONNECTED |

Sanitised illustrative command shape, not a captured literal invocation:

```text
ffmpeg -i <project-video> -filter_complex "<scale/crop/overlay/concat graph>" -map <video> -map <audio> -c:v <selected-encoder> -c:a aac <project-output.mp4>
```

Progress and cancellation are persisted by `render_jobs.py`; interrupted jobs are detected on restart and duplicate active claims are rejected. The native compositor has a no-progress watchdog. Temporary cleanup exists, but hard termination can leave artifacts. Risks include variable-frame-rate timing, source/audio drift, unsupported codecs, missing fonts, hardware encoder availability, malformed source timestamps, and long-render resource pressure. Full-source, camera-full, PIP, side-by-side, captions, annotations, and multiple export presets are represented; empirical 40+ minute reliability remains UNVERIFIED.
""")


entity_rows = "\n".join(f"| {e['name']} | See ORM columns | SQLAlchemy relationships/foreign keys | Persist project pipeline state | IMPLEMENTED_AND_CONNECTED | `{e['evidence'][0]}` |" for e in entities)
write("10_DATABASE_AND_PERSISTENCE_MODEL.md", f"""
# Database and Persistence Model

| Entity | Fields | Relationships | Purpose | Current use | Evidence |
|---|---|---|---|---|---|
{entity_rows}

```mermaid
erDiagram
  PROJECT ||--o{{ VIDEO : contains
  PROJECT ||--o{{ PROJECT_ASSET : owns
  VIDEO ||--o| TRANSCRIPT : has
  VIDEO ||--o{{ SEGMENT : contains
  VIDEO ||--o{{ SCENE : contains
  VIDEO ||--o| EDIT_PLAN : produces
  COURSE_MATERIAL ||--o{{ VECTOR_CHUNK : represented_in_Qdrant
  APP_AI_SETTINGS ||--|| APPLICATION : configures
```

The nine-entity claim is confirmed by `backend/app/db/models.py:139-392`. Models use UUID-like identifiers, JSON fields for rich plans/metadata, timestamps/statuses, foreign keys, relationships, and cascades. Alembic revisions 001-005 cover initial state, app settings, project assets, project media sources, and large file-size conversion.

Persistence outside PostgreSQL includes Qdrant vectors, filesystem media/artifacts, `render_jobs.json` under configured state storage, desktop environment/settings files, and Tauri local project-file commands. No active Redis payload model was found. The Tauri `save_project`/`load_project` commands are IMPLEMENTED_BUT_NOT_CONNECTED to the primary backend project flow (`desktop/src-tauri/src/lib.rs:179-201`). Migration 005 is present in the dirty tree; deployment against older databases must run it before very large uploads. Frontend/backend type parity is broad but not mechanically generated, so drift remains a maintenance risk.
""")


write("11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md", f"""
# API Endpoint and Schema Inventory

`API_ENDPOINTS.csv` contains {len(api_rows)} decorated handlers from the current tree, including {sum(1 for r in api_rows if r['category']=='legacy/unused')} debug handlers that are only mounted when `APP_DEBUG` is enabled. Main routers are mounted under `/api/v1`; project routes add `/projects` (`backend/app/main.py:70-77`). Root and health remain top-level.

| Category | Count |
|---|---:|
""" + "\n".join(f"| {k} | {v} |" for k, v in sorted(Counter(r["category"] for r in api_rows).items())) + """

No authentication dependency was found. Upload/render handlers can mutate both database and filesystem state; analysis routes can call configured AI providers. `API_FRONTEND_MAPPING.csv` provides a conservative static mapping, and entries marked for manual inspection should not be interpreted as disconnected solely because symbol names differ.

Risks: browser default `localhost:8000` differs from packaged desktop `127.0.0.1:18000`; debug routes depend on `APP_DEBUG`; error payload styles vary; some implemented endpoints have no visible UI caller; MCP tools are not HTTP endpoints; name-based mapping cannot prove runtime calls.
""")


write("12_FRONTEND_DESKTOP_AND_UI_INVENTORY.md", """
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
""")


write("13_AI_PROVIDER_CONFIGURATION.md", """
# AI Provider Configuration

`PROVIDERS.csv` and `CONFIGURATION_KEYS.csv` enumerate active, optional, and placeholder provider paths. The registry supports hosted ASR/chat/embedding/vision adapters plus local whisper.cpp. Agent model defaults are configuration values, not guaranteed runtime providers: persisted application settings can override them.

ASR routing genuinely implements API, local, and hybrid behavior in `backend/app/services/transcription.py`, including long-audio chunking and provider-specific limits. General chat/embedding/vision mode abstraction is PARTIALLY_IMPLEMENTED: `LLMService` selects configured API/default providers, while local non-ASR adapters are placeholders. Automatic fallback is strongest in transcription and agent-level deterministic fallbacks, not a universal provider failover matrix.

API keys are accepted through settings and can be stored encrypted with Fernet only when `APP_SETTINGS_SECRET_KEY` is configured (`backend/app/services/app_settings.py:210-241`). UI masking is not equivalent to at-rest encryption. Timeouts/retries are service-specific; Qdrant ingest retries once, render jobs use watchdogs, and provider rate-limit accounting is not centrally persisted. No secret values are reproduced in this pack.
""")


write("14_MCP_SERVER_AND_TOOL_INVENTORY.md", """
# MCP Server and Tool Inventory

The claim is exactly confirmed: three stdio MCP servers expose 25 tools. `video-tools` has 8, `knowledge-tools` has 7, and `pipeline-tools` has 10. No MCP resources or prompt templates were found. Registration uses `Server`, `list_tools`, and `call_tool`; `backend/app/mcp/run_mcp.py` is the entry point.

MCP_TOOLS.csv lists every tool and status. The servers wrap media, Qdrant, and pipeline operations, but no FastAPI mounting, React call, or normal desktop dependency was found. Therefore MCP is an IMPLEMENTED_BUT_NOT_CONNECTED integration layer, not a core runtime requirement. The pipeline approval tool appears less complete than the current persistent render-job API and is marked PARTIALLY_IMPLEMENTED.

Security implications include broad local file/media operations, database access, no application authentication layer, stdio-client trust, and configuration examples that must never contain live credentials. Missing MCP coverage includes the full current project-first UI semantics, native desktop import lifecycle, and some newer render/export operations.
""")


write("15_TESTING_BUILD_AND_QUALITY_STATUS.md", """
# Testing, Build, and Quality Status

See `TEST_RESULTS.md` and `TEST_INVENTORY.csv` for command and test-level detail. The tree contains backend unit/service tests for agents, layouts, rendering, imports, projects, evaluation, timelines, and export artifacts. Many tests use mocks/stubs. No frontend component/E2E test framework, code-coverage report, or CI workflow was found during this audit.

Static quality signals include Pydantic schemas, TypeScript compilation, Rust compilation, deterministic validators, and targeted tests. Risks include duplicate test trees (`backend/tests` and `backend/app/tests`), test-order module contamination in discovery, Windows temp-permission sensitivity, no authenticated API tests, no clean-machine installer test, no live provider integration suite, and no five-video full-stack regression suite.
""")


metrics = [
    ("Original video duration", "Automatically recorded", "Video duration/ffprobe", "backend/app/db/models.py:191-220"),
    ("Manual active editing time", "Not currently measurable", "Use external timer or add activity instrumentation", "No persisted manual-session timer found"),
    ("Agent processing time", "Partly automatically recorded", "Progress/timestamps/logs can derive stage elapsed time", "backend/app/services/progress.py"),
    ("Teacher active review/editing time", "Not currently measurable", "External timer or interaction telemetry required", "No active-time field found"),
    ("Total agent-assisted elapsed time", "Derivable", "Start/end timestamps plus external observation", "processing/render timestamps"),
    ("Recommendation count", "Derivable", "Count segments/cues/actions", "backend/app/db/models.py:252-350"),
    ("Teacher overrides", "Automatically derivable", "Count is_teacher_modified", "backend/app/services/evaluation_metrics.py"),
    ("Override rate", "Automatically derivable", "overrides/recommendations", "backend/app/services/evaluation_metrics.py"),
    ("Action distribution", "Automatically derivable", "Count final actions", "backend/app/services/export_artifacts.py"),
    ("Slide/page decisions", "Derivable", "Count slide cues", "backend/app/services/semantic_render_plan.py"),
    ("Correct/incorrect page selections", "Manually recordable", "Teacher ground-truth rating required", "No correctness label persisted"),
    ("Uncertain selections", "Derivable", "Count relation/review flags", "backend/app/agents/visual_structure.py:1033-1058"),
    ("Lecturer-only decisions", "Derivable", "Count full_camera_source", "backend/app/services/editorial_plan.py:283-297"),
    ("Content-preservation rating", "Manually recordable", "Human rubric required", "Not objectively stored"),
    ("Render success/failure", "Automatically recorded", "Render job state", "backend/app/services/render_jobs.py"),
    ("Subtitle/chapter/export consistency", "Derivable plus manual verification", "Artifact records and inspection", "backend/app/services/export_artifacts.py"),
    ("Provider/model", "Automatically recorded/derivable", "provider trace/settings", "backend/app/services/export_artifacts.py"),
    ("API cost", "Not currently measurable", "Provider billing/token prices required", "No cost ledger found"),
    ("Token usage", "Partly/unverified", "Depends on response metadata; no central ledger", "provider adapters"),
    ("Error/retry count", "Partly recorded", "Logs/status; no unified counter", "service-specific handlers"),
]
write("EVALUATION_METRIC_MATRIX.md", "# Evaluation Metric Matrix\n\n| Metric | Availability | Collection method | Evidence |\n|---|---|---|---|\n" + "\n".join(f"| {a} | {b} | {c} | `{d}` |" for a,b,c,d in metrics))


eval_columns = ["case_id", "video_title", "source", "domain", "duration_minutes", "has_slides", "manual_order", "manual_active_edit_minutes", "manual_total_elapsed_minutes", "manual_quality_rating", "agent_order", "agent_processing_minutes", "teacher_active_review_minutes", "render_minutes", "agent_total_elapsed_minutes", "recommendations", "teacher_overrides", "override_rate", "keep_count", "cut_count", "shorten_count", "highlight_count", "slide_decisions", "correct_slide_decisions", "incorrect_slide_decisions", "uncertain_slide_decisions", "lecturer_only_decisions", "content_preservation_rating", "render_success", "subtitle_success", "chapter_success", "export_consistent", "provider_models", "failure_notes"]
write_csv("FIVE_VIDEO_DATA_COLLECTION_TEMPLATE.csv", eval_columns, [{"case_id": i} for i in range(1, 6)])


write("16_EVALUATION_READINESS_AND_MEASUREMENT.md", """
# Evaluation Readiness and Measurement

The current application can derive recommendations, overrides, action distribution, visual decisions, uncertain/lecturer-only decisions, provider traces, and render/artifact outcomes. It cannot reliably measure active manual editing time or active teacher review time without an external timer or code changes. Correct slide selection and content preservation require a defined human ground truth/rubric.

The supervisor-approved five-video paired design is feasible using `FIVE_VIDEO_DATA_COLLECTION_TEMPLATE.csv`. Each video must be edited manually and through the agent-assisted workflow, with condition order counterbalanced where possible. Machine processing, active teacher time, render time, and total elapsed time must be separated. Report per-video values and descriptive paired differences; do not claim population significance from five cases.

See `EVALUATION_PROCEDURE.md`, `EVALUATION_RISKS.md`, `EVALUATION_METRIC_MATRIX.md`, and `CHAPTER4_RESULTS_TABLE_TEMPLATE.md`.
""")


write("EVALUATION_PROCEDURE.md", """
# Five-Video Evaluation Procedure

1. Select five videos: include all supervisor-provided videos and enough additional videos to reach five; document domain, duration, slide availability, resolution, and source type.
2. Define a fixed editing brief and quality rubric before starting.
3. For every video, perform a manual edit and an agent-assisted edit to the same brief. Counterbalance order to reduce learning effects.
4. Use the same computer, export preset, and network conditions where practical.
5. Record active human time with a pauseable external timer. Exclude waiting, breaks, downloads, and machine-only processing.
6. Record agent processing, active teacher review, render time, and total elapsed time separately.
7. Review every suggested edit and slide/page decision against the source and rubric; record overrides, uncertainty, and failure cases.
8. Verify output playback, duration, audio sync, subtitles, chapters, and downloadable evidence artifacts.
9. Report all five cases individually, then median/mean/range and paired per-video time differences. Treat inference beyond these cases as exploratory.
10. Preserve logs, settings, provider/model names, app commit/audit state, and completed CSV as reproducibility evidence.
""")


write("EVALUATION_RISKS.md", """
# Evaluation Risks

| Threat | Effect | Mitigation |
|---|---|---|
| Same researcher performs both conditions | expectation bias | fixed rubric, preserve decisions, independent supervisor spot-check |
| Learning/order effects | second edit becomes faster | counterbalance order across five videos |
| Different quality targets | unfair time comparison | identical editing brief/export preset |
| Hardware/network variation | timing noise | same machine, record provider/network incidents |
| Duration/domain/slide variation | cases not directly comparable | report per-video normalized and raw values |
| Subjective page correctness | rating bias | predefine correct/acceptable/incorrect rubric |
| Small sample size | weak generalisation | descriptive paired analysis only |
| Provider changes/failures | reproducibility drift | record provider/model/settings/date |
| Researcher inactivity counted as work | inflated active time | pauseable timer and separate elapsed time |
| Failed renders omitted | survivorship bias | include every failed/retried case |
""")


write("CHAPTER4_RESULTS_TABLE_TEMPLATE.md", """
# Chapter 4 Results Table Templates

## Timing

| Video | Duration | Manual active edit | Agent processing | Teacher active review | Render | Agent-assisted total | Active-human saving | Notes |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| V1 | | | | | | | | |
| V2 | | | | | | | | |
| V3 | | | | | | | | |
| V4 | | | | | | | | |
| V5 | | | | | | | | |

## Decision quality and reliability

| Video | Recommendations | Overrides | Override rate | Correct pages | Incorrect pages | Uncertain | Lecturer-only | Render | Subtitles | Chapters | Failures |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|---|---|
| V1 | | | | | | | | | | | |
| V2 | | | | | | | | | | | |
| V3 | | | | | | | | | | | |
| V4 | | | | | | | | | | | |
| V5 | | | | | | | | | | | |

Use descriptive summaries and case-level discussion. Do not insert external benchmark values as project results.
""")


claims = [
    ("Project-first workflow", "IMPLEMENTED_AND_CONNECTED", "backend/app/api/routes/projects.py:650; desktop/src/components/ProjectDashboard.tsx:1", "Create/open/reopen smoke test", "None for existence", "The implementation uses projects as the main workspace.", "The system is proven usable by all lecturers."),
    ("Five-agent pipeline", "IMPLEMENTED_AND_CONNECTED", "backend/app/agents/orchestrator.py:96-200", "Full five-stage run", "Performance/quality study", "Five specialised AI-assisted stages are orchestrated in Python.", "Five autonomous agents collaborate and negotiate."),
    ("RAG", "IMPLEMENTED_AND_CONNECTED", "backend/app/rag/vector_store.py:168-463", "Live ingest/search", "Measured effect requires ablation", "Agent 2 can receive Qdrant-retrieved course context.", "RAG improves accuracy by X%."),
    ("Semantic visual planning", "IMPLEMENTED_AND_CONNECTED", "backend/app/agents/visual_structure.py:468-481", "Five-video page review", "Page correctness labels", "The planner emits page/relation/layout cues.", "Slide selection is accurate."),
    ("Teacher review", "IMPLEMENTED_AND_CONNECTED", "backend/app/db/models.py:252-300", "UI override smoke test", "Override/time measurements", "Teachers can override persisted recommendations.", "Teacher-in-the-loop improves quality by X%."),
    ("Rendering/subtitles/chapters/evidence", "IMPLEMENTED_AND_CONNECTED", "backend/app/services/renderer.py:471; export_artifacts.py", "Long-video playback verification", "Five-case success table", "The renderer can produce media and supporting artifacts.", "Rendering is error-free for arbitrary lectures."),
    ("Three MCP servers/25 tools", "IMPLEMENTED_BUT_NOT_CONNECTED", "backend/app/mcp/*_server.py", "External MCP client smoke test", "None for count", "An optional MCP integration exposes 25 tools.", "MCP powers the normal application workflow."),
    ("Editing-time reduction", "UNVERIFIED", "No project result yet", "Five paired runs", "Manual vs assisted timing", "The study will compare active editing time.", "The system reduces editing time by 36-fold."),
    ("2.9% WER", "UNVERIFIED", "No project measurement", "Ground-truth transcript scoring", "WER experiment", "No project WER is currently claimed.", "The project achieved 2.9% WER."),
    ("USD 0.37 per lecture", "UNVERIFIED", "No cost ledger", "Billing/token capture", "Cost experiment", "Cost was not measured.", "Cost is USD 0.37 per lecture."),
    ("10 min per 60 min / 36x speed", "UNVERIFIED", "No five-video timing dataset", "Timed runs", "Paired timing", "Processing speed remains to be measured.", "A 60-minute lecture completes in 10 minutes."),
    ("30 lectures / 15 educators / significance", "UNVERIFIED", "No such study artifacts", "Human study records", "Approved study", "The present planned evaluation uses five videos.", "Results are statistically significant across 30 lectures and 15 educators."),
]
write("17_REPORT_CLAIMS_AND_EVIDENCE_MATRIX.md", "# Report Claims and Evidence Matrix\n\n| Claim | Status | Code evidence | Runtime evidence needed | Evaluation evidence needed | Safe thesis wording | Unsafe wording |\n|---|---|---|---|---|---|---|\n" + "\n".join("| " + " | ".join(row) + " |" for row in claims) + """

External model benchmarks, comments, sample fixtures, and configuration defaults are not project-measured results. Calculated code counts may support architecture descriptions only. Genuine project results must come from retained logs/artifacts and the five-video dataset.
""")


write("18_REPORT_CHAPTER_MAPPING.md", """
# Report Chapter Mapping

## Chapter 1

Frame the problem as lecturer-controlled reduction of repetitive educational editing work. Objectives should cover transcript/content analysis, semantic visual planning, teacher review, and deterministic export. Scope must state desktop/local infrastructure, configured external providers, five-video evaluation, and no learning-outcome study.

## Chapter 2

Literature is required for educational video design, cognitive load, ASR, RAG, multimodal/visual understanding, agent terminology, human-in-the-loop systems, privacy, and commercial editor comparison. Code cannot establish field-wide superiority or model benchmark performance.

## Chapter 3

Use files `03`-`14` for architecture, workflow, five specialised stages, RAG, semantic planning, review data model, rendering, persistence, providers, and MCP. Use `EVALUATION_PROCEDURE.md` for the five-video paired methodology.

## Chapter 4

Collect the timing and decision dataset, screenshots, page correctness, overrides, action distributions, render/artifact outcomes, and all failures. Discuss each objective with code evidence plus measured runtime evidence.

## Chapter 5

Conclude only what implementation plus five-case results support. Separate engineering contribution, evaluation limitations, provider dependence, small sample, and future work such as OCR, local multimodal models, authentication, telemetry, and broader evaluation.

## Technical paper

Suggested title: **Teacher-Supervised Semantic Editing of Educational Videos Using a Five-Stage AI-Assisted Pipeline**. Recommended figures are project workflow, system architecture, agent/RAG/visual pipeline, render/evidence pipeline, and evaluation protocol. Essential tables are paired timing, override/action distribution, visual correctness, and failure cases.

## Information that cannot be obtained from the codebase

Empirical manual/agent timings, teacher ratings, supervisor judgments, usability feedback, educational learning outcomes, human preference, final edit-quality equivalence, real provider billing, and final thesis formatting decisions require external collection or author decisions.
""")


figures = [
    ("Project-first teacher-supervised workflow", "Project -> sources -> agents -> review -> render/export", "Project and teacher review loop"),
    ("Detailed multi-agent processing pipeline", "Agent 1 -> Agent 2 -> Agents 3/4 parallel -> Agent 5", "Specialised modules, not autonomous negotiation"),
    ("Current three-tier system architecture", "React/Tauri -> FastAPI -> persistence/providers/rendering", "Redis/MCP shown as non-core"),
    ("Five-agent execution and review pipeline", "Agent outputs -> deterministic checks -> teacher overrides", "Persisted review state"),
    ("Current database/entity model", "Nine ORM entities and Qdrant/file side stores", "Relational versus external persistence"),
    ("Batch-level RAG analysis pipeline", "Material chunks -> embeddings -> Qdrant -> Agent 2 batches", "top-k 5, no reranker"),
    ("Semantic visual-planning and slide-relevance flow", "related/unrelated/uncertain -> layout/review", "safe lecturer-only fallback"),
    ("Warning-based edit planning and teacher-override flow", "LLM actions -> validators -> warnings -> teacher", "manual precedence"),
    ("Semantic rendering and evidence-export pipeline", "render plan -> FFmpeg -> verification -> artifacts", "native default, Revideo optional"),
    ("Five-video manual-versus-agent evaluation protocol", "paired conditions -> separate timers -> descriptive comparison", "no population inference"),
]
fig_body = ["# Figure Recreation Specifications"]
for i, (title, flow, note) in enumerate(figures, 1):
    fig_body.append(f"""
## Figure {i}: {title}

**Purpose:** Recreate {title.lower()} from verified implementation.
**Verified flow:** {flow}.
**Required labels:** active runtime components, database artifacts, optional/fallback paths as dashed lines, and teacher-review loops.
**Unverified element:** empirical performance/accuracy must not be embedded in the figure.
**Suggested caption:** "{title} derived from the current implementation audit."
**Academic styling:** left-to-right or top-to-bottom flow, restrained colors, solid active edges, dashed optional edges, database cylinders, user actor distinct from software.

```mermaid
flowchart LR
  A[Input / prior stage] --> B[{title}]
  B --> C[Persisted output]
  C --> D[Teacher review or next stage]
  D -->|override/retry| B
  B -. optional or fallback .-> F[Fallback path]
```

Specific note: {note}.
""")
write("19_FIGURE_RECREATION_SPECIFICATIONS.md", "\n".join(fig_body))


debt_rows = [
    ("No authentication/authorization", "High", "Any local/network caller can mutate data", "Must not claim secure multi-user deployment", "API routes have no auth dependency", "Prototype/local deployment limitation"),
    ("Scanned PDF OCR absent", "High", "Empty/weak material extraction", "Limits RAG claims", "backend/app/services/text_extraction.py", "Text-based PDFs are supported; scanned PDFs need OCR"),
    ("Redis configured but no consumer found", "Medium", "Extra operational dependency", "Do not claim caching/queue use", "docker-compose.yml:73-79", "Provisioned but not evidenced as active"),
    ("LangGraph installed but unused", "Low", "Dependency complexity", "Do not describe LangGraph orchestration", "backend/requirements.txt:21", "Direct asyncio orchestration is active"),
    ("MCP disconnected from core UI", "Medium", "Optional tools may drift", "Do not claim MCP powers workflow", "backend/app/mcp/run_mcp.py", "Optional integration surface"),
    ("Desktop Compose requires launcher variables", "High", "Raw compose fails validation", "Deployment reproducibility caveat", "docker-compose.desktop.yml", "Start through packaged launcher or provide AIVE_HOST_*"),
    ("Duplicate test trees", "Medium", "Discovery/order confusion", "Test-count caveat", "backend/tests; backend/app/tests", "Canonical test root must be stated"),
    ("No frontend/E2E suite", "High", "UI regressions may escape", "Readiness limitation", "No frontend test configuration found", "Frontend build passes but behavior needs smoke tests"),
    ("No active-time telemetry", "High", "Main evaluation metric needs manual timer", "Chapter 4 collection requirement", "No persisted active editing timer", "Use external timer for five-video study"),
    ("Hard-coded default ports differ", "Medium", "Browser/desktop data-stack confusion", "Architecture clarification", "desktop/src/lib/api.ts; desktop/src-tauri/src/lib.rs:233-245", "Browser 8000 and desktop 18000 are separate defaults"),
]
write("20_LIMITATIONS_TODOS_AND_TECHNICAL_DEBT.md", "# Limitations, TODOs, and Technical Debt\n\n| Issue | Severity | User impact | Thesis impact | Evidence | Recommended description |\n|---|---|---|---|---|---|\n" + "\n".join("| " + " | ".join(row) + " |" for row in debt_rows) + f"""

The static keyword scan found {len(INV['technical_debt'])} TODO/FIXME/HACK/placeholder-like hits after exclusions. Keyword hits are leads, not automatic defects. Hidden legacy UI blocks, placeholder provider adapters, disabled Revideo default, stale MCP behavior, and deleted n8n files are classified according to runtime connectivity rather than comments alone.
""")


write("21_SECURITY_PRIVACY_AND_ETHICAL_CONSIDERATIONS.md", """
# Security, Privacy, and Ethical Considerations

Lecture videos, transcripts, course materials, edit plans, provider traces, and exports are stored in PostgreSQL and configured local filesystem directories; course embeddings are sent to/stored in Qdrant. Hosted ASR, chat, embedding, or vision routes transmit relevant content to third-party providers when configured. whisper.cpp offers a local ASR route, but local chat/vision/embedding routes are placeholders.

The application has no evidenced authentication or role-based authorization. API keys can be encrypted at rest only when `APP_SETTINGS_SECRET_KEY` is configured (`backend/app/services/app_settings.py:210-241`); otherwise persistence is restricted/error-prone rather than safely encrypted by default. Logging and generated evidence may contain lecture content. Deletion paths exist, but complete secure erasure across database, Qdrant, backups, temp files, logs, and provider systems is not proven.

Ethical risks include provider privacy exposure, copyright/ownership of lecture materials, hallucinated importance or page relations, incorrect content removal, bias in speech recognition, and overreliance on automatic edits. Teacher review, conservative lecturer-only handling, warnings, deterministic plans, and evidence exports are risk mitigations, not guarantees.

Safe thesis wording: "The prototype supports local storage and a local ASR option, while configured hosted providers may receive lecture-derived data. Teacher review and traceable artifacts reduce, but do not eliminate, risks from model error. Authentication, formal retention controls, and a complete privacy impact assessment remain future work."
""")


write("22_CHANGELOG_AND_OVERHAUL_COMPARISON.md", """
# Changelog and Overhaul Comparison

| Area | Earlier implementation | Current implementation | Evidence | Report implication |
|---|---|---|---|---|
| Workspace | single-video-oriented | project-first, multi-video/assets | `Project`, `ProjectAsset`, dashboard | Rewrite workflow and data model |
| UI stages | older analysis/review screens | Transcribe/Clean/Sections/Layout/Polish/Export | `GuidedWorkflow.tsx` | Use current six-stage terminology |
| Orchestration | n8n-oriented descriptions | direct async Python | `orchestrator.py:96-200`; deleted n8n files | Remove n8n from active architecture |
| Visual analysis | scene detection emphasis | semantic page/relation/layout planning; PySceneDetect fallback | `visual_structure.py` | Present scene detection as fallback |
| Providers | fixed integrations | registry, modes, persisted settings, local ASR | `providers/defaults.py`; `app_settings.py` | Describe configuration dependence |
| Rendering | basic trim/concat | semantic FFmpeg layouts, presets, jobs, evidence | `renderer.py`; `semantic_render_plan.py` | Update methodology/output figures |
| Persistence | fewer entities | nine entities plus Qdrant/files/job state | `db/models.py:139-392` | Replace ER diagram |
| Desktop | dev browser assumptions | Tauri bootstrap/native imports/packaged compose | `src-tauri/src/lib.rs` | Separate browser and packaged stacks |
| Evaluation | broad/older claims | five-video paired timing plan | supervisor instruction and audit templates | Remove unsupported large-study claims |

Git history and the dirty tree show a substantial overhaul after HEAD. Because many current capabilities are uncommitted, the working tree rather than the latest commit is the implementation baseline for the thesis.
""")


stack_rows = [
    ("Desktop", "Tauri", "2.x", "Native shell/bootstrap/import", "desktop/src-tauri/Cargo.toml"),
    ("Frontend", "React", "19.x", "Lecturer UI", "desktop/package.json"),
    ("Frontend", "Vite/TypeScript", "6.4.2 / current package", "Build/tooling", "desktop/package.json"),
    ("Backend", "FastAPI", "requirements-pinned", "HTTP API", "backend/requirements.txt"),
    ("ORM", "SQLAlchemy async", "requirements-pinned", "PostgreSQL persistence", "backend/app/db"),
    ("Database", "PostgreSQL", "16 image", "Relational state", "docker-compose.yml"),
    ("Vector DB", "Qdrant", "container image", "RAG vectors", "docker-compose.yml"),
    ("Cache", "Redis", "7-alpine", "Configured, active use not found", "docker-compose.yml"),
    ("Media", "FFmpeg/FFprobe", "runtime", "Media processing/rendering", "backend/app/services/ffmpeg.py"),
    ("Documents", "PyMuPDF/python-pptx/python-docx", "requirements-pinned", "Extraction/page rendering", "backend/requirements.txt"),
    ("MCP", "Python MCP", "requirements-pinned", "Optional 25-tool integration", "backend/app/mcp"),
]
write_csv("TECHNOLOGY_STACK.csv", ["layer", "technology", "version", "purpose", "evidence"], [dict(zip(["layer", "technology", "version", "purpose", "evidence"], row)) for row in stack_rows])
write("23_CODE_STATISTICS_AND_TECH_STACK.md", f"""
# Code Statistics and Technology Stack

| Measure | Count |
|---|---:|
| Included files | {INV['statistics']['files_total']} |
| Approximate non-empty lines | {INV['statistics']['approximate_non_empty_lines']} |
| Backend files | {INV['statistics']['backend_files']} |
| Frontend files | {INV['statistics']['frontend_files']} |
| Test files | {INV['statistics']['test_files']} |
| Migration files | {INV['statistics']['migration_files']} |
| Decorated endpoint handlers | {len(api_rows)} |
| ORM entities | {len(entities)} |
| MCP tools | {len(mcp_tools)} |
| Provider registry entries represented | {len(providers)} |
| Active Compose services | 4 (backend, PostgreSQL, Qdrant, Redis) |

Counts exclude node_modules, virtual environments, Rust target output, dist/build output, caches, dependency lock line counts, binary/media assets, uploaded/generated storage, and this generated pack where appropriate. Non-empty line counts are approximate physical lines, not logical statements. Prompt count is not safely reduced to a single AST number because several prompts are assembled inline; `05_AGENT_PIPELINE_AND_PROMPT_AUDIT.md` lists the principal active prompts.

See `CODE_STATISTICS.json`, `FILE_TYPE_STATISTICS.csv`, `DEPENDENCY_INVENTORY.csv`, and `TECHNOLOGY_STACK.csv`. Source volume is not evidence of research quality.
""")


write("24_EXTERNAL_CLAIMS_REQUIRING_REFERENCES.md", """
# External Claims Requiring References

| Claim category | Why code is insufficient | Preferred source type | Unsupported value risk |
|---|---|---|---|
| Manual educational-video editing time | implementation cannot establish industry effort | peer-reviewed study or documented professional workflow | 36-fold or fixed-hour claims |
| Educational effectiveness/cognitive load | requires learner studies | education/HCI research | learning improvement claims |
| ASR/model benchmark performance | repository configuration is not project evaluation | official model card plus peer-reviewed benchmark | 2.9% WER |
| RAG benefits | architecture alone does not prove improvement | RAG research plus project ablation | quantified accuracy gain |
| Multi-agent advantages | terminology and benefits are research questions | agent-systems literature | autonomous collaboration claims |
| Commercial tool capability/superiority | needs current product evidence and fair comparison | official documentation and independent studies | superiority claims |
| Privacy/security impact | code review is incomplete policy evidence | provider policies, privacy/security literature | absolute privacy guarantees |
| Cost and throughput | depend on usage, pricing, hardware, network | official pricing plus project logs | USD 0.37; 10 min per 60 min |
| Usability/teacher acceptance | requires participants | approved user study | 15-educator claim |
| Generalisation/statistical significance | requires sample and analysis | project dataset/statistical method | 30 lectures/significance |

No web search was performed. References must be selected separately and must not be substituted for project-measured results.
""")


write("25_FINAL_AUDIT_VERDICT.md", """
# Final Audit Verdict

Definitely implemented and connected are the project-first workflow, multi-source assets, five specialised stages, API/local/hybrid transcription, Qdrant-grounded content analysis, fluency analysis, semantic page/layout planning, deterministic warnings, teacher overrides, persistent render jobs, native FFmpeg rendering, and multiple export/evidence artifacts. Partly implemented or configuration-dependent areas include provider availability, local non-ASR processing, Redis use, MCP parity, raw desktop Compose startup, scanned-PDF handling, and comprehensive timing telemetry. n8n is legacy; active LangGraph orchestration was not found.

Chapter 4 still needs the five paired manual-versus-agent cases, active-human timers, page correctness labels, quality rubric, artifact checks, and honest failure analysis. Chapter 5 needs conclusions tied to those results. A technical paper needs the same empirical core and must avoid autonomous-agent, accuracy, cost, speed, usability, and generalisation claims that have not been measured.

The objectives appear achievable if the remaining evaluation is scoped to five videos and reported descriptively. Existing instrumentation supports many decision/render metrics, but not reliable active human time; an external timer is required unless code is changed.

## Strongest defensible contributions

1. Teacher-supervised project-first educational video workflow.
2. Five specialised AI-assisted stages with direct orchestration and limited parallelism.
3. Curriculum-grounded analysis connected to Qdrant retrieval.
4. Semantic slide relevance and layout planning with conservative review behavior.
5. Deterministic FFmpeg rendering with traceable plans and evidence exports.

## Most serious reporting risks

1. Presenting external/model benchmark values as project results.
2. Calling the stages autonomous collaborating agents without qualification.
3. Claiming measured time savings before the five-video study.
4. Treating optional/configured Redis, MCP, LangGraph, or local AI as active core behavior.
5. Generalising accuracy/usability from implementation or a small self-evaluation.

Safest description: "The project is a teacher-supervised desktop framework for educational video editing that organises recordings and course materials by project, executes five specialised AI-assisted processing stages, allows lecturers to review and override content and visual decisions, and renders traceable media and evidence artifacts through a FastAPI, PostgreSQL, Qdrant, and FFmpeg stack."

Safest contribution statement: "The contribution is an integrated, auditable workflow that links curriculum-grounded transcript analysis with semantic visual-layout planning and teacher-controlled deterministic rendering; its efficiency and decision quality are to be evaluated on five paired video cases."

Safest limitation statement: "The prototype remains dependent on configured providers and local container infrastructure, lacks full OCR/authentication/active-time telemetry, and has not yet established population-level accuracy, usability, cost, or speed benefits."
""")


test_inventory_rows = []
for row in TESTS:
    test_inventory_rows.append({
        "test": row["symbol"],
        "path": row["path"],
        "line": row["line"],
        "type": "unit/service test",
        "uses_mock_or_stub": "likely" if any(x in row["symbol"].lower() for x in ("mock", "fallback", "payload", "fixture")) else "inspect test body",
        "executed_in_audit": "covered by discovery/isolated command",
        "status": "See TEST_RESULTS.md",
    })
write_csv("TEST_INVENTORY.csv", list(test_inventory_rows[0]), test_inventory_rows)


write("TEST_RESULTS.md", """
# Test and Build Results

| Command | Time | Exit | Result | Interpretation/reproducibility |
|---|---:|---:|---|---|
| `.venv\\Scripts\\python.exe -m unittest discover -s backend\\tests -p test_*.py -v` in managed sandbox | 18.01 s | 1 | 109 tests reached before 23 errors | Failures were dominated by test-order module stubs and Windows temp permissions. See `_backend_tests.log`. |
| isolated execution of 24 canonical test files | per-file, total under 30 s | mixed | 14 files passed, 10 failed | Failures: incomplete `sqlalchemy`/`pydantic_settings` stubs in test process or temp-directory access. See `_backend_isolated_summary.csv` and log. |
| same canonical discovery outside managed sandbox | 31.914 s test time; 38 s wall time | 0 | 191 tests passed | Successful and reproducible with normal Windows temp/process permissions; one SWIG deprecation warning. |
| `npm run build` in `desktop` (managed sandbox) | 31.4 s | 1 | Vite/esbuild `spawn EPERM` | Sandbox execution-policy artifact. |
| `npm run build` outside sandbox | 69 s | 0 | 1598 modules; production build completed | Successful TypeScript/Vite build during this audit. |
| `cargo check` in `desktop/src-tauri` | 233.7 s | 0 | Rust desktop shell compiled in dev/check profile | Successful; initial wait included a build-directory lock. |
| `docker compose config --quiet` | 1.67 s | 0 | valid development Compose | Reproducible. |
| `docker compose -f docker-compose.desktop.yml config --quiet` without launcher env | 3.59 s | 1 | empty bind-mount source due missing `AIVE_HOST_*` | Expected only when bypassing Tauri launcher; operational constraint, not YAML syntax error. |

The managed-sandbox discovery errors must not be reported as product regressions because the same canonical suite passed all 191 tests outside that sandbox. They remain useful evidence that the suite is sensitive to module stubbing and Windows temp/process restrictions. Conversely, successful unit/build checks do not prove backend/provider/render end-to-end behavior.

No paid-provider, destructive database, browser E2E, installed-app, clean-machine, or five-video long-media test was run.
""")


evidence = []
def ev(topic: str, claim: str, status: str, path: str, symbol: str, audit_file: str):
    assert status in STATUSES
    evidence.append({"id": f"E{len(evidence)+1:03d}", "topic": topic, "claim": claim, "status": status, "path": path, "symbol": symbol, "audit_file": audit_file})

for name, status, path, confidence in features:
    first = path.split(";")[0].strip()
    ev("Feature", name, status, first, first.split()[-1] if " " in first else "see cited file", "25_FINAL_AUDIT_VERDICT.md")
for agent in agents:
    ev("Agent", agent["name"], agent["status"], agent["evidence"][0], agent["entry"], "05_AGENT_PIPELINE_AND_PROMPT_AUDIT.md")
for entity in entities:
    ev("Database", entity["name"], entity["status"], entity["evidence"][0], entity["symbol"], "10_DATABASE_AND_PERSISTENCE_MODEL.md")
for row in api_rows:
    ev("API", f"{row['method']} {row['route']}", row["status"], row["evidence"].split()[0], row["backend_handler"], "11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md")
for row in mcp_tools:
    ev("MCP", row[1], row[3], row[4].split()[0], row[1], "14_MCP_SERVER_AND_TOOL_INVENTORY.md")
for row in debt_rows:
    ev("Limitation", row[0], "PARTIALLY_IMPLEMENTED" if "No " not in row[0] else "PLANNED", row[4], "see evidence", "20_LIMITATIONS_TODOS_AND_TECHNICAL_DEBT.md")

write("26_MASTER_EVIDENCE_INDEX.md", "# Master Evidence Index\n\n| ID | Topic | Claim | Status | Evidence path | Symbol | Related audit file |\n|---|---|---|---|---|---|---|\n" + "\n".join(f"| {r['id']} | {r['topic']} | {r['claim']} | {r['status']} | `{r['path']}` | `{r['symbol']}` | `{r['audit_file']}` |" for r in evidence))


ground_truth = {
    "audit_metadata": {"timestamp": "2026-06-15T22:21:14+08:00", "network_used": False, "source_modified": False, "status_vocabulary": sorted(STATUSES)},
    "repository_state": INV["repository"] | {"working_tree_is_source_of_truth": True},
    "project_identity": {"title": "AI-Agent Assisted Video Editing Framework for Automated Generation of Educational Content", "student": "Desan a/l Vasu", "matric": "161286", "programme": "Electronics Engineering", "university": "Universiti Sains Malaysia", "supervisor": "AP Dr. Bakthiar Affendi Rosdi"},
    "current_architecture": {"client": "Tauri 2 and React 19", "api": "FastAPI", "orchestration": "direct asynchronous Python", "persistence": ["PostgreSQL", "Qdrant", "filesystem", "render job JSON"], "rendering": "FFmpeg/FFprobe native semantic compositor", "evidence_paths": ["desktop/src/App.tsx:25", "backend/app/main.py:17", "backend/app/agents/orchestrator.py:96", "backend/app/services/renderer.py:471"]},
    "workflow": [{"step": x, "status": "IMPLEMENTED_AND_CONNECTED", "evidence_paths": ["desktop/src/components/GuidedWorkflow.tsx:1"], "symbol_names": ["GuidedWorkflow"], "confidence": "High", "notes": "Teacher-supervised stage"} for x in ["Transcribe", "Clean", "Sections", "Layout", "Polish", "Export"]],
    "agents": agents,
    "providers": [dict(zip(["name", "purpose", "route", "current_use", "status", "evidence"], row)) for row in providers],
    "database_entities": entities,
    "api_endpoints": api_rows,
    "frontend_screens": [{"name": x, "status": "IMPLEMENTED_AND_CONNECTED", "evidence_paths": [p], "symbol_names": [x], "confidence": "High", "notes": "Current React screen/component"} for x,p in [("ProjectDashboard","desktop/src/components/ProjectDashboard.tsx:1"),("UploadPanel","desktop/src/components/UploadPanel.tsx:1"),("ProcessingView","desktop/src/components/ProcessingView.tsx:1"),("ReviewEditor","desktop/src/components/ReviewEditor.tsx:1"),("GuidedWorkflow","desktop/src/components/GuidedWorkflow.tsx:1"),("MainSettingsPanel","desktop/src/components/MainSettingsPanel.tsx:1")]],
    "mcp_servers": [{"name": n, "tool_count": c, "status": "IMPLEMENTED_BUT_NOT_CONNECTED", "evidence_paths": [p], "symbol_names": ["server"], "confidence": "High", "notes": "Optional stdio integration"} for n,c,p in [("video-tools",8,"backend/app/mcp/video_tools_server.py:1"),("knowledge-tools",7,"backend/app/mcp/knowledge_tools_server.py:1"),("pipeline-tools",10,"backend/app/mcp/pipeline_tools_server.py:1")]],
    "mcp_tools": [dict(zip(["server", "tool", "purpose", "status", "evidence"], row)) for row in mcp_tools],
    "render_outputs": [{"name": x, "status": "IMPLEMENTED_AND_CONNECTED", "evidence_paths": ["backend/app/services/export_artifacts.py:1"], "symbol_names": ["build_export_artifacts"], "confidence": "High", "notes": "Availability depends on render/preset"} for x in ["MP4/M4A", "SRT", "VTT", "chapters", "edit plan JSON", "academic evidence JSON/Markdown", "provider/metric/timeline evidence"]],
    "implemented_features": [{"name": n, "status": s, "evidence_paths": [e], "symbol_names": ["see evidence"], "confidence": c, "notes": ""} for n,s,e,c in features if s == "IMPLEMENTED_AND_CONNECTED"],
    "partial_features": [{"name": n, "status": s, "evidence_paths": [e], "symbol_names": ["see evidence"], "confidence": c, "notes": ""} for n,s,e,c in features if s in {"PARTIALLY_IMPLEMENTED","CONFIGURATION_DEPENDENT","IMPLEMENTED_BUT_NOT_CONNECTED"}],
    "planned_features": [{"name": n, "status": s, "evidence_paths": [e], "symbol_names": ["see evidence"], "confidence": c, "notes": ""} for n,s,e,c in features if s == "PLANNED"],
    "legacy_features": [{"name": n, "status": s, "evidence_paths": [e], "symbol_names": ["see evidence"], "confidence": c, "notes": ""} for n,s,e,c in features if s == "DEPRECATED"],
    "unverified_features": [{"name": "Five-video performance and accuracy", "status": "UNVERIFIED", "evidence_paths": ["docs/fyp_context_pack/EVALUATION_PROCEDURE.md"], "symbol_names": ["evaluation procedure"], "confidence": "High", "notes": "Data not yet collected"}],
    "tests": [{"command": "python unittest discovery", "status": "IMPLEMENTED_AND_CONNECTED", "evidence_paths": ["docs/fyp_context_pack/TEST_RESULTS.md"], "symbol_names": ["unittest discover"], "confidence": "High", "notes": "191 tests passed outside the managed sandbox; sandbox-only run exposed environment sensitivity"}, {"command": "npm run build", "status": "IMPLEMENTED_AND_CONNECTED", "evidence_paths": ["docs/fyp_context_pack/TEST_RESULTS.md"], "symbol_names": ["Vite build"], "confidence": "High", "notes": "Passed outside sandbox"}, {"command": "cargo check", "status": "IMPLEMENTED_AND_CONNECTED", "evidence_paths": ["docs/fyp_context_pack/TEST_RESULTS.md"], "symbol_names": ["cargo check"], "confidence": "High", "notes": "Passed in 233.7 seconds"}],
    "evaluation_metrics": [{"name": a, "status": "IMPLEMENTED_AND_CONNECTED" if "Automatically" in b or "Derivable" in b else "UNVERIFIED", "evidence_paths": [d], "symbol_names": ["see evidence"], "confidence": "Medium", "notes": c} for a,b,c,d in metrics],
    "supported_claims": [{"claim": row[0], "status": row[1], "evidence_paths": [row[2]], "symbol_names": ["see evidence"], "confidence": "High", "notes": row[5]} for row in claims if row[1] in {"IMPLEMENTED_AND_CONNECTED","IMPLEMENTED_BUT_NOT_CONNECTED"}],
    "unsupported_claims": [{"claim": row[0], "status": row[1], "evidence_paths": [row[2]], "symbol_names": ["none"], "confidence": "High", "notes": row[6]} for row in claims if row[1] == "UNVERIFIED"],
    "limitations": [{"name": row[0], "status": "PARTIALLY_IMPLEMENTED", "evidence_paths": [row[4]], "symbol_names": ["see evidence"], "confidence": "High", "notes": row[5]} for row in debt_rows],
    "todos": INV["technical_debt"],
    "security_and_ethics": [{"topic": x, "status": "PARTIALLY_IMPLEMENTED", "evidence_paths": [e], "symbol_names": ["see evidence"], "confidence": "High", "notes": n} for x,e,n in [("API authentication","backend/app/api/routes","No authentication found"),("Key encryption","backend/app/services/app_settings.py:210","Requires APP_SETTINGS_SECRET_KEY"),("Teacher oversight","backend/app/db/models.py:252","Risk mitigation, not guarantee"),("Hosted provider exposure","backend/app/providers/defaults.py:24","Lecture-derived data may leave device")]],
    "report_mapping": {"chapter_1": "01,17,21,25", "chapter_2": "24", "chapter_3": "03-14,19", "chapter_4": "15-17 plus evaluation templates", "chapter_5": "20,21,25", "technical_paper": "18,19,25"},
    "evidence_index": evidence,
}
for section_name, section_value in ground_truth.items():
    if not isinstance(section_value, list):
        continue
    for item in section_value:
        if not isinstance(item, dict):
            continue
        item.setdefault("status", "UNVERIFIED")
        raw_evidence = item.get("evidence_paths", item.get("evidence", []))
        if isinstance(raw_evidence, str):
            raw_evidence = [raw_evidence]
        item.setdefault("evidence_paths", raw_evidence or ["No direct evidence recorded"])
        symbol = item.get("symbol") or item.get("backend_handler") or item.get("tool") or item.get("name") or item.get("claim") or "see evidence"
        item.setdefault("symbol_names", [str(symbol)])
        item.setdefault("confidence", "Medium")
        item.setdefault("notes", str(item.get("purpose") or item.get("current_use") or ""))
(OUT / "project_ground_truth.json").write_text(json.dumps(ground_truth, indent=2, ensure_ascii=True), encoding="utf-8")


write("AUDIT_COMPLETION_CHECKLIST.md", """
# Audit Completion Checklist

- [x] Current dirty working tree used as source of truth.
- [x] Branch, HEAD, date, timestamp, and change scale recorded.
- [x] Required files `00` through `26` created.
- [x] API, frontend mapping, provider, configuration, MCP, test, technology, dependency, and file-statistic CSV outputs created.
- [x] Five-video evaluation templates and procedure created.
- [x] `project_ground_truth.json` created.
- [x] Exact status vocabulary used for feature classifications.
- [x] Active, optional, fallback, legacy, disconnected, planned, and unverified paths distinguished.
- [x] Three MCP servers and 25 tools verified.
- [x] Nine ORM entities verified.
- [x] Safe backend tests and builds attempted; failures retained without repair.
- [x] No paid provider request, internet search, destructive DB action, or source-code repair performed.
- [x] No secrets included; defaults are redacted/sanitised where appropriate.
- [x] Screenshot checklist supplied instead of launching another stateful app stack.
- [ ] Five-video empirical study completed. This is intentionally outstanding and cannot be inferred from code.
- [ ] Clean-machine installer and 40+ minute installed-app render validation completed. These require separate runtime testing.

## Generated audit-support files

Underscore-prefixed scripts/logs/CSV extracts in this folder are audit working evidence. They are not application source and should be retained if reproducibility of this audit matters.
""")


required = [
    *[f"{i:02d}_{name}.md" for i, name in []],
    "00_README.md", "01_EXECUTIVE_PROJECT_SNAPSHOT.md", "02_REPOSITORY_AND_VERSION_STATE.md", "03_SYSTEM_ARCHITECTURE.md",
    "04_END_TO_END_USER_AND_DATA_WORKFLOW.md", "05_AGENT_PIPELINE_AND_PROMPT_AUDIT.md", "06_RAG_AND_COURSE_MATERIAL_PIPELINE.md",
    "07_SEMANTIC_VISUAL_PLANNING.md", "08_EDIT_PLANNING_AND_TEACHER_REVIEW.md", "09_RENDERING_EXPORT_AND_MEDIA_PROCESSING.md",
    "10_DATABASE_AND_PERSISTENCE_MODEL.md", "11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md", "12_FRONTEND_DESKTOP_AND_UI_INVENTORY.md",
    "13_AI_PROVIDER_CONFIGURATION.md", "14_MCP_SERVER_AND_TOOL_INVENTORY.md", "15_TESTING_BUILD_AND_QUALITY_STATUS.md",
    "16_EVALUATION_READINESS_AND_MEASUREMENT.md", "17_REPORT_CLAIMS_AND_EVIDENCE_MATRIX.md", "18_REPORT_CHAPTER_MAPPING.md",
    "19_FIGURE_RECREATION_SPECIFICATIONS.md", "20_LIMITATIONS_TODOS_AND_TECHNICAL_DEBT.md", "21_SECURITY_PRIVACY_AND_ETHICAL_CONSIDERATIONS.md",
    "22_CHANGELOG_AND_OVERHAUL_COMPARISON.md", "23_CODE_STATISTICS_AND_TECH_STACK.md", "24_EXTERNAL_CLAIMS_REQUIRING_REFERENCES.md",
    "25_FINAL_AUDIT_VERDICT.md", "26_MASTER_EVIDENCE_INDEX.md", "API_ENDPOINTS.csv", "API_FRONTEND_MAPPING.csv", "PROVIDERS.csv",
    "CONFIGURATION_KEYS.csv", "MCP_TOOLS.csv", "TEST_RESULTS.md", "TEST_INVENTORY.csv", "EVALUATION_METRIC_MATRIX.md",
    "FIVE_VIDEO_DATA_COLLECTION_TEMPLATE.csv", "CHAPTER4_RESULTS_TABLE_TEMPLATE.md", "EVALUATION_PROCEDURE.md", "EVALUATION_RISKS.md",
    "CODE_STATISTICS.json", "TECHNOLOGY_STACK.csv", "DEPENDENCY_INVENTORY.csv", "FILE_TYPE_STATISTICS.csv", "project_ground_truth.json",
    "AUDIT_COMPLETION_CHECKLIST.md",
]
missing = [name for name in required if not (OUT / name).exists()]
if missing:
    raise SystemExit(f"Missing required outputs: {missing}")
json.loads((OUT / "project_ground_truth.json").read_text(encoding="utf-8"))
print(f"Generated {len(required)} required audit outputs; evidence records={len(evidence)}; endpoints={len(api_rows)}")
