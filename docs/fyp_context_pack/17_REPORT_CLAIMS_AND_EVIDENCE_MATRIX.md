# Report Claims and Evidence Matrix

| Claim | Status | Code evidence | Runtime evidence needed | Evaluation evidence needed | Safe thesis wording | Unsafe wording |
|---|---|---|---|---|---|---|
| Project-first workflow | IMPLEMENTED_AND_CONNECTED | backend/app/api/routes/projects.py:650; desktop/src/components/ProjectDashboard.tsx:1 | Create/open/reopen smoke test | None for existence | The implementation uses projects as the main workspace. | The system is proven usable by all lecturers. |
| Five-agent pipeline | IMPLEMENTED_AND_CONNECTED | backend/app/agents/orchestrator.py:96-200 | Full five-stage run | Performance/quality study | Five specialised AI-assisted stages are orchestrated in Python. | Five autonomous agents collaborate and negotiate. |
| RAG | IMPLEMENTED_AND_CONNECTED | backend/app/rag/vector_store.py:168-463 | Live ingest/search | Measured effect requires ablation | Agent 2 can receive Qdrant-retrieved course context. | RAG improves accuracy by X%. |
| Semantic visual planning | IMPLEMENTED_AND_CONNECTED | backend/app/agents/visual_structure.py:468-481 | Five-video page review | Page correctness labels | The planner emits page/relation/layout cues. | Slide selection is accurate. |
| Teacher review | IMPLEMENTED_AND_CONNECTED | backend/app/db/models.py:252-300 | UI override smoke test | Override/time measurements | Teachers can override persisted recommendations. | Teacher-in-the-loop improves quality by X%. |
| Rendering/subtitles/chapters/evidence | IMPLEMENTED_AND_CONNECTED | backend/app/services/renderer.py:471; export_artifacts.py | Long-video playback verification | Five-case success table | The renderer can produce media and supporting artifacts. | Rendering is error-free for arbitrary lectures. |
| Three MCP servers/25 tools | IMPLEMENTED_BUT_NOT_CONNECTED | backend/app/mcp/*_server.py | External MCP client smoke test | None for count | An optional MCP integration exposes 25 tools. | MCP powers the normal application workflow. |
| Editing-time reduction | UNVERIFIED | No project result yet | Five paired runs | Manual vs assisted timing | The study will compare active editing time. | The system reduces editing time by 36-fold. |
| 2.9% WER | UNVERIFIED | No project measurement | Ground-truth transcript scoring | WER experiment | No project WER is currently claimed. | The project achieved 2.9% WER. |
| USD 0.37 per lecture | UNVERIFIED | No cost ledger | Billing/token capture | Cost experiment | Cost was not measured. | Cost is USD 0.37 per lecture. |
| 10 min per 60 min / 36x speed | UNVERIFIED | No five-video timing dataset | Timed runs | Paired timing | Processing speed remains to be measured. | A 60-minute lecture completes in 10 minutes. |
| 30 lectures / 15 educators / significance | UNVERIFIED | No such study artifacts | Human study records | Approved study | The present planned evaluation uses five videos. | Results are statistically significant across 30 lectures and 15 educators. |

External model benchmarks, comments, sample fixtures, and configuration defaults are not project-measured results. Calculated code counts may support architecture descriptions only. Genuine project results must come from retained logs/artifacts and the five-video dataset.

## Verification of the 30 supplied hypotheses

| # | Hypothesis | Verdict | Status | Supporting evidence | Contradictory/caveat evidence | Confidence | Report-writing implication |
|---:|---|---|---|---|---|---|---|
| 1 | Project-first workflow | Confirmed | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/projects.py:650` `create_project`; `desktop/src/components/ProjectDashboard.tsx:1` | Legacy single-video APIs still exist | High | Describe project as the workspace boundary |
| 2 | Six lecturer stages | Confirmed | IMPLEMENTED_AND_CONNECTED | `desktop/src/components/GuidedWorkflow.tsx:1` `GuidedWorkflow` | Stage labels are UI methodology, not separate autonomous services | High | Use Transcribe, Clean, Sections, Layout, Polish, Export |
| 3 | Multiple recordings per project | Confirmed | IMPLEMENTED_AND_CONNECTED | `backend/app/db/models.py:139-220` `Project`, `Video` | Source synchronization still needs valid media metadata | High | Claim one-to-many project/video support |
| 4 | PDF/PPTX linked to project | Confirmed | IMPLEMENTED_AND_CONNECTED | `backend/app/db/models.py:159-188` `ProjectAsset`; `pdf_slides.py`; `pptx_slides.py` | Scanned-PDF OCR is absent | High | Qualify by supported extraction quality |
| 5 | Five specialised agents | Confirmed | IMPLEMENTED_AND_CONNECTED | `backend/app/agents/orchestrator.py:96-200` | They are specialised stages, not negotiating autonomous agents | High | Use qualified multi-agent wording |
| 6 | Agent 1 API/local/hybrid ASR | Confirmed | IMPLEMENTED_AND_CONNECTED | `backend/app/services/transcription.py` `TranscriptionService` | Provider availability and local model files are configuration-dependent | High | Separate routing capability from runtime availability |
| 7 | whisper.cpp local route | Confirmed | CONFIGURATION_DEPENDENT | `backend/app/providers/whisper_cpp.py`; `providers/defaults.py:51-61` | Requires executable and model | High | Claim local ASR option, not turnkey availability |
| 8 | Agent 2 uses Qdrant RAG | Confirmed | IMPLEMENTED_AND_CONNECTED | `content_understanding.py:104-116`; `vector_store.py:422-463` | Retrieval quality not empirically evaluated | High | Claim connected retrieval, not quantified improvement |
| 9 | Agent 3 detects fluency issues | Confirmed | IMPLEMENTED_AND_CONNECTED | `backend/app/agents/fluency.py:96-300` | False-positive rate unmeasured | High | List detected issue classes without accuracy claims |
| 10 | Agent 4 emits related/unrelated/uncertain | Confirmed | IMPLEMENTED_AND_CONNECTED | `visual_structure.py:468-481,1033-1058` | Provider/local fallback may disagree | High | Use exact relation vocabulary |
| 11 | Agent 4 selects page and supported layouts | Confirmed | IMPLEMENTED_AND_CONNECTED | `visual_structure.py`; `semantic_render_plan.py`; `layout_model.py` | Full accuracy and media compatibility unverified | High | Describe selectable outputs, not correctness rate |
| 12 | Unrelated becomes lecturer-only | Confirmed | IMPLEMENTED_AND_CONNECTED | `editorial_plan.py:283-297`; `semantic_render_plan.py:427-442` | Teacher can override | High | Present as conservative default |
| 13 | Uncertain requires review/warning | Confirmed | IMPLEMENTED_AND_CONNECTED | `visual_structure.py:1033-1058` | Review completion is a user action | High | Describe explicit uncertainty handling |
| 14 | Agent 5 supports four actions | Confirmed | IMPLEMENTED_AND_CONNECTED | `backend/app/agents/edit_planner.py:93` | Final teacher action can differ | High | List KEEP/CUT/SHORTEN/HIGHLIGHT |
| 15 | Teacher decisions override agents | Confirmed | IMPLEMENTED_AND_CONNECTED | `db/models.py:252-300`; `GuidedWorkflow.tsx:2606-2662` | No full version-history table | High | Claim persisted precedence, not comprehensive audit versioning |
| 16 | Deterministic warning checks | Confirmed | IMPLEMENTED_AND_CONNECTED | `edit_planner.py:412,488`; `editorial_plan.py` | Coverage is rule-limited | High | Distinguish validators from LLM reasoning |
| 17 | Direct async Python orchestration | Confirmed | IMPLEMENTED_AND_CONNECTED | `orchestrator.py:96-200`, including `asyncio.gather` | LangGraph dependency is installed but unused | High | Make direct orchestration the active architecture |
| 18 | n8n not required | Confirmed | DEPRECATED | Deleted `n8n/` files; no runtime imports | Historical docs may still mention it | High | Remove n8n from current runtime figures |
| 19 | PySceneDetect is fallback | Confirmed | IMPLEMENTED_AND_CONNECTED | `visual_structure.py:76-133,1532` | It may become the effective path when semantic planning fails | High | Draw it as dashed fallback |
| 20 | Tauri 2 and React 19 | Confirmed | IMPLEMENTED_AND_CONNECTED | `desktop/src-tauri/Cargo.toml`; `desktop/package.json` | Installed package/Rust patch versions can differ | High | State major versions |
| 21 | FastAPI backend | Confirmed | IMPLEMENTED_AND_CONNECTED | `backend/app/main.py:1-113` | None found | High | Safe implementation claim |
| 22 | PostgreSQL, Qdrant and Redis are used | Partially confirmed | PARTIALLY_IMPLEMENTED | PostgreSQL/Qdrant active; Redis in Compose/config | No active Redis client consumer found | High | Say Redis is provisioned, not evidenced as actively used |
| 23 | FFmpeg/FFprobe media processing | Confirmed | IMPLEMENTED_AND_CONNECTED | `backend/app/services/ffmpeg.py`; `renderer.py:471` | Binary/codec/hardware availability varies | High | Safe implementation claim with runtime dependency |
| 24 | Provider registry hosted/local | Confirmed | PARTIALLY_IMPLEMENTED | `backend/app/providers/defaults.py:24-107` | Local non-ASR adapters are placeholders | High | Separate registered capabilities from implemented adapters |
| 25 | Three MCP servers, about 25 tools | Confirmed exactly | IMPLEMENTED_BUT_NOT_CONNECTED | `backend/app/mcp/*_server.py`; `MCP_TOOLS.csv` | Not connected to normal UI/API workflow | High | Say optional 3-server/25-tool integration |
| 26 | Nine persisted entities | Confirmed | IMPLEMENTED_AND_CONNECTED | `backend/app/db/models.py:139-392` | Qdrant/files/job JSON add non-ORM persistence | High | Use the nine-entity ER model plus side stores |
| 27 | Renderer creates listed artifacts | Confirmed | IMPLEMENTED_AND_CONNECTED | `renderer.py`; `export_artifacts.py` | Exact artifacts depend on preset and successful render | High | Use "can produce" wording |
| 28 | Multiple outputs/intermediates stored/exportable | Confirmed | IMPLEMENTED_AND_CONNECTED | `export_artifacts.py`; export download UI | Retention/cleanup can vary | High | Describe traceable artifact bundle |
| 29 | Teacher review before rendering | Confirmed | IMPLEMENTED_AND_CONNECTED | `GuidedWorkflow.tsx:2052-2110`; plan update routes | API/debug paths can bypass UI in development | High | Describe normal lecturer workflow |
| 30 | Major pre/post-overhaul difference | Confirmed | DOCUMENTATION_ONLY | Git state/history plus new models, UI, renderer and deleted n8n files | Exact historical behavior is only partly recoverable from current tree | Medium | Explicitly retire old architecture diagrams and claims |
