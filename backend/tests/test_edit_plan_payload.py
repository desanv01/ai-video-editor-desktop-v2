import sys
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from services.edit_plan_payload import (  # noqa: E402
    EDIT_PLAN_SCHEMA_VERSION,
    build_edit_plan_payload,
    get_caption_policy,
    normalize_plan_payload,
    update_cleaning_payload,
    update_caption_policy,
    update_export_metadata,
    update_sections_payload,
)


class EditPlanPayloadTests(unittest.TestCase):
    def test_normalizes_legacy_segment_array_to_v2_envelope(self):
        payload = normalize_plan_payload([
            {"segment_id": "seg-1", "action": "keep"},
        ])

        self.assertEqual(payload["schema_version"], EDIT_PLAN_SCHEMA_VERSION)
        self.assertEqual(payload["segments"][0]["segment_id"], "seg-1")
        self.assertEqual(payload["edit_decisions"], [])
        self.assertEqual(payload["cleaning_suggestions"], [])
        self.assertEqual(payload["sections"], [])
        self.assertEqual(payload["layout_cues"], [])
        self.assertEqual(payload["polish_actions"][0]["kind"], "caption_policy")
        self.assertEqual(payload["export_metadata"]["artifacts"], [])
        self.assertEqual(payload["metadata"]["compatible_from_schema_version"], "legacy.segment-array.v1")

    def test_builds_fresh_plan_with_layout_polish_and_export_defaults(self):
        payload = build_edit_plan_payload(
            segments=[{"segment_id": "seg-1", "action": "highlight"}],
            original_duration=120.0,
            estimated_duration=95.0,
            warnings=["review transition"],
        )

        self.assertEqual(payload["schema_version"], EDIT_PLAN_SCHEMA_VERSION)
        self.assertEqual(payload["segments"][0]["action"], "highlight")
        self.assertEqual(payload["layout_cues"][0]["layout"], "full_screen_source")
        self.assertEqual(payload["layout_cues"][0]["sources"]["screen"]["role"], "screen")
        self.assertEqual(payload["layout_cues"][0]["sources"]["audio"]["enabled"], True)
        self.assertEqual(payload["layout_cues"][0]["output"]["aspect_ratio"], "16:9")
        self.assertEqual(payload["polish_actions"][0]["kind"], "caption_policy")
        self.assertEqual(payload["export_metadata"]["source_duration_seconds"], 120.0)
        self.assertIn("youtube_1080p", payload["export_metadata"]["target_presets"])
        self.assertEqual(payload["summary"]["warnings"], ["review transition"])

    def test_updates_clean_sections_and_export_metadata_without_losing_decisions(self):
        payload = normalize_plan_payload({
            "schema_version": "phase5.transcript-decisions.v1",
            "segments": [{"segment_id": "seg-1", "action": "keep"}],
            "edit_decisions": [{"id": "cut-1", "kind": "transcript_cut", "status": "active"}],
        })

        payload = update_cleaning_payload(
            payload,
            profile="conservative",
            summary={"suggestions_total": 1},
            suggestions=[{"id": "clean-1", "type": "filler_word"}],
            applied=True,
        )
        payload = update_sections_payload(
            payload,
            {
                "schema_version": "phase6.slide-aware-segmentation.v2",
                "summary": {"sections_total": 1},
                "sections": [{"id": "section-1", "label": "Intro"}],
                "chapters": [{"timestamp": 0.0, "label": "Intro"}],
                "youtube_format": "00:00 Intro",
            },
        )
        payload = update_export_metadata(
            payload,
            artifacts=[{"kind": "plan_json", "path": "out.json", "available": True}],
            render={"playable_range_count": 2},
        )

        self.assertEqual(payload["edit_decisions"][0]["id"], "cut-1")
        self.assertEqual(payload["cleaning_suggestions"][0]["status"], "applied")
        self.assertEqual(payload["clean_summary"]["suggestions_total"], 1)
        self.assertEqual(payload["sections"][0]["label"], "Intro")
        self.assertEqual(payload["section_summary"]["youtube_format"], "00:00 Intro")
        self.assertEqual(payload["export_metadata"]["artifacts"][0]["kind"], "plan_json")
        self.assertEqual(payload["export_metadata"]["render"]["playable_range_count"], 2)

    def test_updates_selective_caption_policy(self):
        payload = update_caption_policy(
            normalize_plan_payload({"segments": []}),
            {
                "enabled": True,
                "appearance": "highlight_segments",
                "placement": "top_center",
                "export_behavior": "sidecar_and_burn_in",
                "style": {"font_size": 32, "background": "box"},
            },
        )

        policy = get_caption_policy(payload)

        self.assertEqual(policy["appearance"], "highlight_segments")
        self.assertEqual(policy["placement"], "top_center")
        self.assertEqual(policy["export_behavior"], "sidecar_and_burn_in")
        self.assertEqual(policy["style"]["font_size"], 32)
        self.assertEqual(policy["style"]["background"], "box")
        self.assertEqual(payload["polish_actions"][0]["status"], "active")
        self.assertEqual(payload["export_metadata"]["caption_policy"]["placement"], "top_center")


if __name__ == "__main__":
    unittest.main()
