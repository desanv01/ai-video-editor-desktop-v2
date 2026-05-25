import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from services.ffmpeg import FFmpegService  # noqa: E402
from services.layout_model import build_layout_cue  # noqa: E402
import services.renderer as renderer  # noqa: E402


class PictureInPictureCommandTests(unittest.TestCase):
    def test_builds_pip_command_with_separate_audio_and_sync_offsets(self):
        cmd = FFmpegService.build_picture_in_picture_command(
            screen_path="screen.mp4",
            camera_path="camera.mp4",
            audio_path="voice.wav",
            output_path="out.mp4",
            start_time=10.0,
            end_time=20.0,
            camera_sync_offset=0.4,
            audio_sync_offset=0.2,
            camera_corner="top_left",
        )

        self.assertEqual(cmd[0], "ffmpeg")
        self.assertIn("screen.mp4", cmd)
        self.assertIn("camera.mp4", cmd)
        self.assertIn("voice.wav", cmd)
        self.assertIn("9.6", cmd)
        self.assertIn("9.8", cmd)
        self.assertIn("2:a?", cmd)
        filter_complex = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("scale=1920:1080", filter_complex)
        self.assertIn("overlay=43:43", filter_complex)
        self.assertIn("format=rgba", filter_complex)
        self.assertIn("geq=", filter_complex)

    def test_builds_pip_command_with_screen_audio_fallback(self):
        cmd = FFmpegService.build_picture_in_picture_command(
            screen_path="screen.mp4",
            camera_path="camera.mp4",
            output_path="out.mp4",
            start_time=0.0,
            end_time=5.0,
        )

        self.assertEqual(cmd.count("-i"), 2)
        self.assertIn("0:a?", cmd)

    def test_rectangle_shape_uses_unmasked_camera_overlay(self):
        cmd = FFmpegService.build_picture_in_picture_command(
            screen_path="screen.mp4",
            camera_path="camera.mp4",
            output_path="out.mp4",
            start_time=0.0,
            end_time=5.0,
            camera_shape="rectangle",
        )

        filter_complex = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("force_original_aspect_ratio=decrease", filter_complex)
        self.assertIn("pad=498:280", filter_complex)
        self.assertNotIn("geq=", filter_complex)

    def test_circle_shape_uses_square_crop_and_alpha_mask(self):
        cmd = FFmpegService.build_picture_in_picture_command(
            screen_path="screen.mp4",
            camera_path="camera.mp4",
            output_path="out.mp4",
            start_time=0.0,
            end_time=5.0,
            camera_shape="circle",
        )

        filter_complex = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("scale=486:486:force_original_aspect_ratio=increase", filter_complex)
        self.assertIn("crop=486:486", filter_complex)
        self.assertIn("format=rgba", filter_complex)
        self.assertIn("geq=", filter_complex)
        self.assertIn("overlay=1391:551", filter_complex)


class PictureInPictureRenderSelectionTests(unittest.IsolatedAsyncioTestCase):
    def test_splits_range_around_picture_in_picture_cue(self):
        cue = build_layout_cue(
            cue_id="pip-1",
            layout="picture_in_picture",
            start_time=10.0,
            end_time=20.0,
            screen_source_id="screen",
            camera_source_id="camera",
        )
        spans = renderer._layout_spans_for_range(
            {
                "source_start_time": 0.0,
                "source_end_time": 30.0,
            },
            [cue],
        )

        self.assertEqual([(start, end) for start, end, _ in spans], [(0.0, 10.0), (10.0, 20.0), (20.0, 30.0)])
        self.assertIsNone(spans[0][2])
        self.assertEqual(spans[1][2]["layout"], "picture_in_picture")
        self.assertIsNone(spans[2][2])

    async def test_renders_only_pip_span_with_compositor(self):
        class FakeFFmpeg:
            def __init__(self):
                self.trim_calls = []
                self.pip_calls = []

            async def trim_video(self, **kwargs):
                self.trim_calls.append(kwargs)
                Path(kwargs["output_path"]).write_text("trim", encoding="utf-8")

            async def render_picture_in_picture_clip(self, **kwargs):
                self.pip_calls.append(kwargs)
                Path(kwargs["output_path"]).write_text("pip", encoding="utf-8")

            async def trim_silence_from_clip(self, **kwargs):
                Path(kwargs["output_path"]).write_text("short", encoding="utf-8")

        fake = FakeFFmpeg()
        original_ffmpeg = renderer.ffmpeg_service
        renderer.ffmpeg_service = fake
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                cue = build_layout_cue(
                    cue_id="pip-1",
                    layout="picture_in_picture",
                    start_time=10.0,
                    end_time=20.0,
                    screen_source_id="screen",
                    camera_source_id="camera",
                    audio_source_id="audio",
                )
                context = renderer.LayoutRenderContext(
                    cues=[cue],
                    assets_by_id={
                        "screen": SimpleNamespace(file_path="screen.mp4", sync_offset_seconds=0.0),
                        "camera": SimpleNamespace(file_path="camera.mp4", sync_offset_seconds=0.4),
                        "audio": SimpleNamespace(file_path="voice.wav", sync_offset_seconds=0.2),
                    },
                )

                clip_paths, layout_clip_count = await renderer._render_range_clips(
                    video=SimpleNamespace(file_path="legacy.mp4"),
                    render_range={
                        "source_start_time": 0.0,
                        "source_end_time": 30.0,
                        "action": "keep",
                    },
                    range_index=0,
                    clip_dir=temp_dir,
                    layout_context=context,
                )

            self.assertEqual(len(clip_paths), 3)
            self.assertEqual(layout_clip_count, 1)
            self.assertEqual(len(fake.trim_calls), 2)
            self.assertEqual(len(fake.pip_calls), 1)
            self.assertEqual(fake.pip_calls[0]["screen_path"], "screen.mp4")
            self.assertEqual(fake.pip_calls[0]["camera_sync_offset"], 0.4)
            self.assertEqual(fake.pip_calls[0]["audio_path"], "voice.wav")
            self.assertEqual(fake.pip_calls[0]["camera_shape"], "rounded_rectangle")
        finally:
            renderer.ffmpeg_service = original_ffmpeg


if __name__ == "__main__":
    unittest.main()
