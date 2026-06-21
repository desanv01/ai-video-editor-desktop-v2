import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from agents.visual_structure import (
    CAMERA_VALUES,
    STRUCTURE_VALUES,
    VisualContext,
    _asset_matches,
    _page_scope_from_asset,
    _planning_windows,
    _normalize_llm_slide_timeline,
    _timeline_response_issues,
    _scene_detection_skip_reason,
    _semantic_chunks,
    _shortlist_pages_for_window,
    _stabilize_slide_timeline,
    _visual_result,
)
from db.models import (
    ProjectAssetKind,
    ProjectAssetRole,
    ProjectAssetSyncRole,
)


class VisualStructureTests(unittest.TestCase):
    def test_llm_confidence_labels_are_normalized_without_discarding_slide(self):
        timeline = _normalize_llm_slide_timeline([{
            "start_time": 0,
            "end_time": 20,
            "slide_index": 2,
            "slide_relevance": "direct",
            "slide_relation": "related",
            "confidence": "high",
        }], duration=20, slide_count=4, allowed_slide_indices={0, 1, 2, 3})

        self.assertEqual(timeline[0]["slide_index"], 2)
        self.assertEqual(timeline[0]["confidence"], 0.85)

    def test_llm_plan_rejects_slide_outside_saved_video_scope(self):
        issues = _timeline_response_issues([{
            "start_time": 0,
            "end_time": 20,
            "slide_index": 5,
            "confidence": 0.9,
        }], duration=20, slide_count=10, allowed_slide_indices={0, 1, 2, 3})

        self.assertTrue(any("outside the allowed scope" in issue for issue in issues))

    def test_skips_large_camera_or_mixed_video_when_structure_reference_exists(self):
        video = SimpleNamespace(
            file_path="missing-but-size-is-known.mov",
            file_size_bytes=1024 * 1024 * 1024,
            project_asset_id=None,
        )
        context = VisualContext(
            assets=[
                SimpleNamespace(
                    kind=ProjectAssetKind.PDF_NOTES,
                    role=ProjectAssetRole.NOTES,
                    source_type="pdf_notes",
                    sync_role=ProjectAssetSyncRole.STRUCTURE_REFERENCE,
                )
            ],
            source_roles={"pdf_notes", "notes", "structure_reference"},
            structure_reference_count=1,
            has_screen_reference=False,
            has_camera_reference=False,
            has_structure_reference=True,
        )

        with patch("agents.visual_structure.settings.AGENT4_STRUCTURE_REFERENCE_SKIP_MB", 768):
            reason = _scene_detection_skip_reason(video, context)

        self.assertIn("uploaded teaching structure", reason)

    def test_does_not_skip_screen_recording_even_with_structure_reference(self):
        video = SimpleNamespace(
            file_path="screen.mp4",
            file_size_bytes=1024 * 1024 * 1024,
            project_asset_id=None,
        )
        context = VisualContext(
            assets=[
                SimpleNamespace(kind="screen_video", role="screen", source_type="screen_recording", sync_role="screen_reference"),
                SimpleNamespace(kind="pdf_notes", role="notes", source_type="pdf_notes", sync_role="structure_reference"),
            ],
            source_roles={"screen", "screen_reference", "pdf_notes", "structure_reference"},
            structure_reference_count=1,
            has_screen_reference=True,
            has_camera_reference=False,
            has_structure_reference=True,
        )

        self.assertIsNone(_scene_detection_skip_reason(video, context))

    def test_asset_matching_accepts_enum_and_string_roles(self):
        asset = SimpleNamespace(
            kind=ProjectAssetKind.CAMERA_VIDEO,
            role=ProjectAssetRole.CAMERA,
            source_type="camera_recording",
            sync_role=ProjectAssetSyncRole.CAMERA_OVERLAY,
        )

        self.assertTrue(_asset_matches(asset, CAMERA_VALUES))
        self.assertFalse(_asset_matches(asset, STRUCTURE_VALUES))

    def test_visual_result_reports_source_and_unconfigured_vision_provider(self):
        context = VisualContext(
            assets=[],
            source_roles=set(),
            structure_reference_count=2,
            has_screen_reference=False,
            has_camera_reference=False,
            has_structure_reference=True,
        )

        result = _visual_result(
            status="success",
            scenes_detected=0,
            scene_timestamps=[],
            analysis_source="structure_reference_skip",
            context=context,
            skip_reason="skip",
        )

        self.assertEqual(result["analysis_source"], "structure_reference_skip")
        self.assertEqual(result["structure_reference_count"], 2)
        self.assertEqual(result["vision_provider"], "vision-unconfigured")
        self.assertEqual(result["skip_reason"], "skip")

    def test_manual_page_scope_is_one_based_in_asset_metadata(self):
        asset = SimpleNamespace(metadata_json={"user_metadata": {"slide_page_start": 4, "slide_page_end": 8}})

        self.assertEqual(_page_scope_from_asset(asset, 10), (3, 7))

    def test_semantic_chunks_use_word_timestamps_and_neighbor_context(self):
        words = [
            {"word": "We", "start": 0.0, "end": 1.0},
            {"word": "begin.", "start": 1.0, "end": 9.0},
            {"word": "Next", "start": 9.1, "end": 12.0},
            {"word": "slide.", "start": 12.0, "end": 18.0},
        ]

        chunks = _semantic_chunks([], timed_words=words, min_seconds=4.0, target_seconds=8.0, max_seconds=10.0)

        self.assertEqual(len(chunks), 2)
        self.assertEqual(chunks[0]["text"], "We begin.")
        self.assertIn("Next slide", chunks[0]["context_after"])
        self.assertIn("advance", chunks[1]["signals"])

    def test_semantic_chunks_do_not_cut_a_sentence_at_target_duration(self):
        words = [
            {"word": "This", "start": 0.0, "end": 4.0},
            {"word": "explanation", "start": 4.05, "end": 8.0},
            {"word": "continues", "start": 8.05, "end": 12.0},
            {"word": "through", "start": 12.05, "end": 16.0},
            {"word": "one", "start": 16.05, "end": 19.0},
            {"word": "idea.", "start": 19.05, "end": 22.0},
        ]

        chunks = _semantic_chunks([], timed_words=words, min_seconds=4.0, target_seconds=8.0, max_seconds=30.0)

        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["text"], "This explanation continues through one idea.")

    def test_anchor_planner_keeps_short_reference_on_current_slide(self):
        timeline = [
            {"id": "a", "start_time": 0.0, "end_time": 20.0, "slide_index": 2, "confidence": 0.9},
            {"id": "b", "start_time": 20.0, "end_time": 25.0, "slide_index": 3, "confidence": 0.8},
            {"id": "c", "start_time": 25.0, "end_time": 45.0, "slide_index": 2, "confidence": 0.9},
        ]
        chunks = [
            {"start_time": 0.0, "end_time": 20.0, "signals": []},
            {"start_time": 20.0, "end_time": 25.0, "signals": ["reference"]},
            {"start_time": 25.0, "end_time": 45.0, "signals": ["return"]},
        ]

        result = _stabilize_slide_timeline(timeline, chunks=chunks)

        self.assertTrue(all(item["slide_index"] == 2 for item in result))

    def test_anchor_planner_allows_meaningful_excursion_and_return(self):
        timeline = [
            {"id": "a", "start_time": 0.0, "end_time": 20.0, "slide_index": 2, "confidence": 0.9},
            {"id": "b", "start_time": 20.0, "end_time": 32.0, "slide_index": 3, "confidence": 0.8},
            {"id": "c", "start_time": 32.0, "end_time": 50.0, "slide_index": 2, "confidence": 0.9, "cue_type": "return"},
        ]

        result = _stabilize_slide_timeline(timeline, chunks=[])

        self.assertEqual([item["slide_index"] for item in result], [2, 3, 2])
        self.assertEqual(result[1]["cue_type"], "excursion")

    def test_anchor_planner_advances_after_sustained_evidence(self):
        timeline = [
            {"id": "a", "start_time": 0.0, "end_time": 20.0, "slide_index": 2, "confidence": 0.9},
            {"id": "b", "start_time": 20.0, "end_time": 40.0, "slide_index": 3, "confidence": 0.9},
            {"id": "c", "start_time": 40.0, "end_time": 60.0, "slide_index": 3, "confidence": 0.9},
        ]

        result = _stabilize_slide_timeline(timeline, chunks=[])

        self.assertEqual([item["slide_index"] for item in result], [2, 3, 3])
        self.assertEqual(result[1]["cue_type"], "advance")

    def test_anchor_planner_keeps_sustained_reference_temporary_when_anchor_returns_soon(self):
        timeline = [
            {"id": "a", "start_time": 0.0, "end_time": 20.0, "slide_index": 2, "confidence": 0.9},
            {"id": "b", "start_time": 20.0, "end_time": 40.0, "slide_index": 3, "confidence": 0.9},
            {"id": "c", "start_time": 40.0, "end_time": 60.0, "slide_index": 3, "confidence": 0.9},
            {"id": "d", "start_time": 60.0, "end_time": 80.0, "slide_index": 2, "confidence": 0.9},
        ]

        result = _stabilize_slide_timeline(timeline, chunks=[])

        self.assertEqual([item["slide_index"] for item in result], [2, 3, 2])
        self.assertEqual(result[1]["cue_type"], "excursion")

    def test_long_form_windows_overlap_and_shortlist_relevant_pages(self):
        chunks = [
            {"id": f"c{index}", "start_time": index * 20.0, "end_time": (index + 1) * 20.0, "text": "VCS waveform Verdi"}
            for index in range(12)
        ]
        pages = [
            {"text": "administrative welcome"},
            {"text": "VCS compile simulation waveform Verdi"},
            {"text": "environment login credentials"},
        ]

        windows = _planning_windows(chunks, window_seconds=120.0, overlap_seconds=25.0)
        shortlist = _shortlist_pages_for_window(windows[0]["chunks"], pages, {0, 1, 2}, anchor=2, limit=2)

        self.assertGreaterEqual(len(windows), 2)
        self.assertLess(windows[1]["start_time"], windows[0]["end_time"])
        self.assertIn(1, shortlist)
        self.assertIn(2, shortlist)


if __name__ == "__main__":
    unittest.main()
