"""
MCP Pipeline Tools Server

Exposes pipeline orchestration operations as MCP tools.

Tools:
  - pipeline_list_videos: List all videos and their processing status
  - pipeline_video_status: Get detailed status + progress for a video
  - pipeline_run_agent: Run a specific analysis agent on a video
  - pipeline_get_segments: Get analyzed segments for a video
  - pipeline_get_plan: Get the current edit plan for a video
  - pipeline_update_segment: Change a segment's action (teacher override)
  - pipeline_approve_plan: Approve the edit plan and trigger rendering
  - pipeline_revalidate: Re-validate the plan after modifications
  - pipeline_quality_report: Get quality metrics for a processed video
  - pipeline_get_chapters: Get auto-generated chapter markers

This server enables an LLM orchestrator (like n8n or a custom agent)
to manage the entire video editing pipeline through MCP.
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

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

server = Server("ai-video-editor-pipeline-tools")


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name="pipeline_list_videos",
            description="List all videos in the system with their current processing status.",
            inputSchema={
                "type": "object",
                "properties": {
                    "status_filter": {
                        "type": "string",
                        "description": "Filter by status (optional). One of: uploaded, processing, analyzing, awaiting_review, completed, failed",
                    },
                },
            },
        ),
        Tool(
            name="pipeline_video_status",
            description="Get detailed processing status for a video including current step, timing, and progress percentage.",
            inputSchema={
                "type": "object",
                "properties": {
                    "video_id": {"type": "string", "description": "UUID of the video"},
                },
                "required": ["video_id"],
            },
        ),
        Tool(
            name="pipeline_run_agent",
            description=(
                "Run a specific analysis agent on a video. "
                "Agents: transcription, content_understanding, fluency, visual_structure, edit_planner. "
                "Prerequisites: transcription must run first, content_understanding before fluency/visual_structure."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "video_id": {"type": "string", "description": "UUID of the video"},
                    "agent_name": {
                        "type": "string",
                        "enum": ["transcription", "content_understanding", "fluency", "visual_structure", "edit_planner"],
                        "description": "Which agent to run",
                    },
                },
                "required": ["video_id", "agent_name"],
            },
        ),
        Tool(
            name="pipeline_get_segments",
            description="Get all analyzed segments for a video with importance scores, fluency data, and edit actions.",
            inputSchema={
                "type": "object",
                "properties": {
                    "video_id": {"type": "string", "description": "UUID of the video"},
                    "limit": {"type": "integer", "description": "Max segments to return (default: 50)", "default": 50},
                },
                "required": ["video_id"],
            },
        ),
        Tool(
            name="pipeline_get_plan",
            description="Get the current edit plan for a video, including action counts and timing estimates.",
            inputSchema={
                "type": "object",
                "properties": {
                    "video_id": {"type": "string", "description": "UUID of the video"},
                },
                "required": ["video_id"],
            },
        ),
        Tool(
            name="pipeline_update_segment",
            description=(
                "Change a segment's action (teacher override). "
                "Actions: keep, cut, shorten, highlight."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "video_id": {"type": "string", "description": "UUID of the video"},
                    "segment_id": {"type": "string", "description": "UUID of the segment to update"},
                    "action": {
                        "type": "string",
                        "enum": ["keep", "cut", "shorten", "highlight"],
                        "description": "New action for this segment",
                    },
                    "note": {"type": "string", "description": "Optional note explaining the change"},
                },
                "required": ["video_id", "segment_id", "action"],
            },
        ),
        Tool(
            name="pipeline_approve_plan",
            description="Approve the edit plan and trigger video rendering. Returns immediately; rendering happens in the background.",
            inputSchema={
                "type": "object",
                "properties": {
                    "video_id": {"type": "string", "description": "UUID of the video"},
                    "teacher_notes": {"type": "string", "description": "Optional notes from the teacher"},
                },
                "required": ["video_id"],
            },
        ),
        Tool(
            name="pipeline_revalidate",
            description="Re-validate the edit plan after modifications. Returns warnings about coherence issues and consequences of changes.",
            inputSchema={
                "type": "object",
                "properties": {
                    "video_id": {"type": "string", "description": "UUID of the video"},
                },
                "required": ["video_id"],
            },
        ),
        Tool(
            name="pipeline_quality_report",
            description="Get a comprehensive quality metrics report for a processed video, including duration stats, segment distribution, and topic analysis.",
            inputSchema={
                "type": "object",
                "properties": {
                    "video_id": {"type": "string", "description": "UUID of the video"},
                },
                "required": ["video_id"],
            },
        ),
        Tool(
            name="pipeline_get_chapters",
            description="Get auto-generated chapter markers for a video in YouTube-compatible format.",
            inputSchema={
                "type": "object",
                "properties": {
                    "video_id": {"type": "string", "description": "UUID of the video"},
                },
                "required": ["video_id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    from db.database import async_session, init_db
    from db.models import Video, Segment, EditPlan, SegmentAction, VideoStatus
    from sqlalchemy import select, func

    try:
        await init_db()

        async with async_session() as db:
            if name == "pipeline_list_videos":
                query = select(Video).order_by(Video.created_at.desc())
                if arguments.get("status_filter"):
                    query = query.where(Video.status == arguments["status_filter"])
                result = await db.execute(query.limit(50))
                videos = result.scalars().all()
                return [TextContent(type="text", text=json.dumps({
                    "videos": [
                        {
                            "id": str(v.id),
                            "filename": v.original_filename,
                            "status": v.status.value,
                            "duration": v.duration_seconds,
                            "created_at": str(v.created_at) if v.created_at else None,
                        }
                        for v in videos
                    ],
                    "total": len(videos),
                }, indent=2, default=str))]

            elif name == "pipeline_video_status":
                from services.progress import get_progress
                video = await db.get(Video, arguments["video_id"])
                if not video:
                    return [TextContent(type="text", text=json.dumps({"error": "Video not found"}))]

                progress = get_progress(arguments["video_id"])
                return [TextContent(type="text", text=json.dumps({
                    "video_id": str(video.id),
                    "filename": video.original_filename,
                    "status": video.status.value,
                    "error": video.error_message,
                    "progress": progress,
                }, indent=2, default=str))]

            elif name == "pipeline_run_agent":
                import importlib
                agent_map = {
                    "transcription": ("agents.transcription", "run_transcription_agent"),
                    "content_understanding": ("agents.content_understanding", "run_content_understanding_agent"),
                    "fluency": ("agents.fluency", "run_fluency_agent"),
                    "visual_structure": ("agents.visual_structure", "run_visual_structure_agent"),
                    "edit_planner": ("agents.edit_planner", "run_edit_planner_agent"),
                }
                module_path, func_name = agent_map[arguments["agent_name"]]
                module = importlib.import_module(module_path)
                agent_func = getattr(module, func_name)

                result = await agent_func(arguments["video_id"], db)
                await db.commit()

                return [TextContent(type="text", text=json.dumps({
                    "status": "success",
                    "agent": arguments["agent_name"],
                    "result": result,
                }, indent=2, default=str))]

            elif name == "pipeline_get_segments":
                result = await db.execute(
                    select(Segment)
                    .where(Segment.video_id == arguments["video_id"])
                    .order_by(Segment.segment_index)
                    .limit(arguments.get("limit", 50))
                )
                segments = result.scalars().all()
                return [TextContent(type="text", text=json.dumps({
                    "video_id": arguments["video_id"],
                    "count": len(segments),
                    "segments": [
                        {
                            "id": str(s.id),
                            "index": s.segment_index,
                            "time": f"{s.start_time:.1f}-{s.end_time:.1f}s",
                            "topic": s.topic_label,
                            "type": s.segment_type.value if s.segment_type else None,
                            "importance": s.importance_score,
                            "fluency": s.fluency_score,
                            "fillers": s.filler_count,
                            "action": s.action.value if s.action else None,
                            "teacher_action": s.teacher_action.value if s.teacher_action else None,
                            "text_preview": (s.text or "")[:100],
                        }
                        for s in segments
                    ],
                }, indent=2, default=str))]

            elif name == "pipeline_get_plan":
                result = await db.execute(
                    select(EditPlan).where(EditPlan.video_id == arguments["video_id"])
                )
                plan = result.scalar_one_or_none()
                if not plan:
                    return [TextContent(type="text", text=json.dumps({"error": "No edit plan found"}))]
                return [TextContent(type="text", text=json.dumps({
                    "plan_id": str(plan.id),
                    "original_duration": plan.original_duration,
                    "estimated_duration": plan.estimated_duration,
                    "segments_total": plan.segments_total,
                    "segments_keep": plan.segments_keep,
                    "segments_cut": plan.segments_cut,
                    "segments_highlight": plan.segments_highlight,
                    "filler_words_removed": plan.filler_words_removed,
                    "silence_removed_seconds": plan.silence_removed_seconds,
                    "is_approved": plan.is_approved,
                }, indent=2, default=str))]

            elif name == "pipeline_update_segment":
                seg = await db.get(Segment, arguments["segment_id"])
                if not seg:
                    return [TextContent(type="text", text=json.dumps({"error": "Segment not found"}))]

                action_map = {"keep": SegmentAction.KEEP, "cut": SegmentAction.CUT,
                              "shorten": SegmentAction.SHORTEN, "highlight": SegmentAction.HIGHLIGHT}
                seg.teacher_action = action_map[arguments["action"]]
                seg.teacher_note = arguments.get("note")
                seg.is_teacher_modified = True
                await db.commit()

                return [TextContent(type="text", text=json.dumps({
                    "status": "updated",
                    "segment_id": arguments["segment_id"],
                    "new_action": arguments["action"],
                }))]

            elif name == "pipeline_approve_plan":
                result = await db.execute(
                    select(EditPlan).where(EditPlan.video_id == arguments["video_id"])
                )
                plan = result.scalar_one_or_none()
                if not plan:
                    return [TextContent(type="text", text=json.dumps({"error": "No edit plan found"}))]

                from datetime import datetime
                plan.is_approved = True
                plan.approved_at = datetime.utcnow()
                plan.teacher_notes = arguments.get("teacher_notes")
                await db.commit()

                return [TextContent(type="text", text=json.dumps({
                    "status": "approved",
                    "plan_id": str(plan.id),
                    "message": "Plan approved. Trigger rendering separately.",
                }))]

            elif name == "pipeline_revalidate":
                from agents.edit_planner import revalidate_edit_plan
                result = await revalidate_edit_plan(arguments["video_id"], db)
                return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

            elif name == "pipeline_quality_report":
                from services.renderer import generate_quality_report
                report = await generate_quality_report(arguments["video_id"], db)
                return [TextContent(type="text", text=json.dumps(report, indent=2, default=str))]

            elif name == "pipeline_get_chapters":
                result = await db.execute(
                    select(Segment)
                    .where(Segment.video_id == arguments["video_id"])
                    .order_by(Segment.segment_index)
                )
                segments = result.scalars().all()

                chapters = []
                current_topic = None
                for seg in segments:
                    action = seg.teacher_action if seg.is_teacher_modified else seg.action
                    if action == SegmentAction.CUT:
                        continue
                    topic = seg.topic_label or "Unknown"
                    if topic != current_topic and (seg.importance_score or 0) >= 0.3:
                        m, s = divmod(int(seg.start_time), 60)
                        chapters.append({"timestamp": seg.start_time, "formatted": f"{m:02d}:{s:02d}", "label": topic})
                        current_topic = topic

                return [TextContent(type="text", text=json.dumps({
                    "chapters": chapters,
                    "youtube_format": "\n".join(f"{c['formatted']} {c['label']}" for c in chapters),
                }, indent=2))]

            else:
                return [TextContent(type="text", text=json.dumps({"error": f"Unknown tool: {name}"}))]

    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream, write_stream,
            InitializationOptions(
                server_name="ai-video-editor-pipeline-tools",
                server_version="1.0.0",
            ),
        )


if __name__ == "__main__":
    asyncio.run(main())
