import sys
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from services.edit_plan_payload import normalize_plan_payload  # noqa: E402
from services.layout_model import (  # noqa: E402
    LAYOUT_SCHEMA_VERSION,
    LayoutMode,
    build_layout_cue,
    default_layout_cues,
    normalize_layout_cues,
)


class LayoutDataModelTests(unittest.TestCase):
    def test_default_layout_cue_models_full_screen_source_with_audio(self):
        cue = default_layout_cues(90.0)[0]

        self.assertEqual(cue["schema_version"], LAYOUT_SCHEMA_VERSION)
        self.assertEqual(cue["layout"], "full_screen_source")
        self.assertEqual(cue["start_time"], 0.0)
        self.assertEqual(cue["end_time"], 90.0)
        self.assertEqual(cue["timing"]["duration_seconds"], 90.0)
        self.assertEqual(cue["sources"]["screen"]["role"], "screen")
        self.assertEqual(cue["sources"]["screen"]["enabled"], True)
        self.assertEqual(cue["sources"]["camera"]["enabled"], False)
        self.assertEqual(cue["sources"]["audio"]["role"], "audio")
        self.assertEqual(cue["sources"]["audio"]["enabled"], True)
        self.assertEqual(cue["camera"]["shape"], "rounded_rectangle")
        self.assertEqual(cue["camera"]["corner"], "bottom_right")

    def test_builds_picture_in_picture_with_typed_camera_settings(self):
        cue = build_layout_cue(
            cue_id="cue-pip-1",
            layout=LayoutMode.PICTURE_IN_PICTURE,
            start_time=12.5,
            end_time=35.0,
            camera_shape="circle",
            camera_corner="top_left",
            screen_source_id="screen-asset",
            camera_source_id="camera-asset",
            audio_source_id="audio-asset",
            reason="Show instructor during explanation.",
        )

        self.assertEqual(cue["layout"], "picture_in_picture")
        self.assertEqual(cue["sources"]["screen"]["asset_id"], "screen-asset")
        self.assertEqual(cue["sources"]["camera"]["asset_id"], "camera-asset")
        self.assertEqual(cue["sources"]["camera"]["enabled"], True)
        self.assertEqual(cue["sources"]["audio"]["asset_id"], "audio-asset")
        self.assertEqual(cue["camera"]["shape"], "circle")
        self.assertEqual(cue["camera"]["corner"], "top_left")
        self.assertEqual(cue["timing"]["duration_seconds"], 22.5)

    def test_normalizes_legacy_fullscreen_layout_alias(self):
        cues = normalize_layout_cues([
            {
                "id": "legacy-layout",
                "layout": "single_source_fullscreen",
                "source_role": "primary_timeline",
                "start_time": 3,
                "shape": "circle",
                "corner": "top_right",
            }
        ], duration_seconds=50.0)

        cue = cues[0]
        self.assertEqual(cue["layout"], "full_screen_source")
        self.assertEqual(cue["compatible_from_layout"], "single_source_fullscreen")
        self.assertEqual(cue["sources"]["screen"]["track"], "primary_timeline")
        self.assertEqual(cue["sources"]["camera"]["enabled"], False)
        self.assertEqual(cue["timing"]["start_time"], 3.0)
        self.assertEqual(cue["timing"]["end_time"], 50.0)
        self.assertEqual(cue["camera"]["shape"], "circle")
        self.assertEqual(cue["camera"]["corner"], "top_right")

    def test_normalizes_existing_plan_layout_cues_without_dropping_unknown_fields(self):
        payload = normalize_plan_payload({
            "schema_version": "phase6.edit-plan.v2",
            "summary": {"original_duration_seconds": 120.0},
            "segments": [],
            "layout_cues": [
                {
                    "id": "layout-side-by-side",
                    "layout": "side_by_side",
                    "unknown_future_field": {"keep": True},
                    "output": {"aspect_ratio": "4:3"},
                }
            ],
        })

        cue = payload["layout_cues"][0]
        self.assertEqual(cue["layout"], "side_by_side")
        self.assertEqual(cue["sources"]["screen"]["enabled"], True)
        self.assertEqual(cue["sources"]["camera"]["enabled"], True)
        self.assertEqual(cue["sources"]["audio"]["enabled"], True)
        self.assertEqual(cue["output"]["aspect_ratio"], "4:3")
        self.assertEqual(cue["unknown_future_field"], {"keep": True})


if __name__ == "__main__":
    unittest.main()
