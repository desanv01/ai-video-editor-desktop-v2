"""
FFmpeg service — wraps ffmpeg CLI for all video/audio processing.
This is the core "tool" layer that MCP servers and agents call.
"""

import asyncio
import json
import logging
import os
import re
import subprocess
from collections import Counter
from typing import Any, Callable, List, Tuple, Optional
from config import settings
from services.tooling import ffmpeg_binary, ffprobe_binary

logger = logging.getLogger(__name__)


class FFmpegService:
    """All ffmpeg operations used by the pipeline."""
    _encoder_cache: set[str] | None = None

    @staticmethod
    def _stderr_message(stderr: bytes, limit: int | None = None) -> str:
        message = stderr.decode(errors="replace")
        if limit is None or len(message) <= limit:
            return message
        return f"[earlier FFmpeg output omitted]\n{message[-limit:]}"

    @staticmethod
    async def _run_process(
        cmd: list[str],
        *,
        error_prefix: str,
        stderr_limit: int | None = None,
        cancel_check: Callable[[], None] | None = None,
        allow_failure: bool = False,
    ) -> tuple[bytes, bytes, int]:
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        communicate_task = asyncio.create_task(proc.communicate())

        while not communicate_task.done():
            await asyncio.wait({communicate_task}, timeout=0.2)
            if communicate_task.done():
                break
            if cancel_check:
                try:
                    cancel_check()
                except Exception:
                    if proc.returncode is None:
                        proc.kill()
                    await communicate_task
                    raise

        stdout, stderr = await communicate_task
        if proc.returncode != 0 and not allow_failure:
            message = FFmpegService._stderr_message(stderr, stderr_limit)
            raise RuntimeError(f"{error_prefix}: {message}")
        return stdout, stderr, int(proc.returncode or 0)

    @staticmethod
    async def _run_process_with_encoder_fallback(
        cmd: list[str],
        *,
        error_prefix: str,
        stderr_limit: int | None = None,
        cancel_check: Callable[[], None] | None = None,
        allow_failure: bool = False,
    ) -> tuple[bytes, bytes, int]:
        used_encoder = FFmpegService._encoder_from_command(cmd)
        logger.info(
            "FFmpeg render starting — encoder=%s, fallback_allowed=%s",
            used_encoder,
            bool(getattr(settings, "FFMPEG_HARDWARE_FALLBACK_TO_CPU", True)),
        )
        stdout, stderr, returncode = await FFmpegService._run_process(
            cmd,
            error_prefix=error_prefix,
            stderr_limit=stderr_limit,
            cancel_check=cancel_check,
            allow_failure=True,
        )
        if returncode == 0 or not FFmpegService._command_uses_hardware_encoder(cmd):
            if returncode == 0:
                logger.info("FFmpeg render succeeded — encoder=%s", used_encoder)
            if returncode != 0 and not allow_failure:
                message = FFmpegService._stderr_message(stderr, stderr_limit)
                raise RuntimeError(f"{error_prefix}: {message}")
            return stdout, stderr, returncode

        logger.warning(
            "FFmpeg hardware encoder '%s' FAILED (returncode=%s, stderr=%s) — checking fallback policy",
            used_encoder,
            returncode,
            (FFmpegService._stderr_message(stderr, 500) if stderr else "(no stderr)"),
        )
        if not bool(getattr(settings, "FFMPEG_HARDWARE_FALLBACK_TO_CPU", True)):
            logger.error(
                "FFmpeg HW fallback DISABLED — raising error instead of silently degrading to CPU.",
            )
            if not allow_failure:
                message = FFmpegService._stderr_message(stderr, stderr_limit)
                raise RuntimeError(f"{error_prefix}: {message}")
            return stdout, stderr, returncode

        logger.warning(
            "FFmpeg HW fallback ENABLED — switching from '%s' to libx264 (CPU).",
            used_encoder,
        )
        fallback_cmd = FFmpegService._cpu_fallback_command(cmd)
        return await FFmpegService._run_process(
            fallback_cmd,
            error_prefix=f"{error_prefix} (hardware encoder failed, CPU fallback also failed)",
            stderr_limit=stderr_limit,
            cancel_check=cancel_check,
            allow_failure=allow_failure,
        )

    @staticmethod
    async def get_video_metadata(video_path: str) -> dict:
        """Extract video metadata (duration, resolution, fps, codec)."""
        cmd = [
            ffprobe_binary(), "-v", "quiet",
            "-print_format", "json",
            "-show_format", "-show_streams",
            video_path
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=20)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise RuntimeError("ffprobe timed out while reading video metadata")

        if proc.returncode != 0:
            raise RuntimeError(f"ffprobe failed: {stderr.decode()}")

        data = json.loads(stdout.decode())
        fmt = data.get("format", {})

        # Find video and audio streams
        video_stream = next((s for s in data.get("streams", []) if s["codec_type"] == "video"), {})
        audio_stream = next((s for s in data.get("streams", []) if s["codec_type"] == "audio"), {})

        def stream_float(stream: dict, key: str) -> float:
            try:
                return float(stream.get(key) or 0)
            except (TypeError, ValueError):
                return 0.0

        def stream_int(stream: dict, key: str) -> int:
            try:
                return int(stream.get(key) or 0)
            except (TypeError, ValueError):
                return 0

        def fps_value(rate: str | None) -> float:
            if not rate:
                return 0.0
            try:
                numerator, denominator = str(rate).split("/", 1)
                denominator_value = float(denominator)
                if denominator_value == 0:
                    return 0.0
                return float(numerator) / denominator_value
            except (TypeError, ValueError):
                return 0.0

        return {
            "duration": float(fmt.get("duration", 0)),
            "size_bytes": int(fmt.get("size", 0)),
            "format": fmt.get("format_name", ""),
            "format_tags": fmt.get("tags", {}),
            "video_tags": video_stream.get("tags", {}),
            "audio_tags": audio_stream.get("tags", {}),
            "width": int(video_stream.get("width", 0)),
            "height": int(video_stream.get("height", 0)),
            "fps": fps_value(video_stream.get("r_frame_rate")),
            "video_codec": video_stream.get("codec_name", ""),
            "audio_codec": audio_stream.get("codec_name", ""),
            "audio_sample_rate": int(audio_stream.get("sample_rate", 0)),
            "has_video": bool(video_stream),
            "has_audio": bool(audio_stream),
            "video_duration": stream_float(video_stream, "duration"),
            "audio_duration": stream_float(audio_stream, "duration"),
            "video_bit_rate": stream_int(video_stream, "bit_rate"),
            "audio_bit_rate": stream_int(audio_stream, "bit_rate"),
            "video_frame_count": stream_int(video_stream, "nb_frames"),
        }

    @staticmethod
    async def extract_audio(video_path: str, output_path: str, format: str = "wav") -> str:
        """Extract audio track from video file."""
        cmd = [
            ffmpeg_binary(), "-i", video_path,
            "-vn",                          # no video
            "-acodec", "pcm_s16le" if format == "wav" else "libmp3lame",
            "-ar", "16000",                 # 16kHz — optimal for Whisper
            "-ac", "1",                     # mono
            "-y",                           # overwrite
            output_path
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"Audio extraction failed: {stderr.decode()}")

        return output_path

    @staticmethod
    async def detect_silence(
        audio_path: str,
        threshold_db: int = -40,
        min_duration: float = 1.5
    ) -> List[dict]:
        """Detect silent regions using ffmpeg silencedetect filter."""
        cmd = [
            ffmpeg_binary(), "-i", audio_path,
            "-af", f"silencedetect=noise={threshold_db}dB:d={min_duration}",
            "-f", "null", "-"
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()

        output = stderr.decode()
        silences = []
        current = {}

        for line in output.split("\n"):
            if "silence_start:" in line:
                try:
                    start = float(line.split("silence_start:")[1].strip().split()[0])
                    current = {"start": start}
                except (ValueError, IndexError):
                    continue
            elif "silence_end:" in line and current:
                try:
                    parts = line.split("silence_end:")[1].strip().split("|")
                    end = float(parts[0].strip().split()[0])
                    duration = float(parts[1].split("silence_duration:")[1].strip()) if len(parts) > 1 else end - current["start"]
                    silences.append({
                        "start": current["start"],
                        "end": end,
                        "duration": duration,
                        "type": "pause"
                    })
                    current = {}
                except (ValueError, IndexError):
                    current = {}
                    continue

        return silences

    @staticmethod
    async def trim_video(
        video_path: str,
        output_path: str,
        start_time: float,
        end_time: float,
        cancel_check: Callable[[], None] | None = None,
    ) -> str:
        """Trim a segment from the video without re-encoding (fast)."""
        cmd = [
            ffmpeg_binary(),
            "-ss", str(start_time),
            "-i", video_path,
            "-t", str(end_time - start_time),
            "-c", "copy",                   # no re-encode — fast
            "-avoid_negative_ts", "make_zero",
            "-y",
            output_path
        ]
        await FFmpegService._run_process(
            cmd,
            error_prefix="Trim failed",
            cancel_check=cancel_check,
        )
        return output_path

    @staticmethod
    async def trim_video_accurate(
        video_path: str,
        output_path: str,
        start_time: float,
        end_time: float,
        *,
        cancel_check: Callable[[], None] | None = None,
    ) -> str:
        """Trim a segment from the video with re-encoding for frame-accurate cuts.

        Unlike ``trim_video`` which uses ``-c copy`` (stream copy) and can only
        cut at keyframe boundaries, this method re-encodes so cuts are precise
        to the requested frame.  Essential when the output will be concatenated
        with other clips and A/V sync must be maintained.

        Uses hardware-accelerated decode + encode when an NVIDIA GPU with NVENC
        is available; falls through to the standard encoder-fallback pathway
        otherwise.
        """
        duration = max(0.001, float(end_time) - float(start_time))
        encoder = FFmpegService._preferred_h264_encoder()

        cmd: list[str] = [ffmpeg_binary()]

        # ── Hardware-accelerated decode (NVIDIA only — other backends use
        #     different hwaccel flags so we keep it simple) ────────────────
        if encoder == "h264_nvenc":
            cmd.extend(["-hwaccel", "cuda", "-hwaccel_output_format", "cuda"])

        # ── Input seeking (``-ss`` before ``-i`` is fast but relies on
        #     nearest keyframe, then we re-encode precisely) ───────────────
        cmd.extend([
            "-ss", str(start_time),
            "-i", video_path,
            "-t", str(duration),
        ])

        # ── Re-encode video through the standard encoder pathway ─────────
        cmd.extend(FFmpegService._video_encoder_args(None, "p1" if encoder == "h264_nvenc" else "veryfast"))
        cmd.extend(["-c:a", "aac", "-b:a", "128k"])

        # ── Output ───────────────────────────────────────────────────────
        cmd.extend(["-movflags", "+faststart", "-y", output_path])

        await FFmpegService._run_process(
            cmd,
            error_prefix="Accurate trim failed",
            cancel_check=cancel_check,
        )
        return output_path

    @staticmethod
    async def trim_audio(
        *,
        input_path: str,
        output_path: str,
        start_time: float,
        end_time: float,
        sync_offset: float = 0.0,
        audio_codec: str = "aac",
        audio_bitrate: str = "192k",
        cancel_check: Callable[[], None] | None = None,
    ) -> str:
        """Trim an audio-only range, accepting either audio files or media with audio tracks."""
        cmd = FFmpegService.build_trim_audio_command(
            input_path=input_path,
            output_path=output_path,
            start_time=start_time,
            end_time=end_time,
            sync_offset=sync_offset,
            audio_codec=audio_codec,
            audio_bitrate=audio_bitrate,
        )
        await FFmpegService._run_process(
            cmd,
            error_prefix="Audio trim failed",
            stderr_limit=800,
            cancel_check=cancel_check,
        )
        return output_path

    @staticmethod
    def build_trim_audio_command(
        *,
        input_path: str,
        output_path: str,
        start_time: float,
        end_time: float,
        sync_offset: float = 0.0,
        audio_codec: str = "aac",
        audio_bitrate: str = "192k",
    ) -> list[str]:
        """Build the ffmpeg command for one podcast/audio-only export range."""
        duration = max(0.001, float(end_time) - float(start_time))
        codec = _ffmpeg_audio_codec(audio_codec)
        return [
            ffmpeg_binary(),
            "-ss",
            str(FFmpegService._source_timestamp(start_time, sync_offset)),
            "-t",
            str(duration),
            "-i",
            input_path,
            "-vn",
            "-map",
            "0:a?",
            "-c:a",
            codec,
            "-b:a",
            _normalize_audio_bitrate(audio_bitrate),
            "-ar",
            "48000",
            "-ac",
            "2",
            "-y",
            output_path,
        ]

    @staticmethod
    async def trim_silence_from_audio(
        *,
        input_path: str,
        output_path: str,
        threshold_db: int = -40,
        min_silence: float = 0.8,
        audio_codec: str = "aac",
        audio_bitrate: str = "192k",
        cancel_check: Callable[[], None] | None = None,
    ) -> str:
        """Compress long pauses inside an audio-only clip."""
        cmd = [
            ffmpeg_binary(),
            "-i",
            input_path,
            "-vn",
            "-af",
            (
                f"silenceremove=start_periods=1:start_duration=0.1:start_threshold={threshold_db}dB"
                f":stop_periods=-1:stop_duration={min_silence}:stop_threshold={threshold_db}dB"
            ),
            "-c:a",
            _ffmpeg_audio_codec(audio_codec),
            "-b:a",
            _normalize_audio_bitrate(audio_bitrate),
            "-ar",
            "48000",
            "-ac",
            "2",
            "-y",
            output_path,
        ]
        _, _, returncode = await FFmpegService._run_process(
            cmd,
            error_prefix="Audio silence trim failed",
            stderr_limit=800,
            cancel_check=cancel_check,
            allow_failure=True,
        )

        if returncode != 0:
            import shutil

            shutil.copy2(input_path, output_path)

        return output_path

    @staticmethod
    async def concat_audio(
        *,
        clip_paths: List[str],
        output_path: str,
        audio_codec: str = "aac",
        audio_bitrate: str = "192k",
        cancel_check: Callable[[], None] | None = None,
    ) -> str:
        """Concatenate audio-only clips into one podcast/lecture audio file."""
        list_path = output_path + ".txt"
        with open(list_path, "w", encoding="utf-8") as f:
            for clip in clip_paths:
                f.write(f"file '{clip}'\n")

        try:
            cmd = [
                ffmpeg_binary(),
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                list_path,
                "-vn",
                "-c:a",
                _ffmpeg_audio_codec(audio_codec),
                "-b:a",
                _normalize_audio_bitrate(audio_bitrate),
                "-ar",
                "48000",
                "-ac",
                "2",
                "-movflags",
                "+faststart",
                "-y",
                output_path,
            ]
            await FFmpegService._run_process(
                cmd,
                error_prefix="Audio concat failed",
                stderr_limit=800,
                cancel_check=cancel_check,
            )
        finally:
            if os.path.exists(list_path):
                os.remove(list_path)

        return output_path

    @staticmethod
    async def render_picture_in_picture_clip(
        *,
        screen_path: str,
        camera_path: str,
        output_path: str,
        start_time: float,
        end_time: float,
        screen_sync_offset: float = 0.0,
        camera_sync_offset: float = 0.0,
        audio_path: str | None = None,
        audio_sync_offset: float = 0.0,
        output_width: int = 1920,
        output_height: int = 1080,
        camera_corner: str = "bottom_right",
        camera_shape: str = "rounded_rectangle",
        camera_size: str = "medium",
        margin_percent: float = 4.0,
        cancel_check: Callable[[], None] | None = None,
    ) -> str:
        """
        Render one timeline range as screen-first picture-in-picture.

        Sync offsets are stored relative to the project timeline, so a source
        that starts later than the timeline uses an earlier local timestamp.
        """
        cmd = FFmpegService.build_picture_in_picture_command(
            screen_path=screen_path,
            camera_path=camera_path,
            output_path=output_path,
            start_time=start_time,
            end_time=end_time,
            screen_sync_offset=screen_sync_offset,
            camera_sync_offset=camera_sync_offset,
            audio_path=audio_path,
            audio_sync_offset=audio_sync_offset,
            output_width=output_width,
            output_height=output_height,
            camera_corner=camera_corner,
            camera_shape=camera_shape,
            camera_size=camera_size,
            margin_percent=margin_percent,
        )
        await FFmpegService._run_process_with_encoder_fallback(
            cmd,
            error_prefix="Picture-in-picture render failed",
            stderr_limit=800,
            cancel_check=cancel_check,
        )
        return output_path

    @staticmethod
    async def render_side_by_side_clip(
        *,
        screen_path: str,
        camera_path: str,
        output_path: str,
        start_time: float,
        end_time: float,
        screen_sync_offset: float = 0.0,
        camera_sync_offset: float = 0.0,
        audio_path: str | None = None,
        audio_sync_offset: float = 0.0,
        output_width: int = 1920,
        output_height: int = 1080,
        cancel_check: Callable[[], None] | None = None,
    ) -> str:
        """Render one timeline range as equal-width screen and camera panels."""
        cmd = FFmpegService.build_side_by_side_command(
            screen_path=screen_path,
            camera_path=camera_path,
            output_path=output_path,
            start_time=start_time,
            end_time=end_time,
            screen_sync_offset=screen_sync_offset,
            camera_sync_offset=camera_sync_offset,
            audio_path=audio_path,
            audio_sync_offset=audio_sync_offset,
            output_width=output_width,
            output_height=output_height,
        )
        await FFmpegService._run_process_with_encoder_fallback(
            cmd,
            error_prefix="Side-by-side render failed",
            stderr_limit=800,
            cancel_check=cancel_check,
        )
        return output_path

    @staticmethod
    async def render_full_source_clip(
        *,
        source_path: str,
        output_path: str,
        start_time: float,
        end_time: float,
        source_sync_offset: float = 0.0,
        audio_path: str | None = None,
        audio_sync_offset: float = 0.0,
        output_width: int = 1920,
        output_height: int = 1080,
        cancel_check: Callable[[], None] | None = None,
    ) -> str:
        """Render one source full-frame on the target canvas, with optional separate audio."""
        cmd = FFmpegService.build_full_source_command(
            source_path=source_path,
            output_path=output_path,
            start_time=start_time,
            end_time=end_time,
            source_sync_offset=source_sync_offset,
            audio_path=audio_path,
            audio_sync_offset=audio_sync_offset,
            output_width=output_width,
            output_height=output_height,
        )
        await FFmpegService._run_process_with_encoder_fallback(
            cmd,
            error_prefix="Full-source render failed",
            stderr_limit=800,
            cancel_check=cancel_check,
        )
        return output_path

    @staticmethod
    async def apply_clip_fades(
        *,
        input_path: str,
        output_path: str,
        clip_duration_seconds: float,
        fade_duration_seconds: float,
        fade_in: bool = False,
        fade_out: bool = False,
        cancel_check: Callable[[], None] | None = None,
    ) -> str:
        """Apply simple fade-in/out polish to a rendered clip."""
        cmd = FFmpegService.build_clip_fade_command(
            input_path=input_path,
            output_path=output_path,
            clip_duration_seconds=clip_duration_seconds,
            fade_duration_seconds=fade_duration_seconds,
            fade_in=fade_in,
            fade_out=fade_out,
        )
        await FFmpegService._run_process_with_encoder_fallback(
            cmd,
            error_prefix="Clip fade render failed",
            stderr_limit=800,
            cancel_check=cancel_check,
        )
        return output_path

    @staticmethod
    def build_picture_in_picture_command(
        *,
        screen_path: str,
        camera_path: str,
        output_path: str,
        start_time: float,
        end_time: float,
        screen_sync_offset: float = 0.0,
        camera_sync_offset: float = 0.0,
        audio_path: str | None = None,
        audio_sync_offset: float = 0.0,
        output_width: int = 1920,
        output_height: int = 1080,
        camera_corner: str = "bottom_right",
        camera_shape: str = "rounded_rectangle",
        camera_size: str = "medium",
        margin_percent: float = 4.0,
    ) -> list[str]:
        """Build the ffmpeg command used for a single PIP clip."""
        duration = max(0.001, float(end_time) - float(start_time))
        output_width = max(2, int(output_width or 1920))
        output_height = max(2, int(output_height or 1080))
        camera_width, camera_height = FFmpegService._pip_camera_dimensions(
            output_width,
            output_height,
            camera_size,
            camera_shape,
        )
        margin = max(0, round(min(output_width, output_height) * (float(margin_percent or 0) / 100)))
        overlay_x, overlay_y = FFmpegService._pip_overlay_position(
            output_width,
            output_height,
            camera_width,
            camera_height,
            camera_corner,
            margin,
        )

        audio_input_path = audio_path or screen_path
        uses_separate_audio = bool(audio_path and os.path.abspath(audio_path) != os.path.abspath(screen_path))
        camera_filter = FFmpegService._pip_camera_filter(camera_width, camera_height, camera_shape)
        filter_complex = (
            f"[0:v]scale={output_width}:{output_height}:force_original_aspect_ratio=decrease,"
            f"pad={output_width}:{output_height}:(ow-iw)/2:(oh-ih)/2,setsar=1[screen];"
            f"[1:v]{camera_filter}[cam];"
            f"[screen][cam]overlay={overlay_x}:{overlay_y}:format=auto[v]"
        )

        cmd = [
            ffmpeg_binary(),
            "-ss",
            str(FFmpegService._source_timestamp(start_time, screen_sync_offset)),
            "-t",
            str(duration),
            "-i",
            screen_path,
            "-ss",
            str(FFmpegService._source_timestamp(start_time, camera_sync_offset)),
            "-t",
            str(duration),
            "-i",
            camera_path,
        ]
        if uses_separate_audio:
            cmd.extend([
                "-ss",
                str(FFmpegService._source_timestamp(start_time, audio_sync_offset)),
                "-t",
                str(duration),
                "-i",
                audio_input_path,
            ])

        audio_map = "2:a?" if uses_separate_audio else "0:a?"
        cmd.extend([
            "-filter_complex",
            filter_complex,
            "-map",
            "[v]",
            "-map",
            audio_map,
            *FFmpegService._video_encoder_args(None, "veryfast"),
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            "-movflags",
            "+faststart",
            "-y",
            output_path,
        ])
        return cmd

    @staticmethod
    def build_side_by_side_command(
        *,
        screen_path: str,
        camera_path: str,
        output_path: str,
        start_time: float,
        end_time: float,
        screen_sync_offset: float = 0.0,
        camera_sync_offset: float = 0.0,
        audio_path: str | None = None,
        audio_sync_offset: float = 0.0,
        output_width: int = 1920,
        output_height: int = 1080,
    ) -> list[str]:
        """Build the ffmpeg command used for a single side-by-side clip."""
        duration = max(0.001, float(end_time) - float(start_time))
        output_width = max(2, int(output_width or 1920))
        output_height = max(2, int(output_height or 1080))
        left_width = _even_int(output_width / 2)
        right_width = max(2, output_width - left_width)

        audio_input_path = audio_path or screen_path
        uses_separate_audio = bool(audio_path and os.path.abspath(audio_path) != os.path.abspath(screen_path))
        filter_complex = (
            f"[0:v]scale={left_width}:{output_height}:force_original_aspect_ratio=decrease,"
            f"pad={left_width}:{output_height}:(ow-iw)/2:(oh-ih)/2,setsar=1[left];"
            f"[1:v]scale={right_width}:{output_height}:force_original_aspect_ratio=decrease,"
            f"pad={right_width}:{output_height}:(ow-iw)/2:(oh-ih)/2,setsar=1[right];"
            f"[left][right]hstack=inputs=2[v]"
        )

        cmd = [
            ffmpeg_binary(),
            "-ss",
            str(FFmpegService._source_timestamp(start_time, screen_sync_offset)),
            "-t",
            str(duration),
            "-i",
            screen_path,
            "-ss",
            str(FFmpegService._source_timestamp(start_time, camera_sync_offset)),
            "-t",
            str(duration),
            "-i",
            camera_path,
        ]
        if uses_separate_audio:
            cmd.extend([
                "-ss",
                str(FFmpegService._source_timestamp(start_time, audio_sync_offset)),
                "-t",
                str(duration),
                "-i",
                audio_input_path,
            ])

        audio_map = "2:a?" if uses_separate_audio else "0:a?"
        cmd.extend(FFmpegService._encoded_video_output_args(filter_complex, audio_map, output_path))
        return cmd

    @staticmethod
    def build_full_source_command(
        *,
        source_path: str,
        output_path: str,
        start_time: float,
        end_time: float,
        source_sync_offset: float = 0.0,
        audio_path: str | None = None,
        audio_sync_offset: float = 0.0,
        output_width: int = 1920,
        output_height: int = 1080,
    ) -> list[str]:
        """Build the ffmpeg command used for full-screen source or full-camera clips."""
        duration = max(0.001, float(end_time) - float(start_time))
        output_width = max(2, int(output_width or 1920))
        output_height = max(2, int(output_height or 1080))
        audio_input_path = audio_path or source_path
        uses_separate_audio = bool(audio_path and os.path.abspath(audio_path) != os.path.abspath(source_path))
        filter_complex = (
            f"[0:v]scale={output_width}:{output_height}:force_original_aspect_ratio=decrease,"
            f"pad={output_width}:{output_height}:(ow-iw)/2:(oh-ih)/2,setsar=1[v]"
        )

        cmd = [
            ffmpeg_binary(),
            "-ss",
            str(FFmpegService._source_timestamp(start_time, source_sync_offset)),
            "-t",
            str(duration),
            "-i",
            source_path,
        ]
        if uses_separate_audio:
            cmd.extend([
                "-ss",
                str(FFmpegService._source_timestamp(start_time, audio_sync_offset)),
                "-t",
                str(duration),
                "-i",
                audio_input_path,
            ])

        audio_map = "1:a?" if uses_separate_audio else "0:a?"
        cmd.extend(FFmpegService._encoded_video_output_args(filter_complex, audio_map, output_path))
        return cmd

    @staticmethod
    def build_clip_fade_command(
        *,
        input_path: str,
        output_path: str,
        clip_duration_seconds: float,
        fade_duration_seconds: float,
        fade_in: bool = False,
        fade_out: bool = False,
    ) -> list[str]:
        """Build an ffmpeg command for per-clip fade transitions."""
        duration = max(0.001, float(clip_duration_seconds or 0.001))
        fade_duration = min(max(0.0, float(fade_duration_seconds or 0.0)), duration / 2)
        filters = []
        if fade_in and fade_duration > 0:
            filters.append(f"fade=t=in:st=0:d={round(fade_duration, 3)}")
        if fade_out and fade_duration > 0:
            start = max(0.0, duration - fade_duration)
            filters.append(f"fade=t=out:st={round(start, 3)}:d={round(fade_duration, 3)}")
        video_filter = ",".join(filters) if filters else "null"
        return [
            ffmpeg_binary(),
            "-i",
            input_path,
            "-vf",
            video_filter,
            *FFmpegService._video_encoder_args(None, "veryfast"),
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            "-y",
            output_path,
        ]

    @staticmethod
    def output_dimensions_for_aspect_ratio(aspect_ratio: str | None) -> tuple[int, int]:
        """Return the default render canvas for a supported layout aspect ratio."""
        return {
            "4:3": (1440, 1080),
            "1:1": (1080, 1080),
            "9:16": (1080, 1920),
            "16:9": (1920, 1080),
        }.get(str(aspect_ratio or "16:9"), (1920, 1080))

    @staticmethod
    def _source_timestamp(timeline_time: float, sync_offset: float) -> float:
        return round(max(0.0, float(timeline_time or 0.0) - float(sync_offset or 0.0)), 3)

    @staticmethod
    def _pip_camera_dimensions(output_width: int, output_height: int, size: str, shape: str = "rounded_rectangle") -> tuple[int, int]:
        width_ratio_by_size = {
            "small": 0.20,
            "medium": 0.26,
            "large": 0.34,
        }
        ratio = width_ratio_by_size.get(str(size or "medium").lower(), 0.26)
        camera_width = _even_int(output_width * ratio)
        camera_height = camera_width if str(shape or "").lower() == "circle" else _even_int(camera_width * 9 / 16)
        max_height = _even_int(output_height * 0.45)
        if camera_height > max_height:
            camera_height = max_height
            camera_width = camera_height if str(shape or "").lower() == "circle" else _even_int(camera_height * 16 / 9)
        return max(2, camera_width), max(2, camera_height)

    @staticmethod
    def _pip_camera_filter(camera_width: int, camera_height: int, shape: str) -> str:
        shape_value = str(shape or "rounded_rectangle").lower()
        if shape_value == "circle":
            radius = max(1, min(camera_width, camera_height) // 2)
            alpha = _escape_ffmpeg_expr(
                f"if(lte((X-W/2)*(X-W/2)+(Y-H/2)*(Y-H/2),{radius * radius}),255,0)"
            )
            return (
                f"scale={camera_width}:{camera_height}:force_original_aspect_ratio=increase,"
                f"crop={camera_width}:{camera_height},setsar=1,format=rgba,"
                f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='{alpha}'"
            )
        if shape_value == "rounded_rectangle":
            radius = max(6, min(camera_width, camera_height) // 10)
            alpha = _escape_ffmpeg_expr(
                "if(lte("
                f"pow(max(abs(X-W/2)-(W/2-{radius}),0),2)+"
                f"pow(max(abs(Y-H/2)-(H/2-{radius}),0),2),"
                f"{radius * radius}),255,0)"
            )
            return (
                f"scale={camera_width}:{camera_height}:force_original_aspect_ratio=decrease,"
                f"pad={camera_width}:{camera_height}:(ow-iw)/2:(oh-ih)/2,setsar=1,format=rgba,"
                f"geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':a='{alpha}'"
            )
        return (
            f"scale={camera_width}:{camera_height}:force_original_aspect_ratio=decrease,"
            f"pad={camera_width}:{camera_height}:(ow-iw)/2:(oh-ih)/2,setsar=1"
        )

    @staticmethod
    def _pip_overlay_position(
        output_width: int,
        output_height: int,
        camera_width: int,
        camera_height: int,
        corner: str,
        margin: int,
    ) -> tuple[int, int]:
        corner_value = str(corner or "bottom_right").lower()
        left = margin
        right = max(margin, output_width - camera_width - margin)
        top = margin
        bottom = max(margin, output_height - camera_height - margin)
        return {
            "top_left": (left, top),
            "top_right": (right, top),
            "bottom_left": (left, bottom),
            "bottom_right": (right, bottom),
        }.get(corner_value, (right, bottom))

    @staticmethod
    def _encoded_video_output_args(
        filter_complex: str,
        audio_map: str,
        output_path: str,
        *,
        video_bitrate: str | None = None,
        audio_bitrate: str | None = "192k",
        encoder_preset: str = "veryfast",
    ) -> list[str]:
        args = [
            "-filter_complex",
            filter_complex,
            "-map",
            "[v]",
            "-map",
            audio_map,
        ]
        args.extend(FFmpegService._video_encoder_args(video_bitrate, encoder_preset))
        args.extend([
            "-c:a",
            "aac",
            "-b:a",
            FFmpegService._normalize_audio_bitrate(audio_bitrate),
            "-shortest",
            "-movflags",
            "+faststart",
            "-y",
            output_path,
        ])
        return args

    @staticmethod
    def _normalize_audio_bitrate(value: object) -> str:
        text = str(value or "192k").strip().lower().replace(" ", "")
        if text.endswith("kbps"):
            return f"{text[:-4]}k"
        if text.endswith("mbps"):
            return f"{text[:-4]}M"
        if text.endswith(("k", "m")):
            return text
        if text.isdigit():
            return f"{text}k"
        return "192k"

    @staticmethod
    def _normalize_video_bitrate(value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip().lower().replace(" ", "")
        if not text:
            return None
        if text.endswith("mbps"):
            return f"{text[:-4]}M"
        if text.endswith("kbps"):
            return f"{text[:-4]}k"
        if text.endswith(("m", "k")):
            return text
        if text.isdigit():
            return f"{text}k"
        return None

    @staticmethod
    def _video_quality_args(video_bitrate: object | None) -> list[str]:
        normalized = FFmpegService._normalize_video_bitrate(video_bitrate)
        if not normalized:
            return ["-crf", "20"]
        maxrate = normalized
        bufsize = FFmpegService._double_bitrate(normalized)
        return ["-b:v", normalized, "-maxrate", maxrate, "-bufsize", bufsize]

    @staticmethod
    def _video_encoder_args(video_bitrate: object | None = None, encoder_preset: str = "veryfast") -> list[str]:
        encoder = FFmpegService._preferred_h264_encoder()
        normalized = FFmpegService._normalize_video_bitrate(video_bitrate)
        if encoder == "h264_nvenc":
            args = ["-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr"]
            if normalized:
                args.extend(["-b:v", normalized, "-maxrate", normalized, "-bufsize", FFmpegService._double_bitrate(normalized)])
            else:
                args.extend(["-cq", "20"])
            return args
        if encoder == "h264_qsv":
            args = ["-c:v", "h264_qsv"]
            if normalized:
                args.extend(["-b:v", normalized])
            else:
                args.extend(["-global_quality", "20"])
            return args
        if encoder == "h264_vaapi":
            args = ["-c:v", "h264_vaapi"]
            if normalized:
                args.extend(["-b:v", normalized])
            return args
        if encoder == "h264_amf":
            args = ["-c:v", "h264_amf", "-quality", "speed"]
            if normalized:
                args.extend(["-b:v", normalized])
            else:
                args.extend(["-qp_i", "20", "-qp_p", "22", "-qp_b", "24"])
            return args

        return ["-c:v", "libx264", "-preset", encoder_preset or "veryfast", *FFmpegService._video_quality_args(video_bitrate)]

    @staticmethod
    def _preferred_h264_encoder() -> str | None:
        mode = str(getattr(settings, "FFMPEG_HARDWARE_ACCELERATION", "auto") or "auto").strip().lower()
        if mode in {"off", "none", "false", "cpu", "libx264"}:
            logger.info("FFmpeg HW acceleration explicitly disabled (mode=%s) — using CPU libx264", mode)
            return None
        explicit = {
            "nvenc": "h264_nvenc",
            "nvidia": "h264_nvenc",
            "qsv": "h264_qsv",
            "intel": "h264_qsv",
            "vaapi": "h264_vaapi",
            "amf": "h264_amf",
            "amd": "h264_amf",
        }
        available = FFmpegService._available_h264_encoders()
        if mode in explicit:
            encoder = explicit[mode]
            if encoder in available:
                logger.info("FFmpeg HW encoder selected: %s (explicit mode=%s)", encoder, mode)
                return encoder
            else:
                logger.warning(
                    "FFmpeg HW encoder '%s' requested via mode=%s but NOT AVAILABLE — falling back to CPU libx264",
                    encoder, mode,
                )
                return None
        for encoder in ("h264_nvenc", "h264_qsv", "h264_vaapi", "h264_amf"):
            if encoder in available:
                logger.info("FFmpeg HW encoder selected: %s (auto-detected)", encoder)
                return encoder
        logger.warning(
            "FFmpeg HW acceleration mode=auto but NO hardware encoder detected (available=%s) — using CPU libx264",
            available,
        )
        return None

    @staticmethod
    def _available_h264_encoders() -> set[str]:
        if isinstance(FFmpegService._encoder_cache, set):
            return FFmpegService._encoder_cache
        try:
            proc = subprocess.run(
                [ffmpeg_binary(), "-hide_banner", "-encoders"],
                capture_output=True,
                text=True,
                timeout=8,
                check=False,
            )
            output = f"{proc.stdout}\n{proc.stderr}"
        except Exception:
            output = ""
        encoders = {
            encoder
            for encoder in ("h264_nvenc", "h264_qsv", "h264_vaapi", "h264_amf")
            if encoder in output
        }
        FFmpegService._encoder_cache = encoders
        return encoders

    # ── Public HW encoder probe / resolution ──

    @staticmethod
    async def probe_hw_encoder(encoder_name: str = "h264_nvenc") -> dict:
        """Check if a hardware encoder is available and actually working.

        Returns:
            {'available': True/False, 'encoder': str, 'details': str,
             'fallback': 'libx264', 'verified': True/False}
        The 'verified' flag indicates the encoder passed a short test-encode.
        """
        result: dict = {
            "available": False,
            "encoder": encoder_name,
            "details": "",
            "fallback": "libx264",
            "verified": False,
        }
        # Step 1: check if encoder is compiled in
        registered = FFmpegService._available_h264_encoders()
        if encoder_name not in registered:
            result["details"] = (
                f"Encoder '{encoder_name}' is NOT registered in ffmpeg -encoders. "
                f"Available HW encoders: {sorted(registered) if registered else 'none'}"
            )
            logger.warning("probe_hw_encoder: %s — NOT FOUND in ffmpeg encoders list", encoder_name)
            return result

        result["available"] = True
        result["details"] = f"Encoder '{encoder_name}' found in ffmpeg -encoders output."

        # Step 2: try a short test encode to verify it actually works
        try:
            logger.info("probe_hw_encoder: attempting test encode with %s", encoder_name)
            test_cmd = [
                ffmpeg_binary(), "-y",
                "-f", "lavfi", "-i", f"testsrc2=size=128x128:rate=1:d=1",
                "-c:v", encoder_name,
                "-preset", "p1" if encoder_name == "h264_nvenc" else "veryfast",
                "-t", "1",
                "-f", "null", "-",
            ]
            stdout, stderr, code = await FFmpegService._run_process(
                test_cmd,
                error_prefix=f"Test encode with {encoder_name}",
                allow_failure=True,
            )
            if code == 0:
                result["verified"] = True
                result["details"] += " Test encode PASSED."
                logger.info("probe_hw_encoder: %s test encode SUCCESS", encoder_name)
            else:
                result["details"] += (
                    f" Test encode FAILED (exit code {code}): "
                    f"{stderr.decode()[:200] if stderr else '(no stderr)'}"
                )
                logger.warning(
                    "probe_hw_encoder: %s test encode FAILED (exit code %d). "
                    "Encoder is listed but not functional — likely driver/Docker passthrough issue.",
                    encoder_name, code,
                )
        except Exception as exc:
            result["details"] += f" Test encode raised exception: {exc}"
            logger.error("probe_hw_encoder: %s test encode exception: %s", encoder_name, exc)

        return result

    @staticmethod
    async def resolve_video_encoder(settings_obj=None) -> str:
        """Return the best available video encoder string.

        If hardware acceleration is enabled and a working HW encoder is detected,
        returns e.g. 'h264_nvenc'. Otherwise returns 'libx264'.

        This is the canonical entry point for callers that need to know which
        encoder will actually be used *before* building the ffmpeg command.
        """
        preferred = FFmpegService._preferred_h264_encoder()
        if preferred is None:
            logger.info("resolve_video_encoder: no HW encoder available — returning libx264")
            return "libx264"

        logger.info(
            "resolve_video_encoder: HW encoder candidate '%s' — verifying with test encode",
            preferred,
        )
        probe = await FFmpegService.probe_hw_encoder(preferred)
        if probe["verified"]:
            logger.info(
                "resolve_video_encoder: verified HW encoder '%s' — using it for rendering",
                preferred,
            )
            return preferred

        logger.warning(
            "resolve_video_encoder: HW encoder '%s' listed but failed test encode — "
            "falling back to libx264. Probe details: %s",
            preferred, probe["details"],
        )
        return "libx264"

    @staticmethod
    def _command_uses_hardware_encoder(cmd: list[str]) -> bool:
        hardware_encoders = {"h264_nvenc", "h264_qsv", "h264_vaapi", "h264_amf"}
        return any(part in hardware_encoders for part in cmd)

    @staticmethod
    def _encoder_from_command(cmd: list[str]) -> str:
        """Extract the video encoder name from a command, e.g. 'h264_nvenc' or 'libx264'."""
        hardware_encoders = {"h264_nvenc", "h264_qsv", "h264_vaapi", "h264_amf"}
        for i, part in enumerate(cmd):
            if i > 0 and cmd[i - 1] == "-c:v":
                if part in hardware_encoders:
                    return part
                if part == "libx264":
                    return "libx264"
        # Fallback: scan for known encoder strings anywhere in cmd
        for part in cmd:
            if part in hardware_encoders:
                return part
            if part == "libx264":
                return "libx264"
        return "unknown"

    @staticmethod
    def _cpu_fallback_command(cmd: list[str]) -> list[str]:
        fallback: list[str] = []
        skip_next = False
        hardware_options = {
            "-cq",
            "-global_quality",
            "-qp_i",
            "-qp_p",
            "-qp_b",
            "-quality",
            "-rc",
        }
        for index, part in enumerate(cmd):
            if skip_next:
                skip_next = False
                continue
            if index > 0 and cmd[index - 1] == "-c:v" and part in {"h264_nvenc", "h264_qsv", "h264_vaapi", "h264_amf"}:
                fallback.append("libx264")
                continue
            if part in hardware_options:
                skip_next = True
                continue
            if index > 0 and cmd[index - 1] == "-preset" and part in {"p1", "p2", "p3", "p4", "p5", "p6", "p7"}:
                fallback.append("veryfast")
                continue
            fallback.append(part)
        if "-preset" not in fallback:
            insert_at = fallback.index("libx264") + 1 if "libx264" in fallback else len(fallback) - 1
            fallback[insert_at:insert_at] = ["-preset", "veryfast"]
        if "-crf" not in fallback and "-b:v" not in fallback:
            insert_at = fallback.index("libx264") + 1 if "libx264" in fallback else len(fallback) - 1
            fallback[insert_at:insert_at] = ["-crf", "20"]
        return fallback

    @staticmethod
    def _double_bitrate(value: str) -> str:
        suffix = value[-1]
        number_text = value[:-1] if suffix.lower() in {"k", "m"} else value
        try:
            doubled = float(number_text) * 2
        except ValueError:
            return value
        number = int(doubled) if doubled.is_integer() else round(doubled, 2)
        return f"{number}{suffix}" if suffix.lower() in {"k", "m"} else str(number)

    @staticmethod
    def _xfade_transition_name(transition: str) -> str:
        value = str(transition or "").lower()
        return {
            "crossfade": "fade",
            "fade": "fade",
            "wipe": "wipeleft",
            "wipe_left": "wipeleft",
            "wipe_right": "wiperight",
            "wipe_up": "wipeup",
            "wipe_down": "wipedown",
        }.get(value, "fade")

    @staticmethod
    async def concat_videos(
        clip_paths: List[str],
        output_path: str,
        cancel_check: Callable[[], None] | None = None,
        *,
        video_bitrate: str | None = None,
        audio_bitrate: str | None = "192k",
        output_width: int | None = None,
        output_height: int | None = None,
        fps: int | None = 30,
        prefer_stream_copy: bool = False,
    ) -> str:
        """
        Concatenate multiple video clips into one.

        Uses the FFmpeg concat **filter** (decodes all clips to raw frames
        first) instead of the concat **demuxer**, because the demuxer is
        fragile across clips with different GOP / keyframe structures — even
        when all clips share the same encoder.  The filter path is slower
        (everything must be decoded) but 100 % reliable.
        """
        n = len(clip_paths)
        if n == 0:
            raise ValueError("No clips to concatenate")
        if n == 1:
            # Single clip — just re-encode to normalise
            cmd_single = [
                ffmpeg_binary(), "-i", clip_paths[0],
            ]
            vf = FFmpegService._concat_video_filter(output_width, output_height, fps)
            if vf:
                cmd_single.extend(["-vf", vf])
            cmd_single.extend([
                *FFmpegService._video_encoder_args(video_bitrate, "veryfast"),
                "-c:a", "aac", "-b:a", FFmpegService._normalize_audio_bitrate(audio_bitrate),
                "-ar", "48000", "-ac", "2",
                "-movflags", "+faststart",
                "-y", output_path,
            ])
            _, stderr_s, rc = await FFmpegService._run_process_with_encoder_fallback(
                cmd_single, error_prefix="Concat single clip",
                cancel_check=cancel_check, allow_failure=False,
            )
            if rc != 0:
                raise RuntimeError(f"Single-clip concat failed: {stderr_s.decode()[:800]}")
            return output_path

        # ── Stream-copy fast path (only when explicitly asked) ──────────
        if prefer_stream_copy:
            list_path = output_path + ".txt"
            with open(list_path, "w") as f:
                for clip in clip_paths:
                    f.write(f"file '{clip}'\n")
            try:
                cmd = [ffmpeg_binary(), "-f", "concat", "-safe", "0", "-i", list_path,
                       "-c", "copy", "-movflags", "+faststart", "-y", output_path]
                _, _, rc = await FFmpegService._run_process(
                    cmd, error_prefix="Concat copy",
                    cancel_check=cancel_check, allow_failure=True,
                )
                if rc == 0:
                    return output_path
            finally:
                if os.path.exists(list_path):
                    os.remove(list_path)

        # ── Concat FILTER path (reliable) ──────────────────────────────
        # Build: ffmpeg -i c0 -i c1 ... -filter_complex "[0:v][0:a][1:v][1:a]concat=n=...:v=1:a=1[vraw][araw];[vraw]<video_filter>[outv];[araw]anull[outa]" -map "[outv]" -map "[outa]" ...
        cmd = [ffmpeg_binary()]
        for clip in clip_paths:
            cmd.extend(["-i", clip])

        filter_chunks = "".join(f"[{i}:v][{i}:a]" for i in range(n))
        concat_part = f"{filter_chunks}concat=n={n}:v=1:a=1[vraw][araw]"

        vf = FFmpegService._concat_video_filter(output_width, output_height, fps)
        if vf:
            filter_complex = f"{concat_part};[vraw]{vf}[outv];[araw]anull[outa]"
        else:
            filter_complex = f"{concat_part};[vraw]null[outv];[araw]anull[outa]"

        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "[outv]", "-map", "[outa]",
            *FFmpegService._video_encoder_args(video_bitrate, "veryfast"),
            "-c:a", "aac", "-b:a", FFmpegService._normalize_audio_bitrate(audio_bitrate),
            "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart",
            "-y", output_path,
        ])

        logger.info("Concat: starting concat FILTER render — %d clips", n)
        _, stderr, returncode = await FFmpegService._run_process_with_encoder_fallback(
            cmd,
            error_prefix="Concat filter",
            cancel_check=cancel_check,
            allow_failure=False,
        )
        if returncode != 0:
            raise RuntimeError(f"Concat filter failed: {stderr.decode()[:800]}")

        logger.info("Concat: finished successfully — %d clips → %s", n, output_path)
        return output_path

    @staticmethod
    def _concat_video_filter(output_width: int | None, output_height: int | None, fps: int | None) -> str:
        filters: list[str] = []
        if fps:
            filters.append(f"fps={int(fps)}")
        if output_width and output_height:
            width = max(2, int(output_width))
            height = max(2, int(output_height))
            filters.extend([
                f"scale={width}:{height}:force_original_aspect_ratio=decrease",
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
                "setsar=1",
            ])
        filters.append("format=yuv420p")
        return ",".join(filters)

    @staticmethod
    async def concat_videos_with_transitions(
        *,
        clip_paths: List[str],
        clip_durations: List[float],
        transitions: List[dict[str, Any]],
        output_path: str,
        output_width: int = 1920,
        output_height: int = 1080,
        video_bitrate: str | None = None,
        audio_bitrate: str | None = "192k",
        fps: int | None = 30,
        cancel_check: Callable[[], None] | None = None,
    ) -> str:
        """Concatenate clips through FFmpeg xfade/acrossfade visual transitions."""
        cmd = FFmpegService.build_concat_with_transitions_command(
            clip_paths=clip_paths,
            clip_durations=clip_durations,
            transitions=transitions,
            output_path=output_path,
            output_width=output_width,
            output_height=output_height,
            video_bitrate=video_bitrate,
            audio_bitrate=audio_bitrate,
            fps=fps,
        )
        await FFmpegService._run_process_with_encoder_fallback(
            cmd,
            error_prefix="Transition concat failed",
            stderr_limit=800,
            cancel_check=cancel_check,
        )
        return output_path

    @staticmethod
    def build_concat_with_transitions_command(
        *,
        clip_paths: List[str],
        clip_durations: List[float],
        transitions: List[dict[str, Any]],
        output_path: str,
        output_width: int = 1920,
        output_height: int = 1080,
        video_bitrate: str | None = None,
        audio_bitrate: str | None = "192k",
        fps: int | None = 30,
    ) -> list[str]:
        """Build an FFmpeg filter graph that renders crossfade/wipe boundaries."""
        if len(clip_paths) < 2:
            raise ValueError("At least two clips are required for transition concat")
        if len(clip_durations) != len(clip_paths):
            raise ValueError("clip_durations must match clip_paths")

        transitions_by_boundary = {
            int(item["boundary_index"]): item
            for item in transitions
            if item.get("boundary_index") is not None
        }
        inputs: list[str] = [ffmpeg_binary()]
        for path in clip_paths:
            inputs.extend(["-i", path])

        filter_parts: list[str] = []
        output_width = max(2, int(output_width or 1920))
        output_height = max(2, int(output_height or 1080))
        for index in range(len(clip_paths)):
            filter_parts.append(
                f"[{index}:v]setpts=PTS-STARTPTS,"
                f"scale={output_width}:{output_height}:force_original_aspect_ratio=decrease,"
                f"pad={output_width}:{output_height}:(ow-iw)/2:(oh-ih)/2,"
                f"setsar=1,fps={int(fps or 30)},format=yuv420p[v{index}]"
            )
            filter_parts.append(f"[{index}:a]asetpts=PTS-STARTPTS[a{index}]")

        current_video = "v0"
        current_audio = "a0"
        current_duration = max(0.001, float(clip_durations[0] or 0.001))

        for index in range(1, len(clip_paths)):
            boundary_index = index - 1
            transition = transitions_by_boundary.get(boundary_index)
            next_duration = max(0.001, float(clip_durations[index] or 0.001))
            out_video = f"vx{boundary_index}"
            out_audio = f"ax{boundary_index}"

            if transition:
                duration = min(
                    max(0.001, float(transition.get("duration_seconds") or 0.001)),
                    current_duration / 2,
                    next_duration / 2,
                )
                offset = max(0.0, current_duration - duration)
                xfade_name = FFmpegService._xfade_transition_name(
                    str(transition.get("transition") or "fade")
                )
                filter_parts.append(
                    f"[{current_video}][v{index}]xfade=transition={xfade_name}:"
                    f"duration={round(duration, 3)}:offset={round(offset, 3)}[{out_video}]"
                )
                filter_parts.append(
                    f"[{current_audio}][a{index}]acrossfade=d={round(duration, 3)}:"
                    f"c1=tri:c2=tri[{out_audio}]"
                )
                current_duration = current_duration + next_duration - duration
            else:
                filter_parts.append(
                    f"[{current_video}][{current_audio}][v{index}][a{index}]"
                    f"concat=n=2:v=1:a=1[{out_video}][{out_audio}]"
                )
                current_duration = current_duration + next_duration

            current_video = out_video
            current_audio = out_audio

        return [
            *inputs,
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            f"[{current_video}]",
            "-map",
            f"[{current_audio}]",
            *FFmpegService._video_encoder_args(video_bitrate, "veryfast"),
            "-c:a",
            "aac",
            "-b:a",
            FFmpegService._normalize_audio_bitrate(audio_bitrate),
            "-ar",
            "48000",
            "-ac",
            "2",
            "-movflags",
            "+faststart",
            "-y",
            output_path,
        ]

    @staticmethod
    async def create_solid_color_clip(
        output_path: str,
        *,
        duration_seconds: float,
        width: int = 1920,
        height: int = 1080,
        background_color: str = "#111827",
        cancel_check: Callable[[], None] | None = None,
    ) -> str:
        """Create a silent solid-color MP4 clip for generated title/end cards."""
        color = FFmpegService._ffmpeg_color(background_color)
        duration = max(0.1, float(duration_seconds or 0.1))
        cmd = [
            ffmpeg_binary(),
            "-f", "lavfi",
            "-i", f"color=c={color}:s={int(width)}x{int(height)}:r=30",
            "-f", "lavfi",
            "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-t", str(duration),
            "-shortest",
            *FFmpegService._video_encoder_args(None, "veryfast"),
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",
            "-y",
            output_path,
        ]
        await FFmpegService._run_process_with_encoder_fallback(
            cmd,
            error_prefix="Color clip generation failed",
            stderr_limit=800,
            cancel_check=cancel_check,
        )
        return output_path

    @staticmethod
    async def create_slideshow_clip(
        output_path: str,
        *,
        image_paths: list[str],
        durations: list[float],
        width: int = 1920,
        height: int = 1080,
        background_color: str = "#101827",
        cancel_check: Callable[[], None] | None = None,
    ) -> str:
        """Create a silent MP4 slideshow from pre-rendered page/slide images."""
        if not image_paths:
            raise ValueError("At least one image is required for slideshow generation")
        safe_durations = [
            max(0.1, float(durations[index] if index < len(durations) else durations[-1] if durations else 1.0))
            for index, _ in enumerate(image_paths)
        ]
        total_duration = round(sum(safe_durations), 3)
        color = FFmpegService._ffmpeg_color(background_color)
        manifest_path: str | None = None
        if len(image_paths) == 1:
            cmd = [ffmpeg_binary(), "-loop", "1", "-t", f"{safe_durations[0]:.3f}", "-i", image_paths[0]]
            video_filter = (
                f"[0:v]scale={int(width)}:{int(height)}:force_original_aspect_ratio=decrease,"
                f"pad={int(width)}:{int(height)}:(ow-iw)/2:(oh-ih)/2:color={color},"
                f"setsar=1,fps=30,format=yuv420p,trim=duration={safe_durations[0]:.3f},"
                "setpts=PTS-STARTPTS[v]"
            )
        else:
            # A filter input per page exhausts FFmpeg filter threads on larger decks.
            # FFconcat supplies the same timed image sequence through one video stream.
            manifest_path = f"{output_path}.ffconcat"
            manifest_lines = ["ffconcat version 1.0"]
            for image_path, duration in zip(image_paths, safe_durations):
                manifest_lines.extend([
                    f"file '{FFmpegService._concat_file_path(image_path)}'",
                    f"duration {duration:.6f}",
                ])
            # Repeating the final image makes the concat demuxer apply its duration.
            manifest_lines.append(f"file '{FFmpegService._concat_file_path(image_paths[-1])}'")
            with open(manifest_path, "w", encoding="utf-8", newline="\n") as handle:
                handle.write("\n".join(manifest_lines) + "\n")
            cmd = [ffmpeg_binary(), "-safe", "0", "-f", "concat", "-i", manifest_path]
            video_filter = (
                f"[0:v]scale={int(width)}:{int(height)}:force_original_aspect_ratio=decrease,"
                f"pad={int(width)}:{int(height)}:(ow-iw)/2:(oh-ih)/2:color={color},"
                "setsar=1,fps=30,format=yuv420p[v]"
            )

        cmd.extend([
            "-f", "lavfi",
            "-t", f"{total_duration:.3f}",
            "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
        ])
        cmd.extend([
            "-filter_complex",
            video_filter,
            "-map",
            "[v]",
            "-map",
            "1:a",
            "-t",
            f"{total_duration:.3f}",
            *FFmpegService._video_encoder_args(None, "veryfast"),
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            "-y",
            output_path,
        ])
        try:
            await FFmpegService._run_process_with_encoder_fallback(
                cmd,
                error_prefix="Slideshow generation failed",
                stderr_limit=1600,
                cancel_check=cancel_check,
            )
        finally:
            if manifest_path:
                try:
                    os.remove(manifest_path)
                except FileNotFoundError:
                    pass
        return output_path

    @staticmethod
    async def trim_silence_from_clip(
        input_path: str,
        output_path: str,
        threshold_db: int = -40,
        min_silence: float = 0.8,
        cancel_check: Callable[[], None] | None = None,
    ) -> str:
        """
        Remove silence from a clip (used for SHORTEN action).
        Uses the silenceremove filter to strip leading/trailing silence
        and compress long internal pauses.
        """
        cmd = [
            ffmpeg_binary(), "-i", input_path,
            "-af", (
                f"silenceremove=start_periods=1:start_duration=0.1:start_threshold={threshold_db}dB"
                f":stop_periods=-1:stop_duration={min_silence}:stop_threshold={threshold_db}dB"
            ),
            "-c:v", "copy",
            "-y", output_path,
        ]
        _, _, returncode = await FFmpegService._run_process(
            cmd,
            error_prefix="Silence trim failed",
            cancel_check=cancel_check,
            allow_failure=True,
        )

        if returncode != 0:
            # Fallback: just copy without silence removal
            import shutil
            shutil.copy2(input_path, output_path)

        return output_path

    @staticmethod
    async def burn_subtitles(
        video_path: str,
        srt_path: str,
        output_path: str,
        font_size: int = 24,
        placement: str = "bottom_center",
        style: dict | None = None,
        cancel_check: Callable[[], None] | None = None,
    ) -> str:
        """Burn SRT subtitles into the video (requires re-encoding)."""
        force_style = FFmpegService._subtitle_force_style(
            font_size=font_size,
            placement=placement,
            style=style,
        )
        cmd = [
            ffmpeg_binary(), "-i", video_path,
            "-vf", f"subtitles={FFmpegService._escape_subtitle_path(srt_path)}:force_style='{force_style}'",
            *FFmpegService._video_encoder_args(None, "veryfast"),
            "-c:a", "copy",
            "-movflags", "+faststart",
            "-y",
            output_path
        ]
        await FFmpegService._run_process_with_encoder_fallback(
            cmd,
            error_prefix="Subtitle burn failed",
            cancel_check=cancel_check,
        )
        return output_path

    @staticmethod
    async def burn_ass_overlay(
        video_path: str,
        ass_path: str,
        output_path: str,
        cancel_check: Callable[[], None] | None = None,
    ) -> str:
        """Burn an ASS overlay track into the video while preserving audio."""
        cmd = [
            ffmpeg_binary(), "-i", video_path,
            "-vf", f"subtitles={FFmpegService._escape_subtitle_path(ass_path)}",
            *FFmpegService._video_encoder_args(None, "veryfast"),
            "-c:a", "copy",
            "-movflags", "+faststart",
            "-y",
            output_path,
        ]
        await FFmpegService._run_process_with_encoder_fallback(
            cmd,
            error_prefix="ASS overlay burn failed",
            stderr_limit=800,
            cancel_check=cancel_check,
        )
        return output_path

    @staticmethod
    def _subtitle_force_style(font_size: int, placement: str, style: dict | None = None) -> str:
        style = dict(style or {})
        primary = FFmpegService._ass_color(style.get("primary_color"), "FFFFFF")
        outline = FFmpegService._ass_color(style.get("outline_color"), "000000")
        outline_width = int(style.get("outline_width") if style.get("outline_width") is not None else 2)
        border_style = 3 if style.get("background") == "box" else 1
        alignment = {
            "bottom_left": 1,
            "bottom_center": 2,
            "bottom_right": 3,
            "top_left": 7,
            "top_center": 8,
            "top_right": 9,
        }.get(str(placement or "bottom_center"), 2)
        margin_v = 56 if alignment in {1, 2, 3} else 42
        return (
            f"FontSize={int(font_size or 24)},"
            f"PrimaryColour={primary},"
            f"OutlineColour={outline},"
            f"Outline={max(0, min(8, outline_width))},"
            f"BorderStyle={border_style},"
            f"Alignment={alignment},"
            f"MarginV={margin_v}"
        )

    @staticmethod
    def _ass_color(value: object, default_rgb: str) -> str:
        text = str(value or "").strip().lstrip("#")
        if len(text) != 6:
            text = default_rgb
        try:
            int(text, 16)
        except ValueError:
            text = default_rgb
        red, green, blue = text[0:2], text[2:4], text[4:6]
        return f"&H00{blue}{green}{red}"

    @staticmethod
    def _ffmpeg_color(value: object) -> str:
        text = str(value or "#111827").strip().lstrip("#")
        if len(text) != 6:
            text = "111827"
        try:
            int(text, 16)
        except ValueError:
            text = "111827"
        return f"0x{text}"

    @staticmethod
    def _concat_file_path(path: str) -> str:
        raw_path = str(path or "")
        # os.path.abspath on Linux treats a Windows drive path as relative and
        # incorrectly prefixes the container working directory (for example,
        # /app/C:/...). Preserve drive-qualified paths before normalizing.
        normalized = raw_path if re.match(r"^[A-Za-z]:[\\/]", raw_path) else os.path.abspath(raw_path)
        return normalized.replace("\\", "/").replace("'", r"'\''")

    @staticmethod
    def _escape_subtitle_path(path: str) -> str:
        return str(path).replace("\\", "/").replace(":", r"\:")

    @staticmethod
    async def extract_frame(video_path: str, timestamp: float, output_path: str) -> str:
        """Extract a single frame at a given timestamp."""
        cmd = [
            ffmpeg_binary(),
            "-ss", str(timestamp),
            "-i", video_path,
            "-frames:v", "1",
            "-q:v", "2",
            "-y",
            output_path
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"Frame extraction failed: {stderr.decode()}")

        return output_path

    @staticmethod
    async def extract_frames_batch(
        video_path: str,
        output_dir: str,
        interval: float = 1.0
    ) -> List[str]:
        """Extract frames at regular intervals for scene detection."""
        os.makedirs(output_dir, exist_ok=True)
        cmd = [
            ffmpeg_binary(), "-i", video_path,
            "-vf", f"fps=1/{interval}",
            "-q:v", "2",
            "-y",
            os.path.join(output_dir, "frame_%06d.jpg")
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        await proc.communicate()

        frames = sorted([
            os.path.join(output_dir, f)
            for f in os.listdir(output_dir) if f.endswith(".jpg")
        ])
        return frames

    @staticmethod
    def generate_srt(segments: List[dict]) -> str:
        """Generate SRT subtitle content from segments."""
        srt_lines = []
        for i, seg in enumerate(segments, 1):
            start = FFmpegService._format_srt_time(seg["start"])
            end = FFmpegService._format_srt_time(seg["end"])
            text = seg.get("text", "").strip()
            if text:
                srt_lines.append(f"{i}")
                srt_lines.append(f"{start} --> {end}")
                srt_lines.append(text)
                srt_lines.append("")

        return "\n".join(srt_lines)

    @staticmethod
    def _format_srt_time(seconds: float) -> str:
        """Convert seconds to SRT time format (HH:MM:SS,mmm)."""
        hrs = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds % 1) * 1000)
        return f"{hrs:02d}:{mins:02d}:{secs:02d},{millis:03d}"

    # ------------------------------------------------------------------
    # Letterboxing / black-bar detection and cropping (P2)
    # ------------------------------------------------------------------

    @staticmethod
    async def detect_crop_parameters(video_path: str) -> dict | None:
        """Run cropdetect on the first ~24 frames to find black-bar crop parameters.

        Returns a dict with w, h, x, y, and a ready-to-use crop_filter string,
        or None if no meaningful crop was detected.
        """
        cmd = [
            ffmpeg_binary(),
            "-i", video_path,
            "-vf", "cropdetect=24:2",
            "-f", "null", "-",
        ]

        try:
            _, stderr, _ = await FFmpegService._run_process(
                cmd,
                error_prefix="Crop detection failed",
                allow_failure=True,
                stderr_limit=20000,
            )
        except Exception as exc:
            logger.warning(
                "detect_crop_parameters: ffmpeg cropdetect raised %s — returning None",
                exc,
            )
            return None

        output = stderr.decode(errors="replace")

        # Parse every "crop=W:H:X:Y" line that cropdetect prints to stderr.
        matches: list[tuple[str, str, str, str]] = re.findall(
            r"crop=(\d+):(\d+):(\d+):(\d+)", output
        )
        if not matches:
            logger.info(
                "detect_crop_parameters: no crop= values found in cropdetect output"
            )
            return None

        # Most-frequently-detected crop is the stable letterbox boundary.
        counter = Counter(matches)
        (w_str, h_str, x_str, y_str), count = counter.most_common(1)[0]

        w, h, x, y = int(w_str), int(h_str), int(x_str), int(y_str)
        crop_filter = f"crop={w}:{h}:{x}:{y}"

        logger.info(
            "detect_crop_parameters: most common crop=%s (appeared %d/%d times)",
            crop_filter,
            count,
            len(matches),
        )

        return {
            "w": w,
            "h": h,
            "x": x,
            "y": y,
            "crop_filter": crop_filter,
        }

    @staticmethod
    async def has_letterboxing(video_path: str, threshold: float = 0.10) -> bool:
        """Quick check whether the video has significant black bars.

        Returns True when the black-bar height exceeds *threshold* of the
        total frame height (default 10 %).
        """
        crop = await FFmpegService.detect_crop_parameters(video_path)
        if crop is None:
            return False

        # Get full frame dimensions from ffprobe.
        meta = await FFmpegService.get_video_metadata(video_path)
        frame_height = meta.get("height", 0) or 0
        if frame_height <= 0:
            return False

        bar_height = frame_height - crop["h"]
        return bar_height > (frame_height * threshold)

    @staticmethod
    async def auto_crop_video(
        input_path: str,
        output_path: str,
        crop_params: dict | None = None,
        *,
        cancel_check: Callable[[], None] | None = None,
    ) -> str:
        """Re-encode *input_path* with the detected letterbox crop applied.

        When *crop_params* is None the method runs ``detect_crop_parameters``
        first.  The video is re-encoded through the standard hardware-encoder
        pathway (with automatic CPU fallback).
        """
        if crop_params is None:
            crop_params = await FFmpegService.detect_crop_parameters(input_path)

        if not crop_params:
            logger.info(
                "auto_crop_video: no crop needed for %s — copying (no re-encode)",
                input_path,
            )
            import shutil
            shutil.copy2(input_path, output_path)
            return output_path

        crop_filter = crop_params["crop_filter"] + ",format=yuv420p"
        encoder_args = FFmpegService._video_encoder_args(None, "veryfast")

        cmd = [
            ffmpeg_binary(),
            "-i", input_path,
            "-vf", crop_filter,
            *encoder_args,
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",
            "-y",
            output_path,
        ]

        await FFmpegService._run_process_with_encoder_fallback(
            cmd,
            error_prefix="Auto-crop re-encode failed",
            stderr_limit=800,
            cancel_check=cancel_check,
        )
        logger.info("auto_crop_video: cropped → %s", output_path)
        return output_path

    @staticmethod
    async def preprocess_for_compatibility(
        input_path: str,
        output_path: str,
        cancel_check: Callable[[], None] | None = None,
    ) -> str:
        """Convert iPhone .MOV / HEVC to 1080p H.264 MP4 for compatibility.

        Detects the best available H.264 encoder (hardware or CPU) and
        transcodes the input to a standardised format that the render
        pipeline can handle efficiently:

        - 1920x1080 (auto-scaling, preserving aspect ratio)
        - Constant 24 fps
        - H.264 video (hardware-accelerated when available)
        - AAC 128k audio

        Returns the output path on success.
        """
        encoder = FFmpegService._preferred_h264_encoder()
        video_args: list[str]

        if encoder == "h264_nvenc":
            video_args = [
                "-c:v", "h264_nvenc",
                "-preset", "p2",
                "-rc", "vbr",
                "-b:v", "5M",
                "-maxrate", "5M",
                "-bufsize", "10M",
            ]
        elif encoder == "h264_qsv":
            video_args = ["-c:v", "h264_qsv", "-b:v", "5M"]
        elif encoder == "h264_vaapi":
            video_args = ["-c:v", "h264_vaapi", "-b:v", "5M"]
        elif encoder == "h264_amf":
            video_args = [
                "-c:v", "h264_amf",
                "-quality", "speed",
                "-b:v", "5M",
            ]
        else:
            video_args = [
                "-c:v", "libx264",
                "-preset", "veryfast",
                "-crf", "23",
            ]

        cmd = [
            ffmpeg_binary(),
            "-i", input_path,
            "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,pad=1920:1080:(ow-iw)/2:(oh-ih)/2,fps=24",
            *video_args,
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            "-y",
            output_path,
        ]

        await FFmpegService._run_process_with_encoder_fallback(
            cmd,
            error_prefix="Preprocessing compatibility transcode failed",
            stderr_limit=800,
            cancel_check=cancel_check,
        )
        return output_path


def _even_int(value: float) -> int:
    number = int(round(float(value or 0)))
    return number if number % 2 == 0 else number - 1


def _escape_ffmpeg_expr(expression: str) -> str:
    return expression.replace(",", r"\,")


def _ffmpeg_audio_codec(value: str | None) -> str:
    codec = str(value or "aac").strip().lower()
    return {
        "aac": "aac",
        "mp3": "libmp3lame",
        "libmp3lame": "libmp3lame",
        "opus": "libopus",
        "libopus": "libopus",
    }.get(codec, "aac")


def _normalize_audio_bitrate(value: str | None) -> str:
    text = str(value or "192k").strip().lower().replace(" ", "")
    if text.endswith("kbps"):
        return f"{text[:-4]}k"
    if text.endswith("k"):
        return text
    if text.isdigit():
        return f"{text}k"
    return "192k"
# Singleton
ffmpeg_service = FFmpegService()
