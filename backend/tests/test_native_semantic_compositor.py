import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from services.native_semantic_compositor import render_semantic_plan_with_ffmpeg  # noqa: E402


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
class NativeSemanticCompositorTests(unittest.IsolatedAsyncioTestCase):
    async def test_renders_ranged_layouts_with_audio_video_drift_under_50ms(self):
        with tempfile.TemporaryDirectory(prefix="aive-native-") as temp_dir:
            root = Path(temp_dir)
            source = root / "source.mp4"
            output = root / "output.mp4"
            slide = root / "slide.png"

            subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=4",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=4",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(source),
                ],
                check=True,
            )
            subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "color=c=0x1f4b99:s=640x360",
                    "-frames:v", "1", "-update", "1", str(slide),
                ],
                check=True,
            )

            render_plan = {
                "slides": [{"id": "slide-1", "image_path": str(slide)}],
                "scenes": [
                    {
                        "id": "scene-slide",
                        "start_time": 0.0,
                        "end_time": 2.0,
                        "duration_seconds": 2.0,
                        "source_start_time": 0.0,
                        "source_end_time": 2.0,
                        "layout": "full_screen_source",
                        "slide_id": "slide-1",
                        "camera": {"enabled": False},
                    },
                    {
                        "id": "scene-camera",
                        "start_time": 2.0,
                        "end_time": 4.0,
                        "duration_seconds": 2.0,
                        "source_start_time": 2.0,
                        "source_end_time": 4.0,
                        "layout": "picture_in_picture",
                        "slide_id": "slide-1",
                        "camera": {
                            "enabled": True,
                            "shape": "circle",
                            "size": "small",
                            "corner": "bottom_left",
                            "margin_percent": 6,
                        },
                        "transition": {"type": "crossfade", "duration_seconds": 0.25},
                    },
                ],
            }
            await render_semantic_plan_with_ffmpeg(
                render_plan=render_plan,
                source_video_path=str(source),
                output_path=str(output),
                work_dir=str(root / "work"),
                output_width=640,
                output_height=360,
                fps=30,
                video_bitrate="4M",
                audio_bitrate="192k",
            )

            probe = subprocess.run(
                [
                    "ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration",
                    "-of", "json", str(output),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            streams = json.loads(probe.stdout)["streams"]
            durations = {item["codec_type"]: float(item["duration"]) for item in streams}
            self.assertAlmostEqual(durations["video"], 4.0, delta=0.05)
            self.assertAlmostEqual(durations["audio"], 4.0, delta=0.05)
            self.assertLess(abs(durations["video"] - durations["audio"]), 0.05)

    async def test_thirty_one_scenes_render_without_unbounded_filter_graph(self):
        with tempfile.TemporaryDirectory(prefix="aive-native-many-") as temp_dir:
            root = Path(temp_dir)
            source = root / "source.mp4"
            output = root / "output.mp4"
            slide = root / "slide.png"
            duration = 12.4
            subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", f"testsrc2=size=640x360:rate=30:duration={duration}",
                    "-f", "lavfi", "-i", f"sine=frequency=440:sample_rate=48000:duration={duration}",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-shortest", str(source),
                ],
                check=True,
            )
            subprocess.run(
                [
                    "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                    "-f", "lavfi", "-i", "color=c=0x1f4b99:s=640x360",
                    "-frames:v", "1", "-update", "1", str(slide),
                ],
                check=True,
            )
            scenes = []
            for index in range(31):
                start = index * 0.4
                scenes.append(
                    {
                        "id": f"scene-{index}",
                        "start_time": start,
                        "end_time": start + 0.4,
                        "duration_seconds": 0.4,
                        "source_start_time": start,
                        "source_end_time": start + 0.4,
                        "layout": "full_screen_source" if index % 2 == 0 else "picture_in_picture",
                        "slide_id": "slide-1",
                        "camera": {"enabled": index % 2 == 1},
                    }
                )
            progress_messages = []
            await render_semantic_plan_with_ffmpeg(
                render_plan={"slides": [{"id": "slide-1", "image_path": str(slide)}], "scenes": scenes},
                source_video_path=str(source),
                output_path=str(output),
                work_dir=str(root / "work"),
                output_width=640,
                output_height=360,
                fps=30,
                video_bitrate="4M",
                audio_bitrate="192k",
                progress_callback=lambda value, message: progress_messages.append((value, message)),
            )
            self.assertTrue(output.is_file())
            self.assertTrue(any("scene 31/31" in message for _, message in progress_messages))
            self.assertFalse((root / "work" / "bounded_scenes").exists())
            probe = subprocess.run(
                [
                    "ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration",
                    "-of", "json", str(output),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            streams = json.loads(probe.stdout)["streams"]
            durations = {item["codec_type"]: float(item["duration"]) for item in streams}
            self.assertAlmostEqual(durations["video"], duration, delta=0.12)
            self.assertAlmostEqual(durations["audio"], duration, delta=0.12)
            self.assertLess(abs(durations["video"] - durations["audio"]), 0.05)


if __name__ == "__main__":
    unittest.main()
