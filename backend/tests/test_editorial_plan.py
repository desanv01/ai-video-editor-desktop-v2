import sys
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from services.edit_plan_payload import update_editorial_blocks  # noqa: E402
from services.editorial_plan import (  # noqa: E402
    layout_cues_from_editorial_blocks,
    normalize_editorial_blocks,
    slide_cues_from_editorial_blocks,
)


class EditorialPlanTests(unittest.TestCase):
    def test_low_numeric_confidence_does_not_remove_related_slide(self):
        blocks = normalize_editorial_blocks([{
            "start_time": 0,
            "end_time": 25,
            "slide_index": 2,
            "slide_relevance": "direct",
            "slide_relation": "related",
            "layout": "picture_in_picture",
            "confidence": 0.13,
        }], duration_seconds=25, slide_count=4)

        self.assertEqual(blocks[0]["slide_index"], 2)
        self.assertEqual(blocks[0]["slide_relation"], "related")

    def test_uncertain_slide_is_safe_lecturer_only_and_reviewable(self):
        blocks = normalize_editorial_blocks([{
            "start_time": 0,
            "end_time": 25,
            "slide_index": 1,
            "slide_relation": "uncertain",
            "confidence": "medium",
        }], duration_seconds=25, slide_count=4)

        self.assertIsNone(blocks[0]["slide_index"])
        self.assertEqual(blocks[0]["candidate_slide_index"], 1)
        self.assertTrue(blocks[0]["review_required"])

    def test_unrelated_speech_forces_lecturer_only(self):
        blocks = normalize_editorial_blocks([
            {
                "start_time": 0,
                "end_time": 25,
                "title": "Class housekeeping",
                "slide_index": 2,
                "slide_relevance": "none",
                "layout": "picture_in_picture",
                "confidence": 0.9,
            }
        ], duration_seconds=25, slide_count=4)

        self.assertIsNone(blocks[0]["slide_index"])
        self.assertEqual(blocks[0]["layout"], "full_camera_source")

    def test_combined_blocks_project_matching_slide_and_layout_ranges(self):
        blocks = normalize_editorial_blocks([
            {
                "id": "intro",
                "start_time": 0,
                "end_time": 20,
                "title": "Introduction",
                "slide_index": None,
                "slide_relevance": "none",
                "layout": "full_camera_source",
                "confidence": 0.95,
            },
            {
                "id": "flow",
                "start_time": 20,
                "end_time": 70,
                "title": "VCS flow",
                "slide_index": 3,
                "slide_relevance": "direct",
                "layout": "picture_in_picture",
                "confidence": 0.88,
            },
        ], duration_seconds=70, slide_count=5)

        slides = slide_cues_from_editorial_blocks(blocks)
        layouts = layout_cues_from_editorial_blocks(blocks, duration_seconds=70)

        self.assertEqual([(cue["start_time"], cue["end_time"]) for cue in slides], [(0.0, 20.0), (20.0, 70.0)])
        self.assertEqual([cue["slide_index"] for cue in slides], [None, 3])
        self.assertEqual([cue["layout"] for cue in layouts], ["full_camera_source", "picture_in_picture"])

    def test_projection_preserves_existing_source_assets(self):
        base = [{
            "id": "base",
            "layout": "picture_in_picture",
            "start_time": 0,
            "end_time": 60,
            "sources": {
                "screen": {"asset_id": "slides", "enabled": True},
                "camera": {"asset_id": "camera", "enabled": True},
                "audio": {"asset_id": "mic", "enabled": True},
            },
        }]
        blocks = normalize_editorial_blocks([{
            "start_time": 0,
            "end_time": 60,
            "slide_index": 1,
            "slide_relevance": "critical",
            "layout": "full_screen_source",
            "confidence": 0.9,
        }], duration_seconds=60, slide_count=3)

        cues = layout_cues_from_editorial_blocks(blocks, base_cues=base, duration_seconds=60)

        self.assertEqual(cues[0]["sources"]["screen"]["asset_id"], "slides")
        self.assertEqual(cues[0]["sources"]["camera"]["asset_id"], "camera")
        self.assertEqual(cues[0]["sources"]["audio"]["asset_id"], "mic")
        self.assertTrue(cues[0]["sources"]["screen"]["enabled"])
        self.assertFalse(cues[0]["sources"]["camera"]["enabled"])

    def test_adjacent_same_visual_decisions_form_topic_sized_blocks(self):
        blocks = normalize_editorial_blocks([
            {
                "start_time": 0,
                "end_time": 24,
                "title": "Starting simulation",
                "summary": "Open the simulator.",
                "slide_index": 2,
                "slide_relevance": "direct",
                "layout": "picture_in_picture",
                "confidence": 0.88,
            },
            {
                "start_time": 24,
                "end_time": 52,
                "title": "Compiling the design",
                "summary": "Compile the Verilog sources.",
                "slide_index": 2,
                "slide_relevance": "direct",
                "layout": "picture_in_picture",
                "confidence": 0.83,
            },
        ], duration_seconds=52, slide_count=4)

        self.assertEqual(len(blocks), 1)
        self.assertEqual(blocks[0]["end_time"], 52.0)
        self.assertIn("Compile the Verilog sources", blocks[0]["summary"])

    def test_payload_update_refreshes_both_compatibility_timelines(self):
        payload = {
            "summary": {"original_duration_seconds": 40},
            "layout_cues": [{"id": "base", "layout": "picture_in_picture", "start_time": 0, "end_time": 40}],
        }
        updated = update_editorial_blocks(payload, [{
            "id": "block",
            "start_time": 0,
            "end_time": 40,
            "title": "Waveform verification",
            "slide_index": 2,
            "slide_relevance": "direct",
            "layout": "side_by_side",
            "confidence": 0.85,
        }], source="agent4_editorial_plan")

        self.assertEqual(updated["editorial_blocks"][0]["id"], "block")
        self.assertEqual(updated["slide_cues"][0]["slide_index"], 2)
        self.assertEqual(updated["layout_cues"][0]["layout"], "side_by_side")
        self.assertEqual(updated["metadata"]["editorial_planning"]["block_count"], 1)

    def test_micro_coverage_gap_stays_with_previous_visual_decision(self):
        blocks = normalize_editorial_blocks([
            {
                "id": "slide-one",
                "start_time": 0,
                "end_time": 10,
                "slide_index": 0,
                "slide_relevance": "direct",
                "layout": "picture_in_picture",
            },
            {
                "id": "slide-two",
                "start_time": 11,
                "end_time": 20,
                "slide_index": 1,
                "slide_relevance": "direct",
                "layout": "picture_in_picture",
            },
        ], duration_seconds=20, slide_count=2)

        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0]["end_time"], 11.0)
        self.assertEqual(blocks[1]["start_time"], 11.0)
        self.assertFalse(any(str(block["id"]).startswith("editorial-gap-") for block in blocks))

    def test_existing_micro_coverage_block_is_absorbed(self):
        blocks = normalize_editorial_blocks([
            {
                "id": "slide-one",
                "start_time": 0,
                "end_time": 10,
                "slide_index": 0,
                "slide_relevance": "direct",
                "layout": "picture_in_picture",
            },
            {
                "id": "editorial-gap-0001",
                "start_time": 10,
                "end_time": 11,
                "slide_index": None,
                "slide_relevance": "none",
                "layout": "full_camera_source",
                "source": "semantic_relevance_gate",
                "transcript_excerpt": "",
            },
            {
                "id": "slide-two",
                "start_time": 11,
                "end_time": 20,
                "slide_index": 1,
                "slide_relevance": "direct",
                "layout": "picture_in_picture",
            },
        ], duration_seconds=20, slide_count=2)

        self.assertEqual([(block["id"], block["start_time"], block["end_time"]) for block in blocks], [
            ("slide-one", 0.0, 11.0),
            ("slide-two", 11.0, 20.0),
        ])

    def test_teacher_micro_block_is_preserved(self):
        blocks = normalize_editorial_blocks([
            {
                "id": "teacher-camera",
                "start_time": 0,
                "end_time": 1,
                "slide_index": None,
                "slide_relevance": "none",
                "layout": "full_camera_source",
                "source": "teacher_editorial_override",
                "teacher_modified": True,
            },
            {
                "id": "slide-one",
                "start_time": 1,
                "end_time": 10,
                "slide_index": 0,
                "slide_relevance": "direct",
                "layout": "picture_in_picture",
            },
        ], duration_seconds=10, slide_count=1)

        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0]["id"], "teacher-camera")

    def test_projection_preserves_camera_style_by_editorial_block_id(self):
        blocks = normalize_editorial_blocks([
            {
                "id": "first",
                "start_time": 0,
                "end_time": 20,
                "slide_index": 0,
                "slide_relevance": "direct",
                "layout": "picture_in_picture",
            },
            {
                "id": "second",
                "start_time": 20,
                "end_time": 40,
                "slide_index": 1,
                "slide_relevance": "direct",
                "layout": "picture_in_picture",
            },
        ], duration_seconds=40, slide_count=2)
        base = [
            {
                "id": "second-style",
                "editorial_block_id": "second",
                "layout": "picture_in_picture",
                "start_time": 0,
                "end_time": 40,
                "camera": {"shape": "circle", "corner": "top_left", "size": "small"},
            },
            {
                "id": "first-style",
                "editorial_block_id": "first",
                "layout": "picture_in_picture",
                "start_time": 0,
                "end_time": 40,
                "camera": {"shape": "rounded_rectangle", "corner": "bottom_right", "size": "large"},
            },
        ]

        cues = layout_cues_from_editorial_blocks(blocks, base_cues=base, duration_seconds=40)

        self.assertEqual(cues[0]["camera"]["shape"], "rounded_rectangle")
        self.assertEqual(cues[0]["camera"]["size"], "large")
        self.assertEqual(cues[1]["camera"]["shape"], "circle")
        self.assertEqual(cues[1]["camera"]["corner"], "top_left")


if __name__ == "__main__":
    unittest.main()
