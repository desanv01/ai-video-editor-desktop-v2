import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from services.layout_planner import plan_auto_layout_cues, plan_layout_cues  # noqa: E402


def asset(
    asset_id: str,
    *,
    role: str,
    kind: str,
    source_type: str,
    sync_role: str,
    is_primary: bool = False,
    offset: float = 0.0,
    duration: float = 60.0,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=asset_id,
        role=role,
        kind=kind,
        source_type=source_type,
        sync_role=sync_role,
        is_primary=is_primary,
        status="ready",
        sync_offset_seconds=offset,
        duration_seconds=duration,
        created_at=None,
    )


class LayoutPlannerTests(unittest.TestCase):
    def test_single_mixed_video_defaults_to_full_screen_source(self):
        cues = plan_layout_cues(
            [
                asset(
                    "mixed-asset",
                    role="primary",
                    kind="mixed_video",
                    source_type="mixed_video",
                    sync_role="primary_timeline",
                    is_primary=True,
                    duration=120.0,
                )
            ],
            duration_seconds=120.0,
        )

        self.assertEqual(len(cues), 1)
        self.assertEqual(cues[0]["layout"], "full_screen_source")
        self.assertEqual(cues[0]["sources"]["screen"]["asset_id"], "mixed-asset")
        self.assertEqual(cues[0]["sources"]["screen"]["track"], "primary_timeline")
        self.assertEqual(cues[0]["sources"]["audio"]["asset_id"], "mixed-asset")
        self.assertEqual(cues[0]["end_time"], 120.0)

    def test_camera_only_project_defaults_to_full_camera_source(self):
        cues = plan_layout_cues(
            [
                asset(
                    "camera-asset",
                    role="camera",
                    kind="camera_video",
                    source_type="webcam_recording",
                    sync_role="camera_overlay",
                )
            ],
            duration_seconds=45.0,
        )

        self.assertEqual(cues[0]["layout"], "full_camera_source")
        self.assertEqual(cues[0]["sources"]["camera"]["asset_id"], "camera-asset")
        self.assertEqual(cues[0]["sources"]["camera"]["enabled"], True)
        self.assertEqual(cues[0]["sources"]["screen"]["enabled"], False)

    def test_primary_video_with_notes_generates_slide_screen_and_uses_video_as_camera(self):
        cues = plan_auto_layout_cues(
            [
                asset(
                    "talking-head",
                    role="primary",
                    kind="mixed_video",
                    source_type="mixed_video",
                    sync_role="primary_timeline",
                    is_primary=True,
                    duration=420.0,
                ),
                asset(
                    "notes",
                    role="notes",
                    kind="pdf_notes",
                    source_type="pdf_notes",
                    sync_role="structure_reference",
                    duration=0.0,
                ),
            ],
            duration_seconds=420.0,
        )

        self.assertEqual(cues[0]["layout"], "picture_in_picture")
        self.assertEqual(cues[0]["sources"]["screen"]["asset_id"], None)
        self.assertEqual(cues[0]["sources"]["screen"]["track"], "generated_slides")
        self.assertEqual(cues[0]["sources"]["screen"]["enabled"], True)
        self.assertEqual(cues[0]["sources"]["camera"]["asset_id"], "talking-head")
        self.assertEqual(cues[0]["sources"]["camera"]["enabled"], True)

    def test_screen_camera_audio_project_uses_timed_lecture_rules(self):
        cues = plan_layout_cues(
            [
                asset(
                    "screen-asset",
                    role="screen",
                    kind="screen_video",
                    source_type="screen_recording",
                    sync_role="screen_reference",
                ),
                asset(
                    "camera-asset",
                    role="camera",
                    kind="camera_video",
                    source_type="camera_recording",
                    sync_role="camera_overlay",
                    offset=0.4,
                ),
                asset(
                    "audio-asset",
                    role="audio",
                    kind="audio",
                    source_type="separate_audio",
                    sync_role="audio_master",
                    offset=0.2,
                ),
            ],
            duration_seconds=90.0,
            segments=[
                {"start": 0.0, "end": 12.0, "type": "intro_outro", "action": "keep"},
                {"start": 12.0, "end": 40.0, "type": "core_content", "has_slide_change": True, "action": "keep"},
                {"start": 40.0, "end": 90.0, "type": "core_content", "importance": 0.6, "action": "keep"},
            ],
        )

        self.assertEqual([cue["layout"] for cue in cues], [
            "side_by_side",
            "full_screen_source",
            "picture_in_picture",
        ])
        self.assertEqual(cues[0]["sources"]["screen"]["asset_id"], "screen-asset")
        self.assertEqual(cues[0]["sources"]["camera"]["asset_id"], "camera-asset")
        self.assertEqual(cues[0]["sources"]["camera"]["sync_offset_seconds"], 0.4)
        self.assertEqual(cues[0]["sources"]["audio"]["asset_id"], "audio-asset")
        self.assertEqual(cues[0]["sources"]["audio"]["sync_offset_seconds"], 0.2)
        self.assertEqual(cues[0]["planning"]["strategy"], "rule_based")

    def test_auto_layout_cues_are_marked_for_teacher_override(self):
        cues = plan_auto_layout_cues(
            [
                asset(
                    "screen-asset",
                    role="screen",
                    kind="screen_video",
                    source_type="screen_recording",
                    sync_role="screen_reference",
                ),
                asset(
                    "camera-asset",
                    role="camera",
                    kind="camera_video",
                    source_type="webcam_recording",
                    sync_role="camera_overlay",
                ),
            ],
            duration_seconds=50.0,
            segments=[
                {"start": 0.0, "end": 10.0, "type": "intro_outro", "action": "keep"},
                {"start": 24.0, "end": 50.0, "type": "core_content", "importance": 0.9, "action": "highlight"},
            ],
        )

        self.assertGreaterEqual(len(cues), 2)
        self.assertTrue(all(cue["id"].startswith("layout-auto-") for cue in cues))
        self.assertTrue(all(cue["status"] == "suggested" for cue in cues))
        self.assertTrue(all(cue["planning"]["strategy"] == "ai_auto_rule_assist" for cue in cues))
        self.assertIn("AI auto layout", cues[0]["reason"])


if __name__ == "__main__":
    unittest.main()
