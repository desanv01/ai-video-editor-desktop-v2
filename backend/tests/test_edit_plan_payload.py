import sys
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from services.edit_plan_payload import (  # noqa: E402
    EDIT_PLAN_SCHEMA_VERSION,
    build_edit_plan_payload,
    get_annotations,
    get_caption_policy,
    get_educational_overlays,
    get_end_cards,
    get_layout_cues,
    normalize_plan_payload,
    update_annotations,
    update_cleaning_payload,
    update_caption_policy,
    update_end_cards,
    update_educational_overlays,
    update_export_metadata,
    update_layout_cues,
    update_slide_cues,
    update_sections_payload,
)


class EditPlanPayloadTests(unittest.TestCase):
    def test_normalization_surfaces_legacy_nested_slide_cues(self):
        nested_cues = [
            {
                "start_time": 12.0,
                "end_time": 28.0,
                "slide_index": 2,
                "cue_type": "anchor",
            }
        ]

        normalized = normalize_plan_payload({"render_plan": {"slide_cues": nested_cues}})

        self.assertEqual(normalized["slide_cues"][0]["start_time"], 12.0)
        self.assertEqual(normalized["slide_cues"][0]["end_time"], 28.0)
        self.assertEqual(normalized["slide_cues"][0]["slide_index"], 2)

    def test_editorial_blocks_remove_stale_micro_cues_and_keep_exact_block_style(self):
        normalized = normalize_plan_payload({
            "summary": {"original_duration_seconds": 12.0},
            "editorial_blocks": [
                {
                    "id": "block-a",
                    "start_time": 0.0,
                    "end_time": 5.0,
                    "slide_index": 0,
                    "layout": "picture_in_picture",
                },
                {
                    "id": "editorial-gap-1",
                    "start_time": 5.0,
                    "end_time": 6.0,
                    "slide_index": None,
                    "layout": "full_camera_source",
                    "source": "editorial_gap_coverage",
                },
                {
                    "id": "block-b",
                    "start_time": 6.0,
                    "end_time": 12.0,
                    "slide_index": 1,
                    "layout": "picture_in_picture",
                },
            ],
            "layout_cues": [
                {
                    "id": "styled-a",
                    "editorial_block_id": "block-a",
                    "start_time": 0.0,
                    "end_time": 5.0,
                    "layout": "picture_in_picture",
                    "camera": {"shape": "circle", "size": "small", "corner": "bottom_left"},
                },
                {
                    "id": "stale-gap",
                    "editorial_block_id": "editorial-gap-1",
                    "start_time": 5.0,
                    "end_time": 6.0,
                    "layout": "full_camera_source",
                },
                {
                    "id": "styled-b",
                    "editorial_block_id": "block-b",
                    "start_time": 6.0,
                    "end_time": 12.0,
                    "layout": "picture_in_picture",
                },
            ],
        })

        self.assertEqual([item["id"] for item in normalized["editorial_blocks"]], ["block-a", "block-b"])
        self.assertEqual(len(normalized["slide_cues"]), 2)
        self.assertEqual(len(normalized["layout_cues"]), 2)
        self.assertEqual(normalized["layout_cues"][0]["camera"]["shape"], "circle")
        self.assertEqual(normalized["layout_cues"][0]["camera"]["corner"], "bottom_left")

    def test_teacher_slide_cues_do_not_change_layout_or_export_metadata(self):
        payload = normalize_plan_payload({
            "summary": {"original_duration_seconds": 60.0},
            "layout_cues": [{"id": "layout-1", "start_time": 0.0, "end_time": 60.0, "layout": "side_by_side"}],
            "export_metadata": {"selected_preset": "youtube_1080p"},
        })

        updated = update_slide_cues(payload, [{
            "id": "slide-1",
            "start_time": 0.0,
            "end_time": 20.0,
            "slide_index": 2,
        }])

        self.assertEqual(updated["slide_cues"][0]["source"], "teacher_slide_override")
        self.assertEqual(updated["slide_cues"][0]["confidence"], 1.0)
        self.assertEqual(updated["layout_cues"], payload["layout_cues"])
        self.assertEqual(updated["export_metadata"]["selected_preset"], "youtube_1080p")

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

    def test_updates_layout_cues_for_studio_composition(self):
        payload = update_layout_cues(
            normalize_plan_payload({"summary": {"original_duration_seconds": 60.0}}),
            [
                {
                    "id": "layout-teacher-1",
                    "layout": "picture_in_picture",
                    "start_time": 0.0,
                    "end_time": 60.0,
                    "camera": {"corner": "top_right", "size": "large"},
                    "timing": {"transition_in": "fade", "transition_duration_seconds": 0.5},
                    "sources": {
                        "screen": {"role": "screen", "asset_id": "screen-1", "enabled": True, "track": "screen"},
                        "camera": {"role": "camera", "asset_id": "cam-1", "enabled": True, "track": "camera"},
                        "audio": {"role": "audio", "asset_id": "audio-1", "enabled": True, "track": "audio"},
                    },
                }
            ],
        )

        cues = get_layout_cues(payload)

        self.assertEqual(cues[0]["layout"], "picture_in_picture")
        self.assertEqual(cues[0]["camera"]["corner"], "top_right")
        self.assertEqual(cues[0]["camera"]["size"], "large")
        self.assertEqual(cues[0]["timing"]["transition_in"], "fade")
        self.assertEqual(payload["metadata"]["layout_planning"]["last_updated_by"], "teacher_layout_override")
        self.assertEqual(payload["export_metadata"]["layout_cues"]["picture_in_picture_count"], 1)

    def test_updates_timeline_annotations_and_callouts(self):
        payload = update_annotations(
            normalize_plan_payload({"segments": []}),
            [
                {
                    "id": "callout-1",
                    "annotation_type": "callout",
                    "text": "Remember this formula",
                    "start_time": 4.0,
                    "end_time": 9.0,
                    "position": "middle_right",
                    "style": {"font_size": 34, "border_color": "#22D3EE"},
                    "pointer": {"enabled": True, "direction": "left"},
                },
                {
                    "annotation_type": "label",
                    "text": "Step 1",
                    "start_time": 1.0,
                    "end_time": 3.0,
                    "position": "top_left",
                },
            ],
        )

        annotations = get_annotations(payload)

        self.assertEqual([item["id"] for item in annotations], ["annotation-1000", "callout-1"])
        self.assertEqual(annotations[1]["annotation_type"], "callout")
        self.assertEqual(annotations[1]["x_percent"], 78.0)
        self.assertEqual(annotations[1]["style"]["font_size"], 34)
        self.assertEqual(annotations[1]["animation"]["preset"], "pop")
        self.assertEqual(payload["export_metadata"]["annotations"]["count"], 2)
        self.assertEqual(payload["export_metadata"]["annotations"]["animated_count"], 2)

    def test_updates_educational_overlays_for_labels_and_title_cards(self):
        payload = update_educational_overlays(
            normalize_plan_payload({"segments": []}),
            [
                {
                    "id": "intro-1",
                    "overlay_type": "intro_card",
                    "title": "Gradient Descent",
                    "subtitle": "Learning rate and loss curves",
                    "start_time": 0.0,
                    "end_time": 4.5,
                },
                {
                    "overlay_type": "step_label",
                    "title": "Update parameters",
                    "start_time": 12.0,
                    "end_time": 16.0,
                    "step_number": 2,
                    "position": "top_left",
                    "style": {"accent_color": "#FACC15", "font_size": 30},
                },
            ],
        )

        overlays = get_educational_overlays(payload)

        self.assertEqual([item["id"] for item in overlays], ["intro-1", "step_label-12000"])
        self.assertEqual(overlays[0]["position"], "center")
        self.assertEqual(overlays[1]["step_number"], 2)
        self.assertEqual(overlays[1]["style"]["font_size"], 30)
        self.assertEqual(overlays[0]["animation"]["preset"], "fade")
        self.assertEqual(overlays[1]["animation"]["preset"], "slide_down")
        self.assertEqual(payload["export_metadata"]["educational_overlays"]["intro_card_count"], 1)
        self.assertEqual(payload["export_metadata"]["educational_overlays"]["step_label_count"], 1)
        self.assertEqual(payload["export_metadata"]["educational_overlays"]["animated_count"], 2)

    def test_updates_end_cards_for_summary_next_topic_course_link_and_custom_message(self):
        payload = update_end_cards(
            normalize_plan_payload({"segments": []}),
            [
                {
                    "id": "end-summary",
                    "card_type": "lecture_summary",
                    "title": "What we learned",
                    "message": "You can now explain gradient descent.",
                    "summary_points": ["Loss measures error", "Learning rate controls step size"],
                    "duration_seconds": 7.5,
                },
                {
                    "id": "end-next",
                    "card_type": "next_topic",
                    "title": "Coming up",
                    "next_topic": "Backpropagation",
                    "course_url": "https://example.edu/course",
                    "button_text": "Open lesson",
                    "style": {"accent_color": "#22D3EE", "body_font_size": 28},
                },
            ],
        )

        end_cards = get_end_cards(payload)

        self.assertEqual([item["id"] for item in end_cards], ["end-next", "end-summary"])
        self.assertEqual(end_cards[0]["card_type"], "next_topic")
        self.assertEqual(end_cards[0]["next_topic"], "Backpropagation")
        self.assertEqual(end_cards[0]["course_url"], "https://example.edu/course")
        self.assertEqual(end_cards[0]["style"]["body_font_size"], 28)
        self.assertEqual(end_cards[1]["summary_points"], ["Loss measures error", "Learning rate controls step size"])
        self.assertEqual(end_cards[1]["duration_seconds"], 7.5)
        self.assertEqual(payload["export_metadata"]["end_cards"]["enabled_count"], 2)
        self.assertEqual(payload["export_metadata"]["end_cards"]["lecture_summary_count"], 1)
        self.assertEqual(payload["export_metadata"]["end_cards"]["next_topic_count"], 1)


if __name__ == "__main__":
    unittest.main()
