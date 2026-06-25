# Agent Pipeline and Prompt Audit

| Agent | Input | Output | Model/provider | Connected? | Persisted? | Evidence |
|---|---|---|---|---|---|---|
| Agent 1 - transcription | Video/audio file | Transcript and timed segments | ASR route: Voxtral/OpenAI Whisper/whisper.cpp | Yes | Yes | `backend/app/agents/transcription.py:1` |
| Agent 2 - content understanding | Transcript batches plus Qdrant retrieval | Importance/topic analysis | DeepSeek V4 Flash default, temperature 0.1 | Yes | Yes | `backend/app/agents/content_understanding.py:32` |
| Agent 3 - fluency | Timed transcript segments | Filler/pause/repetition issues | DeepSeek V4 Flash default, temperature 0.1 | Yes | Yes | `backend/app/agents/fluency.py:96` |
| Agent 4 - visual structure | Transcript, project visual assets, rendered pages | Slide relation, page and layout cues | Qwen vision/DeepSeek-assisted semantics plus local fallback | Yes | Yes | `backend/app/agents/visual_structure.py:53` |
| Agent 5 - edit planner | Outputs from Agents 2-4 | KEEP/CUT/SHORTEN/HIGHLIGHT plan | DeepSeek V4 Pro default, temperature 0.1 | Yes | Yes | `backend/app/agents/edit_planner.py:93` |

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
