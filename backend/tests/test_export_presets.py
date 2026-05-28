import sys
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))


from services.edit_plan_payload import normalize_plan_payload, update_export_metadata
from services.export_presets import (
    DEFAULT_EXPORT_PRESET_ID,
    get_export_preset,
    list_grouped_export_presets,
)


class ExportPresetCatalogTests(unittest.TestCase):
    def test_catalog_groups_required_presets(self):
        catalog = list_grouped_export_presets()

        groups = {group["id"]: group for group in catalog["groups"]}
        self.assertEqual(set(groups), {"social", "professional", "education"})
        self.assertEqual(catalog["default_preset_id"], DEFAULT_EXPORT_PRESET_ID)

        presets = {
            preset["id"]: preset
            for group in catalog["groups"]
            for preset in group["presets"]
        }

        self.assertEqual(
            set(presets),
            {
                "youtube_1080p",
                "youtube_4k",
                "tiktok_reels",
                "instagram",
                "linkedin",
                "mp4_1080p",
                "mp4_720p",
                "lms_compatible",
                "podcast_audio",
            },
        )
        self.assertEqual(presets["youtube_4k"]["width"], 3840)
        self.assertEqual(presets["tiktok_reels"]["aspect_ratio"], "9:16")
        self.assertTrue(presets["podcast_audio"]["audio_only"])
        self.assertEqual(presets["lms_compatible"]["group_id"], "education")

    def test_unknown_preset_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Unknown export preset"):
            get_export_preset("not-real")

    def test_selected_preset_can_be_stored_in_export_metadata(self):
        preset = get_export_preset("linkedin")
        payload = update_export_metadata(
            normalize_plan_payload(None),
            target_presets=[preset["id"]],
        )
        payload["export_metadata"]["selected_preset"] = preset

        normalized = normalize_plan_payload(payload)

        self.assertEqual(normalized["export_metadata"]["target_presets"], ["linkedin"])
        self.assertEqual(normalized["export_metadata"]["selected_preset"]["label"], "LinkedIn")


if __name__ == "__main__":
    unittest.main()
