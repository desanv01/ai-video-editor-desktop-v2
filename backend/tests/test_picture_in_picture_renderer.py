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


if __name__ == "__main__":
    unittest.main()
