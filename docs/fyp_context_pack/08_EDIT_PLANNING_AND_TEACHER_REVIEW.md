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
