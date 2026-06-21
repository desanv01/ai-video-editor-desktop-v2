import asyncio
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


APP_DIR = Path(__file__).resolve().parents[1] / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from services.ffmpeg import FFmpegService  # noqa: E402
from services.layout_model import build_layout_cue  # noqa: E402
from services.render_jobs import RenderCancelled  # noqa: E402
from config import settings  # noqa: E402
import services.renderer as renderer  # noqa: E402


class PictureInPictureCommandTests(unittest.TestCase):
    def test_builds_trim_audio_command_with_sync_offset_and_podcast_bitrate(self):
        cmd = FFmpegService.build_trim_audio_command(
            input_path="voice.wav",
            output_path="lecture.m4a",
            start_time=12.0,
            end_time=20.0,
            sync_offset=0.5,
            audio_codec="aac",
            audio_bitrate="192 kbps",
        )

        self.assertEqual(cmd[0], "ffmpeg")
        self.assertIn("11.5", cmd)
        self.assertIn("8.0", cmd)
        self.assertIn("-vn", cmd)
        self.assertIn("0:a?", cmd)
        self.assertIn("192k", cmd)

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


class LayoutModeCommandTests(unittest.TestCase):
    def test_builds_side_by_side_command_with_equal_panels_and_audio_master(self):
        cmd = FFmpegService.build_side_by_side_command(
            screen_path="screen.mp4",
            camera_path="camera.mp4",
            audio_path="voice.wav",
            output_path="out.mp4",
            start_time=10.0,
            end_time=18.0,
            screen_sync_offset=1.0,
            camera_sync_offset=0.25,
            audio_sync_offset=0.5,
        )

        self.assertEqual(cmd[0], "ffmpeg")
        self.assertIn("9.0", cmd)
        self.assertIn("9.75", cmd)
        self.assertIn("9.5", cmd)
        self.assertIn("2:a?", cmd)
        filter_complex = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("scale=960:1080", filter_complex)
        self.assertIn("pad=960:1080", filter_complex)
        self.assertIn("hstack=inputs=2", filter_complex)

    def test_builds_full_source_command_with_canvas_fit_and_audio_fallback(self):
        cmd = FFmpegService.build_full_source_command(
            source_path="screen.mp4",
            output_path="out.mp4",
            start_time=2.0,
            end_time=5.0,
            output_width=1440,
            output_height=1080,
        )

        self.assertEqual(cmd.count("-i"), 1)
        self.assertIn("0:a?", cmd)
        filter_complex = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("scale=1440:1080", filter_complex)
        self.assertIn("pad=1440:1080", filter_complex)

    def test_builds_clip_fade_command_for_transition_polish(self):
        cmd = FFmpegService.build_clip_fade_command(
            input_path="clip.mp4",
            output_path="faded.mp4",
            clip_duration_seconds=8.0,
            fade_duration_seconds=0.5,
            fade_in=True,
            fade_out=True,
        )

        self.assertEqual(cmd[0], "ffmpeg")
        self.assertIn("clip.mp4", cmd)
        video_filter = cmd[cmd.index("-vf") + 1]
        self.assertIn("fade=t=in:st=0:d=0.5", video_filter)
        self.assertIn("fade=t=out:st=7.5:d=0.5", video_filter)

    def test_builds_concat_transition_command_for_crossfade_and_wipe(self):
        cmd = FFmpegService.build_concat_with_transitions_command(
            clip_paths=["one.mp4", "two.mp4", "three.mp4"],
            clip_durations=[4.0, 5.0, 6.0],
            transitions=[
                {"boundary_index": 0, "transition": "crossfade", "duration_seconds": 0.5},
                {"boundary_index": 1, "transition": "wipe_left", "duration_seconds": 0.4},
            ],
            output_path="out.mp4",
            output_width=1280,
            output_height=720,
        )

        self.assertEqual(cmd[0], "ffmpeg")
        self.assertEqual(cmd.count("-i"), 3)
        filter_complex = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("scale=1280:720", filter_complex)
        self.assertIn("pad=1280:720", filter_complex)
        self.assertIn("xfade=transition=fade:duration=0.5:offset=3.5", filter_complex)
        self.assertIn("xfade=transition=wipeleft:duration=0.4:offset=8.1", filter_complex)
        self.assertIn("acrossfade=d=0.5", filter_complex)
        self.assertIn("acrossfade=d=0.4", filter_complex)

    def test_slideshow_concat_path_escaping_normalizes_windows_paths(self):
        escaped = FFmpegService._concat_file_path(r"C:\slides\week 1\page'one.png")

        self.assertEqual(escaped, "C:/slides/week 1/page'\\''one.png")

    def test_render_validation_rejects_short_video_stream(self):
        with self.assertRaisesRegex(RuntimeError, "video stream is too short"):
            renderer._validate_rendered_video_output(
                metadata={
                    "has_video": True,
                    "duration": 436.98,
                    "video_duration": 87.43,
                    "audio_duration": 436.98,
                    "video_frame_count": 2100,
                },
                expected_duration=436.0,
                output_path="broken.mp4",
            )

    def test_maps_supported_aspect_ratios_to_even_render_canvases(self):
        self.assertEqual(FFmpegService.output_dimensions_for_aspect_ratio("16:9"), (1920, 1080))
        self.assertEqual(FFmpegService.output_dimensions_for_aspect_ratio("4:3"), (1440, 1080))
        self.assertEqual(FFmpegService.output_dimensions_for_aspect_ratio("1:1"), (1080, 1080))
        self.assertEqual(FFmpegService.output_dimensions_for_aspect_ratio("9:16"), (1080, 1920))

    def test_builds_subtitle_burn_style_from_caption_policy(self):
        style = FFmpegService._subtitle_force_style(
            font_size=30,
            placement="top_center",
            style={"primary_color": "#F8FAFC", "outline_color": "#111827", "background": "box"},
        )

        self.assertIn("FontSize=30", style)
        self.assertIn("Alignment=8", style)
        self.assertIn("BorderStyle=3", style)
        self.assertIn("PrimaryColour=&H00FCFAF8", style)

    def test_hardware_encoder_auto_prefers_nvenc_when_available(self):
        original_mode = settings.FFMPEG_HARDWARE_ACCELERATION
        original_cache = FFmpegService._encoder_cache
        try:
            settings.FFMPEG_HARDWARE_ACCELERATION = "auto"
            FFmpegService._encoder_cache = {"h264_nvenc", "h264_qsv"}

            self.assertEqual(FFmpegService._preferred_h264_encoder(), "h264_nvenc")
        finally:
            settings.FFMPEG_HARDWARE_ACCELERATION = original_mode
            FFmpegService._encoder_cache = original_cache

    def test_hardware_encoder_command_can_fallback_to_cpu(self):
        cmd = [
            "ffmpeg",
            "-i",
            "input.mp4",
            "-c:v",
            "h264_nvenc",
            "-preset",
            "p4",
            "-rc",
            "vbr",
            "-cq",
            "20",
            "-c:a",
            "aac",
            "out.mp4",
        ]

        fallback = FFmpegService._cpu_fallback_command(cmd)

        self.assertIn("libx264", fallback)
        self.assertIn("veryfast", fallback)
        self.assertNotIn("h264_nvenc", fallback)
        self.assertNotIn("p4", fallback)
        self.assertNotIn("-rc", fallback)
        self.assertNotIn("-cq", fallback)

    def test_slideshow_single_image_does_not_use_concat_filter(self):
        captured = {}

        async def fake_run(cmd, **_kwargs):
            captured["cmd"] = cmd
            return b"", b"", 0

        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "slide.png"
            image_path.write_text("fake", encoding="utf-8")
            output_path = Path(temp_dir) / "slides.mp4"
            with patch.object(FFmpegService, "_run_process_with_encoder_fallback", new=fake_run):
                asyncio.run(
                    FFmpegService.create_slideshow_clip(
                        str(output_path),
                        image_paths=[str(image_path)],
                        durations=[437.04],
                    )
                )

        cmd = captured["cmd"]
        filter_complex = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("trim=duration=437.040", filter_complex)
        self.assertNotIn("concat=n=1", filter_complex)
        self.assertIn("-t", cmd)
        self.assertIn("437.040", cmd)

    def test_slideshow_multiple_images_use_single_concat_input(self):
        captured = {}

        async def fake_run(cmd, **_kwargs):
            captured["cmd"] = cmd
            manifest_path = Path(cmd[cmd.index("-i") + 1])
            captured["manifest"] = manifest_path.read_text(encoding="utf-8")
            return b"", b"", 0

        with tempfile.TemporaryDirectory() as temp_dir:
            image_paths = []
            for index in range(36):
                image_path = Path(temp_dir) / f"slide-{index:02d}.png"
                image_path.write_text("fake", encoding="utf-8")
                image_paths.append(str(image_path))
            output_path = Path(temp_dir) / "slides.mp4"
            with patch.object(FFmpegService, "_run_process_with_encoder_fallback", new=fake_run):
                asyncio.run(
                    FFmpegService.create_slideshow_clip(
                        str(output_path),
                        image_paths=image_paths,
                        durations=[1.25] * len(image_paths),
                    )
                )

            self.assertFalse(Path(f"{output_path}.ffconcat").exists())

        cmd = captured["cmd"]
        self.assertEqual(cmd.count("-i"), 2)
        self.assertEqual(cmd[cmd.index("-f") + 1], "concat")
        self.assertNotIn("concat=n=36", cmd[cmd.index("-filter_complex") + 1])
        self.assertEqual(captured["manifest"].count("duration 1.250000"), 36)
        self.assertEqual(captured["manifest"].count("file '"), 37)

    def test_ffmpeg_error_message_keeps_actionable_tail(self):
        stderr = b"ffmpeg version banner\n" + (b"x" * 100) + b"\nResource temporarily unavailable\nConversion failed!"

        message = FFmpegService._stderr_message(stderr, 80)

        self.assertTrue(message.startswith("[earlier FFmpeg output omitted]"))
        self.assertIn("Resource temporarily unavailable", message)
        self.assertIn("Conversion failed!", message)

    def test_caption_srt_can_target_highlight_ranges_only(self):
        first = SimpleNamespace(id="seg-1", text="Keep this normal explanation.", topic_label="Intro")
        second = SimpleNamespace(id="seg-2", text="Highlight this important theorem.", topic_label="Proof")
        render_ranges = [
            {
                "segment_id": "seg-1",
                "segment": first,
                "source_start_time": 0.0,
                "source_end_time": 3.0,
                "output_start_time": 0.0,
                "output_end_time": 3.0,
                "duration": 3.0,
                "action": "keep",
            },
            {
                "segment_id": "seg-2",
                "segment": second,
                "source_start_time": 3.0,
                "source_end_time": 7.0,
                "output_start_time": 3.0,
                "output_end_time": 7.0,
                "duration": 4.0,
                "action": "highlight",
            },
        ]

        srt = renderer._generate_word_level_srt(
            render_ranges,
            None,
            caption_policy={"enabled": True, "appearance": "highlight_segments"},
        )

        self.assertNotIn("normal explanation", srt)
        self.assertIn("important theorem", srt)
        self.assertIn("00:00:03,000", srt)

    def test_caption_srt_respects_disabled_policy(self):
        segment = SimpleNamespace(id="seg-1", text="This should not appear.", topic_label="Intro")
        srt = renderer._generate_word_level_srt(
            [{
                "segment_id": "seg-1",
                "segment": segment,
                "source_start_time": 0.0,
                "source_end_time": 3.0,
                "output_start_time": 0.0,
                "output_end_time": 3.0,
                "duration": 3.0,
                "action": "keep",
            }],
            None,
            caption_policy={"enabled": False, "export_behavior": "none"},
        )

        self.assertEqual(srt, "")

    def test_annotation_events_map_source_timeline_to_output_ranges(self):
        annotations = [
            {
                "id": "callout-1",
                "kind": "annotation",
                "status": "active",
                "annotation_type": "callout",
                "text": "Key formula",
                "start_time": 2.0,
                "end_time": 8.0,
                "position": "top_right",
                "x_percent": 78.0,
                "y_percent": 12.0,
                "style": {"font_size": 28},
                "pointer": {"enabled": True, "direction": "left"},
            },
        ]
        render_ranges = [
            {
                "source_start_time": 0.0,
                "source_end_time": 4.0,
                "output_start_time": 0.0,
                "output_end_time": 4.0,
            },
            {
                "source_start_time": 6.0,
                "source_end_time": 10.0,
                "output_start_time": 4.0,
                "output_end_time": 8.0,
            },
        ]

        events = renderer._annotation_events_for_render_ranges(annotations, render_ranges)
        ass = renderer._generate_annotation_ass(events)

        self.assertEqual([(event["output_start_time"], event["output_end_time"]) for event in events], [(2.0, 4.0), (4.0, 6.0)])
        self.assertIn("<- Key formula", ass)
        self.assertIn("\\pos(1497,129)", ass)

    def test_educational_overlay_events_render_title_cards_and_step_labels(self):
        overlays = [
            {
                "id": "intro-1",
                "kind": "educational_overlay",
                "status": "active",
                "overlay_type": "intro_card",
                "title": "Course Setup",
                "subtitle": "Tools and workflow",
                "start_time": 0.0,
                "end_time": 4.0,
                "position": "center",
                "x_percent": 50.0,
                "y_percent": 50.0,
                "style": {"font_size": 44, "subtitle_font_size": 24, "accent_color": "#FACC15"},
            },
            {
                "id": "step-1",
                "kind": "educational_overlay",
                "status": "active",
                "overlay_type": "step_label",
                "title": "Install dependencies",
                "start_time": 8.0,
                "end_time": 12.0,
                "position": "top_left",
                "x_percent": 9.0,
                "y_percent": 10.0,
                "style": {"font_size": 28},
                "step_number": 1,
            },
        ]
        render_ranges = [
            {
                "source_start_time": 0.0,
                "source_end_time": 10.0,
                "output_start_time": 0.0,
                "output_end_time": 10.0,
            },
        ]

        events = renderer._annotation_events_for_render_ranges(overlays, render_ranges)
        ass = renderer._generate_annotation_ass(events)

        self.assertEqual([(event["output_start_time"], event["output_end_time"]) for event in events], [(0.0, 4.0), (8.0, 10.0)])
        self.assertIn("Course Setup", ass)
        self.assertIn("Tools and workflow", ass)
        self.assertIn("STEP 1: Install dependencies", ass)
        self.assertIn("\\an5\\pos(960,540)", ass)

    def test_end_card_ass_renders_summary_next_topic_and_course_link_cta(self):
        events = [
            {
                "id": "end-card-1",
                "kind": "end_card",
                "card_type": "course_link",
                "title": "What we learned",
                "message": "You can now set up the project.",
                "summary_points": ["Install the tools", "Run the first command"],
                "next_topic": "Data loading",
                "course_url": "https://example.edu/course",
                "button_text": "Open course",
                "duration_seconds": 6.0,
                "style": {"font_size": 42, "body_font_size": 24, "accent_color": "#22D3EE"},
                "animation": {"preset": "fade", "duration_seconds": 0.45},
                "output_start_time": 0.0,
                "output_end_time": 6.0,
                "position": "center",
                "x_percent": 50.0,
                "y_percent": 50.0,
            },
        ]

        ass = renderer._generate_annotation_ass(events)

        self.assertIn("What we learned", ass)
        self.assertIn("- Install the tools", ass)
        self.assertIn("Next: Data loading", ass)
        self.assertIn("Open course: https://example.edu/course", ass)
        self.assertIn("\\an5\\pos(960,540)", ass)


class FFmpegProcessCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_process_kills_active_subprocess_when_cancelled(self):
        class FakeProcess:
            def __init__(self):
                self.returncode = None
                self.killed = False

            async def communicate(self):
                while self.returncode is None:
                    await asyncio.sleep(0.01)
                return b"", b"killed"

            def kill(self):
                self.killed = True
                self.returncode = -9

        process = FakeProcess()

        async def create_process(*_args, **_kwargs):
            return process

        def cancel_check():
            raise RenderCancelled("Render cancelled by user")

        with patch("asyncio.create_subprocess_exec", new=create_process):
            with self.assertRaises(RenderCancelled):
                await FFmpegService._run_process(
                    ["ffmpeg", "-i", "input.mp4", "output.mp4"],
                    error_prefix="Render failed",
                    cancel_check=cancel_check,
                )

        self.assertTrue(process.killed)


class PictureInPictureRenderSelectionTests(unittest.IsolatedAsyncioTestCase):
    async def test_generates_exact_pdf_page_slideshow_for_uploaded_notes(self):
        try:
            import fitz
        except ImportError:
            self.skipTest("PyMuPDF is not installed in this local test environment")

        class FakeFFmpeg:
            def __init__(self):
                self.slideshow_calls = []

            async def create_slideshow_clip(self, output_path, **kwargs):
                self.slideshow_calls.append({"output_path": output_path, **kwargs})
                Path(output_path).write_text("slideshow", encoding="utf-8")

        fake = FakeFFmpeg()
        original_ffmpeg = renderer.ffmpeg_service
        original_temp_path = renderer.settings.TEMP_PATH
        renderer.ffmpeg_service = fake
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                renderer.settings.TEMP_PATH = temp_dir
                pdf_path = Path(temp_dir) / "lecture-notes.pdf"
                doc = fitz.open()
                page = doc.new_page(width=400, height=225)
                page.insert_textbox(fitz.Rect(32, 48, 360, 120), "Exact PDF Slide", fontsize=24)
                doc.save(pdf_path)
                doc.close()

                video = SimpleNamespace(id="video-pdf", duration_seconds=40.0)
                notes = SimpleNamespace(
                    id="notes-pdf",
                    role="notes",
                    kind="pdf_notes",
                    sync_role="structure_reference",
                    source_type="pdf_notes",
                    filename="lecture-notes.pdf",
                    original_filename="lecture-notes.pdf",
                    file_path=str(pdf_path),
                    metadata_json={
                        "structure_reference": {
                            "title": "Lecture Notes",
                            "reference_role": "pdf_notes",
                            "document_format": "pdf",
                            "items": [{"index": 1, "title": "Exact PDF Slide", "text": "Rendered from the PDF page."}],
                        }
                    },
                )

                generated = await renderer._generated_slide_background_asset(video, [notes], {"layout_cues": []})

                self.assertTrue(Path(fake.slideshow_calls[0]["image_paths"][0]).exists())

            self.assertIsNotNone(generated)
            self.assertEqual(generated.metadata_json["render_mode"], "rasterized_pages")
            self.assertEqual(generated.metadata_json["rasterized_slide_count"], 1)
            self.assertEqual(generated.metadata_json["rasterized_sources"], ["pdf"])
            self.assertEqual(len(fake.slideshow_calls), 1)
            self.assertEqual(len(fake.slideshow_calls[0]["image_paths"]), 1)
            self.assertEqual(fake.slideshow_calls[0]["durations"], [40.0])
        finally:
            renderer.ffmpeg_service = original_ffmpeg
            renderer.settings.TEMP_PATH = original_temp_path

    async def test_generated_background_prefers_rasterized_slides_when_available(self):
        class FakeFFmpeg:
            def __init__(self):
                self.slideshow_calls = []

            async def create_slideshow_clip(self, output_path, **kwargs):
                self.slideshow_calls.append({"output_path": output_path, **kwargs})
                Path(output_path).write_text("slideshow", encoding="utf-8")

        fake = FakeFFmpeg()
        original_ffmpeg = renderer.ffmpeg_service
        original_temp_path = renderer.settings.TEMP_PATH
        renderer.ffmpeg_service = fake
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                renderer.settings.TEMP_PATH = temp_dir
                image_path = Path(temp_dir) / "page.png"
                image_path.write_text("fake-image", encoding="utf-8")
                video = SimpleNamespace(id="video-raster", duration_seconds=30.0)
                notes = SimpleNamespace(
                    id="notes-1",
                    role="notes",
                    kind="pdf_notes",
                    sync_role="structure_reference",
                    source_type="pdf_notes",
                    filename="lecture-notes.pdf",
                    original_filename="lecture-notes.pdf",
                    file_path=str(Path(temp_dir) / "lecture-notes.pdf"),
                    metadata_json={
                        "structure_reference": {
                            "title": "Lecture Notes",
                            "reference_role": "pdf_notes",
                            "items": [{"index": 1, "title": "Rendered", "text": "Rendered page."}],
                        }
                    },
                )

                with patch.object(
                    renderer,
                    "_render_structure_reference_images",
                    return_value=[{"path": str(image_path), "render_source": "pdf"}],
                ):
                    generated = await renderer._generated_slide_background_asset(video, [notes], {"layout_cues": []})

            self.assertEqual(generated.metadata_json["render_mode"], "rasterized_pages")
            self.assertEqual(generated.metadata_json["rasterized_slide_count"], 1)
            self.assertEqual(fake.slideshow_calls[0]["image_paths"], [str(image_path)])
            self.assertEqual(fake.slideshow_calls[0]["durations"], [30.0])
        finally:
            renderer.ffmpeg_service = original_ffmpeg
            renderer.settings.TEMP_PATH = original_temp_path

    async def test_generates_slide_background_from_uploaded_structure_reference(self):
        class FakeFFmpeg:
            def __init__(self):
                self.color_calls = []
                self.overlay_calls = []

            async def create_solid_color_clip(self, output_path, **kwargs):
                self.color_calls.append({"output_path": output_path, **kwargs})
                Path(output_path).write_text("base", encoding="utf-8")

            async def burn_ass_overlay(self, input_path, ass_path, output_path, **kwargs):
                self.overlay_calls.append(
                    {
                        "input_path": input_path,
                        "ass_path": ass_path,
                        "output_path": output_path,
                        **kwargs,
                    }
                )
                Path(output_path).write_text("slides", encoding="utf-8")

        fake = FakeFFmpeg()
        original_ffmpeg = renderer.ffmpeg_service
        original_temp_path = renderer.settings.TEMP_PATH
        renderer.ffmpeg_service = fake
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                renderer.settings.TEMP_PATH = temp_dir
                video = SimpleNamespace(id="video-1", duration_seconds=60.0)
                notes = SimpleNamespace(
                    id="notes-1",
                    role="notes",
                    kind="pdf_notes",
                    sync_role="structure_reference",
                    source_type="pdf_notes",
                    filename="lecture-notes.pdf",
                    original_filename="lecture-notes.pdf",
                    metadata_json={
                        "structure_reference": {
                            "title": "Lecture Notes",
                            "reference_role": "pdf_notes",
                            "document_format": "pdf",
                            "items": [
                                {"index": 1, "title": "Setup", "text": "Install tools and prepare the workspace."},
                                {"index": 2, "title": "Simulation", "text": "Run the command-line simulation flow."},
                            ],
                        }
                    },
                )

                generated = await renderer._generated_slide_background_asset(video, [notes], {"layout_cues": []})

            self.assertIsNotNone(generated)
            self.assertTrue(generated.file_path.endswith("generated_slides.mp4"))
            self.assertEqual(generated.metadata_json["track"], "generated_slides")
            self.assertEqual(generated.metadata_json["structure_reference_count"], 1)
            self.assertEqual(fake.color_calls[0]["duration_seconds"], 60.0)
            self.assertEqual(len(fake.overlay_calls), 1)
        finally:
            renderer.ffmpeg_service = original_ffmpeg
            renderer.settings.TEMP_PATH = original_temp_path

    async def test_generated_slide_pip_uses_camera_audio_when_no_audio_asset_exists(self):
        class FakeFFmpeg:
            def __init__(self):
                self.pip_calls = []

            async def render_picture_in_picture_clip(self, **kwargs):
                self.pip_calls.append(kwargs)
                Path(kwargs["output_path"]).write_text("pip", encoding="utf-8")

        fake = FakeFFmpeg()
        original_ffmpeg = renderer.ffmpeg_service
        renderer.ffmpeg_service = fake
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                output_path = str(Path(temp_dir) / "pip.mp4")
                cue = build_layout_cue(
                    cue_id="generated-pip",
                    layout="picture_in_picture",
                    start_time=0.0,
                    end_time=10.0,
                    camera_source_id="camera",
                )
                cue["sources"]["screen"]["asset_id"] = None
                cue["sources"]["screen"]["track"] = "generated_slides"
                context = renderer.LayoutRenderContext(
                    cues=[cue],
                    assets_by_id={
                        "camera": SimpleNamespace(file_path="camera.mp4", sync_offset_seconds=0.25),
                    },
                    assets_by_track={
                        "generated_slides": SimpleNamespace(
                            file_path="generated_slides.mp4",
                            sync_offset_seconds=0.0,
                            kind="generated_slides",
                            source_type="generated_slides",
                            metadata_json={"generated": True, "track": "generated_slides"},
                        ),
                    },
                )

                rendered = await renderer._render_layout_span(
                    cue=cue,
                    layout_context=context,
                    output_path=output_path,
                    fallback_video_path="legacy.mp4",
                    start_time=0.0,
                    end_time=10.0,
                )

            self.assertEqual(rendered, "picture_in_picture")
            self.assertEqual(fake.pip_calls[0]["screen_path"], "generated_slides.mp4")
            self.assertEqual(fake.pip_calls[0]["camera_path"], "camera.mp4")
            self.assertEqual(fake.pip_calls[0]["audio_path"], "camera.mp4")
            self.assertEqual(fake.pip_calls[0]["camera_sync_offset"], 0.25)
        finally:
            renderer.ffmpeg_service = original_ffmpeg

    async def test_audio_only_export_uses_cleaned_ranges_and_audio_asset(self):
        class FakeFFmpeg:
            def __init__(self):
                self.trim_audio_calls = []
                self.silence_calls = []
                self.concat_calls = []

            async def trim_audio(self, **kwargs):
                self.trim_audio_calls.append(kwargs)
                Path(kwargs["output_path"]).write_text("audio", encoding="utf-8")

            async def trim_silence_from_audio(self, **kwargs):
                self.silence_calls.append(kwargs)
                Path(kwargs["output_path"]).write_text("short", encoding="utf-8")

            async def concat_audio(self, **kwargs):
                self.concat_calls.append(kwargs)
                Path(kwargs["output_path"]).write_text("final", encoding="utf-8")

            async def get_video_metadata(self, path):
                return {"duration": 4.0, "audio_codec": "aac"}

        fake = FakeFFmpeg()
        original_ffmpeg = renderer.ffmpeg_service
        original_video_path = renderer.settings.VIDEO_STORAGE_PATH
        original_temp_path = renderer.settings.TEMP_PATH
        renderer.ffmpeg_service = fake
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                renderer.settings.VIDEO_STORAGE_PATH = temp_dir
                renderer.settings.TEMP_PATH = temp_dir
                segment_one = _renderer_segment("seg-1", 0, 0.0, 6.0, action="keep")
                segment_two = _renderer_segment("seg-2", 1, 6.0, 10.0, action="shorten")
                plan = SimpleNamespace(
                    id="plan-1",
                    plan_json={"export_metadata": {"selected_preset": {"id": "podcast_audio", "container": "m4a", "extension": ".m4a", "audio_codec": "aac", "audio_bitrate": "192 kbps", "audio_only": True}}},
                    original_duration=10.0,
                    estimated_duration=4.0,
                    segments_total=2,
                    segments_keep=2,
                    segments_cut=0,
                    segments_highlight=0,
                    filler_words_removed=0,
                    silence_removed_seconds=0,
                    approved_at=None,
                    teacher_notes=None,
                )
                video = SimpleNamespace(
                    id="video-1",
                    file_path="legacy.mp4",
                    original_filename="lecture.mp4",
                    duration_seconds=10.0,
                    resolution="1920x1080",
                    fps=30,
                    project_asset_id="primary",
                    processed_video_path=None,
                    status=None,
                )
                context = renderer.LayoutRenderContext(
                    cues=[],
                    assets_by_id={},
                    assets_by_track={
                        "audio": SimpleNamespace(id="audio-1", file_path="voice.wav", sync_offset_seconds=0.25),
                    },
                )
                render_ranges = [
                    {
                        "segment_id": "seg-1",
                        "segment_index": 0,
                        "source_start_time": 0.0,
                        "source_end_time": 2.0,
                        "duration": 2.0,
                        "output_start_time": 0.0,
                        "output_end_time": 2.0,
                        "action": "keep",
                        "segment": segment_one,
                    },
                    {
                        "segment_id": "seg-2",
                        "segment_index": 1,
                        "source_start_time": 6.0,
                        "source_end_time": 8.0,
                        "duration": 2.0,
                        "output_start_time": 2.0,
                        "output_end_time": 4.0,
                        "action": "shorten",
                        "segment": segment_two,
                    },
                ]

                result = await renderer._render_audio_only_export(
                    video=video,
                    plan=plan,
                    segments=[segment_one, segment_two],
                    transcript=SimpleNamespace(words_json=[]),
                    render_ranges=render_ranges,
                    included_segment_ids={"seg-1", "seg-2"},
                    sync_plan={
                        "schema_version": "phase5.transcript-decisions.v1",
                        "cut_intervals": [],
                        "export_plan": {"transcript_cut_count": 1, "estimated_output_duration_seconds": 4.0},
                    },
                    plan_payload=plan.plan_json,
                    selected_preset=plan.plan_json["export_metadata"]["selected_preset"],
                    layout_context=context,
                    render_job_id=None,
                    video_id="video-1",
                )

            self.assertEqual(result["output_kind"], "audio_only")
            self.assertTrue(result["output_path"].endswith("_audio.m4a"))
            self.assertEqual(video.processed_video_path, result["output_path"])
            self.assertEqual(fake.trim_audio_calls[0]["input_path"], "voice.wav")
            self.assertEqual(fake.trim_audio_calls[0]["sync_offset"], 0.25)
            self.assertEqual(len(fake.trim_audio_calls), 2)
            self.assertEqual(len(fake.silence_calls), 1)
            self.assertEqual(len(fake.concat_calls[0]["clip_paths"]), 2)
            self.assertEqual(plan.plan_json["export_metadata"]["render"]["output_kind"], "audio_only")
            self.assertEqual(plan.plan_json["export_metadata"]["artifacts"][0]["kind"], "audio_only")
        finally:
            renderer.ffmpeg_service = original_ffmpeg
            renderer.settings.VIDEO_STORAGE_PATH = original_video_path
            renderer.settings.TEMP_PATH = original_temp_path

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

    def test_layout_spans_drop_micro_ranges_before_ffmpeg(self):
        cue = build_layout_cue(
            cue_id="micro",
            layout="picture_in_picture",
            start_time=10.0,
            end_time=10.000004,
            screen_source_id="screen",
            camera_source_id="camera",
        )

        spans = renderer._layout_spans_for_range(
            {
                "source_start_time": 10.0,
                "source_end_time": 10.000004,
            },
            [cue],
        )

        self.assertEqual(spans, [])

    async def test_render_range_clips_skips_micro_ranges_without_ffmpeg_call(self):
        class FakeFFmpeg:
            def __init__(self):
                self.trim_calls = []

            async def trim_video(self, **kwargs):
                self.trim_calls.append(kwargs)
                Path(kwargs["output_path"]).write_text("trim", encoding="utf-8")

        fake = FakeFFmpeg()
        original_ffmpeg = renderer.ffmpeg_service
        renderer.ffmpeg_service = fake
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                clip_paths, clip_durations, layout_counts = await renderer._render_range_clips(
                    video=SimpleNamespace(file_path="legacy.mp4"),
                    render_range={
                        "source_start_time": 10.0,
                        "source_end_time": 10.000004,
                        "action": "keep",
                    },
                    range_index=0,
                    clip_dir=temp_dir,
                    layout_context=None,
                )

            self.assertEqual(clip_paths, [])
            self.assertEqual(clip_durations, [])
            self.assertEqual(layout_counts, {})
            self.assertEqual(fake.trim_calls, [])
        finally:
            renderer.ffmpeg_service = original_ffmpeg

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

                clip_paths, clip_durations, layout_counts = await renderer._render_range_clips(
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
            self.assertEqual(clip_durations, [10.0, 10.0, 10.0])
            self.assertEqual(layout_counts, {"picture_in_picture": 1})
            self.assertEqual(len(fake.trim_calls), 2)
            self.assertEqual(len(fake.pip_calls), 1)
            self.assertEqual(fake.pip_calls[0]["screen_path"], "screen.mp4")
            self.assertEqual(fake.pip_calls[0]["camera_sync_offset"], 0.4)
            self.assertEqual(fake.pip_calls[0]["audio_path"], "voice.wav")
            self.assertEqual(fake.pip_calls[0]["camera_shape"], "rounded_rectangle")
        finally:
            renderer.ffmpeg_service = original_ffmpeg

    async def test_resolves_layout_sources_from_track_names_and_applies_fades(self):
        class FakeFFmpeg:
            def __init__(self):
                self.full_source_calls = []
                self.fade_calls = []

            async def trim_video(self, **kwargs):
                Path(kwargs["output_path"]).write_text("trim", encoding="utf-8")

            async def render_full_source_clip(self, **kwargs):
                self.full_source_calls.append(kwargs)
                Path(kwargs["output_path"]).write_text("full", encoding="utf-8")

            async def apply_clip_fades(self, **kwargs):
                self.fade_calls.append(kwargs)
                Path(kwargs["output_path"]).write_text("fade", encoding="utf-8")

        fake = FakeFFmpeg()
        original_ffmpeg = renderer.ffmpeg_service
        renderer.ffmpeg_service = fake
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                cue = build_layout_cue(
                    cue_id="screen-fade",
                    layout="full_screen_source",
                    start_time=0.0,
                    end_time=5.0,
                )
                cue["sources"]["screen"]["track"] = "screen"
                cue["sources"]["audio"]["track"] = "audio"
                cue["timing"]["transition_in"] = "fade"
                cue["timing"]["transition_out"] = "fade"
                cue["timing"]["transition_duration_seconds"] = 0.4
                context = renderer.LayoutRenderContext(
                    cues=[cue],
                    assets_by_id={},
                    assets_by_track={
                        "screen": SimpleNamespace(file_path="screen.mp4", sync_offset_seconds=0.2),
                        "audio": SimpleNamespace(file_path="voice.wav", sync_offset_seconds=0.1),
                    },
                )

                _, _, layout_counts = await renderer._render_range_clips(
                    video=SimpleNamespace(file_path="legacy.mp4"),
                    render_range={
                        "source_start_time": 0.0,
                        "source_end_time": 5.0,
                        "duration": 5.0,
                        "output_start_time": 0.0,
                        "output_end_time": 5.0,
                        "action": "keep",
                    },
                    range_index=0,
                    clip_dir=temp_dir,
                    layout_context=context,
                )

            self.assertEqual(layout_counts, {"full_screen_source": 1})
            self.assertEqual(fake.full_source_calls[0]["source_path"], "screen.mp4")
            self.assertEqual(fake.full_source_calls[0]["audio_path"], "voice.wav")
            self.assertEqual(fake.full_source_calls[0]["source_sync_offset"], 0.2)
            self.assertEqual(fake.fade_calls[0]["fade_in"], True)
            self.assertEqual(fake.fade_calls[0]["fade_out"], True)
        finally:
            renderer.ffmpeg_service = original_ffmpeg

    def test_transition_events_map_layout_cues_to_edited_output_time(self):
        cue = build_layout_cue(
            cue_id="cue-transition",
            layout="full_screen_source",
            start_time=8.0,
            end_time=12.0,
        )
        cue["timing"]["transition_in"] = "fade"
        cue["timing"]["transition_out"] = "wipe_left"
        cue["timing"]["transition_duration_seconds"] = 0.5
        render_ranges = [
            {
                "source_start_time": 5.0,
                "source_end_time": 10.0,
                "output_start_time": 0.0,
                "output_end_time": 5.0,
                "duration": 5.0,
            },
            {
                "source_start_time": 10.0,
                "source_end_time": 15.0,
                "output_start_time": 5.0,
                "output_end_time": 10.0,
                "duration": 5.0,
            },
        ]

        events = renderer._layout_transition_events_for_render_ranges([cue], render_ranges)

        self.assertEqual([event["edge"] for event in events], ["in", "out"])
        self.assertEqual(events[0]["output_time"], 3.0)
        self.assertEqual(events[0]["render_strategy"], "clip_fade")
        self.assertEqual(events[1]["output_time"], 7.0)
        self.assertEqual(events[1]["render_strategy"], "concat_compositor")

    def test_concat_transition_specs_map_events_to_clip_boundaries(self):
        events = [
            {
                "cue_id": "cue-transition",
                "transition": "crossfade",
                "duration_seconds": 0.5,
                "output_time": 4.0,
                "render_strategy": "concat_compositor",
            },
            {
                "cue_id": "cue-transition",
                "transition": "wipe_left",
                "duration_seconds": 0.4,
                "output_time": 9.0,
                "render_strategy": "concat_compositor",
            },
        ]

        specs = renderer._concat_transition_specs(events, [4.0, 5.0, 6.0])

        self.assertEqual(
            specs,
            [
                {
                    "boundary_index": 0,
                    "transition": "crossfade",
                    "duration_seconds": 0.5,
                    "output_time": 4.0,
                    "cue_id": "cue-transition",
                },
                {
                    "boundary_index": 1,
                    "transition": "wipe_left",
                    "duration_seconds": 0.4,
                    "output_time": 9.0,
                    "cue_id": "cue-transition",
                },
            ],
        )

    async def test_renders_side_by_side_and_fullscreen_spans_with_layout_compositor(self):
        class FakeFFmpeg:
            def __init__(self):
                self.trim_calls = []
                self.side_by_side_calls = []
                self.full_source_calls = []

            async def trim_video(self, **kwargs):
                self.trim_calls.append(kwargs)
                Path(kwargs["output_path"]).write_text("trim", encoding="utf-8")

            async def render_side_by_side_clip(self, **kwargs):
                self.side_by_side_calls.append(kwargs)
                Path(kwargs["output_path"]).write_text("side", encoding="utf-8")

            async def render_full_source_clip(self, **kwargs):
                self.full_source_calls.append(kwargs)
                Path(kwargs["output_path"]).write_text("full", encoding="utf-8")

        fake = FakeFFmpeg()
        original_ffmpeg = renderer.ffmpeg_service
        renderer.ffmpeg_service = fake
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                side_by_side = build_layout_cue(
                    cue_id="side-1",
                    layout="side_by_side",
                    start_time=0.0,
                    end_time=10.0,
                    screen_source_id="screen",
                    camera_source_id="camera",
                    audio_source_id="audio",
                )
                full_screen = build_layout_cue(
                    cue_id="screen-1",
                    layout="full_screen_source",
                    start_time=10.0,
                    end_time=20.0,
                    screen_source_id="screen",
                    audio_source_id="audio",
                )
                context = renderer.LayoutRenderContext(
                    cues=[side_by_side, full_screen],
                    assets_by_id={
                        "screen": SimpleNamespace(file_path="screen.mp4", sync_offset_seconds=0.0),
                        "camera": SimpleNamespace(file_path="camera.mp4", sync_offset_seconds=0.25),
                        "audio": SimpleNamespace(file_path="voice.wav", sync_offset_seconds=0.5),
                    },
                )

                clip_paths, _, layout_counts = await renderer._render_range_clips(
                    video=SimpleNamespace(file_path="legacy.mp4"),
                    render_range={
                        "source_start_time": 0.0,
                        "source_end_time": 20.0,
                        "action": "keep",
                    },
                    range_index=0,
                    clip_dir=temp_dir,
                    layout_context=context,
                )

            self.assertEqual(len(clip_paths), 2)
            self.assertEqual(layout_counts, {"side_by_side": 1, "full_screen_source": 1})
            self.assertEqual(fake.side_by_side_calls[0]["screen_path"], "screen.mp4")
            self.assertEqual(fake.side_by_side_calls[0]["camera_sync_offset"], 0.25)
            self.assertEqual(fake.side_by_side_calls[0]["audio_path"], "voice.wav")
            self.assertEqual(fake.full_source_calls[0]["source_path"], "screen.mp4")
            self.assertEqual(fake.full_source_calls[0]["audio_sync_offset"], 0.5)
            self.assertEqual(len(fake.trim_calls), 0)
        finally:
            renderer.ffmpeg_service = original_ffmpeg

    async def test_renders_full_camera_span_from_camera_asset(self):
        class FakeFFmpeg:
            def __init__(self):
                self.full_source_calls = []

            async def trim_video(self, **kwargs):
                Path(kwargs["output_path"]).write_text("trim", encoding="utf-8")

            async def render_full_source_clip(self, **kwargs):
                self.full_source_calls.append(kwargs)
                Path(kwargs["output_path"]).write_text("camera", encoding="utf-8")

        fake = FakeFFmpeg()
        original_ffmpeg = renderer.ffmpeg_service
        renderer.ffmpeg_service = fake
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                cue = build_layout_cue(
                    cue_id="camera-1",
                    layout="full_camera_source",
                    start_time=2.0,
                    end_time=8.0,
                    camera_source_id="camera",
                )
                context = renderer.LayoutRenderContext(
                    cues=[cue],
                    assets_by_id={
                        "camera": SimpleNamespace(file_path="camera.mp4", sync_offset_seconds=0.75),
                    },
                )

                _, _, layout_counts = await renderer._render_range_clips(
                    video=SimpleNamespace(file_path="legacy.mp4"),
                    render_range={
                        "source_start_time": 2.0,
                        "source_end_time": 8.0,
                        "action": "keep",
                    },
                    range_index=0,
                    clip_dir=temp_dir,
                    layout_context=context,
                )

            self.assertEqual(layout_counts, {"full_camera_source": 1})
            self.assertEqual(fake.full_source_calls[0]["source_path"], "camera.mp4")
            self.assertEqual(fake.full_source_calls[0]["source_sync_offset"], 0.75)
        finally:
            renderer.ffmpeg_service = original_ffmpeg


def _renderer_segment(segment_id, segment_index, start, end, action="keep"):
    return SimpleNamespace(
        id=segment_id,
        segment_index=segment_index,
        start_time=start,
        end_time=end,
        duration=end - start,
        topic_label="Topic",
        text="Rendered segment text.",
        summary="Summary",
        segment_type=None,
        speaker=None,
        importance_score=0.8,
        fluency_score=0.9,
        filler_count=0,
        pause_duration_total=0,
        has_slide_change=False,
        action=SimpleNamespace(value=action),
        action_confidence=0.9,
        action_reason="test",
        teacher_action=None,
        teacher_note=None,
        is_teacher_modified=False,
    )


if __name__ == "__main__":
    unittest.main()
