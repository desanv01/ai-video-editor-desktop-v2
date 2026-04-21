"""
FFmpeg service — wraps ffmpeg CLI for all video/audio processing.
This is the core "tool" layer that MCP servers and agents call.
"""

import asyncio
import json
import os
import subprocess
from typing import List, Tuple, Optional
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
        stdout, stderr = await proc.communicate()

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
        font_size: int = 24
    ) -> str:
        """Burn SRT subtitles into the video (requires re-encoding)."""
        cmd = [
            "ffmpeg", "-i", video_path,
            "-vf", f"subtitles={srt_path}:force_style='FontSize={font_size},PrimaryColour=&HFFFFFF,OutlineColour=&H000000,Outline=2'",
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


# Singleton
ffmpeg_service = FFmpegService()
