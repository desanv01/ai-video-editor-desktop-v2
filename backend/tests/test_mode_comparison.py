import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from services.mode_comparison import (  # noqa: E402
    MODE_COMPARISON_SCHEMA_VERSION,
    build_mode_comparison_markdown,
    build_mode_comparison_report,
)


class ModeComparisonTests(unittest.TestCase):
    def test_builds_api_local_hybrid_stage_report(self):
        video = SimpleNamespace(
            id="video-1",
            project_id="project-1",
            duration_seconds=180.0,
        )
        plan = SimpleNamespace(
            original_duration=180.0,
            estimated_duration=120.0,
        )
        transcript = SimpleNamespace(asr_provider="whisper-cpp")
        segments = [
            SimpleNamespace(duration=60.0, start_time=0.0, end_time=60.0),
            SimpleNamespace(duration=60.0, start_time=60.0, end_time=120.0),
            SimpleNamespace(duration=60.0, start_time=120.0, end_time=180.0),
        ]
        settings_record = SimpleNamespace(
            preferred_processing_mode="hybrid",
            capabilities_json={
                "transcription": {
                    "api_provider_id": "mistral",
                    "local_provider_id": "whisper-cpp",
                    "hybrid_fallback_order": ["local", "api"],
                },
                "chat": {
                    "api_provider_id": "deepseek-chat",
                    "local_provider_id": "ollama",
                    "hybrid_fallback_order": ["api", "local"],
                },
            },
            api_keys_json={
                "mistral": {
                    "source": "encrypted_db",
                    "encrypted_value": "ciphertext",
                }
            },
            local_model_paths_json={
                "transcription": "models/ggml-small.bin",
                "chat": "models/local-chat.gguf",
            },
        )
        quality_report = {
            "original_duration_seconds": 180.0,
            "estimated_duration_seconds": 120.0,
            "evaluation_metrics": {
                "summary": {
                    "transcription_accuracy_proxy_score": 0.82,
                    "segment_quality_score": 0.78,
                    "layout_correctness_score": 0.9,
                    "teacher_override_rate": 0.1,
                    "filler_removal_rate": 0.7,
                    "dead_air_removal_rate": 0.6,
                },
                "duration_reduction": {"reduction_percent": 33.33},
                "cost": {"processing_mode": "hybrid"},
            },
        }

        report = build_mode_comparison_report(
            video=video,
            plan=plan,
            segments=segments,
            transcript=transcript,
            plan_payload={"metadata": {"processing_mode": "hybrid"}},
            quality_report=quality_report,
            settings_record=settings_record,
            render_job={"elapsed_seconds": 44.0},
        )

        self.assertEqual(report["schema_version"], MODE_COMPARISON_SCHEMA_VERSION)
        self.assertEqual(report["current_mode"], "hybrid")
        self.assertEqual(len(report["modes"]), 3)
        self.assertEqual({mode["mode"] for mode in report["modes"]}, {"api", "local", "hybrid"})
        for mode in report["modes"]:
            self.assertEqual(len(mode["stages"]), 4)
            self.assertEqual(mode["stages"][-1]["stage"], "rendering")
            self.assertEqual(mode["stages"][-1]["mode"], "local")
            self.assertEqual(mode["stages"][-1]["estimated_runtime_seconds"], 44.0)

        mode_costs = {
            mode["mode"]: mode["summary"]["estimated_total_cost_usd"]
            for mode in report["modes"]
        }
        self.assertGreater(mode_costs["api"], mode_costs["hybrid"])
        self.assertEqual(mode_costs["local"], 0.0)
        self.assertEqual(report["comparison"]["lowest_cost_mode"], "local")
        self.assertIn(report["comparison"]["recommended_mode"], {"api", "local", "hybrid"})
        self.assertEqual(report["workflow"][-1]["output"], "mode_comparison_json_and_markdown")

    def test_markdown_contains_mode_summary_table(self):
        report = {
            "generated_at": "2026-05-27T00:00:00Z",
            "video_id": "video-1",
            "current_mode": "hybrid",
            "baseline": {
                "duration_seconds": 60,
                "estimated_output_duration_seconds": 45,
                "segment_count": 2,
                "transcript_provider": "mistral",
            },
            "comparison": {
                "recommended_mode": "hybrid",
                "fastest_mode": "api",
                "lowest_cost_mode": "local",
                "highest_quality_mode": "api",
            },
            "modes": [
                {
                    "mode": "hybrid",
                    "label": "Hybrid mode",
                    "summary": {
                        "estimated_total_runtime_seconds": 38,
                        "estimated_total_cost_usd": 0.01,
                        "estimated_quality_score": 0.86,
                        "privacy_score": 0.78,
                        "readiness": "ready",
                    },
                    "stages": [
                        {
                            "label": "Transcription",
                            "provider_strategy": "local_first_api_fallback_asr",
                            "estimated_runtime_seconds": 20,
                            "estimated_cost_usd": 0.001,
                            "estimated_quality_score": 0.83,
                        }
                    ],
                }
            ],
        }

        markdown = build_mode_comparison_markdown(report)

        self.assertIn("# API vs Local vs Hybrid Comparison", markdown)
        self.assertIn("| Mode | Runtime | Cost | Quality | Privacy | Readiness |", markdown)
        self.assertIn("Hybrid mode", markdown)
        self.assertIn("local_first_api_fallback_asr", markdown)


if __name__ == "__main__":
    unittest.main()
