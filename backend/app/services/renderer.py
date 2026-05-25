"""
Video Renderer & Export Service

Phase H: Production-ready render pipeline.

Takes the approved edit plan and produces:
  1. Edited MP4 video (trimmed + concatenated segments)
  2. Word-level SRT subtitles (not 60s blocks — proper sentence splits)
  3. VTT subtitles (for web playback)
  4. Chapter markers file (YouTube-compatible)
  5. Edit plan JSON export (for reproducibility / thesis documentation)
  6. Quality report (metrics dashboard data)

SHORTEN action:
  Unlike KEEP, SHORTEN runs ffmpeg silenceremove filter to strip pauses
  from within the segment before including it.

HIGHLIGHT action:
  Same as KEEP but flagged in metadata — the desktop app can add visual
  emphasis during playback. We don't burn any effect in the video itself
  (that would be lossy and opinionated).
"""

import os
import json
import uuid
import shutil
import logging
from typing import List
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from db.models import Video, Transcript, Segment, EditPlan, SegmentAction, VideoStatus
from services.ffmpeg import ffmpeg_service, FFmpegService
from services.progress import start_step, complete_step, PipelineStep
from services.edit_plan_payload import normalize_plan_payload, update_export_metadata
from services.transcript_edit_decisions import build_synced_timeline_plan
from config import settings

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════
#  MAIN RENDER FUNCTION
# ═══════════════════════════════════════════

async def render_final_video(video_id: str, db: AsyncSession) -> dict:
    """
    Render the final edited video based on the approved edit plan.

    Steps:
        1. Load approved plan + segments
        2. Trim each KEEP/HIGHLIGHT segment from original video
        3. For SHORTEN segments, trim AND remove silence
        4. Concatenate all clips in order
        5. Generate word-level SRT + VTT subtitles
        6. Generate chapter markers
        7. Export edit plan JSON
        8. Update video record

    Returns:
        {
            "status": "success",
            "output_path": "...",
            "subtitle_path": "...",
            "chapters_path": "...",
            "plan_export_path": "...",
            "output_duration": N,
            "segments_included": N,
            "segments_removed": N,
        }
    """
    video = await db.get(Video, video_id)
    if not video:
        raise ValueError(f"Video {video_id} not found")

    # Load edit plan
    result = await db.execute(
        select(EditPlan).where(EditPlan.video_id == video_id)
    )
    plan = result.scalar_one_or_none()
    if not plan or not plan.is_approved:
        raise ValueError("Edit plan not found or not yet approved")

    # Load segments
    result = await db.execute(
        select(Segment)
        .where(Segment.video_id == video_id)
        .order_by(Segment.segment_index)
    )
    segments = list(result.scalars().all())

    # Load transcript for word-level timestamps
    result = await db.execute(
        select(Transcript).where(Transcript.video_id == video_id)
    )
    transcript = result.scalar_one_or_none()

    video.status = VideoStatus.RENDERING
    await db.flush()

    logger.info(f"Renderer: Starting render for video {video_id} ({len(segments)} segments)")

    try:
        # ── Step 1: Determine playable ranges from segment and transcript edits ──
        sync_plan = build_synced_timeline_plan(
            plan=plan,
            segments=segments,
            duration_seconds=video.duration_seconds,
        )
        segment_by_id = {str(segment.id): segment for segment in segments}
        render_ranges = [
            {**playable_range, "segment": segment_by_id[playable_range["segment_id"]]}
            for playable_range in sync_plan["playable_ranges"]
            if playable_range["segment_id"] in segment_by_id
        ]
        included_segment_ids = {item["segment_id"] for item in render_ranges}

        if not render_ranges:
            raise ValueError("No playable ranges to render after edit decisions")

        logger.info(
            "  Keeping %s/%s segments across %s ranges after %s transcript cuts",
            len(included_segment_ids),
            len(segments),
            len(render_ranges),
            sync_plan["export_plan"]["transcript_cut_count"],
        )

        # ── Step 2: Trim clips ──
        clip_dir = os.path.join(settings.TEMP_PATH, f"clips_{video.id}")
        os.makedirs(clip_dir, exist_ok=True)

        clip_paths = []
        for i, render_range in enumerate(render_ranges):
            action = render_range["action"]
            raw_clip = os.path.join(clip_dir, f"raw_{i:04d}.mp4")

            # Trim the segment from the original video
            await ffmpeg_service.trim_video(
                video_path=video.file_path,
                output_path=raw_clip,
                start_time=render_range["source_start_time"],
                end_time=render_range["source_end_time"],
            )

            if action == SegmentAction.SHORTEN.value:
                # Additional silence removal for SHORTEN segments
                shortened_clip = os.path.join(clip_dir, f"clip_{i:04d}.mp4")
                await ffmpeg_service.trim_silence_from_clip(
                    input_path=raw_clip,
                    output_path=shortened_clip,
                    threshold_db=settings.SILENCE_THRESHOLD_DB,
                    min_silence=0.8,
                )
                clip_paths.append(shortened_clip)
                # Clean raw clip
                try:
                    os.remove(raw_clip)
                except OSError:
                    pass
            else:
                # Rename raw to final clip
                final_clip = os.path.join(clip_dir, f"clip_{i:04d}.mp4")
                os.rename(raw_clip, final_clip)
                clip_paths.append(final_clip)

        logger.info(f"  Trimmed {len(clip_paths)} clips")

        # ── Step 3: Concatenate all clips ──
        output_filename = f"{video.id}_edited.mp4"
        output_path = os.path.join(settings.VIDEO_STORAGE_PATH, output_filename)

        await ffmpeg_service.concat_videos(
            clip_paths=clip_paths,
            output_path=output_path,
        )

        logger.info(f"  Concatenated → {output_path}")

        # ── Step 4: Generate subtitles ──
        word_timestamps = transcript.words_json if transcript else None

        srt_content = _generate_word_level_srt(render_ranges, word_timestamps)
        srt_filename = f"{video.id}_subtitles.srt"
        srt_path = os.path.join(settings.VIDEO_STORAGE_PATH, srt_filename)
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(srt_content)

        vtt_content = _srt_to_vtt(srt_content)
        vtt_filename = f"{video.id}_subtitles.vtt"
        vtt_path = os.path.join(settings.VIDEO_STORAGE_PATH, vtt_filename)
        with open(vtt_path, "w", encoding="utf-8") as f:
            f.write(vtt_content)

        logger.info(f"  Generated SRT + VTT subtitles")

        # ── Step 5: Generate chapter markers ──
        chapters = _generate_chapter_file(render_ranges)
        chapters_filename = f"{video.id}_chapters.txt"
        chapters_path = os.path.join(settings.VIDEO_STORAGE_PATH, chapters_filename)
        with open(chapters_path, "w", encoding="utf-8") as f:
            f.write(chapters)

        # ── Step 6: Export edit plan JSON ──
        plan_filename = f"{video.id}_edit_plan.json"
        plan_path = os.path.join(settings.VIDEO_STORAGE_PATH, plan_filename)
        plan_export = _export_plan_json(
            video,
            plan,
            segments,
            render_ranges,
            sync_plan,
            artifact_paths={
                "edited_video": output_path,
                "subtitles_srt": srt_path,
                "subtitles_vtt": vtt_path,
                "chapters": chapters_path,
                "plan_json": plan_path,
            },
        )
        with open(plan_path, "w", encoding="utf-8") as f:
            json.dump(plan_export, f, indent=2, default=str)

        logger.info(f"  Exported chapters + plan JSON")

        # ── Step 7: Get output metadata ──
        metadata = await ffmpeg_service.get_video_metadata(output_path)
        output_duration = metadata.get("duration", 0)

        # ── Step 8: Update video record ──
        video.processed_video_path = output_path
        video.status = VideoStatus.COMPLETED
        await db.flush()

        # ── Cleanup temp clips ──
        try:
            shutil.rmtree(clip_dir, ignore_errors=True)
        except Exception:
            pass

        logger.info(
            f"Render complete: {output_duration:.1f}s output, "
            f"{len(included_segment_ids)} segments included, "
            f"{len(segments) - len(included_segment_ids)} removed"
        )

        return {
            "status": "success",
            "output_path": output_path,
            "subtitle_path": srt_path,
            "vtt_path": vtt_path,
            "chapters_path": chapters_path,
            "plan_export_path": plan_path,
            "output_duration": round(output_duration, 2),
            "original_duration": round(video.duration_seconds or 0, 2),
            "segments_included": len(included_segment_ids),
            "segments_removed": len(segments) - len(included_segment_ids),
            "playable_ranges": len(render_ranges),
            "transcript_cuts_applied": sync_plan["export_plan"]["transcript_cut_count"],
        }

    except Exception as e:
        video.status = VideoStatus.FAILED
        video.error_message = f"Render failed: {str(e)}"
        await db.flush()
        logger.error(f"Render failed: {e}")
        raise


# ═══════════════════════════════════════════
#  SUBTITLE GENERATION
# ═══════════════════════════════════════════

def _generate_word_level_srt(
    render_ranges: List[dict],
    word_timestamps: list | None,
    max_chars_per_line: int = 80,
    max_duration_per_cue: float = 5.0,
) -> str:
    """
    Generate SRT subtitles with sentence-level timing.

    If word_timestamps are available (from Voxtral/Whisper), uses them
    for precise timing. Otherwise falls back to segment-level timing
    with text split into manageable chunks.

    The timestamps are REMAPPED to the edited timeline (cumulative offset).
    """
    cues = []
    cumulative_offset = 0.0

    for render_range in render_ranges:
        seg = render_range["segment"]
        source_start = float(render_range["source_start_time"])
        source_end = float(render_range["source_end_time"])
        seg_duration = source_end - source_start

        if word_timestamps:
            # Find words within this segment's original time range
            seg_words = [
                w for w in word_timestamps
                if w.get("start", 0) >= source_start
                and w.get("end", 0) <= source_end
            ]

            if seg_words:
                # Group words into cues (max N chars or N seconds)
                current_cue_words = []
                current_cue_text = ""
                cue_start = None

                for word in seg_words:
                    word_text = word.get("word", word.get("text", "")).strip()
                    if not word_text:
                        continue

                    if cue_start is None:
                        cue_start = word["start"] - source_start + cumulative_offset

                    current_cue_words.append(word)
                    current_cue_text += (" " if current_cue_text else "") + word_text
                    cue_end = word["end"] - source_start + cumulative_offset
                    cue_duration = cue_end - cue_start

                    # Flush cue if line is long enough or duration exceeded
                    if len(current_cue_text) >= max_chars_per_line or cue_duration >= max_duration_per_cue:
                        cues.append({
                            "start": max(0, cue_start),
                            "end": cue_end,
                            "text": current_cue_text.strip(),
                        })
                        current_cue_words = []
                        current_cue_text = ""
                        cue_start = None

                # Flush remaining words
                if current_cue_text.strip() and cue_start is not None:
                    cues.append({
                        "start": max(0, cue_start),
                        "end": cue_end,
                        "text": current_cue_text.strip(),
                    })

                cumulative_offset += seg_duration
                continue

        # Fallback: segment-level with text splitting
        text = (seg.text or "").strip()
        if not text:
            cumulative_offset += seg_duration
            continue

        # Split text into chunks at sentence boundaries
        sentences = _split_into_sentences(text, max_chars_per_line)
        time_per_char = seg_duration / max(len(text), 1)

        char_offset = 0
        for sentence in sentences:
            s_start = cumulative_offset + (char_offset * time_per_char)
            s_end = cumulative_offset + ((char_offset + len(sentence)) * time_per_char)
            s_end = min(s_end, cumulative_offset + seg_duration)

            cues.append({
                "start": max(0, s_start),
                "end": s_end,
                "text": sentence.strip(),
            })
            char_offset += len(sentence)

        cumulative_offset += seg_duration

    # Build SRT string
    return FFmpegService.generate_srt(cues)


def _split_into_sentences(text: str, max_chars: int = 80) -> List[str]:
    """Split text into subtitle-friendly chunks at natural breakpoints."""
    import re

    # First split by sentence endings
    raw_sentences = re.split(r'(?<=[.!?])\s+', text)

    chunks = []
    for sentence in raw_sentences:
        if len(sentence) <= max_chars:
            chunks.append(sentence)
        else:
            # Split long sentences at commas or midpoint
            parts = re.split(r'(?<=,)\s+', sentence)
            current = ""
            for part in parts:
                if len(current) + len(part) + 1 <= max_chars:
                    current += (" " if current else "") + part
                else:
                    if current:
                        chunks.append(current)
                    current = part
            if current:
                chunks.append(current)

    return chunks if chunks else [text]


def _srt_to_vtt(srt_content: str) -> str:
    """Convert SRT to WebVTT format."""
    vtt_lines = ["WEBVTT", ""]
    for line in srt_content.strip().split("\n"):
        # Replace SRT time separator with VTT format
        vtt_lines.append(line.replace(",", "."))
    return "\n".join(vtt_lines)


# ═══════════════════════════════════════════
#  CHAPTER MARKERS
# ═══════════════════════════════════════════

def _generate_chapter_file(render_ranges: List[dict]) -> str:
    """
    Generate YouTube-compatible chapter markers.
    Based on topic transitions in the kept segments.
    """
    chapters = []
    current_topic = None
    cumulative_time = 0.0

    seen_segments = set()
    for render_range in render_ranges:
        seg = render_range["segment"]
        if str(seg.id) in seen_segments:
            cumulative_time += render_range["duration"]
            continue
        seen_segments.add(str(seg.id))
        topic = seg.topic_label or "Unknown"
        if topic != current_topic and (seg.importance_score or 0) >= 0.3:
            minutes = int(cumulative_time // 60)
            seconds = int(cumulative_time % 60)
            chapters.append(f"{minutes:02d}:{seconds:02d} {topic}")
            current_topic = topic

        cumulative_time += render_range["duration"]

    return "\n".join(chapters) if chapters else "00:00 Full Lecture"


# ═══════════════════════════════════════════
#  EDIT PLAN EXPORT
# ═══════════════════════════════════════════

def _export_plan_json(
    video: Video,
    plan: EditPlan,
    all_segments: List[Segment],
    render_ranges: List[dict],
    sync_plan: dict,
    artifact_paths: dict[str, str] | None = None,
) -> dict:
    """
    Export the complete edit plan as a standalone JSON file.
    Used for thesis documentation and reproducibility.
    """
    ranges_by_segment: dict[str, list[dict]] = {}
    for render_range in render_ranges:
        segment_id = render_range["segment_id"]
        ranges_by_segment.setdefault(segment_id, []).append({
            "source_start_time": render_range["source_start_time"],
            "source_end_time": render_range["source_end_time"],
            "duration": render_range["duration"],
            "output_start_time": render_range["output_start_time"],
            "output_end_time": render_range["output_end_time"],
            "action": render_range["action"],
        })

    artifacts = [
        {"kind": kind, "path": path, "available": bool(path and os.path.exists(path))}
        for kind, path in (artifact_paths or {}).items()
    ]
    render_metadata = {
        "playable_range_count": len(render_ranges),
        "transcript_cuts_applied": sync_plan.get("export_plan", {}).get("transcript_cut_count", 0),
        "estimated_output_duration_seconds": sync_plan.get("export_plan", {}).get(
            "estimated_output_duration_seconds"
        ),
    }
    plan_payload = update_export_metadata(
        normalize_plan_payload(plan.plan_json),
        artifacts=artifacts,
        render=render_metadata,
    )
    plan.plan_json = plan_payload

    return {
        "export_version": "2.0",
        "exported_at": datetime.utcnow().isoformat(),
        "video": {
            "id": str(video.id),
            "filename": video.original_filename,
            "original_duration": video.duration_seconds,
            "resolution": video.resolution,
            "fps": video.fps,
        },
        "plan": {
            "id": str(plan.id),
            "original_duration": plan.original_duration,
            "estimated_duration": plan.estimated_duration,
            "segments_total": plan.segments_total,
            "segments_keep": plan.segments_keep,
            "segments_cut": plan.segments_cut,
            "segments_highlight": plan.segments_highlight,
            "filler_words_removed": plan.filler_words_removed,
            "silence_removed_seconds": plan.silence_removed_seconds,
            "approved_at": str(plan.approved_at) if plan.approved_at else None,
            "teacher_notes": plan.teacher_notes,
        },
        "transcript_edit_sync": {
            "schema_version": sync_plan.get("schema_version"),
            "cut_intervals": sync_plan.get("cut_intervals", []),
            "export_plan": sync_plan.get("export_plan", {}),
        },
        "edit_plan_payload": plan_payload,
        "layout_cues": plan_payload.get("layout_cues", []),
        "polish_actions": plan_payload.get("polish_actions", []),
        "sections": plan_payload.get("sections", []),
        "chapters": plan_payload.get("chapters", []),
        "export_metadata": plan_payload.get("export_metadata", {}),
        "segments": [
            {
                "index": seg.segment_index,
                "start": seg.start_time,
                "end": seg.end_time,
                "duration": seg.duration,
                "topic": seg.topic_label,
                "summary": seg.summary,
                "type": seg.segment_type.value if seg.segment_type else None,
                "speaker": seg.speaker,
                "importance": seg.importance_score,
                "fluency": seg.fluency_score,
                "fillers": seg.filler_count,
                "pause_seconds": seg.pause_duration_total,
                "has_slide_change": seg.has_slide_change,
                "ai_action": seg.action.value if seg.action else None,
                "ai_confidence": seg.action_confidence,
                "ai_reason": seg.action_reason,
                "teacher_action": seg.teacher_action.value if seg.teacher_action else None,
                "teacher_note": seg.teacher_note,
                "final_action": (seg.teacher_action or seg.action).value if (seg.teacher_action or seg.action) else None,
                "included_in_output": str(seg.id) in ranges_by_segment,
                "output_ranges": ranges_by_segment.get(str(seg.id), []),
            }
            for seg in all_segments
        ],
    }


# ═══════════════════════════════════════════
#  QUALITY REPORT
# ═══════════════════════════════════════════

async def generate_quality_report(video_id: str, db: AsyncSession) -> dict:
    """
    Generate a quality metrics report.
    Data source for the desktop app's StatsPanel and thesis evaluation.
    """
    video = await db.get(Video, video_id)
    result = await db.execute(
        select(EditPlan).where(EditPlan.video_id == video_id)
    )
    plan = result.scalar_one_or_none()

    result = await db.execute(
        select(Segment)
        .where(Segment.video_id == video_id)
        .order_by(Segment.segment_index)
    )
    segments = list(result.scalars().all())

    if not plan or not segments:
        return {"error": "No data available"}

    sync_plan = build_synced_timeline_plan(
        plan=plan,
        segments=segments,
        duration_seconds=video.duration_seconds if video else None,
    )

    # ── Compute metrics ──
    total_fillers = sum(s.filler_count or 0 for s in segments)
    total_pauses = sum(s.pause_duration_total or 0 for s in segments)
    avg_importance = sum(s.importance_score or 0 for s in segments) / len(segments)
    avg_fluency = sum(s.fluency_score or 0 for s in segments) / len(segments)

    # Topic distribution
    topics = {}
    for s in segments:
        label = s.topic_label or "Unknown"
        if label not in topics:
            topics[label] = {"count": 0, "total_duration": 0}
        topics[label]["count"] += 1
        topics[label]["total_duration"] += round(s.duration or 0, 1)

    # Segment type distribution
    type_dist = {}
    for s in segments:
        stype = s.segment_type.value if s.segment_type else "unknown"
        type_dist[stype] = type_dist.get(stype, 0) + 1

    # Action distribution (final actions including teacher overrides)
    action_dist = {}
    for s in segments:
        final = (s.teacher_action or s.action)
        action_key = final.value if final else "unknown"
        action_dist[action_key] = action_dist.get(action_key, 0) + 1

    # Teacher intervention stats
    teacher_modified = sum(1 for s in segments if s.is_teacher_modified)
    teacher_overrides = sum(
        1 for s in segments
        if s.is_teacher_modified and s.teacher_action != s.action
    )

    time_saved = (plan.original_duration or 0) - (plan.estimated_duration or 0)
    reduction_pct = (time_saved / plan.original_duration * 100) if plan.original_duration else 0

    # Output video duration (if rendered)
    output_duration = None
    if video and video.processed_video_path and os.path.exists(video.processed_video_path):
        try:
            meta = await ffmpeg_service.get_video_metadata(video.processed_video_path)
            output_duration = meta.get("duration")
        except Exception:
            pass

    return {
        "video_id": str(video_id),
        "video_filename": video.original_filename if video else None,
        "original_duration_seconds": plan.original_duration,
        "estimated_duration_seconds": plan.estimated_duration,
        "actual_output_duration_seconds": output_duration,
        "time_saved_seconds": round(time_saved, 1),
        "reduction_percent": round(reduction_pct, 1),
        "total_segments": len(segments),
        "segments_keep": plan.segments_keep,
        "segments_cut": plan.segments_cut,
        "segments_highlight": plan.segments_highlight,
        "total_filler_words": total_fillers,
        "total_pause_seconds": round(total_pauses, 1),
        "average_importance_score": round(avg_importance, 3),
        "average_fluency_score": round(avg_fluency, 3),
        "topic_distribution": topics,
        "segment_type_distribution": type_dist,
        "action_distribution": action_dist,
        "teacher_modifications": teacher_modified,
        "teacher_overrides": teacher_overrides,
        "transcript_edit_sync": sync_plan["export_plan"],
        "is_rendered": video.status == VideoStatus.COMPLETED if video else False,
        "output_files": {
            "video": video.processed_video_path if video else None,
            "srt": os.path.join(settings.VIDEO_STORAGE_PATH, f"{video_id}_subtitles.srt"),
            "vtt": os.path.join(settings.VIDEO_STORAGE_PATH, f"{video_id}_subtitles.vtt"),
            "chapters": os.path.join(settings.VIDEO_STORAGE_PATH, f"{video_id}_chapters.txt"),
            "plan_json": os.path.join(settings.VIDEO_STORAGE_PATH, f"{video_id}_edit_plan.json"),
        },
    }
