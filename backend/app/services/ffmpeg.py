"""
FFmpeg service — wraps ffmpeg CLI for all video/audio processing.
This is the core "tool" layer that MCP servers and agents call.
"""

import asyncio
import json
import os
import subprocess
from typing import Any, List, Tuple, Optional
from config import settings


class FFmpegService:
    """All ffmpeg operations used by the pipeline."""

    @staticmethod
    async def get_video_metadata(video_path: str) -> dict:
        """Extract video metadata (duration, resolution, fps, codec)."""
        cmd = [
            "ffprobe", "-v", "quiet",
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

        return {
            "duration": float(fmt.get("duration", 0)),
            "size_bytes": int(fmt.get("size", 0)),
            "format": fmt.get("format_name", ""),
            "format_tags": fmt.get("tags", {}),
            "video_tags": video_stream.get("tags", {}),
            "audio_tags": audio_stream.get("tags", {}),
            "width": int(video_stream.get("width", 0)),
            "height": int(video_stream.get("height", 0)),
            "fps": eval(video_stream.get("r_frame_rate", "0/1")) if video_stream.get("r_frame_rate") else 0,
            "video_codec": video_stream.get("codec_name", ""),
            "audio_codec": audio_stream.get("codec_name", ""),
            "audio_sample_rate": int(audio_stream.get("sample_rate", 0)),
        }

    @staticmethod
    async def extract_audio(video_path: str, output_path: str, format: str = "wav") -> str:
        """Extract audio track from video file."""
        cmd = [
            "ffmpeg", "-i", video_path,
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
            "ffmpeg", "-i", audio_path,
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
        end_time: float
    ) -> str:
        """Trim a segment from the video without re-encoding (fast)."""
        cmd = [
            "ffmpeg",
            "-ss", str(start_time),
            "-i", video_path,
            "-t", str(end_time - start_time),
            "-c", "copy",                   # no re-encode — fast
            "-avoid_negative_ts", "make_zero",
            "-y",
            output_path
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"Trim failed: {stderr.decode()}")

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
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"Picture-in-picture render failed: {stderr.decode()[:800]}")

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
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"Side-by-side render failed: {stderr.decode()[:800]}")

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
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"Full-source render failed: {stderr.decode()[:800]}")

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
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"Clip fade render failed: {stderr.decode()[:800]}")

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
            "ffmpeg",
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
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
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
            "ffmpeg",
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
            "ffmpeg",
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
            "ffmpeg",
            "-i",
            input_path,
            "-vf",
            video_filter,
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "23",
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
    def _encoded_video_output_args(filter_complex: str, audio_map: str, output_path: str) -> list[str]:
        return [
            "-filter_complex",
            filter_complex,
            "-map",
            "[v]",
            "-map",
            audio_map,
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-shortest",
            "-movflags",
            "+faststart",
            "-y",
            output_path,
        ]

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
    async def concat_videos(clip_paths: List[str], output_path: str) -> str:
        """
        Concatenate multiple video clips into one.
        Tries stream copy first (fast), falls back to re-encode if codecs mismatch.
        """
        list_path = output_path + ".txt"
        with open(list_path, "w") as f:
            for clip in clip_paths:
                f.write(f"file '{clip}'\n")

        # Attempt 1: stream copy (fast, no quality loss)
        cmd = [
            "ffmpeg",
            "-f", "concat", "-safe", "0",
            "-i", list_path,
            "-c", "copy",
            "-movflags", "+faststart",
            "-y", output_path,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            # Attempt 2: re-encode (handles codec mismatches between clips)
            cmd_reencode = [
                "ffmpeg",
                "-f", "concat", "-safe", "0",
                "-i", list_path,
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
                "-y", output_path,
            ]
            proc2 = await asyncio.create_subprocess_exec(
                *cmd_reencode, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
            _, stderr2 = await proc2.communicate()

            os.remove(list_path)

            if proc2.returncode != 0:
                raise RuntimeError(f"Concat failed (both copy and re-encode): {stderr2.decode()[:500]}")
        else:
            os.remove(list_path)

        return output_path

    @staticmethod
    async def concat_videos_with_transitions(
        *,
        clip_paths: List[str],
        clip_durations: List[float],
        transitions: List[dict[str, Any]],
        output_path: str,
        output_width: int = 1920,
        output_height: int = 1080,
    ) -> str:
        """Concatenate clips through FFmpeg xfade/acrossfade visual transitions."""
        cmd = FFmpegService.build_concat_with_transitions_command(
            clip_paths=clip_paths,
            clip_durations=clip_durations,
            transitions=transitions,
            output_path=output_path,
            output_width=output_width,
            output_height=output_height,
        )
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"Transition concat failed: {stderr.decode()[:800]}")

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
        inputs: list[str] = ["ffmpeg"]
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
                f"setsar=1,format=yuv420p[v{index}]"
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
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
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
    ) -> str:
        """Create a silent solid-color MP4 clip for generated title/end cards."""
        color = FFmpegService._ffmpeg_color(background_color)
        duration = max(0.1, float(duration_seconds or 0.1))
        cmd = [
            "ffmpeg",
            "-f", "lavfi",
            "-i", f"color=c={color}:s={int(width)}x{int(height)}:r=30",
            "-f", "lavfi",
            "-i", "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-t", str(duration),
            "-shortest",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            "-y",
            output_path,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"Color clip generation failed: {stderr.decode()[:800]}")

        return output_path

    @staticmethod
    async def trim_silence_from_clip(
        input_path: str,
        output_path: str,
        threshold_db: int = -40,
        min_silence: float = 0.8,
    ) -> str:
        """
        Remove silence from a clip (used for SHORTEN action).
        Uses the silenceremove filter to strip leading/trailing silence
        and compress long internal pauses.
        """
        cmd = [
            "ffmpeg", "-i", input_path,
            "-af", (
                f"silenceremove=start_periods=1:start_duration=0.1:start_threshold={threshold_db}dB"
                f":stop_periods=-1:stop_duration={min_silence}:stop_threshold={threshold_db}dB"
            ),
            "-c:v", "copy",
            "-y", output_path,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
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
    ) -> str:
        """Burn SRT subtitles into the video (requires re-encoding)."""
        force_style = FFmpegService._subtitle_force_style(
            font_size=font_size,
            placement=placement,
            style=style,
        )
        cmd = [
            "ffmpeg", "-i", video_path,
            "-vf", f"subtitles={FFmpegService._escape_subtitle_path(srt_path)}:force_style='{force_style}'",
            "-c:a", "copy",
            "-y",
            output_path
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"Subtitle burn failed: {stderr.decode()}")

        return output_path

    @staticmethod
    async def burn_ass_overlay(video_path: str, ass_path: str, output_path: str) -> str:
        """Burn an ASS overlay track into the video while preserving audio."""
        cmd = [
            "ffmpeg", "-i", video_path,
            "-vf", f"subtitles={FFmpegService._escape_subtitle_path(ass_path)}",
            "-c:a", "copy",
            "-y",
            output_path,
        ]
        proc = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"ASS overlay burn failed: {stderr.decode()[:800]}")

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
    def _escape_subtitle_path(path: str) -> str:
        return str(path).replace("\\", "/").replace(":", r"\:")

    @staticmethod
    async def extract_frame(video_path: str, timestamp: float, output_path: str) -> str:
        """Extract a single frame at a given timestamp."""
        cmd = [
            "ffmpeg",
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
            "ffmpeg", "-i", video_path,
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


def _even_int(value: float) -> int:
    number = int(round(float(value or 0)))
    return number if number % 2 == 0 else number - 1


def _escape_ffmpeg_expr(expression: str) -> str:
    return expression.replace(",", r"\,")


# Singleton
ffmpeg_service = FFmpegService()
