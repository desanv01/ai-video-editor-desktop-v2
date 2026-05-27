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
    artifact_records,
    build_academic_evidence_artifact,
    build_evidence_markdown,
    create_artifact_bundle,
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

        markdown = build_evidence_markdown(evidence)
        self.assertIn("AI Video Editor Evidence Summary", markdown)
        self.assertIn("Teacher overrides: 1 of 2 segments", markdown)
        self.assertIn("Transcription accuracy proxy: 0.91", markdown)
        self.assertIn("Estimated cost: $0.00000", markdown)

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
