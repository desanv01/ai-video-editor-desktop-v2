# Evaluation Metric Matrix

| Metric | Availability | Collection method | Evidence |
|---|---|---|---|
| Original video duration | Automatically recorded | Video duration/ffprobe | `backend/app/db/models.py:191-220` |
| Manual active editing time | Not currently measurable | Use external timer or add activity instrumentation | `No persisted manual-session timer found` |
| Agent processing time | Partly automatically recorded | Progress/timestamps/logs can derive stage elapsed time | `backend/app/services/progress.py` |
| Teacher active review/editing time | Not currently measurable | External timer or interaction telemetry required | `No active-time field found` |
| Total agent-assisted elapsed time | Derivable | Start/end timestamps plus external observation | `processing/render timestamps` |
| Recommendation count | Derivable | Count segments/cues/actions | `backend/app/db/models.py:252-350` |
| Teacher overrides | Automatically derivable | Count is_teacher_modified | `backend/app/services/evaluation_metrics.py` |
| Override rate | Automatically derivable | overrides/recommendations | `backend/app/services/evaluation_metrics.py` |
| Action distribution | Automatically derivable | Count final actions | `backend/app/services/export_artifacts.py` |
| Slide/page decisions | Derivable | Count slide cues | `backend/app/services/semantic_render_plan.py` |
| Correct/incorrect page selections | Manually recordable | Teacher ground-truth rating required | `No correctness label persisted` |
| Uncertain selections | Derivable | Count relation/review flags | `backend/app/agents/visual_structure.py:1033-1058` |
| Lecturer-only decisions | Derivable | Count full_camera_source | `backend/app/services/editorial_plan.py:283-297` |
| Content-preservation rating | Manually recordable | Human rubric required | `Not objectively stored` |
| Render success/failure | Automatically recorded | Render job state | `backend/app/services/render_jobs.py` |
| Subtitle/chapter/export consistency | Derivable plus manual verification | Artifact records and inspection | `backend/app/services/export_artifacts.py` |
| Provider/model | Automatically recorded/derivable | provider trace/settings | `backend/app/services/export_artifacts.py` |
| API cost | Not currently measurable | Provider billing/token prices required | `No cost ledger found` |
| Token usage | Partly/unverified | Depends on response metadata; no central ledger | `provider adapters` |
| Error/retry count | Partly recorded | Logs/status; no unified counter | `service-specific handlers` |
