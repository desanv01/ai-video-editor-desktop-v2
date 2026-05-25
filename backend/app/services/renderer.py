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
from dataclasses import dataclass
from typing import List
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from db.models import Video, Transcript, Segment, EditPlan, ProjectAsset, SegmentAction, VideoStatus
from services.ffmpeg import ffmpeg_service, FFmpegService
from services.progress import start_step, complete_step, PipelineStep
from services.edit_plan_payload import get_caption_policy, normalize_plan_payload, update_export_metadata
from services.layout_model import LayoutMode
from services.transcript_edit_decisions import build_synced_timeline_plan
from config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LayoutRenderContext:
    cues: list[dict]
    assets_by_id: dict[str, ProjectAsset]
    fallback_screen_asset: ProjectAsset | None = None
    fallback_camera_asset: ProjectAsset | None = None
    fallback_audio_asset: ProjectAsset | None = None


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
        plan_payload = normalize_plan_payload(plan.plan_json)
        layout_render_context = await _build_layout_render_context(video, plan_payload, db)

        clip_dir = os.path.join(settings.TEMP_PATH, f"clips_{video.id}")
        os.makedirs(clip_dir, exist_ok=True)

        clip_paths = []
        layout_clip_count = 0
        layout_render_counts: dict[str, int] = {}
        for i, render_range in enumerate(render_ranges):
            rendered_paths, rendered_layout_counts = await _render_range_clips(
                video=video,
                render_range=render_range,
                range_index=i,
                clip_dir=clip_dir,
                layout_context=layout_render_context,
            )
            clip_paths.extend(rendered_paths)
            for layout, count in rendered_layout_counts.items():
                layout_render_counts[layout] = layout_render_counts.get(layout, 0) + count
                layout_clip_count += count

        logger.info(
            "  Prepared %s clips (%s rendered layout clips)",
            len(clip_paths),
            layout_clip_count,
        )

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

        caption_policy = get_caption_policy(plan_payload)
        srt_content = _generate_word_level_srt(
            render_ranges,
            word_timestamps,
            caption_policy=caption_policy,
        )
        srt_filename = f"{video.id}_subtitles.srt"
        srt_path = os.path.join(settings.VIDEO_STORAGE_PATH, srt_filename)
        vtt_filename = f"{video.id}_subtitles.vtt"
        vtt_path = os.path.join(settings.VIDEO_STORAGE_PATH, vtt_filename)
        sidecar_enabled = _caption_sidecar_enabled(caption_policy)
        burn_in_enabled = _caption_burn_in_enabled(caption_policy)

        if sidecar_enabled:
            with open(srt_path, "w", encoding="utf-8") as f:
                f.write(srt_content)
            with open(vtt_path, "w", encoding="utf-8") as f:
                f.write(_srt_to_vtt(srt_content))
        else:
            _remove_file(srt_path)
            _remove_file(vtt_path)

        if burn_in_enabled and srt_content.strip():
            burn_srt_path = srt_path if sidecar_enabled else os.path.join(clip_dir, f"{video.id}_burn_subtitles.srt")
            if not sidecar_enabled:
                with open(burn_srt_path, "w", encoding="utf-8") as f:
                    f.write(srt_content)
            burned_output_path = os.path.join(settings.VIDEO_STORAGE_PATH, f"{video.id}_edited_burned.mp4")
            await ffmpeg_service.burn_subtitles(
                video_path=output_path,
                srt_path=burn_srt_path,
                output_path=burned_output_path,
                font_size=int(_dict_value(caption_policy.get("style")).get("font_size") or 24),
                placement=str(caption_policy.get("placement") or "bottom_center"),
                style=_dict_value(caption_policy.get("style")),
            )
            output_path = burned_output_path

        logger.info(
            "  Caption export policy: %s (%s cues)",
            caption_policy.get("export_behavior"),
            srt_content.count(" --> "),
        )

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
            render_metadata_extra={
                "layout_renderer": "phase7_layouts" if layout_clip_count else "single_source",
                "layout_clip_count": layout_clip_count,
                "layout_render_counts": layout_render_counts,
                "picture_in_picture_clip_count": layout_render_counts.get(LayoutMode.PICTURE_IN_PICTURE.value, 0),
                "side_by_side_clip_count": layout_render_counts.get(LayoutMode.SIDE_BY_SIDE.value, 0),
                "full_screen_source_clip_count": layout_render_counts.get(LayoutMode.FULL_SCREEN_SOURCE.value, 0),
                "full_camera_source_clip_count": layout_render_counts.get(LayoutMode.FULL_CAMERA_SOURCE.value, 0),
                "caption_policy": {
                    "enabled": bool(caption_policy.get("enabled")),
                    "appearance": caption_policy.get("appearance"),
                    "placement": caption_policy.get("placement"),
                    "export_behavior": caption_policy.get("export_behavior"),
                    "sidecar_files": sidecar_enabled,
                    "burned_in": burn_in_enabled,
                    "cue_count": srt_content.count(" --> "),
                },
            },
            artifact_paths={
                "edited_video": output_path,
                "subtitles_srt": srt_path if sidecar_enabled else None,
                "subtitles_vtt": vtt_path if sidecar_enabled else None,
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
            "picture_in_picture_clips": layout_render_counts.get(LayoutMode.PICTURE_IN_PICTURE.value, 0),
            "layout_clip_count": layout_clip_count,
            "layout_render_counts": layout_render_counts,
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

async def _build_layout_render_context(
    video: Video,
    plan_payload: dict,
    db: AsyncSession,
) -> LayoutRenderContext | None:
    cues = list(plan_payload.get("layout_cues") or [])
    if not any(_is_renderable_layout_cue(cue) for cue in cues):
        return None
    if not video.project_id:
        return None

    result = await db.execute(
        select(ProjectAsset).where(ProjectAsset.project_id == video.project_id)
    )
    assets = list(result.scalars().all())
    assets_by_id = {str(asset.id): asset for asset in assets}
    return LayoutRenderContext(
        cues=cues,
        assets_by_id=assets_by_id,
        fallback_screen_asset=_first_asset_with_role(assets, {"screen", "primary"}),
        fallback_camera_asset=_first_asset_with_role(assets, {"camera"}),
        fallback_audio_asset=_first_asset_with_role(assets, {"audio"}),
    )


async def _render_range_clips(
    *,
    video: Video,
    render_range: dict,
    range_index: int,
    clip_dir: str,
    layout_context: LayoutRenderContext | None,
) -> tuple[list[str], dict[str, int]]:
    clip_paths = []
    layout_counts: dict[str, int] = {}
    spans = _layout_spans_for_range(render_range, layout_context.cues if layout_context else [])

    for span_index, (start_time, end_time, cue) in enumerate(spans):
        raw_clip = os.path.join(clip_dir, f"raw_{range_index:04d}_{span_index:02d}.mp4")
        rendered_layout = None
        if layout_context and _is_renderable_layout_cue(cue):
            rendered_layout = await _render_layout_span(
                cue=cue,
                layout_context=layout_context,
                output_path=raw_clip,
                fallback_video_path=video.file_path,
                start_time=start_time,
                end_time=end_time,
            )

        if rendered_layout:
            layout_counts[rendered_layout] = layout_counts.get(rendered_layout, 0) + 1
        else:
            await _trim_single_source_clip(video.file_path, raw_clip, start_time, end_time)

        if render_range["action"] == SegmentAction.SHORTEN.value:
            final_clip = os.path.join(clip_dir, f"clip_{range_index:04d}_{span_index:02d}.mp4")
            await ffmpeg_service.trim_silence_from_clip(
                input_path=raw_clip,
                output_path=final_clip,
                threshold_db=settings.SILENCE_THRESHOLD_DB,
                min_silence=0.8,
            )
            try:
                os.remove(raw_clip)
            except OSError:
                pass
        else:
            final_clip = os.path.join(clip_dir, f"clip_{range_index:04d}_{span_index:02d}.mp4")
            os.rename(raw_clip, final_clip)
        clip_paths.append(final_clip)

    return clip_paths, layout_counts


async def _render_layout_span(
    *,
    cue: dict | None,
    layout_context: LayoutRenderContext,
    output_path: str,
    fallback_video_path: str,
    start_time: float,
    end_time: float,
) -> str | None:
    layout = str(_dict_value(cue).get("layout") or "")
    output_width, output_height = FFmpegService.output_dimensions_for_aspect_ratio(
        _dict_value(_dict_value(cue).get("output")).get("aspect_ratio")
    )
    screen_asset = _cue_asset(cue, "screen", layout_context) or layout_context.fallback_screen_asset
    camera_asset = _cue_asset(cue, "camera", layout_context) or layout_context.fallback_camera_asset
    audio_asset = _cue_asset(cue, "audio", layout_context) or layout_context.fallback_audio_asset

    if layout == LayoutMode.PICTURE_IN_PICTURE.value and screen_asset and camera_asset:
        await ffmpeg_service.render_picture_in_picture_clip(
            screen_path=screen_asset.file_path,
            camera_path=camera_asset.file_path,
            audio_path=audio_asset.file_path if audio_asset else None,
            output_path=output_path,
            start_time=start_time,
            end_time=end_time,
            screen_sync_offset=_cue_sync_offset(cue, "screen", screen_asset),
            camera_sync_offset=_cue_sync_offset(cue, "camera", camera_asset),
            audio_sync_offset=_cue_sync_offset(cue, "audio", audio_asset),
            output_width=output_width,
            output_height=output_height,
            camera_corner=str(_dict_value(cue.get("camera")).get("corner") or "bottom_right"),
            camera_shape=str(_dict_value(cue.get("camera")).get("shape") or "rounded_rectangle"),
            camera_size=str(_dict_value(cue.get("camera")).get("size") or "medium"),
            margin_percent=_float_value(_dict_value(cue.get("camera")).get("margin_percent"), 4.0),
        )
        return layout

    if layout == LayoutMode.SIDE_BY_SIDE.value and screen_asset and camera_asset:
        await ffmpeg_service.render_side_by_side_clip(
            screen_path=screen_asset.file_path,
            camera_path=camera_asset.file_path,
            audio_path=audio_asset.file_path if audio_asset else None,
            output_path=output_path,
            start_time=start_time,
            end_time=end_time,
            screen_sync_offset=_cue_sync_offset(cue, "screen", screen_asset),
            camera_sync_offset=_cue_sync_offset(cue, "camera", camera_asset),
            audio_sync_offset=_cue_sync_offset(cue, "audio", audio_asset),
            output_width=output_width,
            output_height=output_height,
        )
        return layout

    if layout == LayoutMode.FULL_SCREEN_SOURCE.value:
        source_asset = screen_asset
        if source_asset:
            await ffmpeg_service.render_full_source_clip(
                source_path=source_asset.file_path,
                audio_path=audio_asset.file_path if audio_asset else None,
                output_path=output_path,
                start_time=start_time,
                end_time=end_time,
                source_sync_offset=_cue_sync_offset(cue, "screen", source_asset),
                audio_sync_offset=_cue_sync_offset(cue, "audio", audio_asset),
                output_width=output_width,
                output_height=output_height,
            )
            return layout
        if not screen_asset:
            await ffmpeg_service.render_full_source_clip(
                source_path=fallback_video_path,
                output_path=output_path,
                start_time=start_time,
                end_time=end_time,
                output_width=output_width,
                output_height=output_height,
            )
            return layout

    if layout == LayoutMode.FULL_CAMERA_SOURCE.value and camera_asset:
        await ffmpeg_service.render_full_source_clip(
            source_path=camera_asset.file_path,
            audio_path=audio_asset.file_path if audio_asset else None,
            output_path=output_path,
            start_time=start_time,
            end_time=end_time,
            source_sync_offset=_cue_sync_offset(cue, "camera", camera_asset),
            audio_sync_offset=_cue_sync_offset(cue, "audio", audio_asset),
            output_width=output_width,
            output_height=output_height,
        )
        return layout

    return None


async def _trim_single_source_clip(
    video_path: str,
    output_path: str,
    start_time: float,
    end_time: float,
) -> None:
    await ffmpeg_service.trim_video(
        video_path=video_path,
        output_path=output_path,
        start_time=start_time,
        end_time=end_time,
    )


def _layout_spans_for_range(
    render_range: dict,
    cues: list[dict],
) -> list[tuple[float, float, dict | None]]:
    range_start = float(render_range["source_start_time"])
    range_end = float(render_range["source_end_time"])
    boundaries = {range_start, range_end}
    for cue in cues:
        cue_start = _float_value(cue.get("start_time"), 0.0) or 0.0
        cue_end = cue.get("end_time")
        if range_start < cue_start < range_end:
            boundaries.add(cue_start)
        if cue_end is not None:
            cue_end_value = _float_value(cue_end, range_end) or range_end
            if range_start < cue_end_value < range_end:
                boundaries.add(cue_end_value)

    ordered = sorted(boundaries)
    spans = []
    for start_time, end_time in zip(ordered, ordered[1:]):
        if end_time <= start_time:
            continue
        spans.append((start_time, end_time, _cue_at_time(cues, start_time)))
    return spans or [(range_start, range_end, _cue_at_time(cues, range_start))]


def _cue_at_time(cues: list[dict], timestamp: float) -> dict | None:
    matching = []
    for cue in cues:
        cue_start = _float_value(cue.get("start_time"), 0.0) or 0.0
        cue_end = cue.get("end_time")
        cue_end_value = float("inf") if cue_end is None else (_float_value(cue_end, cue_start) or cue_start)
        if cue_start <= timestamp < cue_end_value:
            matching.append((cue_start, cue))
    if not matching:
        return None
    return sorted(matching, key=lambda item: item[0])[-1][1]


def _is_picture_in_picture_cue(cue: dict | None) -> bool:
    return isinstance(cue, dict) and cue.get("layout") == LayoutMode.PICTURE_IN_PICTURE.value


def _is_renderable_layout_cue(cue: dict | None) -> bool:
    return isinstance(cue, dict) and cue.get("layout") in {
        LayoutMode.PICTURE_IN_PICTURE.value,
        LayoutMode.SIDE_BY_SIDE.value,
        LayoutMode.FULL_SCREEN_SOURCE.value,
        LayoutMode.FULL_CAMERA_SOURCE.value,
    }


def _cue_asset(
    cue: dict | None,
    role: str,
    context: LayoutRenderContext,
) -> ProjectAsset | None:
    source = _dict_value(_dict_value(cue).get("sources")).get(role)
    source_dict = _dict_value(source)
    if not source_dict.get("enabled", True):
        return None
    asset_id = source_dict.get("asset_id")
    if asset_id:
        return context.assets_by_id.get(str(asset_id))
    return None


def _cue_sync_offset(cue: dict | None, role: str, asset: ProjectAsset | None) -> float:
    source = _dict_value(_dict_value(cue).get("sources")).get(role)
    source_offset = _float_value(_dict_value(source).get("sync_offset_seconds"), None)
    asset_offset = float(asset.sync_offset_seconds or 0.0) if asset else 0.0
    if asset_offset:
        return asset_offset
    return source_offset or 0.0


def _first_asset_with_role(assets: list[ProjectAsset], roles: set[str]) -> ProjectAsset | None:
    sync_roles = {
        "screen_reference" if "screen" in roles else "",
        "primary_timeline" if "primary" in roles else "",
        "camera_overlay" if "camera" in roles else "",
        "audio_master" if "audio" in roles else "",
    }
    candidates = [
        asset for asset in assets
        if _enum_value(getattr(asset, "role", None)) in roles
        or _enum_value(getattr(asset, "sync_role", None)) in sync_roles
    ]
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda asset: (
            0 if asset.is_primary else 1,
            0 if _enum_value(asset.status) == "ready" else 1,
            asset.created_at or datetime.min,
        ),
    )[0]


def _enum_value(value) -> str:
    return str(value.value if hasattr(value, "value") else value or "").lower()


def _dict_value(value) -> dict:
    return dict(value) if isinstance(value, dict) else {}


def _float_value(value, default: float | None) -> float | None:
    if isinstance(value, bool) or value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _generate_word_level_srt(
    render_ranges: List[dict],
    word_timestamps: list | None,
    max_chars_per_line: int = 80,
    max_duration_per_cue: float = 5.0,
    caption_policy: dict | None = None,
) -> str:
    """
    Generate SRT subtitles with sentence-level timing.

    If word_timestamps are available (from Voxtral/Whisper), uses them
    for precise timing. Otherwise falls back to segment-level timing
    with text split into manageable chunks.

    The timestamps are REMAPPED to the edited timeline (cumulative offset).
    """
    policy = _caption_policy_value(caption_policy)
    style = _dict_value(policy.get("style"))
    max_chars_per_line = int(style.get("max_chars_per_line") or max_chars_per_line)
    max_duration_per_cue = float(style.get("max_duration_per_cue") or max_duration_per_cue)
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

    cues = _filter_caption_cues(cues, render_ranges, policy)
    return FFmpegService.generate_srt(cues)


def _caption_sidecar_enabled(caption_policy: dict | None) -> bool:
    policy = _caption_policy_value(caption_policy)
    behavior = str(policy.get("export_behavior") or "sidecar")
    return bool(policy.get("enabled")) and behavior in {"sidecar", "sidecar_and_burn_in"}


def _caption_burn_in_enabled(caption_policy: dict | None) -> bool:
    policy = _caption_policy_value(caption_policy)
    behavior = str(policy.get("export_behavior") or "sidecar")
    return bool(policy.get("enabled")) and behavior in {"burn_in", "sidecar_and_burn_in"}


def _caption_policy_value(caption_policy: dict | None) -> dict:
    if isinstance(caption_policy, dict):
        return get_caption_policy({"polish_actions": [{"kind": "caption_policy", **caption_policy}]})
    return get_caption_policy({})


def _filter_caption_cues(cues: list[dict], render_ranges: List[dict], caption_policy: dict) -> list[dict]:
    if not caption_policy.get("enabled") or caption_policy.get("appearance") == "off":
        return []
    intervals = _caption_active_intervals(render_ranges, caption_policy)
    if not intervals:
        return list(cues)

    filtered = []
    for cue in cues:
        cue_start = float(cue.get("start") or 0.0)
        cue_end = float(cue.get("end") or cue_start)
        for start, end in intervals:
            if cue_start < end and cue_end > start:
                filtered.append({
                    **cue,
                    "start": max(cue_start, start),
                    "end": min(cue_end, end),
                })
                break
    return [cue for cue in filtered if float(cue.get("end") or 0) > float(cue.get("start") or 0)]


def _caption_active_intervals(render_ranges: List[dict], caption_policy: dict) -> list[tuple[float, float]]:
    appearance = str(caption_policy.get("appearance") or "always")
    if appearance == "always":
        return []
    if appearance == "highlight_segments":
        return [
            (float(item["output_start_time"]), float(item["output_end_time"]))
            for item in render_ranges
            if item.get("action") == SegmentAction.HIGHLIGHT.value
        ]
    if appearance == "section_starts":
        seconds = _float_value(caption_policy.get("section_intro_seconds"), 6.0) or 6.0
        intervals = []
        current_topic = object()
        for item in render_ranges:
            segment = item.get("segment")
            topic = getattr(segment, "topic_label", None) or getattr(segment, "summary", None) or item.get("segment_id")
            if topic == current_topic:
                continue
            current_topic = topic
            start = float(item["output_start_time"])
            end = min(float(item["output_end_time"]), start + seconds)
            if end > start:
                intervals.append((start, end))
        return intervals
    if appearance == "manual_ranges":
        intervals = []
        for item in caption_policy.get("ranges") or []:
            if not isinstance(item, dict):
                continue
            start = _float_value(item.get("start_time"), None)
            end = _float_value(item.get("end_time"), None)
            if start is not None and end is not None and end > start:
                intervals.append((start, end))
        return intervals
    return []


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


def _remove_file(path: str) -> None:
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except OSError:
        logger.warning("Could not remove stale caption sidecar: %s", path)


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
    render_metadata_extra: dict | None = None,
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
    render_metadata.update(render_metadata_extra or {})
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
