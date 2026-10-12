import copy
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

APP_DIR = Path(__file__).resolve().parents[1] / 'app'
sys.path.insert(0, str(APP_DIR))
import services.renderer as renderer
import services.native_semantic_compositor as native
from services.render_jobs import RenderCancelled


def fixture(asset_offset=2, cue_offset=-2):
    primary = SimpleNamespace(id='primary-asset', file_path='master.mp4', sync_offset_seconds=0)
    camera = SimpleNamespace(id='camera-asset', file_path='selected-camera.mp4', sync_offset_seconds=asset_offset)
    video = SimpleNamespace(id='video', file_path=primary.file_path)
    cue = {'id': 'teacher-cue', 'start_time': 5, 'end_time': 20,
           'sources': {'camera': {'asset_id': camera.id, 'enabled': True,
                                  'sync_offset_seconds': cue_offset}}}
    context = renderer.LayoutRenderContext(cues=[cue], assets_by_id={primary.id: primary, camera.id: camera},
                                          fallback_camera_asset=camera)
    scene = {'id': 'scene', 'layout_cue_id': cue['id'], 'source_start_time': 6,
             'duration_seconds': 3, 'layout': 'picture_in_picture', 'camera': {'enabled': True}}
    plan = {'timeline': {'scene_count': 1}, 'scenes': [scene]}
    return video, context, plan


def scene_command(scene):
    return native._build_bounded_scene_command(
        source_video_path='master-proxy.mp4', slide_path='slide.png', output_path='out.mp4',
        scene=scene, output_width=640, output_height=360, fps=30,
        video_bitrate='4M', audio_bitrate='192k')


class SourceBindingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Command-contract tests do not discover or execute hardware encoders.
        encoder = patch.object(native.FFmpegService, '_preferred_h264_encoder', return_value=None)
        encoder.start()
        self.addCleanup(encoder.stop)

    async def test_renderer_handoff_is_private_and_prefers_nonzero_asset(self):
        video, context, plan = fixture()
        original = copy.deepcopy(plan)
        handoff = AsyncMock()
        with patch.object(renderer, 'render_semantic_plan_with_ffmpeg', handoff), \
             patch.object(renderer.settings, 'NATIVE_SEMANTIC_COMPOSITOR_ENABLED', True):
            result = await renderer._try_render_native_semantic_timeline_clip(
                video=video, plan=SimpleNamespace(plan_json={}), segments=[], transcript=None,
                plan_payload={'render_plan': plan}, layout_context=context, clip_dir='clips',
                selected_preset={}, render_job_id=None, video_id=video.id)
        self.assertIsNotNone(result)
        args = handoff.await_args.kwargs
        self.assertEqual(args['source_video_path'], 'master.mp4')
        binding = args['scene_source_bindings']['scene']
        self.assertEqual(binding['camera']['asset_id'], 'camera-asset')
        self.assertEqual(binding['camera']['file_path'], 'selected-camera.mp4')
        self.assertEqual(binding['camera']['sync_offset_seconds'], 2)
        self.assertEqual(binding['primary']['asset_id'], 'primary-asset')
        self.assertEqual(binding['primary']['provenance'], 'primary_master')
        self.assertEqual(plan, original)

    def test_zero_asset_uses_cue_offset_and_maps_by_source_time(self):
        video, context, plan = fixture(0, -2)
        plan['scenes'][0].pop('layout_cue_id')
        binding = renderer._native_semantic_source_bindings(video, plan, context)['scene']
        self.assertEqual(binding['camera']['sync_offset_seconds'], -2)
        scene = {**plan['scenes'][0], 'native_sources': binding}
        command = scene_command(scene)
        self.assertEqual(command[command.index('-ss') + 1], '8.000')

    def test_scene_cue_identity_and_offsets_are_independent(self):
        video, context, plan = fixture(0, 2)
        other = SimpleNamespace(id='second', file_path='second-camera.mp4', sync_offset_seconds=-1)
        context.assets_by_id[other.id] = other
        context.cues.append({'id': 'second-cue', 'start_time': 10, 'end_time': 20,
                             'sources': {'camera': {'asset_id': other.id, 'sync_offset_seconds': 9}}})
        plan['scenes'].append({**plan['scenes'][0], 'id': 'second-scene',
                              'layout_cue_id': 'second-cue', 'source_start_time': 12})
        bindings = renderer._native_semantic_source_bindings(video, plan, context)
        for scene, expected_path, seek in [(plan['scenes'][0], 'selected-camera.mp4', '4.000'),
                                           (plan['scenes'][1], 'second-camera.mp4', '13.000')]:
            cmd = scene_command({**scene, 'native_sources': bindings[scene['id']]})
            self.assertEqual(cmd[cmd.index('-i') + 1], expected_path)
            self.assertEqual(cmd[cmd.index('-ss') + 1], seek)
            self.assertEqual(cmd[cmd.index('-t') + 1], '3.000')

    def test_selected_camera_inputs_all_camera_layouts_and_master_audio(self):
        video, context, plan = fixture()
        binding = renderer._native_semantic_source_bindings(video, plan, context)['scene']
        for layout in ('picture_in_picture', 'side_by_side', 'full_camera_source'):
            with self.subTest(layout=layout):
                cmd = scene_command({**plan['scenes'][0], 'layout': layout, 'native_sources': binding})
                self.assertEqual(cmd[cmd.index('-i') + 1], 'selected-camera.mp4')
                self.assertEqual(cmd[cmd.index('-ss') + 1], '4.000')
                self.assertIn('[0:v]', cmd[cmd.index('-filter_complex') + 1])
                self.assertIn('-an', cmd)
        audio = native._build_bounded_audio_command(source_video_path='master-proxy.mp4',
                                                   output_path='audio.m4a', scenes=plan['scenes'], audio_bitrate='192k')
        self.assertEqual(audio[audio.index('-i') + 1], 'master-proxy.mp4')
        self.assertEqual(audio[audio.index('-ss') + 1], '6.000')
        self.assertNotIn('selected-camera.mp4', audio)
        self.assertEqual(audio[audio.index('-map') + 1], '[a]')

    def test_clamp_and_millisecond_rounding(self):
        video, context, plan = fixture(8, -2)
        binding = renderer._native_semantic_source_bindings(video, plan, context)['scene']
        self.assertEqual(scene_command({**plan['scenes'][0], 'native_sources': binding})[5], '0.000')
        context.fallback_camera_asset.sync_offset_seconds = 1.23456
        binding = renderer._native_semantic_source_bindings(video, plan, context)['scene']
        cmd = scene_command({**plan['scenes'][0], 'native_sources': binding})
        self.assertEqual(cmd[cmd.index('-ss') + 1], '4.765')

    def test_no_camera_default_and_disabled_role(self):
        video, context, plan = fixture()
        default = renderer._native_semantic_source_bindings(video, plan, None)['scene']
        self.assertEqual(default['camera']['file_path'], 'master.mp4')
        self.assertEqual(default['camera']['sync_offset_seconds'], 0)
        legacy = scene_command(plan['scenes'][0])
        self.assertEqual(legacy[legacy.index('-i') + 1], 'master-proxy.mp4')
        self.assertEqual(legacy[legacy.index('-ss') + 1], '6.000')
        context.cues[0]['sources']['camera']['enabled'] = False
        disabled = renderer._native_semantic_source_bindings(video, plan, context)['scene']
        self.assertFalse(disabled['camera']['enabled'])
        cmd = scene_command({**plan['scenes'][0], 'native_sources': disabled})
        self.assertNotIn('[0:v]', cmd[cmd.index('-filter_complex') + 1])
        self.assertNotIn('selected-camera.mp4', cmd)

    async def test_camera_proxy_lineage_and_primary_audio_survive_handoff(self):
        video, context, plan = fixture()
        original = copy.deepcopy(plan)
        bindings = renderer._native_semantic_source_bindings(video, plan, context)
        proxy = AsyncMock(side_effect=['master-proxy.mp4', 'camera-proxy.mp4'])
        sequence = AsyncMock()
        with patch.object(native.os.path, 'isfile', return_value=True), \
             patch.object(native.os.path, 'getsize', return_value=100), \
             patch.object(native, '_ensure_render_proxy', proxy), \
             patch.object(native, '_render_slide_images', return_value=['slide.png']), \
             patch.object(native, '_render_bounded_scene_sequence', sequence), \
             tempfile.TemporaryDirectory() as work:
            await native.render_semantic_plan_with_ffmpeg(render_plan=plan, source_video_path=video.file_path,
                scene_source_bindings=bindings, output_path='out.mp4', work_dir=work)
        self.assertEqual([call.kwargs['source_video_path'] for call in proxy.await_args_list],
                         ['master.mp4', 'selected-camera.mp4'])
        args = sequence.await_args.kwargs
        self.assertEqual(args['source_video_path'], 'master-proxy.mp4')
        camera = args['scenes'][0]['native_sources']['camera']
        self.assertEqual(camera['file_path'], 'camera-proxy.mp4')
        self.assertEqual(camera['original_file_path'], 'selected-camera.mp4')
        self.assertEqual(camera['asset_id'], 'camera-asset')
        self.assertEqual(camera['sync_offset_seconds'], 2)
        self.assertEqual(plan, original)

    async def test_bounded_sequence_primary_audio_mux_and_cancellation_cleanup(self):
        video, context, plan = fixture()
        binding = renderer._native_semantic_source_bindings(video, plan, context)['scene']
        scene = {**plan['scenes'][0], 'native_sources': binding}
        run = AsyncMock()
        process = AsyncMock()
        with tempfile.TemporaryDirectory() as work, \
             patch.object(native, '_run_ffmpeg_with_progress', run), \
             patch.object(native.FFmpegService, '_run_process', process):
            kwargs = dict(source_video_path='master-proxy.mp4', output_path='out.mp4', work_dir=work,
                          scenes=[scene], slide_paths=['slide.png'], output_width=640, output_height=360,
                          fps=30, video_bitrate='4M', audio_bitrate='192k', total_duration=3,
                          progress_callback=None, cancel_check=None)
            await native._render_bounded_scene_sequence(**kwargs)
            self.assertEqual(run.await_args_list[1].args[0][run.await_args_list[1].args[0].index('-i') + 1],
                             'master-proxy.mp4')
            mux = process.await_args_list[-1].args[0]
            self.assertEqual([mux[i + 1] for i, part in enumerate(mux) if part == '-map'], ['0:v:0', '1:a:0'])
            self.assertFalse((Path(work) / 'bounded_scenes').exists())
            def cancel():
                raise RenderCancelled('cancelled')
            run.reset_mock()
            with self.assertRaises(RenderCancelled):
                await native._render_bounded_scene_sequence(**{**kwargs, 'cancel_check': cancel})
            run.assert_not_awaited()
            self.assertFalse((Path(work) / 'bounded_scenes').exists())


if __name__ == '__main__':
    unittest.main()