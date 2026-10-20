import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from services.native_semantic_compositor import render_semantic_plan_with_ffmpeg  # noqa: E402
from services import native_semantic_compositor as compositor  # noqa: E402


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



class RenderProxyLifecycleTests(unittest.IsolatedAsyncioTestCase):
    """Small mocked inputs exercise ownership; no media process is started."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="aive-proxy-unit-")
        self.addCleanup(self.temporary.cleanup)
        self.source = Path(self.temporary.name) / "camera.mov"
        self.source.write_bytes(b"original-source")
        real_getsize = os.path.getsize

        def source_size(path):
            if os.fspath(path) == str(self.source):
                return 512 * 1024 * 1024
            return real_getsize(path)

        self.enterContext(patch.object(compositor.os.path, "getsize", side_effect=source_size))
        self.enterContext(patch.object(compositor, "_proxy_locks", {}))
        self.enterContext(patch.object(compositor, "ffmpeg_binary", return_value="mock-ffmpeg"))
        self.enterContext(patch.object(compositor.FFmpegService, "_video_encoder_args",
                                       return_value=["-c:v", "h264_nvenc"]))
        self.enterContext(patch("services.ffmpeg.settings.FFMPEG_HARDWARE_FALLBACK_TO_CPU", True))

    def proxy_paths(self):
        stat = self.source.stat()
        identity = f"{self.source.absolute()}:{stat.st_size}:{stat.st_mtime_ns}:1920x1080:30"
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
        proxy = self.source.parent / ".aive-proxies" / f"{digest}.mp4"
        return proxy, Path(f"{proxy}.partial.mp4")

    async def ensure_proxy(self, cancel_check=None, progress_callback=None):
        return await compositor._ensure_render_proxy(
            source_video_path=str(self.source), output_width=1920,
            output_height=1080, fps=30, progress_callback=progress_callback,
            cancel_check=cancel_check,
        )

    async def test_cancel_callback_cleans_partial_without_hardware_retry(self):
        proxy, partial = self.proxy_paths()
        abort = RuntimeError("render cancelled")
        cancelled = False

        def check():
            if cancelled:
                raise abort

        async def run(command, **kwargs):
            nonlocal cancelled
            partial.write_bytes(b"incomplete")
            cancelled = True
            kwargs["cancel_check"]()
            self.fail("Cancellation did not propagate")

        with patch.object(compositor.FFmpegService, "_run_process", new_callable=AsyncMock) as run_process:
            run_process.side_effect = run
            with self.assertRaises(RuntimeError) as error:
                await self.ensure_proxy(check)
        self.assertIs(error.exception, abort)
        self.assertEqual(run_process.await_count, 1)
        self.assertFalse(partial.exists())
        self.assertFalse(proxy.exists())
        self.assertEqual(self.source.read_bytes(), b"original-source")

    async def test_task_cancellation_settles_owner_before_partial_cleanup(self):
        proxy, partial = self.proxy_paths()
        started = asyncio.Event()
        settled = asyncio.Event()

        async def run(command, **kwargs):
            partial.write_bytes(b"incomplete")
            started.set()
            try:
                while True:
                    await asyncio.sleep(0.01)
                    kwargs["cancel_check"]()
            finally:
                self.assertTrue(partial.exists(), "Partial removed before process owner settled")
                settled.set()

        with patch.object(compositor.FFmpegService, "_run_process", new_callable=AsyncMock) as run_process:
            run_process.side_effect = run
            task = asyncio.create_task(self.ensure_proxy())
            try:
                await asyncio.wait_for(started.wait(), 1)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(task, 1)
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        self.assertTrue(settled.is_set())
        self.assertEqual(run_process.await_count, 1)
        self.assertFalse(partial.exists())
        self.assertFalse(proxy.exists())

    async def test_cancel_after_hardware_failure_prevents_cpu_retry(self):
        _, partial = self.proxy_paths()
        cancelled = False
        abort = RuntimeError("cancelled after hardware failure")

        def check():
            if cancelled:
                raise abort

        async def run(command, **kwargs):
            nonlocal cancelled
            partial.write_bytes(b"incomplete")
            cancelled = True
            return b"", b"hardware failure", 1

        with patch.object(compositor.FFmpegService, "_run_process", new_callable=AsyncMock) as run_process:
            run_process.side_effect = run
            with self.assertRaises(RuntimeError) as error:
                await self.ensure_proxy(check)
        self.assertIs(error.exception, abort)
        self.assertEqual(run_process.await_count, 1)
        self.assertFalse(partial.exists())

    async def test_cpu_fallback_failure_cleans_partial_preserves_completed_file(self):
        proxy, partial = self.proxy_paths()
        proxy.parent.mkdir()
        proxy.write_bytes(b"previous-completed-proxy")
        commands = []

        async def run(command, **kwargs):
            commands.append(command)
            partial.write_bytes(b"failed-output")
            if len(commands) == 1:
                return b"", b"hardware failure", 1
            raise RuntimeError("CPU fallback failed")

        with patch.object(compositor.FFmpegService, "_run_process", new_callable=AsyncMock) as run_process:
            run_process.side_effect = run
            with self.assertRaisesRegex(RuntimeError, "CPU fallback failed"):
                await self.ensure_proxy()
        self.assertEqual(run_process.await_count, 2)
        self.assertIn("h264_nvenc", commands[0])
        self.assertIn("libx264", commands[1])
        self.assertFalse(partial.exists())
        self.assertEqual(proxy.read_bytes(), b"previous-completed-proxy")

    async def test_success_promotes_partial_then_reuses_cache_without_process(self):
        proxy, partial = self.proxy_paths()

        async def run(command, **kwargs):
            partial.write_bytes(b"x" * (1024 * 1024 + 1))
            return b"", b"", 0

        with patch.object(compositor.FFmpegService, "_run_process", new_callable=AsyncMock) as run_process:
            run_process.side_effect = run
            self.assertEqual(await self.ensure_proxy(), str(proxy))
            self.assertFalse(partial.exists())
            completed = proxy.read_bytes()
            self.assertEqual(await self.ensure_proxy(), str(proxy))
        self.assertEqual(run_process.await_count, 1)
        self.assertEqual(proxy.read_bytes(), completed)
        self.assertEqual(self.source.read_bytes(), b"original-source")

    async def test_cancel_before_work_leaves_cache_and_directories_untouched(self):
        abort = RuntimeError("already cancelled")

        def check():
            raise abort

        with patch.object(compositor.FFmpegService, "_run_process", new_callable=AsyncMock) as run_process:
            with self.assertRaises(RuntimeError) as error:
                await self.ensure_proxy(check)
        self.assertIs(error.exception, abort)
        run_process.assert_not_awaited()
        self.assertFalse((self.source.parent / ".aive-proxies").exists())

    async def test_cancellation_while_waiting_lock_does_not_return_cached_proxy(self):
        proxy, partial = self.proxy_paths()
        proxy.parent.mkdir()
        proxy.write_bytes(b"x" * (1024 * 1024 + 1))
        lock = asyncio.Lock()
        compositor._proxy_locks[str(proxy)] = lock
        await lock.acquire()
        entered = asyncio.Event()
        cancelled = False
        abort = RuntimeError("cancelled while queued")

        def check():
            entered.set()
            if cancelled:
                raise abort

        with patch.object(compositor.FFmpegService, "_run_process", new_callable=AsyncMock) as run_process:
            task = asyncio.create_task(self.ensure_proxy(check))
            try:
                await asyncio.wait_for(entered.wait(), 1)
                cancelled = True
                lock.release()
                with self.assertRaises(RuntimeError) as error:
                    await task
            finally:
                if lock.locked():
                    lock.release()
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        self.assertIs(error.exception, abort)
        run_process.assert_not_awaited()
        self.assertEqual(proxy.stat().st_size, 1024 * 1024 + 1)
        self.assertFalse(partial.exists())


if __name__ == "__main__":
    unittest.main()
