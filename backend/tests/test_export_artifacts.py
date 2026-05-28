import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from services.export_artifacts import (  # noqa: E402
    EXPORT_ARTIFACT_SCHEMA_VERSION,
    TIMELINE_DECISION_CSV_FIELDS,
    artifact_records,
    build_academic_evidence_artifact,
    build_before_after_comparison,
    build_evidence_markdown,
    build_generated_evidence_index,
    build_metrics_summary_artifact,
    build_provider_mode_trace,
    build_timeline_decision_rows,
    build_timeline_decisions_artifact,
    create_artifact_bundle,
    write_csv_artifact,
    write_json_artifact,
    write_text_artifact,
)


class ExportArtifactTests(unittest.TestCase):
    def test_builds_academic_evidence_with_metrics_and_decision_audit(self):
        video = SimpleNamespace(
            id="video-1",
            original_filename="lecture.mp4",
            duration_seconds=120.0,
            resolution="1920x1080",
            fps=30,
            status=SimpleNamespace(value="completed"),
        )
        plan = SimpleNamespace(id="plan-1")
        transcript = SimpleNamespace(asr_provider="whisper-cpp", language="en")
        segments = [
            SimpleNamespace(
                segment_index=0,
                start_time=0.0,
                end_time=30.0,
                topic_label="Intro",
                action=SimpleNamespace(value="keep"),
                action_confidence=0.91,
                action_reason="Core setup",
                teacher_action=None,
                teacher_note=None,
                is_teacher_modified=False,
            ),
            SimpleNamespace(
                segment_index=1,
                start_time=30.0,
                end_time=60.0,
                topic_label="Pause cleanup",
                action=SimpleNamespace(value="keep"),
                action_confidence=0.72,
                action_reason="Maybe useful",
                teacher_action=SimpleNamespace(value="cut"),
                teacher_note="Removed dead air",
                is_teacher_modified=True,
            ),
        ]
        plan_payload = {
            "schema_version": "phase6.edit-plan.v2",
            "metadata": {"source": "agent5_edit_planner", "created_by": "ai-video-editor"},
            "chapters": [{"formatted": "00:00", "label": "Intro"}],
            "sections": [],
            "polish_actions": [{"kind": "caption_policy", "export_behavior": "sidecar"}],
            "export_metadata": {"selected_preset": {"id": "youtube_1080p"}},
        }
        quality_report = {
            "original_duration_seconds": 120.0,
            "estimated_duration_seconds": 75.0,
            "actual_output_duration_seconds": 74.5,
            "time_saved_seconds": 45.0,
            "reduction_percent": 37.5,
            "transcript_edit_sync": {"transcript_cut_count": 2},
            "evaluation_metrics": {
                "summary": {
                    "transcription_accuracy_proxy_score": 0.91,
                    "processing_time_seconds": 83.5,
                    "estimated_cost_usd": 0.0,
                    "filler_removal_rate": 0.8,
                    "dead_air_removal_rate": 0.75,
                    "segment_quality_score": 0.86,
                    "layout_correctness_score": 1.0,
                }
            },
        }

        evidence = build_academic_evidence_artifact(
            video=video,
            plan=plan,
            segments=segments,
            transcript=transcript,
            plan_payload=plan_payload,
            quality_report=quality_report,
            artifact_manifest=[{"kind": "plan_json", "available": True}],
            render_metadata={"renderer_schema_version": "phase9.multitrack-renderer.v1"},
        )

        self.assertEqual(evidence["schema_version"], EXPORT_ARTIFACT_SCHEMA_VERSION)
        self.assertEqual(evidence["provider_trace"]["transcription_provider"], "whisper-cpp")
        self.assertEqual(evidence["metrics_summary"]["teacher_overrides"], 1)
        self.assertEqual(evidence["metrics_summary"]["teacher_override_rate"], 0.5)
        self.assertEqual(evidence["metrics_summary"]["segment_quality_score"], 0.86)
        self.assertEqual(evidence["evaluation_metrics"]["summary"]["layout_correctness_score"], 1.0)
        self.assertEqual(evidence["decision_audit"][1]["final_action"], "cut")
        self.assertEqual(evidence["chapters"][0]["label"], "Intro")
        self.assertEqual(evidence["provider_trace"]["processing_mode"], "local")
        self.assertEqual(evidence["before_after_comparison"]["after"]["segments_cut"], 1)
        self.assertEqual(evidence["timeline_decisions"]["decision_count"], 2)
        self.assertEqual(evidence["thesis_metrics_summary"]["quality"]["segment_quality_score"], 0.86)

        markdown = build_evidence_markdown(evidence)
        self.assertIn("AI Video Editor Evidence Summary", markdown)
        self.assertIn("Processing mode used: local", markdown)
        self.assertIn("Teacher overrides: 1 of 2 segments", markdown)
        self.assertIn("Transcription accuracy proxy: 0.91", markdown)
        self.assertIn("Estimated cost: $0.00000", markdown)

    def test_builds_thesis_specific_artifacts(self):
        video = SimpleNamespace(
            id="video-1",
            original_filename="lecture.mp4",
            duration_seconds=100.0,
            resolution="1280x720",
            fps=30,
        )
        plan = SimpleNamespace(id="plan-1", original_duration=100.0, estimated_duration=65.0)
        transcript = SimpleNamespace(asr_provider="mistral", language="en")
        segments = [
            SimpleNamespace(
                id="segment-1",
                segment_index=0,
                start_time=0.0,
                end_time=40.0,
                duration=40.0,
                topic_label="Setup",
                summary="Course setup",
                action=SimpleNamespace(value="keep"),
                action_confidence=0.9,
                action_reason="Core concept",
                teacher_action=None,
                teacher_note=None,
            ),
            SimpleNamespace(
                id="segment-2",
                segment_index=1,
                start_time=40.0,
                end_time=100.0,
                duration=60.0,
                topic_label="Dead air",
                summary="Long pause",
                action=SimpleNamespace(value="cut"),
                action_confidence=0.8,
                action_reason="Dead air",
                teacher_action=SimpleNamespace(value="shorten"),
                teacher_note="Keep first example only",
            ),
        ]
        plan_payload = {
            "metadata": {"processing_mode": "hybrid", "source": "agent5_edit_planner"},
            "edit_decisions": [
                {
                    "id": "cut-1",
                    "kind": "transcript_cut",
                    "action": "cut",
                    "source": "manual_text_selection",
                    "start_time": 48.0,
                    "end_time": 53.0,
                    "duration": 5.0,
                    "text": "um let me restart",
                    "segment_indexes": [1],
                }
            ],
            "export_metadata": {"selected_preset": {"id": "lms_compatible"}},
        }
        quality_report = {
            "video_id": "video-1",
            "video_filename": "lecture.mp4",
            "original_duration_seconds": 100.0,
            "estimated_duration_seconds": 65.0,
            "time_saved_seconds": 35.0,
            "reduction_percent": 35.0,
            "teacher_modifications": 1,
            "teacher_overrides": 1,
            "teacher_override_rate": 0.5,
            "transcript_edit_sync": {"transcript_cut_count": 1, "transcript_cut_duration_seconds": 5.0},
            "evaluation_metrics": {
                "summary": {
                    "processing_time_seconds": 42.0,
                    "estimated_cost_usd": 0.006,
                    "segment_quality_score": 0.81,
                    "layout_correctness_score": 0.9,
                },
                "cost": {"processing_mode": "hybrid"},
            },
        }
        mode_comparison = {
            "current_mode": "hybrid",
            "comparison": {"recommended_mode": "local"},
            "stage_matrix": {"transcription": {"hybrid": {"provider_strategy": "local_first_api_fallback_asr"}}},
        }

        before_after = build_before_after_comparison(
            video=video,
            plan=plan,
            segments=segments,
            plan_payload=plan_payload,
            quality_report=quality_report,
        )
        timeline = build_timeline_decisions_artifact(
            segments=segments,
            plan_payload=plan_payload,
            quality_report=quality_report,
        )
        provider = build_provider_mode_trace(
            transcript=transcript,
            plan_payload=plan_payload,
            quality_report=quality_report,
            mode_comparison=mode_comparison,
        )
        metrics = build_metrics_summary_artifact(quality_report)
        rows = build_timeline_decision_rows(
            segments=segments,
            plan_payload=plan_payload,
            quality_report=quality_report,
        )

        self.assertEqual(before_after["before"]["duration_seconds"], 100.0)
        self.assertEqual(before_after["after"]["segments_shortened"], 1)
        self.assertEqual(before_after["after"]["transcript_cut_count"], 1)
        self.assertEqual(timeline["decision_count"], 3)
        self.assertEqual(rows[-1]["kind"], "transcript_cut")
        self.assertEqual(provider["processing_mode"], "hybrid")
        self.assertEqual(provider["mode_comparison_recommendation"], "local")
        self.assertEqual(metrics["processing"]["processing_mode"], "hybrid")

        with tempfile.TemporaryDirectory() as temp_dir:
            csv_path = Path(temp_dir) / "timeline.csv"
            write_csv_artifact(str(csv_path), rows, TIMELINE_DECISION_CSV_FIELDS)
            self.assertIn("transcript_cut", csv_path.read_text(encoding="utf-8"))

    def test_artifact_records_and_bundle_include_available_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            plan_path = root / "video_edit_plan.json"
            summary_path = root / "video_academic_evidence.md"
            missing_path = root / "video_subtitles.srt"
            write_json_artifact(str(plan_path), {"ok": True})
            write_text_artifact(str(summary_path), "# Summary\n")

            records = artifact_records(
                {
                    "plan_json": str(plan_path),
                    "academic_evidence_markdown": str(summary_path),
                    "subtitles_srt": str(missing_path),
                }
            )
            by_kind = {record["kind"]: record for record in records}

            self.assertTrue(by_kind["plan_json"]["available"])
            self.assertEqual(by_kind["plan_json"]["media_type"], "application/json")
            self.assertFalse(by_kind["subtitles_srt"]["available"])
            index = build_generated_evidence_index(records)
            self.assertEqual(index["total_files"], 3)
            self.assertEqual(index["available_files"], 2)

            bundle_path = root / "bundle.zip"
            bundle = create_artifact_bundle(str(bundle_path), records)

            self.assertTrue(bundle["available"])
            self.assertEqual(len(bundle["included_artifacts"]), 2)
            self.assertGreater(bundle["size_bytes"], 0)

            import zipfile

            with zipfile.ZipFile(bundle_path) as archive:
                self.assertEqual(
                    set(archive.namelist()),
                    {"video_edit_plan.json", "video_academic_evidence.md"},
                )
                payload = json.loads(archive.read("video_edit_plan.json"))
                self.assertEqual(payload["ok"], True)


if __name__ == "__main__":
    unittest.main()
