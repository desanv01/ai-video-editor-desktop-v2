"""
MCP Video Tools Server

Exposes FFmpeg video/audio operations as MCP tools that LLMs can call.

Tools:
  - video_metadata: Get video file metadata (duration, resolution, fps, codecs)
  - video_extract_audio: Extract audio track from video → WAV file
  - video_trim: Trim a segment from a video file
  - video_concat: Concatenate multiple video clips into one
  - video_detect_silence: Detect silence regions in audio
  - video_extract_frame: Extract a single frame at a timestamp
  - subtitle_generate: Generate SRT subtitles from segment data
  - subtitle_burn: Burn SRT subtitles into a video file

This server wraps the existing FFmpegService so LLM agents can
perform video editing operations through the Model Context Protocol.
"""

import os
import sys
import json
import asyncio
import logging

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from mcp.server.models import InitializationOptions

logger = logging.getLogger(__name__)

# Add app to path for imports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

server = Server("ai-video-editor-video-tools")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="video_metadata",
            description="Get metadata for a video file: duration, resolution, fps, codec, file size.",
            inputSchema={
                "type": "object",
                "properties": {
                    "video_path": {"type": "string", "description": "Absolute path to the video file"},
                },
                "required": ["video_path"],
            },
        ),
        Tool(
            name="video_extract_audio",
            description="Extract audio track from a video file as WAV. Returns the output audio file path.",
            inputSchema={
                "type": "object",
                "properties": {
                    "video_path": {"type": "string", "description": "Path to the input video file"},
                    "output_path": {"type": "string", "description": "Path for the output WAV file"},
                },
                "required": ["video_path", "output_path"],
            },
        ),
        Tool(
            name="video_trim",
            description="Trim a segment from a video file between start_time and end_time (in seconds). Returns the output file path.",
            inputSchema={
                "type": "object",
                "properties": {
                    "video_path": {"type": "string", "description": "Path to the input video"},
                    "output_path": {"type": "string", "description": "Path for the trimmed output"},
                    "start_time": {"type": "number", "description": "Start time in seconds"},
                    "end_time": {"type": "number", "description": "End time in seconds"},
                },
                "required": ["video_path", "output_path", "start_time", "end_time"],
            },
        ),
        Tool(
            name="video_concat",
            description="Concatenate multiple video clips into a single output file. Clips must be provided in the desired order.",
            inputSchema={
                "type": "object",
                "properties": {
                    "clip_paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Ordered list of video clip file paths to concatenate",
                    },
                    "output_path": {"type": "string", "description": "Path for the concatenated output"},
                },
                "required": ["clip_paths", "output_path"],
            },
        ),
        Tool(
            name="video_detect_silence",
            description="Detect silence/pause regions in an audio file. Returns list of {start, end, duration} for each silent region.",
            inputSchema={
                "type": "object",
                "properties": {
                    "audio_path": {"type": "string", "description": "Path to the audio file (WAV or MP3)"},
                    "threshold_db": {"type": "integer", "description": "Silence threshold in dB (default: -40)", "default": -40},
                    "min_duration": {"type": "number", "description": "Minimum silence duration in seconds (default: 1.5)", "default": 1.5},
                },
                "required": ["audio_path"],
            },
        ),
        Tool(
            name="video_extract_frame",
            description="Extract a single frame from a video at a given timestamp. Returns the output image path.",
            inputSchema={
                "type": "object",
                "properties": {
                    "video_path": {"type": "string", "description": "Path to the video file"},
                    "timestamp": {"type": "number", "description": "Timestamp in seconds to extract the frame"},
                    "output_path": {"type": "string", "description": "Path for the output JPEG image"},
                },
                "required": ["video_path", "timestamp", "output_path"],
            },
        ),
        Tool(
            name="subtitle_generate",
            description="Generate an SRT subtitle file from a list of segments with text, start time, and end time.",
            inputSchema={
                "type": "object",
                "properties": {
                    "segments": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "start": {"type": "number"},
                                "end": {"type": "number"},
                            },
                            "required": ["text", "start", "end"],
                        },
                        "description": "List of subtitle segments",
                    },
                    "output_path": {"type": "string", "description": "Path for the output SRT file"},
                },
                "required": ["segments", "output_path"],
            },
        ),
        Tool(
            name="subtitle_burn",
            description="Burn SRT subtitles into a video file (hardcoded subtitles). Requires re-encoding.",
            inputSchema={
                "type": "object",
                "properties": {
                    "video_path": {"type": "string", "description": "Path to the input video"},
                    "srt_path": {"type": "string", "description": "Path to the SRT subtitle file"},
                    "output_path": {"type": "string", "description": "Path for the output video with burned subtitles"},
                    "font_size": {"type": "integer", "description": "Subtitle font size (default: 24)", "default": 24},
                },
                "required": ["video_path", "srt_path", "output_path"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    from services.ffmpeg import ffmpeg_service, FFmpegService

    try:
        if name == "video_metadata":
            result = await ffmpeg_service.get_video_metadata(arguments["video_path"])
            return [TextContent(type="text", text=json.dumps(result, indent=2))]

        elif name == "video_extract_audio":
            path = await ffmpeg_service.extract_audio(
                arguments["video_path"], arguments["output_path"]
            )
            return [TextContent(type="text", text=json.dumps({"status": "success", "output_path": path}))]

        elif name == "video_trim":
            path = await ffmpeg_service.trim_video(
                video_path=arguments["video_path"],
                output_path=arguments["output_path"],
                start_time=arguments["start_time"],
                end_time=arguments["end_time"],
            )
            return [TextContent(type="text", text=json.dumps({"status": "success", "output_path": path}))]

        elif name == "video_concat":
            path = await ffmpeg_service.concat_videos(
                clip_paths=arguments["clip_paths"],
                output_path=arguments["output_path"],
            )
            return [TextContent(type="text", text=json.dumps({"status": "success", "output_path": path}))]

        elif name == "video_detect_silence":
            regions = await ffmpeg_service.detect_silence(
                audio_path=arguments["audio_path"],
                threshold_db=arguments.get("threshold_db", -40),
                min_duration=arguments.get("min_duration", 1.5),
            )
            return [TextContent(type="text", text=json.dumps({"silence_regions": regions, "count": len(regions)}))]

        elif name == "video_extract_frame":
            path = await ffmpeg_service.extract_frame(
                video_path=arguments["video_path"],
                timestamp=arguments["timestamp"],
                output_path=arguments["output_path"],
            )
            return [TextContent(type="text", text=json.dumps({"status": "success", "output_path": path}))]

        elif name == "subtitle_generate":
            srt_content = FFmpegService.generate_srt(arguments["segments"])
            with open(arguments["output_path"], "w", encoding="utf-8") as f:
                f.write(srt_content)
            cue_count = srt_content.count(" --> ")
            return [TextContent(type="text", text=json.dumps({
                "status": "success", "output_path": arguments["output_path"], "cues": cue_count,
            }))]

        elif name == "subtitle_burn":
            path = await ffmpeg_service.burn_subtitles(
                video_path=arguments["video_path"],
                srt_path=arguments["srt_path"],
                output_path=arguments["output_path"],
                font_size=arguments.get("font_size", 24),
            )
            return [TextContent(type="text", text=json.dumps({"status": "success", "output_path": path}))]

        else:
            return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream,
            InitializationOptions(
                server_name="ai-video-editor-video-tools",
                server_version="1.0.0",
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
