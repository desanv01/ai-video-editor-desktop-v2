# Master Evidence Index

| ID | Topic | Claim | Status | Evidence path | Symbol | Related audit file |
|---|---|---|---|---|---|---|
| E001 | Feature | Project-first workflow | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/projects.py:650 create_project` | `create_project` | `25_FINAL_AUDIT_VERDICT.md` |
| E002 | Feature | Six lecturer stages | IMPLEMENTED_AND_CONNECTED | `desktop/src/components/GuidedWorkflow.tsx:1 GuidedWorkflow` | `GuidedWorkflow` | `25_FINAL_AUDIT_VERDICT.md` |
| E003 | Feature | Multiple videos per project | IMPLEMENTED_AND_CONNECTED | `backend/app/db/models.py:139 Project` | `Project` | `25_FINAL_AUDIT_VERDICT.md` |
| E004 | Feature | PDF/PPTX project assets | IMPLEMENTED_AND_CONNECTED | `backend/app/services/pdf_slides.py:1` | `see cited file` | `25_FINAL_AUDIT_VERDICT.md` |
| E005 | Feature | Five specialised agents | IMPLEMENTED_AND_CONNECTED | `backend/app/agents/orchestrator.py:96 run_full_pipeline` | `run_full_pipeline` | `25_FINAL_AUDIT_VERDICT.md` |
| E006 | Feature | API/local/hybrid ASR | IMPLEMENTED_AND_CONNECTED | `backend/app/services/transcription.py:1 TranscriptionService` | `TranscriptionService` | `25_FINAL_AUDIT_VERDICT.md` |
| E007 | Feature | RAG over Qdrant | IMPLEMENTED_AND_CONNECTED | `backend/app/rag/vector_store.py:168 ingest_course_material` | `ingest_course_material` | `25_FINAL_AUDIT_VERDICT.md` |
| E008 | Feature | Semantic slide relations | IMPLEMENTED_AND_CONNECTED | `backend/app/agents/visual_structure.py:468 semantic prompt` | `prompt` | `25_FINAL_AUDIT_VERDICT.md` |
| E009 | Feature | Teacher override | IMPLEMENTED_AND_CONNECTED | `backend/app/db/models.py:252 Segment` | `Segment` | `25_FINAL_AUDIT_VERDICT.md` |
| E010 | Feature | Direct async orchestration | IMPLEMENTED_AND_CONNECTED | `backend/app/agents/orchestrator.py:184 asyncio.gather` | `asyncio.gather` | `25_FINAL_AUDIT_VERDICT.md` |
| E011 | Feature | n8n runtime | DEPRECATED | `git status shows deleted n8n files` | `files` | `25_FINAL_AUDIT_VERDICT.md` |
| E012 | Feature | LangGraph runtime | IMPLEMENTED_BUT_NOT_CONNECTED | `backend/requirements.txt:21 only` | `only` | `25_FINAL_AUDIT_VERDICT.md` |
| E013 | Feature | Redis application use | CONFIGURATION_DEPENDENT | `docker-compose.yml:73` | `see cited file` | `25_FINAL_AUDIT_VERDICT.md` |
| E014 | Feature | MCP core workflow | IMPLEMENTED_BUT_NOT_CONNECTED | `backend/app/mcp/run_mcp.py:1` | `see cited file` | `25_FINAL_AUDIT_VERDICT.md` |
| E015 | Feature | Local non-ASR AI providers | PLANNED | `backend/app/providers/placeholders.py:1` | `see cited file` | `25_FINAL_AUDIT_VERDICT.md` |
| E016 | Feature | OCR for scanned PDFs | PLANNED | `backend/app/services/text_extraction.py:1 docstring mentions OCR but no OCR path exists` | `exists` | `25_FINAL_AUDIT_VERDICT.md` |
| E017 | Feature | Authentication/authorization | PLANNED | `API inventory shows no authentication dependency` | `dependency` | `25_FINAL_AUDIT_VERDICT.md` |
| E018 | Agent | Agent 1 - transcription | IMPLEMENTED_AND_CONNECTED | `backend/app/agents/transcription.py:1` | `run_transcription_agent` | `05_AGENT_PIPELINE_AND_PROMPT_AUDIT.md` |
| E019 | Agent | Agent 2 - content understanding | IMPLEMENTED_AND_CONNECTED | `backend/app/agents/content_understanding.py:32` | `run_content_understanding_agent` | `05_AGENT_PIPELINE_AND_PROMPT_AUDIT.md` |
| E020 | Agent | Agent 3 - fluency | IMPLEMENTED_AND_CONNECTED | `backend/app/agents/fluency.py:96` | `run_fluency_agent` | `05_AGENT_PIPELINE_AND_PROMPT_AUDIT.md` |
| E021 | Agent | Agent 4 - visual structure | IMPLEMENTED_AND_CONNECTED | `backend/app/agents/visual_structure.py:53` | `run_visual_structure_agent` | `05_AGENT_PIPELINE_AND_PROMPT_AUDIT.md` |
| E022 | Agent | Agent 5 - edit planner | IMPLEMENTED_AND_CONNECTED | `backend/app/agents/edit_planner.py:93` | `run_edit_planner_agent` | `05_AGENT_PIPELINE_AND_PROMPT_AUDIT.md` |
| E023 | Database | Project | IMPLEMENTED_AND_CONNECTED | `backend/app/db/models.py:139` | `Project` | `10_DATABASE_AND_PERSISTENCE_MODEL.md` |
| E024 | Database | ProjectAsset | IMPLEMENTED_AND_CONNECTED | `backend/app/db/models.py:159` | `ProjectAsset` | `10_DATABASE_AND_PERSISTENCE_MODEL.md` |
| E025 | Database | Video | IMPLEMENTED_AND_CONNECTED | `backend/app/db/models.py:191` | `Video` | `10_DATABASE_AND_PERSISTENCE_MODEL.md` |
| E026 | Database | Transcript | IMPLEMENTED_AND_CONNECTED | `backend/app/db/models.py:223` | `Transcript` | `10_DATABASE_AND_PERSISTENCE_MODEL.md` |
| E027 | Database | Segment | IMPLEMENTED_AND_CONNECTED | `backend/app/db/models.py:252` | `Segment` | `10_DATABASE_AND_PERSISTENCE_MODEL.md` |
| E028 | Database | Scene | IMPLEMENTED_AND_CONNECTED | `backend/app/db/models.py:303` | `Scene` | `10_DATABASE_AND_PERSISTENCE_MODEL.md` |
| E029 | Database | EditPlan | IMPLEMENTED_AND_CONNECTED | `backend/app/db/models.py:321` | `EditPlan` | `10_DATABASE_AND_PERSISTENCE_MODEL.md` |
| E030 | Database | CourseMaterial | IMPLEMENTED_AND_CONNECTED | `backend/app/db/models.py:353` | `CourseMaterial` | `10_DATABASE_AND_PERSISTENCE_MODEL.md` |
| E031 | Database | AppAISettings | IMPLEMENTED_AND_CONNECTED | `backend/app/db/models.py:368` | `AppAISettings` | `10_DATABASE_AND_PERSISTENCE_MODEL.md` |
| E032 | API | POST /debug/transcribe | CONFIGURATION_DEPENDENT | `backend/app/api/routes/debug.py:24` | `debug_transcribe` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E033 | API | POST /debug/extract-audio | CONFIGURATION_DEPENDENT | `backend/app/api/routes/debug.py:149` | `debug_extract_audio` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E034 | API | GET /debug/config | CONFIGURATION_DEPENDENT | `backend/app/api/routes/debug.py:213` | `debug_config` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E035 | API | GET /debug/rag/stats | CONFIGURATION_DEPENDENT | `backend/app/api/routes/debug.py:253` | `debug_rag_stats` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E036 | API | POST /debug/rag/search | CONFIGURATION_DEPENDENT | `backend/app/api/routes/debug.py:263` | `debug_rag_search` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E037 | API | POST /debug/rag/extract-text | CONFIGURATION_DEPENDENT | `backend/app/api/routes/debug.py:299` | `debug_extract_text` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E038 | API | POST /debug/rag/reset | CONFIGURATION_DEPENDENT | `backend/app/api/routes/debug.py:368` | `debug_rag_reset` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E039 | API | POST /debug/agents/run/{agent_name} | CONFIGURATION_DEPENDENT | `backend/app/api/routes/debug.py:382` | `debug_run_agent` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E040 | API | GET /debug/agents/segments/{video_id} | CONFIGURATION_DEPENDENT | `backend/app/api/routes/debug.py:447` | `debug_view_segments` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E041 | API | GET /debug/agents/scenes/{video_id} | CONFIGURATION_DEPENDENT | `backend/app/api/routes/debug.py:498` | `debug_view_scenes` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E042 | API | POST /debug/render/force-approve/{video_id} | CONFIGURATION_DEPENDENT | `backend/app/api/routes/debug.py:536` | `debug_force_approve` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E043 | API | POST /debug/render/run/{video_id} | CONFIGURATION_DEPENDENT | `backend/app/api/routes/debug.py:561` | `debug_render` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E044 | API | GET /debug/render/exports/{video_id} | CONFIGURATION_DEPENDENT | `backend/app/api/routes/debug.py:592` | `debug_view_exports` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E045 | API | GET /api/v1/settings/models/local-transcription | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/models.py:31` | `get_local_transcription_model_catalog` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E046 | API | POST /api/v1/settings/models/local-transcription/{model_id}/download | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/models.py:80` | `download_local_transcription_model` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E047 | API | GET /api/v1/settings/models/local-transcription/{model_id}/download | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/models.py:97` | `get_local_transcription_model_download` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E048 | API | DELETE /api/v1/settings/models/local-transcription/{model_id} | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/models.py:112` | `remove_local_transcription_model` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E049 | API | POST /api/v1/projects | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/projects.py:635` | `create_project` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E050 | API | GET /api/v1/projects | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/projects.py:669` | `list_projects` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E051 | API | GET /api/v1/projects/{project_id} | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/projects.py:676` | `get_project` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E052 | API | PATCH /api/v1/projects/{project_id} | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/projects.py:690` | `update_project` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E053 | API | DELETE /api/v1/projects/{project_id} | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/projects.py:719` | `delete_project` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E054 | API | GET /api/v1/projects/{project_id}/assets | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/projects.py:756` | `list_project_assets` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E055 | API | GET /api/v1/projects/{project_id}/source-sync | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/projects.py:829` | `get_project_source_sync_plan` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E056 | API | POST /api/v1/projects/{project_id}/source-sync/apply-metadata | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/projects.py:836` | `apply_project_source_sync_metadata` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E057 | API | POST /api/v1/projects/{project_id}/assets/upload | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/projects.py:870` | `upload_project_asset` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E058 | API | POST /api/v1/projects/{project_id}/videos/upload | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/projects.py:890` | `upload_project_primary_video` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E059 | API | POST /api/v1/projects/{project_id}/imports/native/primary/init | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/projects.py:1007` | `init_native_project_primary_import` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E060 | API | POST /api/v1/projects/{project_id}/imports/browser/primary/init | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/projects.py:1066` | `init_browser_project_primary_import` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E061 | API | POST /api/v1/projects/{project_id}/imports/native/primary/{token}/finalize | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/projects.py:1125` | `finalize_native_project_primary_import` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E062 | API | POST /api/v1/projects/{project_id}/imports/native/primary/{token}/cancel | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/projects.py:1161` | `cancel_native_project_primary_import` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E063 | API | GET /api/v1/projects/{project_id}/imports/browser/primary/{token} | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/projects.py:1191` | `get_browser_project_primary_import_status` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E064 | API | PUT /api/v1/projects/{project_id}/imports/browser/primary/{token}/chunk | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/projects.py:1216` | `append_browser_project_primary_import_chunk` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E065 | API | POST /api/v1/projects/{project_id}/imports/browser/primary/{token}/finalize | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/projects.py:1269` | `finalize_browser_project_primary_import` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E066 | API | POST /api/v1/projects/{project_id}/imports/browser/primary/{token}/cancel | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/projects.py:1305` | `cancel_browser_project_primary_import` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E067 | API | GET /api/v1/projects/{project_id}/imports/native/orphans | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/projects.py:1335` | `list_native_project_import_orphans` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E068 | API | POST /api/v1/projects/{project_id}/assets/video | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/projects.py:1360` | `upload_project_video_asset` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E069 | API | POST /api/v1/projects/{project_id}/assets/screen | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/projects.py:1372` | `upload_project_screen_asset` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E070 | API | POST /api/v1/projects/{project_id}/assets/camera | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/projects.py:1383` | `upload_project_camera_asset` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E071 | API | POST /api/v1/projects/{project_id}/assets/webcam | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/projects.py:1394` | `upload_project_webcam_asset` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E072 | API | POST /api/v1/projects/{project_id}/assets/phone-camera | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/projects.py:1405` | `upload_project_phone_camera_asset` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E073 | API | POST /api/v1/projects/{project_id}/assets/audio | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/projects.py:1416` | `upload_project_audio_asset` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E074 | API | POST /api/v1/projects/{project_id}/assets/slides | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/projects.py:1428` | `upload_project_slide_asset` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E075 | API | POST /api/v1/projects/{project_id}/assets/notes | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/projects.py:1439` | `upload_project_notes_asset` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E076 | API | POST /api/v1/projects/{project_id}/assets/materials | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/projects.py:1450` | `upload_project_supporting_material_asset` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E077 | API | GET /api/v1/projects/{project_id}/assets/{asset_id} | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/projects.py:1461` | `get_project_asset` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E078 | API | PUT /api/v1/projects/{project_id}/assets/{asset_id}/sync | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/projects.py:1474` | `update_project_asset_sync_offset` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E079 | API | PATCH /api/v1/projects/{project_id}/assets/{asset_id}/metadata | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/projects.py:1524` | `update_project_asset_metadata` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E080 | API | GET /api/v1/projects/{project_id}/assets/{asset_id}/download | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/projects.py:1557` | `download_project_asset` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E081 | API | DELETE /api/v1/projects/{project_id}/assets/{asset_id} | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/projects.py:1577` | `delete_project_asset` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E082 | API | POST /api/v1/videos/upload | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:129` | `upload_video` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E083 | API | POST /api/v1/videos/{video_id}/process | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:273` | `start_video_processing` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E084 | API | GET /api/v1/videos | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:323` | `list_videos` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E085 | API | GET /api/v1/videos/{video_id} | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:332` | `get_video` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E086 | API | GET /api/v1/videos/{video_id}/status | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:353` | `get_processing_status` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E087 | API | GET /api/v1/videos/{video_id}/transcript/timeline | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:414` | `get_transcript_timeline` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E088 | API | GET /api/v1/videos/{video_id}/transcript/cuts | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:440` | `get_transcript_cut_decisions` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E089 | API | POST /api/v1/videos/{video_id}/transcript/cuts | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:454` | `create_transcript_cut` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E090 | API | DELETE /api/v1/videos/{video_id}/transcript/cuts/{decision_id} | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:513` | `delete_transcript_cut` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E091 | API | PUT /api/v1/videos/{video_id}/transcript/cuts/{decision_id}/trim | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:538` | `update_transcript_cut_trim_settings` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E092 | API | POST /api/v1/videos/{video_id}/transcript/cuts/{decision_id}/restore-word | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:577` | `restore_transcript_cut_word` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E093 | API | GET /api/v1/videos/{video_id}/edit-decision-sync | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:627` | `get_edit_decision_sync` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E094 | API | GET /api/v1/videos/{video_id}/clean/analyze | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:654` | `analyze_clean_tools` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E095 | API | POST /api/v1/videos/{video_id}/clean/apply | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:695` | `apply_clean_tools` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E096 | API | GET /api/v1/videos/{video_id}/segments | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:753` | `get_segments` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E097 | API | PUT /api/v1/videos/{video_id}/segments/{segment_id} | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:764` | `update_segment` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E098 | API | PUT /api/v1/videos/{video_id}/segments/bulk | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:787` | `bulk_update_segments` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E099 | API | GET /api/v1/videos/{video_id}/plan | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:811` | `get_edit_plan` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E100 | API | GET /api/v1/videos/{video_id}/render-plan | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:823` | `get_semantic_render_plan` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E101 | API | POST /api/v1/videos/{video_id}/render-plan/regenerate | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:839` | `regenerate_semantic_render_plan` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E102 | API | GET /api/v1/videos/{video_id}/render-plan/slides/{slide_id} | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:855` | `get_semantic_render_slide` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E103 | API | PUT /api/v1/videos/{video_id}/plan/captions | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:872` | `update_plan_captions` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E104 | API | PUT /api/v1/videos/{video_id}/plan/layout-cues | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:895` | `update_plan_layout_cues` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E105 | API | PUT /api/v1/videos/{video_id}/plan/slide-cues | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:929` | `update_plan_slide_cues` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E106 | API | PUT /api/v1/videos/{video_id}/plan/editorial-blocks | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:961` | `update_plan_editorial_blocks` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E107 | API | POST /api/v1/videos/{video_id}/plan/layout-cues/auto | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:993` | `auto_generate_plan_layout_cues` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E108 | API | PUT /api/v1/videos/{video_id}/plan/annotations | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:1060` | `update_plan_annotations` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E109 | API | PUT /api/v1/videos/{video_id}/plan/educational-overlays | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:1083` | `update_plan_educational_overlays` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E110 | API | PUT /api/v1/videos/{video_id}/plan/end-cards | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:1106` | `update_plan_end_cards` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E111 | API | GET /api/v1/export/presets | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:1129` | `get_export_presets` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E112 | API | POST /api/v1/videos/{video_id}/plan/approve | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:1135` | `approve_edit_plan` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E113 | API | POST /api/v1/videos/{video_id}/render/cancel | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:1206` | `cancel_render` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E114 | API | POST /api/v1/videos/{video_id}/plan/revalidate | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:1262` | `revalidate_plan` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E115 | API | GET /api/v1/videos/{video_id}/chapters | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:1281` | `get_chapters` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E116 | API | POST /api/v1/videos/{video_id}/section-clips/export | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:1337` | `export_section_clips` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E117 | API | GET /api/v1/videos/{video_id}/section-clips/manifest | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:1400` | `download_section_clip_manifest` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E118 | API | GET /api/v1/videos/{video_id}/section-clips/{clip_index}/download | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:1411` | `download_section_clip` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E119 | API | GET /api/v1/videos/{video_id}/report | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:1501` | `get_quality_report` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E120 | API | GET /api/v1/videos/{video_id}/mode-comparison | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:1510` | `get_mode_comparison_report` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E121 | API | POST /api/v1/materials/upload | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:1520` | `upload_course_material` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E122 | API | GET /api/v1/materials | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:1593` | `list_course_materials` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E123 | API | DELETE /api/v1/materials/{material_id} | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:1602` | `delete_course_material` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E124 | API | GET /api/v1/settings | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:1625` | `get_settings` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E125 | API | GET /api/v1/settings/ai | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:1632` | `get_ai_settings` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E126 | API | PUT /api/v1/settings/ai | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:1639` | `update_settings` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E127 | API | PUT /api/v1/settings/domain-terms | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:1648` | `update_domain_terms` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E128 | API | GET /api/v1/videos/{video_id}/stream | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:1674` | `stream_original_video` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E129 | API | GET /api/v1/videos/{video_id}/download | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:1692` | `download_rendered_video` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E130 | API | GET /api/v1/videos/{video_id}/subtitles | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:1728` | `download_subtitles` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E131 | API | GET /api/v1/videos/{video_id}/subtitles/vtt | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:1744` | `download_subtitles_vtt` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E132 | API | GET /api/v1/videos/{video_id}/chapters/download | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:1760` | `download_chapters` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E133 | API | GET /api/v1/videos/{video_id}/plan/export | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:1776` | `download_plan_export` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E134 | API | GET /api/v1/videos/{video_id}/report/export | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:1792` | `download_quality_report_export` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E135 | API | GET /api/v1/videos/{video_id}/mode-comparison/export | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:1809` | `download_mode_comparison_export` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E136 | API | GET /api/v1/videos/{video_id}/mode-comparison/summary | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:1826` | `download_mode_comparison_summary` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E137 | API | GET /api/v1/videos/{video_id}/evidence/export | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:1843` | `download_academic_evidence_export` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E138 | API | GET /api/v1/videos/{video_id}/evidence/summary | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:1860` | `download_academic_evidence_summary` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E139 | API | GET /api/v1/videos/{video_id}/evidence/before-after | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:1877` | `download_before_after_comparison` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E140 | API | GET /api/v1/videos/{video_id}/evidence/timeline-decisions | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:1894` | `download_timeline_decisions` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E141 | API | GET /api/v1/videos/{video_id}/evidence/provider-mode | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:1911` | `download_provider_mode_trace` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E142 | API | GET /api/v1/videos/{video_id}/evidence/metrics-summary | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:1928` | `download_metrics_summary` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E143 | API | GET /api/v1/videos/{video_id}/evidence/bundle | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:1945` | `download_academic_evidence_bundle` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E144 | API | GET /api/v1/videos/{video_id}/exports | IMPLEMENTED_AND_CONNECTED | `backend/app/api/routes/videos.py:1964` | `list_exports` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E145 | API | GET / | IMPLEMENTED_AND_CONNECTED | `backend/app/main.py:98` | `root` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E146 | API | GET /health | IMPLEMENTED_AND_CONNECTED | `backend/app/main.py:108` | `health_check` | `11_API_ENDPOINT_AND_SCHEMA_INVENTORY.md` |
| E147 | MCP | get_video_metadata | IMPLEMENTED_BUT_NOT_CONNECTED | `backend/app/mcp/video_tools_server.py:1` | `get_video_metadata` | `14_MCP_SERVER_AND_TOOL_INVENTORY.md` |
| E148 | MCP | extract_audio | IMPLEMENTED_BUT_NOT_CONNECTED | `backend/app/mcp/video_tools_server.py:1` | `extract_audio` | `14_MCP_SERVER_AND_TOOL_INVENTORY.md` |
| E149 | MCP | trim_video | IMPLEMENTED_BUT_NOT_CONNECTED | `backend/app/mcp/video_tools_server.py:1` | `trim_video` | `14_MCP_SERVER_AND_TOOL_INVENTORY.md` |
| E150 | MCP | concatenate_videos | IMPLEMENTED_BUT_NOT_CONNECTED | `backend/app/mcp/video_tools_server.py:1` | `concatenate_videos` | `14_MCP_SERVER_AND_TOOL_INVENTORY.md` |
| E151 | MCP | detect_silence | IMPLEMENTED_BUT_NOT_CONNECTED | `backend/app/mcp/video_tools_server.py:1` | `detect_silence` | `14_MCP_SERVER_AND_TOOL_INVENTORY.md` |
| E152 | MCP | extract_frame | IMPLEMENTED_BUT_NOT_CONNECTED | `backend/app/mcp/video_tools_server.py:1` | `extract_frame` | `14_MCP_SERVER_AND_TOOL_INVENTORY.md` |
| E153 | MCP | generate_subtitles | IMPLEMENTED_BUT_NOT_CONNECTED | `backend/app/mcp/video_tools_server.py:1` | `generate_subtitles` | `14_MCP_SERVER_AND_TOOL_INVENTORY.md` |
| E154 | MCP | burn_subtitles | IMPLEMENTED_BUT_NOT_CONNECTED | `backend/app/mcp/video_tools_server.py:1` | `burn_subtitles` | `14_MCP_SERVER_AND_TOOL_INVENTORY.md` |
| E155 | MCP | search_knowledge | IMPLEMENTED_BUT_NOT_CONNECTED | `backend/app/mcp/knowledge_tools_server.py:1` | `search_knowledge` | `14_MCP_SERVER_AND_TOOL_INVENTORY.md` |
| E156 | MCP | ingest_course_material | IMPLEMENTED_BUT_NOT_CONNECTED | `backend/app/mcp/knowledge_tools_server.py:1` | `ingest_course_material` | `14_MCP_SERVER_AND_TOOL_INVENTORY.md` |
| E157 | MCP | ingest_transcript | IMPLEMENTED_BUT_NOT_CONNECTED | `backend/app/mcp/knowledge_tools_server.py:1` | `ingest_transcript` | `14_MCP_SERVER_AND_TOOL_INVENTORY.md` |
| E158 | MCP | list_materials | IMPLEMENTED_BUT_NOT_CONNECTED | `backend/app/mcp/knowledge_tools_server.py:1` | `list_materials` | `14_MCP_SERVER_AND_TOOL_INVENTORY.md` |
| E159 | MCP | delete_material | IMPLEMENTED_BUT_NOT_CONNECTED | `backend/app/mcp/knowledge_tools_server.py:1` | `delete_material` | `14_MCP_SERVER_AND_TOOL_INVENTORY.md` |
| E160 | MCP | extract_text | IMPLEMENTED_BUT_NOT_CONNECTED | `backend/app/mcp/knowledge_tools_server.py:1` | `extract_text` | `14_MCP_SERVER_AND_TOOL_INVENTORY.md` |
| E161 | MCP | get_collection_stats | IMPLEMENTED_BUT_NOT_CONNECTED | `backend/app/mcp/knowledge_tools_server.py:1` | `get_collection_stats` | `14_MCP_SERVER_AND_TOOL_INVENTORY.md` |
| E162 | MCP | list_videos | IMPLEMENTED_BUT_NOT_CONNECTED | `backend/app/mcp/pipeline_tools_server.py:1` | `list_videos` | `14_MCP_SERVER_AND_TOOL_INVENTORY.md` |
| E163 | MCP | get_video_status | IMPLEMENTED_BUT_NOT_CONNECTED | `backend/app/mcp/pipeline_tools_server.py:1` | `get_video_status` | `14_MCP_SERVER_AND_TOOL_INVENTORY.md` |
| E164 | MCP | run_agent | IMPLEMENTED_BUT_NOT_CONNECTED | `backend/app/mcp/pipeline_tools_server.py:1` | `run_agent` | `14_MCP_SERVER_AND_TOOL_INVENTORY.md` |
| E165 | MCP | get_segments | IMPLEMENTED_BUT_NOT_CONNECTED | `backend/app/mcp/pipeline_tools_server.py:1` | `get_segments` | `14_MCP_SERVER_AND_TOOL_INVENTORY.md` |
| E166 | MCP | get_edit_plan | IMPLEMENTED_BUT_NOT_CONNECTED | `backend/app/mcp/pipeline_tools_server.py:1` | `get_edit_plan` | `14_MCP_SERVER_AND_TOOL_INVENTORY.md` |
| E167 | MCP | update_segment | IMPLEMENTED_BUT_NOT_CONNECTED | `backend/app/mcp/pipeline_tools_server.py:1` | `update_segment` | `14_MCP_SERVER_AND_TOOL_INVENTORY.md` |
| E168 | MCP | approve_edit_plan | PARTIALLY_IMPLEMENTED | `backend/app/mcp/pipeline_tools_server.py:1` | `approve_edit_plan` | `14_MCP_SERVER_AND_TOOL_INVENTORY.md` |
| E169 | MCP | revalidate_plan | IMPLEMENTED_BUT_NOT_CONNECTED | `backend/app/mcp/pipeline_tools_server.py:1` | `revalidate_plan` | `14_MCP_SERVER_AND_TOOL_INVENTORY.md` |
| E170 | MCP | get_quality_report | IMPLEMENTED_BUT_NOT_CONNECTED | `backend/app/mcp/pipeline_tools_server.py:1` | `get_quality_report` | `14_MCP_SERVER_AND_TOOL_INVENTORY.md` |
| E171 | MCP | get_chapters | IMPLEMENTED_BUT_NOT_CONNECTED | `backend/app/mcp/pipeline_tools_server.py:1` | `get_chapters` | `14_MCP_SERVER_AND_TOOL_INVENTORY.md` |
| E172 | Limitation | No authentication/authorization | PLANNED | `API routes have no auth dependency` | `see evidence` | `20_LIMITATIONS_TODOS_AND_TECHNICAL_DEBT.md` |
| E173 | Limitation | Scanned PDF OCR absent | PARTIALLY_IMPLEMENTED | `backend/app/services/text_extraction.py` | `see evidence` | `20_LIMITATIONS_TODOS_AND_TECHNICAL_DEBT.md` |
| E174 | Limitation | Redis configured but no consumer found | PARTIALLY_IMPLEMENTED | `docker-compose.yml:73-79` | `see evidence` | `20_LIMITATIONS_TODOS_AND_TECHNICAL_DEBT.md` |
| E175 | Limitation | LangGraph installed but unused | PARTIALLY_IMPLEMENTED | `backend/requirements.txt:21` | `see evidence` | `20_LIMITATIONS_TODOS_AND_TECHNICAL_DEBT.md` |
| E176 | Limitation | MCP disconnected from core UI | PARTIALLY_IMPLEMENTED | `backend/app/mcp/run_mcp.py` | `see evidence` | `20_LIMITATIONS_TODOS_AND_TECHNICAL_DEBT.md` |
| E177 | Limitation | Desktop Compose requires launcher variables | PARTIALLY_IMPLEMENTED | `docker-compose.desktop.yml` | `see evidence` | `20_LIMITATIONS_TODOS_AND_TECHNICAL_DEBT.md` |
| E178 | Limitation | Duplicate test trees | PARTIALLY_IMPLEMENTED | `backend/tests; backend/app/tests` | `see evidence` | `20_LIMITATIONS_TODOS_AND_TECHNICAL_DEBT.md` |
| E179 | Limitation | No frontend/E2E suite | PLANNED | `No frontend test configuration found` | `see evidence` | `20_LIMITATIONS_TODOS_AND_TECHNICAL_DEBT.md` |
| E180 | Limitation | No active-time telemetry | PLANNED | `No persisted active editing timer` | `see evidence` | `20_LIMITATIONS_TODOS_AND_TECHNICAL_DEBT.md` |
| E181 | Limitation | Hard-coded default ports differ | PARTIALLY_IMPLEMENTED | `desktop/src/lib/api.ts; desktop/src-tauri/src/lib.rs:233-245` | `see evidence` | `20_LIMITATIONS_TODOS_AND_TECHNICAL_DEBT.md` |
| E182 | Rendering | Multi-page slideshow generation now uses FFconcat single-stream assembly for large slide decks | IMPLEMENTED_AND_CONNECTED | `backend/app/services/ffmpeg.py:1621-1706` | `create_slideshow_clip` | `27_RENDER_FIX_UPDATE_2026-06-16.md` |
| E183 | Rendering | FFmpeg stderr preservation now keeps the actionable tail instead of the version banner | IMPLEMENTED_AND_CONNECTED | `backend/app/services/ffmpeg.py:24-28` | `_stderr_message` | `27_RENDER_FIX_UPDATE_2026-06-16.md` |
| E184 | Testing | Renderer regression tests cover multi-image FFconcat slideshow construction | IMPLEMENTED_AND_CONNECTED | `backend/tests/test_picture_in_picture_renderer.py:293-324` | `test_slideshow_multiple_images_use_single_concat_input` | `15_TESTING_BUILD_AND_QUALITY_STATUS.md` |
| E185 | Testing | Renderer regression tests cover actionable FFmpeg tail-error reporting | IMPLEMENTED_AND_CONNECTED | `backend/tests/test_picture_in_picture_renderer.py:327-334` | `test_ffmpeg_error_message_keeps_actionable_tail` | `15_TESTING_BUILD_AND_QUALITY_STATUS.md` |
