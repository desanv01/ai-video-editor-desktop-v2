import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from services.evaluation_metrics import (  # noqa: E402
    EVALUATION_METRICS_SCHEMA_VERSION,
    build_evaluation_metrics,
)


def enum_value(value: str) -> SimpleNamespace:
    return SimpleNamespace(value=value)


class EvaluationMetricsTests(unittest.TestCase):
    def test_builds_phase10_metrics_from_existing_processing_data(self):
        started = datetime(2026, 5, 27, 8, 0, tzinfo=timezone.utc)
        video = SimpleNamespace(
            duration_seconds=120.0,
            created_at=started,
            updated_at=started + timedelta(seconds=80),
        )
        plan = SimpleNamespace(
            original_duration=120.0,
            estimated_duration=75.0,
            filler_words_removed=3,
            silence_removed_seconds=8.0,
            created_at=started + timedelta(seconds=50),
            updated_at=started + timedelta(seconds=90),
        )
        transcript = SimpleNamespace(
            full_text="Welcome today we remove um pauses and keep the core lecture.",
            word_count=10,
            asr_provider="whisper-cpp",
            words_json=[
                {"word": "Welcome", "start": 0.0, "end": 0.4},
                {"word": "today", "start": 0.5, "end": 0.9},
                {"word": "we", "start": 1.0, "end": 1.1},
            ],
        )
        segments = [
            SimpleNamespace(
                start_time=0.0,
                end_time=30.0,
                duration=30.0,
                text="Welcome today we keep the core lecture",
                filler_count=0,
                pause_duration_total=0.5,
                importance_score=0.9,
                fluency_score=0.85,
                action_confidence=0.92,
                segment_type=enum_value("core_content"),
                action=enum_value("keep"),
                teacher_action=None,
                is_teacher_modified=False,
            ),
            SimpleNamespace(
                start_time=30.0,
                end_time=45.0,
                duration=15.0,
                text="um",
                filler_count=3,
                pause_duration_total=8.0,
                importance_score=0.1,
                fluency_score=0.2,
                action_confidence=0.88,
                segment_type=enum_value("filler"),
                action=enum_value("cut"),
                teacher_action=None,
                is_teacher_modified=False,
            ),
            SimpleNamespace(
                start_time=45.0,
                end_time=120.0,
                duration=75.0,
                text="This segment is useful but the teacher shortens it",
                filler_count=1,
                pause_duration_total=1.0,
                importance_score=0.75,
                fluency_score=0.72,
                action_confidence=0.7,
                segment_type=enum_value("example"),
                action=enum_value("keep"),
                teacher_action=enum_value("shorten"),
                is_teacher_modified=True,
            ),
        ]
        plan_payload = {
            "metadata": {"processing_mode": "hybrid"},
            "layout_cues": [
                {
                    "id": "layout-1",
                    "layout": "picture_in_picture",
                    "start_time": 0.0,
                    "end_time": 120.0,
                    "sources": {
                        "screen": {"enabled": True, "asset_id": "screen-1"},
                        "camera": {"enabled": True, "asset_id": "camera-1"},
                    },
                }
            ],
        }

        metrics = build_evaluation_metrics(
            video=video,
            plan=plan,
            segments=segments,
            transcript=transcript,
            plan_payload=plan_payload,
            actual_output_duration_seconds=74.0,
        )

        self.assertEqual(metrics["schema_version"], EVALUATION_METRICS_SCHEMA_VERSION)
        self.assertEqual(metrics["duration_reduction"]["reduction_percent"], 37.5)
        self.assertEqual(metrics["filler_dead_air_removal"]["removed_filler_words"], 3)
        self.assertEqual(metrics["filler_dead_air_removal"]["dead_air_removal_rate"], 0.8421)
        self.assertEqual(metrics["processing_time"]["total_seconds"], 90.0)
        self.assertEqual(metrics["cost"]["estimated_total_usd"], 0.0)
        self.assertEqual(metrics["cost"]["processing_mode"], "hybrid")
        self.assertEqual(metrics["layout_correctness"]["score"], 1.0)
        self.assertEqual(metrics["user_override_rate"]["teacher_overrides"], 1)
        self.assertGreater(metrics["segment_quality"]["score"], 0.7)
        self.assertGreater(metrics["transcription_accuracy_proxy"]["score"], 0.5)
        self.assertEqual(metrics["summary"]["teacher_override_rate"], 0.3333)

    def test_api_provider_cost_uses_duration_proxy(self):
        plan = SimpleNamespace(original_duration=300.0, estimated_duration=240.0)
        transcript = SimpleNamespace(asr_provider="openai-whisper", full_text="", word_count=0, words_json=[])

        metrics = build_evaluation_metrics(
            video=None,
            plan=plan,
            segments=[],
            transcript=transcript,
            plan_payload={},
        )

        self.assertEqual(metrics["cost"]["breakdown"]["transcription"]["cost_per_minute_usd"], 0.006)
        self.assertEqual(metrics["cost"]["estimated_total_usd"], 0.03)


if __name__ == "__main__":
    unittest.main()
