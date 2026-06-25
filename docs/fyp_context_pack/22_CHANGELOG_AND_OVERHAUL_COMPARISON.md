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
