import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "scripts" / "generate_synthetic_test_media.py"
SOURCE_DIR = REPO_ROOT / "fixtures" / "synthetic_media" / "source"

spec = importlib.util.spec_from_file_location("generate_synthetic_test_media", SCRIPT_PATH)
synthetic_media = importlib.util.module_from_spec(spec)
sys.modules["generate_synthetic_test_media"] = synthetic_media
spec.loader.exec_module(synthetic_media)


class SyntheticMediaFixtureTests(unittest.TestCase):
    def test_source_manifest_covers_required_private_safe_assets(self):
        manifest = json.loads((SOURCE_DIR / "synthetic_lecture_manifest.json").read_text(encoding="utf-8"))
        assets = manifest["assets"]
        source_types = {asset["source_type"] for asset in assets}

        self.assertFalse(manifest["privacy"]["contains_private_recordings"])
        self.assertFalse(manifest["privacy"]["contains_real_student_data"])
        self.assertIn("mixed_video", source_types)
        self.assertIn("screen_recording", source_types)
        self.assertIn("webcam_recording", source_types)
        self.assertIn("separate_audio", source_types)
        self.assertIn("slide_deck", source_types)
        self.assertIn("transcript", source_types)

        for asset in assets:
            self.assertFalse(Path(asset["relative_path"]).is_absolute())

    def test_metadata_generation_writes_word_level_transcript_and_sidecars(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            outputs = synthetic_media.write_metadata_fixtures(output_dir, force=True, skip_pptx=True)

            transcript = json.loads(outputs["transcript_path"].read_text(encoding="utf-8"))
            manifest = json.loads(outputs["manifest_path"].read_text(encoding="utf-8"))
            words = transcript["words"]

            self.assertGreater(len(words), len(transcript["segments"]))
            self.assertEqual(words[0]["segment_id"], "seg-001")
            self.assertGreaterEqual(words[0]["start"], transcript["segments"][0]["start_time"])
            self.assertLessEqual(words[-1]["end"], transcript["segments"][-1]["end_time"])
            self.assertIn("WEBVTT", outputs["vtt_path"].read_text(encoding="utf-8"))
            self.assertIn("00:00:12,000 --> 00:00:26,000", outputs["srt_path"].read_text(encoding="utf-8"))
            self.assertEqual(len(outputs["slide_svg_paths"]), 5)
            self.assertEqual(manifest["generated_sidecars"]["slide_svgs"][0], "slides/slide_01.svg")

    def test_generation_plan_names_all_demo_media_outputs(self):
        planned = "\n".join(synthetic_media.describe_generation_plan(Path("generated")))

        self.assertIn("lecture_video.mp4", planned)
        self.assertIn("screen_recording.mp4", planned)
        self.assertIn("webcam_recording.mp4", planned)
        self.assertIn("separate_audio.wav", planned)
        self.assertIn("synthetic_lecture_slides.pptx", planned)
        self.assertIn("synthetic_lecture_transcript.json", planned)


if __name__ == "__main__":
    unittest.main()
