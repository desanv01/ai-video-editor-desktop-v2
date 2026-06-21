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
import uuid
import shutil
import logging
import subprocess
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import List
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from db.models import Video, Transcript, Segment, EditPlan, ProjectAsset, SegmentAction, VideoStatus
from services.ffmpeg import ffmpeg_service, FFmpegService
from services.progress import start_step, complete_step, PipelineStep
from services.render_jobs import RenderCancelled, ensure_not_cancelled, update_render_job
from services.edit_plan_payload import (
    get_annotations,
    get_caption_policy,
    get_educational_overlays,
    get_end_cards,
    normalize_plan_payload,
    update_export_metadata,
)
from services.export_artifacts import (
    artifact_records,
    build_academic_evidence_artifact,
    build_before_after_comparison,
    build_evidence_markdown,
    build_generated_evidence_index,
    build_metrics_summary_artifact,
    build_provider_mode_trace,
    build_timeline_decision_rows,
    build_timeline_decisions_artifact,
    TIMELINE_DECISION_CSV_FIELDS,
    write_csv_artifact,
    write_json_artifact,
    write_text_artifact,
)
from services.evaluation_metrics import build_evaluation_metrics
from services.layout_model import LayoutMode
from services.lecture_structure import build_structure_references_from_assets
from services.transcript_edit_decisions import build_synced_timeline_plan
from services.export_presets import get_export_preset
from services.native_semantic_compositor import render_semantic_plan_with_ffmpeg
from services.revideo_renderer import RevideoUnavailable, render_semantic_plan_with_revideo
from services.semantic_render_plan import build_semantic_render_plan, with_semantic_render_plan
from config import settings

logger = logging.getLogger(__name__)
MIN_RENDER_SPAN_SECONDS = 0.05

# Layout mode mapping: Agent 5 new names → compositor legacy names
AGENT5_LAYOUT_MAP = {
    "full_slide": "full_screen_source",
    "pip_slide": "picture_in_picture",
    "half_half": "side_by_side",
    "full_face": "full_camera_source",
}


def _resolve_compositor_layout_mode(layout_mode: str | None) -> str:
    """Map Agent 5's layout_mode values to the compositor's expected format.

    Agent 5 outputs: full_slide, pip_slide, half_half, full_face
    Compositor expects: full_screen_source, picture_in_picture, side_by_side, full_camera_source
    """
    if layout_mode in AGENT5_LAYOUT_MAP:
        return AGENT5_LAYOUT_MAP[layout_mode]
    return layout_mode or "picture_in_picture"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class LayoutRenderContext:
    cues: list[dict]
    assets_by_id: dict[str, ProjectAsset]
    assets_by_track: dict[str, ProjectAsset] = field(default_factory=dict)
    assets_by_role: dict[str, ProjectAsset] = field(default_factory=dict)
    timeline_tracks: list[dict] = field(default_factory=list)
    source_manifest: list[dict] = field(default_factory=list)
    transition_events: list[dict] = field(default_factory=list)
    fallback_screen_asset: ProjectAsset | None = None
    fallback_camera_asset: ProjectAsset | None = None
    fallback_audio_asset: ProjectAsset | None = None


async def _try_render_revideo_timeline_clip(
    *,
    video: Video,
    plan: EditPlan,
    segments: list[Segment],
    transcript: Transcript | None,
    plan_payload: dict,
    layout_context: LayoutRenderContext | None,
    clip_dir: str,
    render_job_id: str | None,
    video_id: str,
) -> str | None:
    """Render the whole semantic composition with Revideo when available."""
    if not bool(getattr(settings, "REVIDEO_RENDERER_ENABLED", False)):
        return None
    max_duration = float(getattr(settings, "REVIDEO_RENDERER_MAX_DEFAULT_DURATION_SECONDS", 90.0) or 90.0)
    if float(video.duration_seconds or 0.0) > max_duration:
        logger.info(
            "Renderer: skipping Revideo for %s because %.1fs exceeds %.1fs short-form limit",
            video_id,
            float(video.duration_seconds or 0.0),
            max_duration,
        )
        return None

    render_plan = _dict_value(plan_payload.get("render_plan"))
    assets = list((layout_context.assets_by_id or {}).values()) if layout_context else []
    current_render_plan = build_semantic_render_plan(
        video=video,
        plan=plan,
        segments=segments,
        transcript=transcript,
        assets=assets,
    )
    if not render_plan or render_plan.get("plan_hash") != current_render_plan.get("plan_hash"):
        render_plan = current_render_plan
        updated_payload = with_semantic_render_plan(plan_payload, render_plan)
        plan_payload.clear()
        plan_payload.update(updated_payload)
        plan.plan_json = plan_payload

    output_path = os.path.join(clip_dir, "revideo_semantic_timeline.mp4")

    def progress(progress_value: float, message: str) -> None:
        _render_progress(
            render_job_id,
            video_id,
            18 + int(max(0.0, min(1.0, progress_value)) * 38),
            "revideo_composition",
            "Rendering semantic composition",
            message or "Rendering Revideo composition",
            {
                "renderer": "revideo",
                "progress": round(progress_value, 3),
                "scene_count": _dict_value(render_plan.get("timeline")).get("scene_count", 0),
            },
        )

    try:
        await render_semantic_plan_with_revideo(
            render_plan=render_plan,
            source_video_path=video.file_path,
            output_path=output_path,
            progress_callback=progress,
            cancel_check=_cancel_check_callback(render_job_id, video_id),
        )
        logger.info("Renderer: Revideo semantic timeline rendered for %s -> %s", video_id, output_path)
        return output_path
    except RevideoUnavailable as exc:
        logger.warning("Revideo renderer unavailable; using FFmpeg fallback: %s", exc)
    except Exception as exc:
        if not bool(getattr(settings, "REVIDEO_RENDERER_FALLBACK_ENABLED", True)):
            raise
        logger.warning("Revideo renderer failed; using FFmpeg fallback: %s", exc)
    return None


async def _try_render_native_semantic_timeline_clip(
    *,
    video: Video,
    plan: EditPlan,
    segments: list[Segment],
    transcript: Transcript | None,
    plan_payload: dict,
    layout_context: LayoutRenderContext | None,
    clip_dir: str,
    selected_preset: dict,
    render_job_id: str | None,
    video_id: str,
) -> str | None:
    """Render the semantic teaching timeline with the fast native FFmpeg compositor."""
    if not bool(getattr(settings, "NATIVE_SEMANTIC_COMPOSITOR_ENABLED", True)):
        return None

    render_plan = _dict_value(plan_payload.get("render_plan"))
    if not render_plan:
        assets = list((layout_context.assets_by_id or {}).values()) if layout_context else []
        render_plan = build_semantic_render_plan(
            video=video,
            plan=plan,
            segments=segments,
            transcript=transcript,
            assets=assets,
        )
        updated_payload = with_semantic_render_plan(plan_payload, render_plan)
        plan_payload.clear()
        plan_payload.update(updated_payload)
        plan.plan_json = plan_payload

    if not _dict_value(render_plan.get("timeline")).get("scene_count"):
        return None

    output_path = os.path.join(clip_dir, "native_semantic_timeline.mp4")
    work_dir = os.path.join(clip_dir, "native_semantic")
    preset_width, preset_height = _preset_output_dimensions(selected_preset, plan_payload)
    fallback_width, fallback_height = _annotation_canvas_dimensions(plan_payload)
    output_width = int(preset_width or fallback_width or 1920)
    output_height = int(preset_height or fallback_height or 1080)
    fps = _preset_fps(selected_preset) or 30
    video_bitrate = _ffmpeg_video_bitrate(selected_preset.get("video_bitrate"))
    audio_bitrate = _ffmpeg_audio_bitrate(selected_preset.get("audio_bitrate"))

    def progress(progress_value: float, message: str) -> None:
        _render_progress(
            render_job_id,
            video_id,
            18 + int(max(0.0, min(1.0, progress_value)) * 38),
            "native_semantic_composition",
            "Composing semantic lecture timeline",
            message or "Composing slide and lecturer video timeline with FFmpeg",
            {
                "renderer": "ffmpeg_native_semantic",
                "progress": round(progress_value, 3),
                "scene_count": _dict_value(render_plan.get("timeline")).get("scene_count", 0),
                "hardware_acceleration": str(getattr(settings, "FFMPEG_HARDWARE_ACCELERATION", "auto") or "auto"),
            },
        )

    try:
        await render_semantic_plan_with_ffmpeg(
            render_plan=render_plan,
            source_video_path=video.file_path,
            output_path=output_path,
            work_dir=work_dir,
            output_width=output_width,
            output_height=output_height,
            fps=fps,
            video_bitrate=video_bitrate,
            audio_bitrate=audio_bitrate,
            progress_callback=progress,
            cancel_check=_cancel_check_callback(render_job_id, video_id),
        )
        logger.info("Renderer: native semantic timeline rendered for %s -> %s", video_id, output_path)
        return output_path
    except Exception as exc:
        logger.warning("Native semantic compositor failed; using legacy clip renderer fallback: %s", exc)
        return None


async def _fast_ffmpeg_concat_path(
    *,
    video: Video,
    render_ranges: list[dict],
    clip_dir: str,
    selected_preset: dict,
    preset_width: int,
    preset_height: int,
    video_bitrate: str | None,
    audio_bitrate: str,
    fps: int,
    plan_payload: dict,
    transcript: Transcript | None,
    render_job_id: str | None,
    video_id: str,
) -> dict | None:
    """Fast FFmpeg direct concat pipeline — trims, concats, and encodes with HW acceleration.

    Bypasses the Revideo browser compositor entirely for simple trim+concat cases.
    Trims each render range from the source video with stream copy (-c copy),
    then concatenates and re-encodes using the configured hardware encoder
    (h264_nvenc / qsv / vaapi / amf) with libx264 fallback.
    Optionally burns SRT subtitles via FFmpeg's subtitles filter in a single encode pass.

    Returns {"path": str, "duration": float, "subtitles_burned": bool} or None on failure.
    """
    cancel_check = _cancel_check_callback(render_job_id, video_id)

    # ── Step 1: Trim each range from source with frame-accurate re-encode ──
    trim_dir = os.path.join(clip_dir, "fast_trim")
    os.makedirs(trim_dir, exist_ok=True)
    trimmed_paths: list[str] = []
    total_duration = 0.0

    for i, render_range in enumerate(render_ranges):
        cancel_check()
        start_time = float(render_range["source_start_time"])
        end_time = float(render_range["source_end_time"])
        duration = max(0.001, end_time - start_time)

        raw_clip = os.path.join(trim_dir, f"trim_{i:04d}.mp4")
        await ffmpeg_service.trim_video_accurate(
            video_path=video.file_path,
            output_path=raw_clip,
            start_time=start_time,
            end_time=end_time,
            cancel_check=cancel_check,
        )

        # Apply silence removal for SHORTEN segments
        action = render_range.get("action", "")
        if action == SegmentAction.SHORTEN.value:
            silence_trimmed = os.path.join(trim_dir, f"trim_{i:04d}_silence.mp4")
            await ffmpeg_service.trim_silence_from_clip(
                input_path=raw_clip,
                output_path=silence_trimmed,
                cancel_check=cancel_check,
            )
            _remove_file(raw_clip)
            raw_clip = silence_trimmed

        trimmed_paths.append(raw_clip)
        total_duration += duration

    if not trimmed_paths:
        return None

    _render_progress(
        render_job_id, video_id, 12,
        "fast_concat", "Fast FFmpeg concat",
        f"Trimming {len(trimmed_paths)} ranges, preparing concat",
        {"range_count": len(trimmed_paths)},
    )

    # ── Step 2: Build concat file list for FFmpeg concat demuxer ──
    concat_list_path = os.path.join(trim_dir, "concat_list.txt")
    with open(concat_list_path, "w") as f:
        for p in trimmed_paths:
            f.write(f"file '{p}'\n")

    # ── Step 3: Prepare subtitle burn-in if enabled ──
    caption_policy = get_caption_policy(plan_payload)
    subtitles_burned = False
    srt_path = None
    srt_filter = ""

    if _caption_burn_in_enabled(caption_policy):
        word_timestamps = transcript.words_json if transcript else None
        srt_content = _generate_word_level_srt(
            render_ranges, word_timestamps, caption_policy=caption_policy,
        )
        if srt_content.strip():
            srt_path = os.path.join(trim_dir, f"{video.id}_concat_subtitles.srt")
            with open(srt_path, "w", encoding="utf-8") as f:
                f.write(srt_content)
            font_size = int(_dict_value(caption_policy.get("style")).get("font_size") or 24)
            placement = str(caption_policy.get("placement") or "bottom_center")
            force_style = FFmpegService._subtitle_force_style(
                font_size=font_size, placement=placement,
                style=_dict_value(caption_policy.get("style")),
            )
            srt_filter = f",subtitles={FFmpegService._escape_subtitle_path(srt_path)}:force_style='{force_style}'"
            subtitles_burned = True

    # ── Step 4: Concat + encode with HW acceleration + optional subtitle burn ──
    output_path = os.path.join(clip_dir, "fast_ffmpeg_concat_output.mp4")

    video_filter = FFmpegService._concat_video_filter(
        preset_width or None, preset_height or None, fps or 30,
    )
    if srt_filter:
        video_filter = (video_filter + srt_filter) if video_filter else srt_filter.lstrip(",")

    cmd = [
        "ffmpeg",
        "-f", "concat", "-safe", "0",
        "-i", concat_list_path,
    ]
    if video_filter:
        cmd.extend(["-vf", video_filter])
    cmd.extend([
        *FFmpegService._video_encoder_args(video_bitrate, "veryfast"),
        "-c:a", "aac", "-b:a", FFmpegService._normalize_audio_bitrate(audio_bitrate),
        "-ar", "48000", "-ac", "2",
        "-movflags", "+faststart",
        "-y", output_path,
    ])

    try:
        _, stderr, returncode = await FFmpegService._run_process_with_encoder_fallback(
            cmd,
            error_prefix="Fast FFmpeg concat failed",
            cancel_check=cancel_check,
            allow_failure=True,
        )
    except Exception as exc:
        logger.warning("Fast FFmpeg concat exception: %s", exc)
        returncode = 1
        stderr = b""

    # Clean up temp files regardless of outcome
    _remove_file(concat_list_path)
    for p in trimmed_paths:
        _remove_file(p)
    if srt_path:
        _remove_file(srt_path)

    if returncode != 0:
        err_msg = stderr.decode()[:500] if isinstance(stderr, bytes) else str(stderr)[:500]
        logger.warning("Fast FFmpeg concat failed (returncode=%s): %s", returncode, err_msg)
        _remove_file(output_path)
        return None

    logger.info(
        "Fast FFmpeg concat rendered for %s -> %s (%.1fs, subtitles_burned=%s)",
        video_id, output_path, total_duration, subtitles_burned,
    )

    return {
        "path": output_path,
        "duration": total_duration,
        "subtitles_burned": subtitles_burned,
    }


def _is_pure_trim_concat_export(plan_payload: dict) -> bool:
    """Return True only when the export is a simple trim+concat with no layouts, overlays, annotations, or burn-in captions.

    When False the render pipeline must fall through to the full semantic compositor
    (native FFmpeg composition or Revideo) so that layout cues, annotations, and
    educational overlays are rendered correctly.
    """
    # Layout cues (picture-in-picture, side-by-side, etc.) require compositor
    layout_cues = plan_payload.get("layout_cues") or []
    if layout_cues:
        return False

    # Burn-in captions require compositor (sidecar-only is fine for fast concat)
    caption_policy = get_caption_policy(plan_payload)
    if caption_policy.get("enabled") and str(caption_policy.get("export_behavior") or "sidecar") in {"burn_in", "sidecar_and_burn_in"}:
        return False

    # Annotations require compositor
    annotations = plan_payload.get("annotations") or []
    if annotations:
        return False

    # Educational overlays require compositor
    educational_overlays = plan_payload.get("educational_overlays") or []
    if educational_overlays:
        return False

    return True


# ═══════════════════════════════════════════
#  MAIN RENDER FUNCTION
# ═══════════════════════════════════════════

async def render_final_video(video_id: str, db: AsyncSession, render_job_id: str | None = None) -> dict:
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
    _render_progress(
        render_job_id,
        video_id,
        4,
        "preparing",
        "Preparing render inputs",
        "Loading approved edit plan, transcript, and segment decisions",
    )

    logger.info(f"Renderer: Starting render for video {video_id} ({len(segments)} segments)")

    try:
        _check_render_cancel(render_job_id, video_id)
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
            and _render_range_duration(playable_range) >= MIN_RENDER_SPAN_SECONDS
        ]
        included_segment_ids = {item["segment_id"] for item in render_ranges}

        if not render_ranges:
            raise ValueError("No playable ranges to render after edit decisions")
        _render_progress(
            render_job_id,
            video_id,
            10,
            "timeline",
            "Building render timeline",
            f"{len(render_ranges)} playable ranges queued for export",
            {"playable_ranges": len(render_ranges), "segments_total": len(segments)},
        )

        logger.info(
            "  Keeping %s/%s segments across %s ranges after %s transcript cuts",
            len(included_segment_ids),
            len(segments),
            len(render_ranges),
            sync_plan["export_plan"]["transcript_cut_count"],
        )

        # ── Step 2: Trim clips ──
        plan_payload = normalize_plan_payload(plan.plan_json)
        layout_render_context = await _build_layout_render_context(
            video,
            plan_payload,
            db,
            render_job_id=render_job_id,
        )
        selected_preset = _selected_export_preset(plan_payload)
        preset_width, preset_height = _preset_output_dimensions(selected_preset, plan_payload)
        preset_video_bitrate = _ffmpeg_video_bitrate(selected_preset.get("video_bitrate"))
        preset_audio_bitrate = _ffmpeg_audio_bitrate(selected_preset.get("audio_bitrate"))
        preset_fps = _preset_fps(selected_preset)
        if _is_audio_only_export(selected_preset):
            result = await _render_audio_only_export(
                video=video,
                plan=plan,
                segments=segments,
                transcript=transcript,
                render_ranges=render_ranges,
                included_segment_ids=included_segment_ids,
                sync_plan=sync_plan,
                plan_payload=plan_payload,
                selected_preset=selected_preset,
                layout_context=layout_render_context,
                render_job_id=render_job_id,
                video_id=video_id,
                db=db,
            )
            await db.flush()
            return result

        transition_events = _layout_transition_events_for_render_ranges(
            layout_render_context.cues if layout_render_context else [],
            render_ranges,
        )

        clip_dir = os.path.join(settings.TEMP_PATH, f"clips_{video.id}")
        os.makedirs(clip_dir, exist_ok=True)

        clip_paths = []
        clip_durations: list[float] = []
        layout_clip_count = 0
        layout_render_counts: dict[str, int] = {}
        end_cards = get_end_cards(plan_payload)
        enabled_end_cards = [card for card in end_cards if card.get("enabled")]
        end_card_clip_paths: list[str] = []
        single_composed_clip = False

        # ── Fast FFmpeg concat path (bypasses Revideo for simple trim+concat exports) ──
        if _is_pure_trim_concat_export(plan_payload):
            fast_concat_path = await _fast_ffmpeg_concat_path(
                video=video,
                render_ranges=render_ranges,
                clip_dir=clip_dir,
                selected_preset=selected_preset,
                preset_width=preset_width,
                preset_height=preset_height,
                video_bitrate=str(preset_video_bitrate) if preset_video_bitrate else None,
                audio_bitrate=str(preset_audio_bitrate) if preset_audio_bitrate else "192k",
                fps=preset_fps or 30,
                plan_payload=plan_payload,
                transcript=transcript,
                render_job_id=render_job_id,
                video_id=video_id,
            )
            if fast_concat_path:
                clip_paths.append(fast_concat_path["path"])
                clip_durations.append(max(0.1, float(fast_concat_path.get("duration", 0))))
                layout_clip_count = 1
                layout_render_counts["fast_ffmpeg_concat"] = 1
                transition_events = []
                single_composed_clip = True
                logger.info("Renderer: using fast FFmpeg concat path for %s", video_id)
        else:
            logger.warning("Renderer: skipping fast concat because layout/overlay cues require full compositor")

        if not single_composed_clip:
            native_semantic_clip_path = await _try_render_native_semantic_timeline_clip(
            video=video,
            plan=plan,
            segments=segments,
            transcript=transcript,
            plan_payload=plan_payload,
            layout_context=layout_render_context,
            clip_dir=clip_dir,
            selected_preset=selected_preset,
            render_job_id=render_job_id,
            video_id=video_id,
        )
            revideo_clip_path = None if native_semantic_clip_path else await _try_render_revideo_timeline_clip(
            video=video,
            plan=plan,
            segments=segments,
            transcript=transcript,
            plan_payload=plan_payload,
            layout_context=layout_render_context,
            clip_dir=clip_dir,
            render_job_id=render_job_id,
            video_id=video_id,
        )
            if native_semantic_clip_path:
                render_plan = _dict_value(plan_payload.get("render_plan"))
                timeline_duration = float(_dict_value(render_plan.get("timeline")).get("duration_seconds") or sync_plan["export_plan"]["estimated_output_duration_seconds"] or 0.1)
                clip_paths.append(native_semantic_clip_path)
                clip_durations.append(max(0.1, timeline_duration))
                layout_clip_count = 1
                layout_render_counts["ffmpeg_native_semantic_composition"] = 1
                transition_events = []
                single_composed_clip = True
            if revideo_clip_path:
                render_plan = _dict_value(plan_payload.get("render_plan"))
                timeline_duration = float(_dict_value(render_plan.get("timeline")).get("duration_seconds") or sync_plan["export_plan"]["estimated_output_duration_seconds"] or 0.1)
                clip_paths.append(revideo_clip_path)
                clip_durations.append(max(0.1, timeline_duration))
                layout_clip_count = 1
                layout_render_counts["revideo_semantic_composition"] = 1
                transition_events = []
                single_composed_clip = True
        if not single_composed_clip:
            # Build plan_payload segment lookup for layout_mode (from Agent 5)
            plan_segment_by_id: dict[str, dict] = {}
            for ps in (plan_payload.get("segments") or []):
                sid = ps.get("segment_id")
                if sid:
                    plan_segment_by_id[sid] = ps

            for i, render_range in enumerate(render_ranges):
                _check_render_cancel(render_job_id, video_id)
                _render_progress(
                    render_job_id,
                    video_id,
                    _range_progress(i, len(render_ranges)),
                    "rendering_clips",
                    "Rendering timeline clips",
                    f"Rendering range {i + 1} of {len(render_ranges)}",
                    {"current_range": i + 1, "total_ranges": len(render_ranges)},
                )
                segment = render_range.get("segment")
                segment_id = render_range.get("segment_id")
                plan_seg = plan_segment_by_id.get(segment_id) if segment_id else None
                # Edit actions (keep/cut/highlight) are not layout modes. Timed
                # teacher layout cues are resolved by the semantic render plan.
                teacher_mode = getattr(segment, 'teacher_layout', None)
                if teacher_mode:
                    layout_mode = _resolve_compositor_layout_mode(teacher_mode)
                else:
                    layout_mode = _resolve_compositor_layout_mode(plan_seg.get("layout_mode")) if plan_seg else None
                slide_image_path = _resolve_slide_image(segment, str(video_id)) if segment else None

                if slide_image_path and layout_mode and render_range["action"] != "cut":
                    # Use Static Image Compositor for slide-based rendering
                    logger.info(
                        "Renderer: slide compositor for range %s (layout=%s, slide=%s)",
                        i, layout_mode, slide_image_path,
                    )
                    rendered_paths, rendered_durations, rendered_layout_counts = await _render_slide_composited_clip(
                        video=video,
                        render_range=render_range,
                        range_index=i,
                        clip_dir=clip_dir,
                        slide_image_path=slide_image_path,
                        layout_mode=layout_mode,
                        cancel_check=_cancel_check_callback(render_job_id, video_id),
                    )
                else:
                    rendered_paths, rendered_durations, rendered_layout_counts = await _render_range_clips(
                        video=video,
                        render_range=render_range,
                        range_index=i,
                        clip_dir=clip_dir,
                        layout_context=layout_render_context,
                        cancel_check=_cancel_check_callback(render_job_id, video_id),
                    )
                clip_paths.extend(rendered_paths)
                clip_durations.extend(rendered_durations)
                for layout, count in rendered_layout_counts.items():
                    layout_render_counts[layout] = layout_render_counts.get(layout, 0) + count
                    layout_clip_count += count

        if enabled_end_cards:
            _check_render_cancel(render_job_id, video_id)
            _render_progress(
                render_job_id,
                video_id,
                58,
                "end_cards",
                "Rendering end cards",
                f"Rendering {len(enabled_end_cards)} end card clips",
                {"end_card_count": len(enabled_end_cards)},
            )
            width, height = _annotation_canvas_dimensions(plan_payload)
            for index, end_card in enumerate(enabled_end_cards):
                _check_render_cancel(render_job_id, video_id)
                end_card_clip = await _render_end_card_clip(
                    end_card=end_card,
                    output_path=os.path.join(clip_dir, f"end_card_{index:02d}.mp4"),
                    clip_dir=clip_dir,
                    width=width,
                    height=height,
                    index=index,
                    cancel_check=_cancel_check_callback(render_job_id, video_id),
                )
                clip_paths.append(end_card_clip)
                clip_durations.append(float(end_card.get("duration_seconds") or 0.1))
                end_card_clip_paths.append(end_card_clip)

        logger.info(
            "  Prepared %s clips (%s rendered layout clips, %s end cards)",
            len(clip_paths),
            layout_clip_count,
            len(end_card_clip_paths),
        )
        expected_output_duration = _expected_concat_duration(clip_durations, transition_events)
        # ── Step 3: Concatenate all clips ──
        _check_render_cancel(render_job_id, video_id)
        _render_progress(
            render_job_id,
            video_id,
            64,
            "concatenating",
            "Concatenating clips",
            f"Combining {len(clip_paths)} clips into the final video",
            {"clip_count": len(clip_paths)},
        )
        output_filename = f"{video.id}_edited.mp4"
        output_path = os.path.join(settings.VIDEO_STORAGE_PATH, output_filename)

        concat_transition_specs = _concat_transition_specs(transition_events, clip_durations)
        if single_composed_clip and len(clip_paths) == 1 and not concat_transition_specs:
            shutil.copyfile(clip_paths[0], output_path)
        elif concat_transition_specs:
            transition_width, transition_height = _annotation_canvas_dimensions(plan_payload)
            try:
                await ffmpeg_service.concat_videos_with_transitions(
                    clip_paths=clip_paths,
                    clip_durations=clip_durations,
                    transitions=concat_transition_specs,
                    output_path=output_path,
                    output_width=preset_width or transition_width,
                    output_height=preset_height or transition_height,
                    video_bitrate=preset_video_bitrate,
                    audio_bitrate=preset_audio_bitrate,
                    fps=preset_fps,
                    cancel_check=_cancel_check_callback(render_job_id, video_id),
                )
            except Exception as exc:
                logger.warning("Transition compositor failed; falling back to direct concat: %s", exc)
                await ffmpeg_service.concat_videos(
                    clip_paths=clip_paths,
                    output_path=output_path,
                    video_bitrate=preset_video_bitrate,
                    audio_bitrate=preset_audio_bitrate,
                    output_width=preset_width,
                    output_height=preset_height,
                    fps=preset_fps,
                    cancel_check=_cancel_check_callback(render_job_id, video_id),
                )
        else:
            await ffmpeg_service.concat_videos(
                clip_paths=clip_paths,
                output_path=output_path,
                video_bitrate=preset_video_bitrate,
                audio_bitrate=preset_audio_bitrate,
                output_width=preset_width,
                output_height=preset_height,
                fps=preset_fps,
                cancel_check=_cancel_check_callback(render_job_id, video_id),
            )

        logger.info(f"  Concatenated → {output_path}")

        # ── Step 4: Generate subtitles ──
        _check_render_cancel(render_job_id, video_id)
        _render_progress(
            render_job_id,
            video_id,
            72,
            "captions_overlays",
            "Rendering captions and overlays",
            "Generating sidecar captions and burn-in overlays",
        )
        word_timestamps = transcript.words_json if transcript else None

        caption_policy = get_caption_policy(plan_payload)
        annotations = get_annotations(plan_payload)
        educational_overlays = get_educational_overlays(plan_payload)
        annotation_events = _annotation_events_for_render_ranges(annotations, render_ranges)
        educational_overlay_events = _annotation_events_for_render_ranges(educational_overlays, render_ranges)
        annotation_burned_in = False
        if annotation_events or educational_overlay_events:
            _check_render_cancel(render_job_id, video_id)
            ass_width, ass_height = _annotation_canvas_dimensions(plan_payload)
            annotation_ass_content = _generate_annotation_ass(
                annotation_events + educational_overlay_events,
                width=ass_width,
                height=ass_height,
            )
            annotation_ass_path = os.path.join(clip_dir, f"{video.id}_annotations.ass")
            with open(annotation_ass_path, "w", encoding="utf-8") as f:
                f.write(annotation_ass_content)
            annotated_output_path = os.path.join(settings.VIDEO_STORAGE_PATH, f"{video.id}_edited_annotated.mp4")
            await ffmpeg_service.burn_ass_overlay(
                video_path=output_path,
                ass_path=annotation_ass_path,
                output_path=annotated_output_path,
                cancel_check=_cancel_check_callback(render_job_id, video_id),
            )
            output_path = annotated_output_path
            annotation_burned_in = True

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
            _check_render_cancel(render_job_id, video_id)
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
                cancel_check=_cancel_check_callback(render_job_id, video_id),
            )
            output_path = burned_output_path

        logger.info(
            "  Caption export policy: %s (%s cues)",
            caption_policy.get("export_behavior"),
            srt_content.count(" --> "),
        )

        # ── Step 5: Generate chapter markers ──
        _check_render_cancel(render_job_id, video_id)
        _render_progress(
            render_job_id,
            video_id,
            84,
            "exporting_artifacts",
            "Writing export artifacts",
            "Writing chapters and reproducible edit plan JSON",
        )
        chapters = _generate_chapter_file(render_ranges)
        chapters_filename = f"{video.id}_chapters.txt"
        chapters_path = os.path.join(settings.VIDEO_STORAGE_PATH, chapters_filename)
        with open(chapters_path, "w", encoding="utf-8") as f:
            f.write(chapters)

        # ── Step 6: Export edit plan JSON ──
        plan_filename = f"{video.id}_edit_plan.json"
        plan_path = os.path.join(settings.VIDEO_STORAGE_PATH, plan_filename)
        quality_report_path = os.path.join(settings.VIDEO_STORAGE_PATH, f"{video.id}_quality_report.json")
        evidence_json_path = os.path.join(settings.VIDEO_STORAGE_PATH, f"{video.id}_academic_evidence.json")
        evidence_markdown_path = os.path.join(settings.VIDEO_STORAGE_PATH, f"{video.id}_academic_evidence.md")
        before_after_path = os.path.join(settings.VIDEO_STORAGE_PATH, f"{video.id}_before_after_comparison.json")
        timeline_json_path = os.path.join(settings.VIDEO_STORAGE_PATH, f"{video.id}_timeline_decisions.json")
        timeline_csv_path = os.path.join(settings.VIDEO_STORAGE_PATH, f"{video.id}_timeline_decisions.csv")
        provider_mode_path = os.path.join(settings.VIDEO_STORAGE_PATH, f"{video.id}_provider_mode_trace.json")
        metrics_summary_path = os.path.join(settings.VIDEO_STORAGE_PATH, f"{video.id}_metrics_summary.json")
        evidence_index_path = os.path.join(settings.VIDEO_STORAGE_PATH, f"{video.id}_generated_evidence_index.json")
        artifact_paths = {
            "edited_video": output_path,
            "subtitles_srt": srt_path if sidecar_enabled else None,
            "subtitles_vtt": vtt_path if sidecar_enabled else None,
            "chapters": chapters_path,
            "plan_json": plan_path,
            "quality_report": quality_report_path,
            "academic_evidence_json": evidence_json_path,
            "academic_evidence_markdown": evidence_markdown_path,
            "before_after_comparison_json": before_after_path,
            "timeline_decisions_json": timeline_json_path,
            "timeline_decisions_csv": timeline_csv_path,
            "provider_mode_trace_json": provider_mode_path,
            "metrics_summary_json": metrics_summary_path,
            "generated_evidence_index_json": evidence_index_path,
        }
        plan_export = _export_plan_json(
            video,
            plan,
            segments,
            render_ranges,
            sync_plan,
            render_metadata_extra={
                "layout_renderer": "phase7_layouts" if layout_clip_count else "single_source",
                "renderer_schema_version": "phase9.multitrack-renderer.v1",
                "layout_clip_count": layout_clip_count,
                "layout_render_counts": layout_render_counts,
                "timeline_tracks": layout_render_context.timeline_tracks if layout_render_context else [],
                "source_manifest": layout_render_context.source_manifest if layout_render_context else [],
                "transition_events": transition_events,
                "transition_count": len(transition_events),
                "applied_clip_transition_count": sum(
                    1 for item in transition_events if item.get("render_strategy") == "clip_fade"
                ),
                "applied_concat_transition_count": len(concat_transition_specs),
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
                "annotations": {
                    "count": len(annotations),
                    "rendered_event_count": len(annotation_events),
                    "burned_in": annotation_burned_in,
                },
                "educational_overlays": {
                    "count": len(educational_overlays),
                    "rendered_event_count": len(educational_overlay_events),
                    "intro_card_count": sum(1 for item in educational_overlays if item.get("overlay_type") == "intro_card"),
                    "section_title_card_count": sum(1 for item in educational_overlays if item.get("overlay_type") == "section_title_card"),
                    "chapter_label_count": sum(1 for item in educational_overlays if item.get("overlay_type") == "chapter_label"),
                    "step_label_count": sum(1 for item in educational_overlays if item.get("overlay_type") == "step_label"),
                    "burned_in": bool(educational_overlay_events),
                },
                "end_cards": {
                    "count": len(end_cards),
                    "enabled_count": len(enabled_end_cards),
                    "rendered_clip_count": len(end_card_clip_paths),
                    "total_duration_seconds": round(sum(float(card.get("duration_seconds") or 0) for card in enabled_end_cards), 3),
                    "types": [str(card.get("card_type")) for card in enabled_end_cards],
                    "appended_to_output": len(end_card_clip_paths) > 0,
                },
            },
            artifact_paths=artifact_paths,
        )
        write_json_artifact(plan_path, plan_export)

        logger.info(f"  Exported chapters + plan JSON")

        # ── Step 7: Get output metadata ──
        _check_render_cancel(render_job_id, video_id)
        _render_progress(
            render_job_id,
            video_id,
            94,
            "finalizing",
            "Finalizing render",
            "Reading output metadata and updating the project record",
        )
        metadata = await ffmpeg_service.get_video_metadata(output_path)
        _validate_rendered_video_output(
            metadata=metadata,
            expected_duration=expected_output_duration,
            output_path=output_path,
        )
        output_duration = metadata.get("duration", 0)

        # ── Step 8: Update video record ──
        video.processed_video_path = output_path
        await db.flush()
        evaluation_artifacts = await _write_evaluation_artifacts(
            video=video,
            plan=plan,
            segments=segments,
            transcript=transcript,
            db=db,
            plan_export=plan_export,
            plan_path=plan_path,
            artifact_paths=artifact_paths,
            render_metadata=plan_export.get("export_metadata", {}).get("render", {}),
        )

        # ── Cleanup temp clips ──
        try:
            shutil.rmtree(clip_dir, ignore_errors=True)
        except Exception:
            pass

        video.status = VideoStatus.COMPLETED
        await db.flush()

        logger.info(
            f"Render complete: {output_duration:.1f}s output, "
            f"{len(included_segment_ids)} segments included, "
            f"{len(segments) - len(included_segment_ids)} removed"
        )
        _render_progress(
            render_job_id,
            video_id,
            100,
            "completed",
            "Render complete",
            "Export files are ready",
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
            "transition_count": len(transition_events),
            "applied_clip_transition_count": sum(
                1 for item in transition_events if item.get("render_strategy") == "clip_fade"
            ),
            "applied_concat_transition_count": len(concat_transition_specs),
            "annotations_burned_in": annotation_burned_in,
            "annotation_count": len(annotations),
            "educational_overlay_count": len(educational_overlays),
            "end_card_count": len(enabled_end_cards),
            "quality_report_path": quality_report_path,
            "academic_evidence_path": evidence_json_path,
            "academic_evidence_markdown_path": evidence_markdown_path,
            "artifact_count": len(evaluation_artifacts["artifact_manifest"]),
        }

    except RenderCancelled:
        video.status = VideoStatus.AWAITING_REVIEW
        video.error_message = "Render cancelled by user"
        await db.flush()
        logger.info("Render cancelled for video %s", video_id)
        raise

    except Exception as e:
        video.status = VideoStatus.FAILED
        video.error_message = f"Render failed: {str(e)}"
        await db.flush()
        logger.error(f"Render failed: {e}")
        raise


# ═══════════════════════════════════════════
#  SUBTITLE GENERATION
# ═══════════════════════════════════════════

def _render_progress(
    render_job_id: str | None,
    video_id: str,
    progress_percent: float,
    phase: str,
    phase_label: str,
    message: str,
    details: dict | None = None,
) -> None:
    update_render_job(
        render_job_id,
        video_id,
        progress_percent=progress_percent,
        phase=phase,
        phase_label=phase_label,
        message=message,
        details=details,
    )


def _check_render_cancel(render_job_id: str | None, video_id: str) -> None:
    ensure_not_cancelled(render_job_id, video_id)


def _cancel_check_callback(render_job_id: str | None, video_id: str):
    return lambda: ensure_not_cancelled(render_job_id, video_id)


def _range_progress(index: int, total: int) -> float:
    if total <= 0:
        return 14.0
    return 14.0 + (float(index) / float(total)) * 40.0


def _render_range_duration(render_range: dict) -> float:
    try:
        start = float(render_range.get("source_start_time") or 0.0)
        end = float(render_range.get("source_end_time") or start)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, end - start)


def _resolve_slide_image(segment, video_id: str) -> str | None:
    """Return path to slide PNG if segment has a slide_index, else None."""
    slide_index = getattr(segment, 'slide_index', None)
    if slide_index is None:
        return None

    slide_path = os.path.join(
        settings.VIDEO_STORAGE_PATH,
        f"slides_{video_id}",
        f"page_{int(slide_index):03d}.png"
    )
    if os.path.isfile(slide_path):
        return slide_path
    return None


def _detect_layout_mode(segment, render_range: dict) -> str:
    """Determine which layout mode to use for this segment.

    Priority:
    1. segment.layout_mode (set by Agent 5 via plan_payload)
    2. Default to "picture_in_picture"
    """
    layout = render_range.get("layout_mode")
    if layout:
        return layout
    return "picture_in_picture"


async def _build_layout_render_context(
    video: Video,
    plan_payload: dict,
    db: AsyncSession,
    *,
    render_job_id: str | None = None,
) -> LayoutRenderContext | None:
    cues = list(plan_payload.get("layout_cues") or [])
    if not video.project_id:
        return (
            LayoutRenderContext(
                cues=cues,
                assets_by_id={},
                assets_by_track={},
                assets_by_role={},
                timeline_tracks=_timeline_tracks_from_plan(plan_payload, []),
                source_manifest=[],
                transition_events=[],
            )
            if any(_is_renderable_layout_cue(cue) for cue in cues)
            else None
        )

    result = await db.execute(
        select(ProjectAsset).where(ProjectAsset.project_id == video.project_id)
    )
    assets = list(result.scalars().all())
    generated_slide_asset = await _generated_slide_background_asset(
        video,
        assets,
        plan_payload,
        render_job_id=render_job_id,
    )
    render_assets = assets + ([generated_slide_asset] if generated_slide_asset else [])
    assets_by_id = {str(asset.id): asset for asset in render_assets}
    assets_by_track = _assets_by_track(render_assets)
    assets_by_role = _assets_by_role(render_assets)
    timeline_tracks = _timeline_tracks_from_plan(plan_payload, render_assets)

    if not cues and render_assets:
        cues = _implicit_full_source_cues(video, render_assets)

    if not any(_is_renderable_layout_cue(cue) for cue in cues) and not timeline_tracks:
        return None

    return LayoutRenderContext(
        cues=cues,
        assets_by_id=assets_by_id,
        assets_by_track=assets_by_track,
        assets_by_role=assets_by_role,
        timeline_tracks=timeline_tracks,
        source_manifest=_source_manifest(render_assets, timeline_tracks),
        transition_events=[],
        fallback_screen_asset=generated_slide_asset or _first_asset_with_role(assets, {"screen", "primary"}),
        fallback_camera_asset=_first_asset_with_role(assets, {"camera"}) or _structure_backed_primary_asset(assets),
        fallback_audio_asset=_first_asset_with_role(assets, {"audio"}),
    )


async def _generated_slide_background_asset(
    video: Video,
    assets: list[ProjectAsset],
    plan_payload: dict,
    *,
    render_job_id: str | None = None,
) -> object | None:
    """Create a renderable screen track from uploaded notes/PDF/PPT structure."""
    if _first_asset_with_role(assets, {"screen"}):
        return None

    structure_references = build_structure_references_from_assets(assets)
    if not structure_references:
        structure_references = _fallback_structure_references_from_assets(assets)
    if not structure_references:
        return None

    duration = _render_source_duration(video, assets, plan_payload)
    if duration <= 0:
        return None

    width, height = _annotation_canvas_dimensions(plan_payload)
    output_dir = os.path.join(settings.TEMP_PATH, f"generated_slides_{video.id}")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "generated_slides.mp4")

    rasterized_slides = _render_structure_reference_images(assets, output_dir, width, height)
    cancel_check = lambda: _check_render_cancel(render_job_id, str(video.id))
    if rasterized_slides:
        _render_progress(
            render_job_id,
            str(video.id),
            12,
            "visual_sources",
            "Preparing visual sources",
            f"Rendering {len(rasterized_slides)} slide pages for the export timeline",
            {"slide_pages": len(rasterized_slides)},
        )
        durations = _slide_durations(len(rasterized_slides), duration)
        await ffmpeg_service.create_slideshow_clip(
            output_path,
            image_paths=[slide["path"] for slide in rasterized_slides],
            durations=durations,
            width=width,
            height=height,
            background_color="#101827",
            cancel_check=cancel_check,
        )
        return _generated_slide_asset(
            video=video,
            output_path=output_path,
            duration=duration,
            structure_reference_count=len(structure_references),
            source="uploaded_structure_raster",
            render_mode="rasterized_pages",
            rasterized_slide_count=len(rasterized_slides),
            rasterized_sources=sorted({slide.get("render_source", "unknown") for slide in rasterized_slides}),
        )

    events = _structure_reference_slide_events(structure_references, duration)
    if not events:
        return None

    base_path = os.path.join(output_dir, "generated_slides_base.mp4")
    ass_path = os.path.join(output_dir, "generated_slides.ass")
    await ffmpeg_service.create_solid_color_clip(
        base_path,
        duration_seconds=duration,
        width=width,
        height=height,
        background_color="#101827",
        cancel_check=cancel_check,
    )
    with open(ass_path, "w", encoding="utf-8") as handle:
        handle.write(_generate_annotation_ass(events, width=width, height=height))
    await ffmpeg_service.burn_ass_overlay(
        base_path,
        ass_path,
        output_path,
        cancel_check=cancel_check,
    )

    return _generated_slide_asset(
        video=video,
        output_path=output_path,
        duration=duration,
        structure_reference_count=len(structure_references),
        source="uploaded_structure_reference",
        render_mode="text_cards",
        rasterized_slide_count=0,
        rasterized_sources=[],
    )


def _generated_slide_asset(
    *,
    video: Video,
    output_path: str,
    duration: float,
    structure_reference_count: int,
    source: str,
    render_mode: str,
    rasterized_slide_count: int,
    rasterized_sources: list[str],
) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"generated-slides-{video.id}",
        role="screen",
        kind="generated_slides",
        source_type="generated_slides",
        sync_role="screen_reference",
        status="ready",
        is_primary=False,
        filename="generated_slides.mp4",
        original_filename="Generated teaching slides",
        file_path=output_path,
        duration_seconds=duration,
        sync_offset_seconds=0.0,
        created_at=datetime.min,
        metadata_json={
            "generated": True,
            "track": "generated_slides",
            "timeline_track": "generated_slides",
            "structure_reference_count": structure_reference_count,
            "source": source,
            "render_mode": render_mode,
            "rasterized_slide_count": rasterized_slide_count,
            "rasterized_sources": rasterized_sources,
        },
    )


def _render_structure_reference_images(
    assets: list[ProjectAsset],
    output_dir: str,
    width: int,
    height: int,
) -> list[dict]:
    slides: list[dict] = []
    image_dir = os.path.join(output_dir, "rasterized")
    os.makedirs(image_dir, exist_ok=True)
    for asset in assets:
        if not _asset_is_structure_reference(asset):
            continue
        file_path = str(getattr(asset, "file_path", "") or "")
        if not os.path.isfile(file_path):
            continue
        ext = os.path.splitext(file_path)[1].lower()
        try:
            if ext == ".pdf":
                slides.extend(_render_pdf_pages_to_images(asset, image_dir, width, height))
            elif ext in {".ppt", ".pptx"}:
                slides.extend(_render_presentation_to_images(asset, image_dir, width, height))
        except Exception as exc:
            logger.warning("Could not rasterize teaching material %s: %s", file_path, exc)
        if len(slides) >= 80:
            break
    return slides[:80]


def _render_pdf_pages_to_images(asset: ProjectAsset, image_dir: str, width: int, height: int) -> list[dict]:
    import fitz

    slides = []
    doc = fitz.open(str(asset.file_path))
    try:
        for page_index in range(min(len(doc), 80)):
            page = doc[page_index]
            zoom = min(float(width) / max(float(page.rect.width), 1.0), float(height) / max(float(page.rect.height), 1.0))
            pixmap = page.get_pixmap(matrix=fitz.Matrix(max(0.5, zoom), max(0.5, zoom)), alpha=False)
            image_path = os.path.join(image_dir, f"{_safe_asset_stem(asset)}_page_{page_index + 1:03d}.png")
            pixmap.save(image_path)
            slides.append(
                {
                    "path": image_path,
                    "asset_id": str(getattr(asset, "id", "")),
                    "page_index": page_index + 1,
                    "render_source": "pdf",
                    "exact": True,
                }
            )
    finally:
        doc.close()
    return slides


def _render_presentation_to_images(asset: ProjectAsset, image_dir: str, width: int, height: int) -> list[dict]:
    pdf_path = _convert_presentation_to_pdf(asset.file_path, image_dir)
    if pdf_path and os.path.isfile(pdf_path):
        rendered = _render_pdf_pages_to_images(
            SimpleNamespace(
                id=getattr(asset, "id", ""),
                file_path=pdf_path,
                filename=getattr(asset, "filename", "presentation.pdf"),
                original_filename=getattr(asset, "original_filename", "presentation.pdf"),
            ),
            image_dir,
            width,
            height,
        )
        for slide in rendered:
            slide["render_source"] = "pptx_via_libreoffice_pdf"
            slide["asset_id"] = str(getattr(asset, "id", ""))
            slide["exact"] = True
        return rendered
    return _render_pptx_text_slides_to_images(asset, image_dir, width, height)


def _convert_presentation_to_pdf(file_path: str, image_dir: str) -> str | None:
    executable = shutil.which("soffice") or shutil.which("libreoffice")
    if not executable:
        return None
    output_dir = os.path.join(image_dir, "office_pdf")
    os.makedirs(output_dir, exist_ok=True)
    try:
        subprocess.run(
            [
                executable,
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                output_dir,
                str(file_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
            check=True,
        )
    except Exception as exc:
        logger.warning("Presentation PDF conversion failed for %s: %s", file_path, exc)
        return None
    candidate = os.path.join(output_dir, f"{os.path.splitext(os.path.basename(file_path))[0]}.pdf")
    return candidate if os.path.isfile(candidate) else None


def _render_pptx_text_slides_to_images(asset: ProjectAsset, image_dir: str, width: int, height: int) -> list[dict]:
    import fitz
    from pptx import Presentation

    presentation = Presentation(str(asset.file_path))
    slides = []
    for slide_index, slide in enumerate(presentation.slides, start=1):
        title, bullets = _pptx_slide_text(slide, slide_index)
        doc = fitz.open()
        page = doc.new_page(width=width, height=height)
        page.draw_rect(fitz.Rect(0, 0, width, height), color=(1, 1, 1), fill=(1, 1, 1))
        page.draw_rect(
            fitz.Rect(0, 0, width, int(height * 0.18)),
            color=(0.10, 0.12, 0.18),
            fill=(0.10, 0.12, 0.18),
        )
        page.insert_textbox(
            fitz.Rect(width * 0.06, height * 0.045, width * 0.94, height * 0.16),
            title,
            fontsize=42,
            fontname="helv",
            color=(1, 1, 1),
            align=0,
        )
        y = height * 0.25
        for bullet in bullets[:8]:
            page.insert_textbox(
                fitz.Rect(width * 0.09, y, width * 0.90, y + 72),
                f"- {bullet}",
                fontsize=28,
                fontname="helv",
                color=(0.08, 0.10, 0.16),
                align=0,
            )
            y += 78
        page.insert_textbox(
            fitz.Rect(width * 0.78, height * 0.90, width * 0.95, height * 0.96),
            f"Slide {slide_index}",
            fontsize=20,
            fontname="helv",
            color=(0.35, 0.40, 0.50),
            align=2,
        )
        image_path = os.path.join(image_dir, f"{_safe_asset_stem(asset)}_slide_{slide_index:03d}.png")
        page.get_pixmap(alpha=False).save(image_path)
        doc.close()
        slides.append(
            {
                "path": image_path,
                "asset_id": str(getattr(asset, "id", "")),
                "page_index": slide_index,
                "render_source": "pptx_text_visual",
                "exact": False,
            }
        )
        if len(slides) >= 80:
            break
    return slides


def _pptx_slide_text(slide, slide_index: int) -> tuple[str, list[str]]:
    texts = []
    for shape in slide.shapes:
        if getattr(shape, "has_text_frame", False):
            for paragraph in shape.text_frame.paragraphs:
                text = " ".join(str(paragraph.text or "").split())
                if text:
                    texts.append(text)
        if getattr(shape, "has_table", False):
            for row in shape.table.rows:
                row_text = " | ".join(" ".join(str(cell.text or "").split()) for cell in row.cells if str(cell.text or "").strip())
                if row_text:
                    texts.append(row_text)
    title = texts[0] if texts else f"Slide {slide_index}"
    bullets = texts[1:] if len(texts) > 1 else []
    return _compact_text(title, 90), [_compact_text(text, 160) for text in bullets if text]


def _slide_durations(slide_count: int, duration_seconds: float) -> list[float]:
    if slide_count <= 0:
        return []
    base = max(1.0, float(duration_seconds) / float(slide_count))
    return [base for _ in range(slide_count)]


def _structure_reference_slide_events(
    structure_references: list[dict],
    duration_seconds: float,
) -> list[dict]:
    items: list[dict] = []
    for reference in structure_references:
        source_title = str(reference.get("title") or reference.get("source_filename") or "").strip()
        for item in reference.get("items") or []:
            if not isinstance(item, dict):
                continue
            title = _compact_text(item.get("title") or source_title or "Lecture section", 90)
            body = _compact_text(item.get("text") or "", 220)
            items.append({
                "title": title,
                "subtitle": body,
                "source_title": source_title,
            })

    if not items:
        return []

    max_items = min(len(items), 36)
    selected = items[:max_items]
    span = max(4.0, float(duration_seconds) / max(len(selected), 1))
    events = []
    for index, item in enumerate(selected):
        start = min(float(duration_seconds), index * span)
        end = float(duration_seconds) if index == len(selected) - 1 else min(float(duration_seconds), (index + 1) * span)
        if end <= start:
            continue
        events.append({
            "id": f"generated-slide-{index + 1:03d}",
            "kind": "educational_overlay",
            "overlay_type": "section_title_card",
            "title": item["title"],
            "subtitle": item["subtitle"],
            "output_start_time": round(start, 3),
            "output_end_time": round(end, 3),
            "position": "center",
            "x_percent": 50.0,
            "y_percent": 50.0,
            "style": {
                "font_size": 42,
                "subtitle_font_size": 24,
                "text_color": "#FFFFFF",
                "subtitle_color": "#CBD5E1",
                "background_color": "#111827",
                "accent_color": "#A78BFA",
                "opacity": 0.92,
            },
            "animation": {
                "preset": "fade",
                "duration_seconds": 0.45,
            },
        })
    return events


def _fallback_structure_references_from_assets(assets: list[ProjectAsset]) -> list[dict]:
    references = []
    structure_roles = {"slides", "notes", "supporting_material"}
    structure_kinds = {"slide_deck", "pdf_notes", "text_notes"}
    for asset in assets:
        role = _enum_value(getattr(asset, "role", None))
        kind = _enum_value(getattr(asset, "kind", None))
        sync_role = _enum_value(getattr(asset, "sync_role", None))
        if role not in structure_roles and kind not in structure_kinds and sync_role != "structure_reference":
            continue
        title = _compact_text(
            getattr(asset, "original_filename", None)
            or getattr(asset, "filename", None)
            or "Uploaded teaching material",
            90,
        )
        references.append(
            {
                "title": title,
                "source_filename": getattr(asset, "original_filename", None) or getattr(asset, "filename", None),
                "reference_role": role or kind or "structure_reference",
                "items": [
                    {
                        "index": 1,
                        "title": title,
                        "text": "Uploaded structure reference for the lecture.",
                    }
                ],
            }
        )
    return references


def _asset_is_structure_reference(asset: object) -> bool:
    return (
        _enum_value(getattr(asset, "role", None)) in {"slides", "notes", "supporting_material"}
        or _enum_value(getattr(asset, "kind", None)) in {"slide_deck", "pdf_notes", "text_notes"}
        or _enum_value(getattr(asset, "sync_role", None)) == "structure_reference"
    )


def _safe_asset_stem(asset: object) -> str:
    raw = os.path.splitext(str(getattr(asset, "filename", None) or getattr(asset, "original_filename", None) or "asset"))[0]
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in raw)[:80] or "asset"


def _compact_text(value: object, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


async def _render_slide_composited_clip(
    *,
    video: Video,
    render_range: dict,
    range_index: int,
    clip_dir: str,
    slide_image_path: str,
    layout_mode: str,
    cancel_check=None,
) -> tuple[list[str], list[float], dict[str, int]]:
    """
    Render a single clip by compositing face video over a static slide PNG.

    Uses FFmpeg with filter_complex to overlay face video onto a static slide background.
    Returns same format as _render_range_clips: (paths, durations, layout_counts)
    """
    start_time = float(render_range["source_start_time"])
    end_time = float(render_range["source_end_time"])
    duration = max(0.1, end_time - start_time)

    output_path = os.path.join(clip_dir, f"slide_composite_{range_index:04d}.mp4")

    output_width = 1920
    output_height = 1080

    if layout_mode == "full_screen_source":
        # Slide fills entire canvas. Face video hidden.
        filter_complex = (
            f"[0:v]scale={output_width}:{output_height}:force_original_aspect_ratio=decrease,"
            f"pad={output_width}:{output_height}:(ow-iw)/2:(oh-ih)/2:white[bg];"
            f"[bg]null[out]"
        )
    elif layout_mode == "side_by_side":
        # Slide on left half, face on right half
        half_w = output_width // 2
        filter_complex = (
            f"[0:v]scale={half_w}:{output_height}:force_original_aspect_ratio=decrease,"
            f"pad={half_w}:{output_height}:(ow-iw)/2:(oh-ih)/2:white[left];"
            f"[1:v]scale={half_w}:{output_height}:force_original_aspect_ratio=decrease,"
            f"pad={half_w}:{output_height}:(ow-iw)/2:(oh-ih)/2:white[right];"
            f"[left][right]hstack=2[out]"
        )
    elif layout_mode == "full_camera_source":
        # Face full-screen, no slide. Just trim the video.
        cmd = [
            "ffmpeg",
            "-ss", str(start_time),
            "-i", video.file_path,
            "-t", str(duration),
            "-c:v", "copy",
            "-c:a", "copy",
            "-y", output_path,
        ]
        # Use fast copy when possible; fall back to encode if needed
        try:
            result = await FFmpegService._run_process_with_encoder_fallback(
                cmd,
                error_prefix=f"Slide compositor full_camera_source range {range_index}",
                cancel_check=cancel_check,
                allow_failure=True,
            )
            _, stderr, returncode = result
        except Exception:
            returncode = 1

        if returncode != 0:
            # Fall back to full re-encode with hw acceleration
            cmd_encode = [
                "ffmpeg",
                "-ss", str(start_time),
                "-i", video.file_path,
                "-t", str(duration),
                *FFmpegService._video_encoder_args("5000k", "veryfast"),
                "-c:a", "aac", "-b:a", "192k",
                "-ar", "48000", "-ac", "2",
                "-movflags", "+faststart",
                "-y", output_path,
            ]
            await FFmpegService._run_process_with_encoder_fallback(
                cmd_encode,
                error_prefix=f"Slide compositor full_camera_source encode range {range_index}",
                cancel_check=cancel_check,
            )

        return [output_path], [duration], {"slide_composite_full_camera_source": 1}
    else:
        # Default: picture_in_picture — Slide background with PiP face in bottom-right
        face_w = 480
        face_h = 270
        margin = 20
        filter_complex = (
            f"[0:v]scale={output_width}:{output_height}:force_original_aspect_ratio=decrease,"
            f"pad={output_width}:{output_height}:(ow-iw)/2:(oh-ih)/2:white[bg];"
            f"[1:v]scale={face_w}:{face_h}[face];"
            f"[bg][face]overlay=W-w-{margin}:H-h-{margin}[out]"
        )

    # Build FFmpeg command for layout modes that need filter_complex
    cmd = [
        "ffmpeg",
        "-loop", "1",
        "-i", slide_image_path,
        "-ss", str(start_time),
        "-i", video.file_path,
        "-t", str(duration),
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-map", "1:a",
        "-c:a", "copy",
        *FFmpegService._video_encoder_args("5000k", "veryfast"),
        "-movflags", "+faststart",
        "-y", output_path,
    ]

    await FFmpegService._run_process_with_encoder_fallback(
        cmd,
        error_prefix=f"Slide compositor range {range_index} (layout={layout_mode})",
        cancel_check=cancel_check,
    )

    layout_label = f"slide_composite_{layout_mode}"
    return [output_path], [duration], {layout_label: 1}


async def _render_range_clips(
    *,
    video: Video,
    render_range: dict,
    range_index: int,
    clip_dir: str,
    layout_context: LayoutRenderContext | None,
    cancel_check=None,
) -> tuple[list[str], list[float], dict[str, int]]:
    clip_paths = []
    clip_durations = []
    layout_counts: dict[str, int] = {}
    spans = _layout_spans_for_range(render_range, layout_context.cues if layout_context else [])

    for span_index, (start_time, end_time, cue) in enumerate(spans):
        span_duration = float(end_time) - float(start_time)
        if span_duration < MIN_RENDER_SPAN_SECONDS:
            continue
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
                cancel_check=cancel_check,
            )

        if rendered_layout:
            layout_counts[rendered_layout] = layout_counts.get(rendered_layout, 0) + 1
        else:
            await _trim_single_source_clip(video.file_path, raw_clip, start_time, end_time, cancel_check=cancel_check)

        raw_clip = await _apply_span_transition_polish(
            cue=cue,
            input_path=raw_clip,
            range_index=range_index,
            span_index=span_index,
            clip_dir=clip_dir,
            start_time=start_time,
            end_time=end_time,
            cancel_check=cancel_check,
        )

        if render_range["action"] == SegmentAction.SHORTEN.value:
            final_clip = os.path.join(clip_dir, f"clip_{range_index:04d}_{span_index:02d}.mp4")
            await ffmpeg_service.trim_silence_from_clip(
                input_path=raw_clip,
                output_path=final_clip,
                threshold_db=settings.SILENCE_THRESHOLD_DB,
                min_silence=0.8,
                cancel_check=cancel_check,
            )
            try:
                os.remove(raw_clip)
            except OSError:
                pass
        else:
            final_clip = os.path.join(clip_dir, f"clip_{range_index:04d}_{span_index:02d}.mp4")
            os.rename(raw_clip, final_clip)
        clip_paths.append(final_clip)
        clip_durations.append(span_duration)

    return clip_paths, clip_durations, layout_counts


async def _render_audio_only_export(
    *,
    video: Video,
    plan: EditPlan,
    segments: List[Segment],
    transcript: Transcript | None,
    render_ranges: List[dict],
    included_segment_ids: set[str],
    sync_plan: dict,
    plan_payload: dict,
    selected_preset: dict,
    layout_context: LayoutRenderContext | None,
    render_job_id: str | None,
    video_id: str,
    db: AsyncSession | None = None,
) -> dict:
    """Render a podcast/lecture audio-only output from the cleaned edit timeline."""
    clip_dir = os.path.join(settings.TEMP_PATH, f"audio_clips_{video.id}")
    os.makedirs(clip_dir, exist_ok=True)

    audio_source = _audio_export_source(video, layout_context)
    audio_codec = str(selected_preset.get("audio_codec") or "aac")
    audio_bitrate = _ffmpeg_audio_bitrate(selected_preset.get("audio_bitrate"))
    output_extension = _audio_output_extension(selected_preset)
    output_filename = f"{video.id}_audio{output_extension}"
    output_path = os.path.join(settings.VIDEO_STORAGE_PATH, output_filename)
    clip_paths: list[str] = []
    clip_durations: list[float] = []

    try:
        for index, render_range in enumerate(render_ranges):
            _check_render_cancel(render_job_id, video_id)
            _render_progress(
                render_job_id,
                video_id,
                _range_progress(index, len(render_ranges)),
                "rendering_audio",
                "Rendering cleaned audio",
                f"Rendering audio range {index + 1} of {len(render_ranges)}",
                {
                    "current_range": index + 1,
                    "total_ranges": len(render_ranges),
                    "output_kind": "audio_only",
                    "source": audio_source["source"],
                },
            )
            raw_clip = os.path.join(clip_dir, f"raw_audio_{index:04d}{output_extension}")
            await ffmpeg_service.trim_audio(
                input_path=audio_source["path"],
                output_path=raw_clip,
                start_time=render_range["source_start_time"],
                end_time=render_range["source_end_time"],
                sync_offset=audio_source["sync_offset_seconds"],
                audio_codec=audio_codec,
                audio_bitrate=audio_bitrate,
                cancel_check=_cancel_check_callback(render_job_id, video_id),
            )

            final_clip = os.path.join(clip_dir, f"audio_{index:04d}{output_extension}")
            if render_range["action"] == SegmentAction.SHORTEN.value:
                await ffmpeg_service.trim_silence_from_audio(
                    input_path=raw_clip,
                    output_path=final_clip,
                    threshold_db=settings.SILENCE_THRESHOLD_DB,
                    min_silence=0.8,
                    audio_codec=audio_codec,
                    audio_bitrate=audio_bitrate,
                    cancel_check=_cancel_check_callback(render_job_id, video_id),
                )
                _remove_file(raw_clip)
            else:
                os.rename(raw_clip, final_clip)
            clip_paths.append(final_clip)
            clip_durations.append(float(render_range["duration"]))

        _check_render_cancel(render_job_id, video_id)
        _render_progress(
            render_job_id,
            video_id,
            64,
            "concatenating_audio",
            "Concatenating cleaned audio",
            f"Combining {len(clip_paths)} audio clips into the final podcast file",
            {"clip_count": len(clip_paths), "output_kind": "audio_only"},
        )
        await ffmpeg_service.concat_audio(
            clip_paths=clip_paths,
            output_path=output_path,
            audio_codec=audio_codec,
            audio_bitrate=audio_bitrate,
            cancel_check=_cancel_check_callback(render_job_id, video_id),
        )

        _check_render_cancel(render_job_id, video_id)
        _render_progress(
            render_job_id,
            video_id,
            78,
            "transcript_artifacts",
            "Writing transcript artifacts",
            "Generating transcript sidecars and chapter markers for the audio export",
            {"output_kind": "audio_only"},
        )
        srt_content = _generate_word_level_srt(
            render_ranges,
            transcript.words_json if transcript else None,
            caption_policy={
                "enabled": True,
                "appearance": "always",
                "export_behavior": "sidecar",
            },
        )
        srt_path = os.path.join(settings.VIDEO_STORAGE_PATH, f"{video.id}_subtitles.srt")
        vtt_path = os.path.join(settings.VIDEO_STORAGE_PATH, f"{video.id}_subtitles.vtt")
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(srt_content)
        with open(vtt_path, "w", encoding="utf-8") as f:
            f.write(_srt_to_vtt(srt_content))

        chapters = _generate_chapter_file(render_ranges)
        chapters_path = os.path.join(settings.VIDEO_STORAGE_PATH, f"{video.id}_chapters.txt")
        with open(chapters_path, "w", encoding="utf-8") as f:
            f.write(chapters)

        _check_render_cancel(render_job_id, video_id)
        _render_progress(
            render_job_id,
            video_id,
            92,
            "exporting_audio_plan",
            "Writing audio export plan",
            "Recording audio-only export metadata and artifact paths",
            {"output_kind": "audio_only"},
        )
        plan_path = os.path.join(settings.VIDEO_STORAGE_PATH, f"{video.id}_edit_plan.json")
        quality_report_path = os.path.join(settings.VIDEO_STORAGE_PATH, f"{video.id}_quality_report.json")
        evidence_json_path = os.path.join(settings.VIDEO_STORAGE_PATH, f"{video.id}_academic_evidence.json")
        evidence_markdown_path = os.path.join(settings.VIDEO_STORAGE_PATH, f"{video.id}_academic_evidence.md")
        before_after_path = os.path.join(settings.VIDEO_STORAGE_PATH, f"{video.id}_before_after_comparison.json")
        timeline_json_path = os.path.join(settings.VIDEO_STORAGE_PATH, f"{video.id}_timeline_decisions.json")
        timeline_csv_path = os.path.join(settings.VIDEO_STORAGE_PATH, f"{video.id}_timeline_decisions.csv")
        provider_mode_path = os.path.join(settings.VIDEO_STORAGE_PATH, f"{video.id}_provider_mode_trace.json")
        metrics_summary_path = os.path.join(settings.VIDEO_STORAGE_PATH, f"{video.id}_metrics_summary.json")
        evidence_index_path = os.path.join(settings.VIDEO_STORAGE_PATH, f"{video.id}_generated_evidence_index.json")
        artifact_paths = {
            "audio_only": output_path,
            "transcript_srt": srt_path,
            "transcript_vtt": vtt_path,
            "chapters": chapters_path,
            "plan_json": plan_path,
            "quality_report": quality_report_path,
            "academic_evidence_json": evidence_json_path,
            "academic_evidence_markdown": evidence_markdown_path,
            "before_after_comparison_json": before_after_path,
            "timeline_decisions_json": timeline_json_path,
            "timeline_decisions_csv": timeline_csv_path,
            "provider_mode_trace_json": provider_mode_path,
            "metrics_summary_json": metrics_summary_path,
            "generated_evidence_index_json": evidence_index_path,
        }
        metadata = await ffmpeg_service.get_video_metadata(output_path)
        output_duration = float(metadata.get("duration") or sum(clip_durations))
        plan_export = _export_plan_json(
            video,
            plan,
            segments,
            render_ranges,
            sync_plan,
            render_metadata_extra={
                "renderer_schema_version": "phase9.audio-only-export.v1",
                "output_kind": "audio_only",
                "selected_preset_id": selected_preset.get("id"),
                "container": selected_preset.get("container"),
                "audio_codec": audio_codec,
                "audio_bitrate": audio_bitrate,
                "audio_source": audio_source,
                "audio_clip_count": len(clip_paths),
                "caption_policy": {
                    "enabled": True,
                    "appearance": "always",
                    "export_behavior": "transcript_export",
                    "sidecar_files": True,
                    "burned_in": False,
                    "cue_count": srt_content.count(" --> "),
                },
            },
            artifact_paths=artifact_paths,
        )
        write_json_artifact(plan_path, plan_export)

        video.processed_video_path = output_path
        if db is not None:
            await db.flush()
            evaluation_artifacts = await _write_evaluation_artifacts(
                video=video,
                plan=plan,
                segments=segments,
                transcript=transcript,
                db=db,
                plan_export=plan_export,
                plan_path=plan_path,
                artifact_paths=artifact_paths,
                render_metadata=plan_export.get("export_metadata", {}).get("render", {}),
            )
        else:
            evaluation_artifacts = {"artifact_manifest": artifact_records(artifact_paths)}

        video.status = VideoStatus.COMPLETED
        if db is not None:
            await db.flush()

        _render_progress(
            render_job_id,
            video_id,
            100,
            "completed",
            "Audio export complete",
            "Podcast audio and transcript files are ready",
            {"output_kind": "audio_only"},
        )

        return {
            "status": "success",
            "output_path": output_path,
            "output_kind": "audio_only",
            "audio_path": output_path,
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
            "audio_clip_count": len(clip_paths),
            "audio_source": audio_source,
            "quality_report_path": quality_report_path,
            "academic_evidence_path": evidence_json_path,
            "academic_evidence_markdown_path": evidence_markdown_path,
            "artifact_count": len(evaluation_artifacts["artifact_manifest"]),
        }
    finally:
        try:
            shutil.rmtree(clip_dir, ignore_errors=True)
        except Exception:
            pass


async def _render_layout_span(
    *,
    cue: dict | None,
    layout_context: LayoutRenderContext,
    output_path: str,
    fallback_video_path: str,
    start_time: float,
    end_time: float,
    cancel_check=None,
) -> str | None:
    layout = str(_dict_value(cue).get("layout") or "")
    output_width, output_height = FFmpegService.output_dimensions_for_aspect_ratio(
        _dict_value(_dict_value(cue).get("output")).get("aspect_ratio")
    )
    screen_asset = _cue_asset(cue, "screen", layout_context) or layout_context.fallback_screen_asset
    camera_asset = _cue_asset(cue, "camera", layout_context) or layout_context.fallback_camera_asset
    audio_asset = _cue_asset(cue, "audio", layout_context) or layout_context.fallback_audio_asset
    if not audio_asset and _asset_is_generated_slides(screen_asset) and camera_asset:
        audio_asset = camera_asset

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
            cancel_check=cancel_check,
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
            cancel_check=cancel_check,
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
                cancel_check=cancel_check,
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
                cancel_check=cancel_check,
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
            cancel_check=cancel_check,
        )
        return layout

    return None


async def _trim_single_source_clip(
    video_path: str,
    output_path: str,
    start_time: float,
    end_time: float,
    cancel_check=None,
) -> None:
    """Trim a segment with re-encoding for frame-accurate cuts.

    Uses re-encoding (via trim_video_accurate) so clips have consistent
    codec parameters and are safe to concatenate with the concat demuxer.
    """
    trim_method = getattr(ffmpeg_service, "trim_video_accurate", None)
    if not callable(trim_method):
        trim_method = ffmpeg_service.trim_video
    await trim_method(
        video_path=video_path,
        output_path=output_path,
        start_time=start_time,
        end_time=end_time,
        cancel_check=cancel_check,
    )


async def _apply_span_transition_polish(
    *,
    cue: dict | None,
    input_path: str,
    range_index: int,
    span_index: int,
    clip_dir: str,
    start_time: float,
    end_time: float,
    cancel_check=None,
) -> str:
    timing = _dict_value(_dict_value(cue).get("timing"))
    duration = min(
        _float_value(timing.get("transition_duration_seconds"), 0.0) or 0.0,
        max(0.0, (float(end_time) - float(start_time)) / 2),
    )
    if duration <= 0:
        return input_path

    fade_in = str(timing.get("transition_in") or "").lower() in {"fade", "dip_to_black"}
    fade_out = str(timing.get("transition_out") or "").lower() in {"fade", "dip_to_black"}
    if not fade_in and not fade_out:
        return input_path

    output_path = os.path.join(clip_dir, f"transition_{range_index:04d}_{span_index:02d}.mp4")
    await ffmpeg_service.apply_clip_fades(
        input_path=input_path,
        output_path=output_path,
        clip_duration_seconds=max(0.001, float(end_time) - float(start_time)),
        fade_duration_seconds=duration,
        fade_in=fade_in,
        fade_out=fade_out,
        cancel_check=cancel_check,
    )
    _remove_file(input_path)
    return output_path


def _layout_spans_for_range(
    render_range: dict,
    cues: list[dict],
) -> list[tuple[float, float, dict | None]]:
    range_start = float(render_range["source_start_time"])
    range_end = float(render_range["source_end_time"])
    if range_end - range_start < MIN_RENDER_SPAN_SECONDS:
        return []
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
    # Build raw spans
    raw_spans: list[tuple[float, float, dict | None]] = []
    for start_time, end_time in zip(ordered, ordered[1:]):
        if end_time - start_time < MIN_RENDER_SPAN_SECONDS:
            continue
        raw_spans.append((start_time, end_time, _cue_at_time(cues, start_time)))

    # Merge adjacent spans that share the same cue (no layout change)
    merged: list[tuple[float, float, dict | None]] = []
    for span_start, span_end, cue in raw_spans:
        if merged and merged[-1][2] == cue:
            # Same cue, merge: extend the previous span
            merged[-1] = (merged[-1][0], span_end, cue)
        else:
            merged.append((span_start, span_end, cue))

    return merged or [(range_start, range_end, _cue_at_time(cues, range_start))]


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
        asset = context.assets_by_id.get(str(asset_id))
        if asset:
            return asset
    track = str(source_dict.get("track") or "").strip().lower()
    if track and track in context.assets_by_track:
        return context.assets_by_track[track]
    source_role = str(source_dict.get("role") or role).strip().lower()
    return context.assets_by_role.get(source_role)


def _assets_by_track(assets: list[ProjectAsset]) -> dict[str, ProjectAsset]:
    tracked: dict[str, ProjectAsset] = {}
    for asset in sorted(assets, key=_asset_sort_key):
        for track in _asset_track_keys(asset):
            tracked.setdefault(track, asset)
    return tracked


def _assets_by_role(assets: list[ProjectAsset]) -> dict[str, ProjectAsset]:
    by_role: dict[str, ProjectAsset] = {}
    for asset in sorted(assets, key=_asset_sort_key):
        role = _enum_value(getattr(asset, "role", None))
        if role:
            by_role.setdefault(role, asset)
        sync_role = _enum_value(getattr(asset, "sync_role", None))
        if sync_role:
            by_role.setdefault(sync_role, asset)
    return by_role


def _asset_track_keys(asset: ProjectAsset) -> list[str]:
    metadata = _dict_value(getattr(asset, "metadata_json", None))
    candidates = [
        metadata.get("track"),
        metadata.get("timeline_track"),
        _enum_value(getattr(asset, "role", None)),
        _enum_value(getattr(asset, "sync_role", None)),
        _enum_value(getattr(asset, "source_type", None)),
    ]
    role = _enum_value(getattr(asset, "role", None))
    sync_role = _enum_value(getattr(asset, "sync_role", None))
    if role == "screen" or sync_role == "screen_reference":
        candidates.append("screen")
    if role == "camera" or sync_role == "camera_overlay":
        candidates.append("camera")
    if role == "audio" or sync_role in {"audio_master", "audio_reference"}:
        candidates.append("audio")
    if role == "primary" or sync_role == "primary_timeline":
        candidates.append("primary_timeline")
    return [str(item).strip().lower() for item in candidates if str(item or "").strip()]


def _asset_sort_key(asset: ProjectAsset) -> tuple[int, int, datetime]:
    return (
        0 if bool(getattr(asset, "is_primary", False)) else 1,
        0 if _enum_value(getattr(asset, "status", None)) == "ready" else 1,
        getattr(asset, "created_at", None) or datetime.min,
    )


def _timeline_tracks_from_plan(plan_payload: dict, assets: list[ProjectAsset]) -> list[dict]:
    tracks = []
    raw_tracks = plan_payload.get("timeline_tracks")
    if isinstance(raw_tracks, list):
        for index, raw_track in enumerate(raw_tracks):
            if not isinstance(raw_track, dict):
                continue
            track_id = str(raw_track.get("id") or raw_track.get("track") or f"track-{index + 1}")
            tracks.append({
                **raw_track,
                "id": track_id,
                "role": str(raw_track.get("role") or raw_track.get("kind") or track_id).lower(),
                "enabled": bool(raw_track.get("enabled", True)),
                "asset_id": raw_track.get("asset_id"),
            })

    existing_ids = {str(track.get("id")).lower() for track in tracks}
    for asset in assets:
        for track in _asset_track_keys(asset):
            if track in existing_ids:
                continue
            tracks.append({
                "id": track,
                "role": _enum_value(getattr(asset, "role", None)) or track,
                "enabled": True,
                "asset_id": str(asset.id),
                "source_type": _enum_value(getattr(asset, "source_type", None)),
                "sync_role": _enum_value(getattr(asset, "sync_role", None)),
            })
            existing_ids.add(track)
    return tracks


def _source_manifest(assets: list[ProjectAsset], timeline_tracks: list[dict]) -> list[dict]:
    tracks_by_asset: dict[str, list[str]] = {}
    for track in timeline_tracks:
        asset_id = track.get("asset_id")
        if asset_id:
            tracks_by_asset.setdefault(str(asset_id), []).append(str(track.get("id")))
    return [
        {
            "asset_id": str(asset.id),
            "filename": getattr(asset, "original_filename", None) or getattr(asset, "filename", None),
            "role": _enum_value(getattr(asset, "role", None)),
            "source_type": _enum_value(getattr(asset, "source_type", None)),
            "sync_role": _enum_value(getattr(asset, "sync_role", None)),
            "sync_offset_seconds": float(getattr(asset, "sync_offset_seconds", 0.0) or 0.0),
            "tracks": sorted(set(tracks_by_asset.get(str(asset.id), _asset_track_keys(asset)))),
        }
        for asset in sorted(assets, key=_asset_sort_key)
    ]


def _implicit_full_source_cues(video: Video, assets: list[ProjectAsset]) -> list[dict]:
    screen_asset = _first_asset_with_role(assets, {"screen", "primary"})
    audio_asset = _first_asset_with_role(assets, {"audio"})
    if not screen_asset and not audio_asset:
        return []
    return [
        {
            "id": "renderer-implicit-full-source",
            "kind": "layout_cue",
            "schema_version": "phase9.multitrack-renderer.v1",
            "status": "planned",
            "layout": LayoutMode.FULL_SCREEN_SOURCE.value,
            "start_time": 0.0,
            "end_time": video.duration_seconds,
            "timing": {
                "start_time": 0.0,
                "end_time": video.duration_seconds,
                "duration_seconds": video.duration_seconds,
                "transition_in": "cut",
                "transition_out": "cut",
                "transition_duration_seconds": 0.0,
            },
            "sources": {
                "screen": {
                    "role": "screen",
                    "asset_id": str(screen_asset.id) if screen_asset else None,
                    "enabled": True,
                    "track": "screen" if screen_asset else "primary_timeline",
                    "sync_offset_seconds": 0.0,
                },
                "camera": {
                    "role": "camera",
                    "asset_id": None,
                    "enabled": False,
                    "track": "camera",
                    "sync_offset_seconds": 0.0,
                },
                "audio": {
                    "role": "audio",
                    "asset_id": str(audio_asset.id) if audio_asset else None,
                    "enabled": True,
                    "track": "audio",
                    "sync_offset_seconds": 0.0,
                },
            },
            "output": {"aspect_ratio": "16:9"},
            "camera": {"enabled": False, "shape": "rounded_rectangle", "corner": "bottom_right", "size": "medium", "margin_percent": 4},
            "reason": "Implicit renderer cue for multi-source project assets.",
        }
    ]


def _layout_transition_events_for_render_ranges(cues: list[dict], render_ranges: List[dict]) -> list[dict]:
    events = []
    for cue in cues:
        if not _is_renderable_layout_cue(cue):
            continue
        timing = _dict_value(cue.get("timing"))
        transition_duration = _float_value(timing.get("transition_duration_seconds"), 0.0) or 0.0
        if transition_duration <= 0:
            continue
        for edge, field in (("in", "transition_in"), ("out", "transition_out")):
            transition = str(timing.get(field) or "cut").lower()
            if transition == "cut":
                continue
            source_time = _float_value(cue.get("start_time") if edge == "in" else cue.get("end_time"), None)
            if source_time is None:
                continue
            for render_range in render_ranges:
                source_start = float(render_range["source_start_time"])
                source_end = float(render_range["source_end_time"])
                if source_start <= source_time <= source_end:
                    output_time = float(render_range["output_start_time"]) + (source_time - source_start)
                    render_strategy = (
                        "clip_fade"
                        if transition in {"fade", "dip_to_black"}
                        else "concat_compositor"
                        if _is_supported_concat_transition(transition)
                        else "metadata_only"
                    )
                    events.append({
                        "cue_id": cue.get("id"),
                        "layout": cue.get("layout"),
                        "edge": edge,
                        "transition": transition,
                        "duration_seconds": round(min(transition_duration, float(render_range["duration"]) / 2), 3),
                        "source_time": round(source_time, 3),
                        "output_time": round(output_time, 3),
                        "render_strategy": render_strategy,
                    })
                    break
    return sorted(events, key=lambda item: (item["output_time"], item["cue_id"] or "", item["edge"]))


def _concat_transition_specs(
    transition_events: list[dict],
    clip_durations: list[float],
) -> list[dict]:
    """Map source/output transition metadata to concrete clip boundaries."""
    supported_events = [
        event
        for event in transition_events
        if event.get("render_strategy") == "concat_compositor"
        and _is_supported_concat_transition(str(event.get("transition") or ""))
    ]
    if not supported_events or len(clip_durations) < 2:
        return []

    specs: list[dict] = []
    used_boundaries: set[int] = set()
    cumulative = 0.0
    boundaries = []
    for index, duration in enumerate(clip_durations[:-1]):
        cumulative += max(0.001, float(duration or 0.001))
        boundaries.append((index, cumulative))

    for event in supported_events:
        output_time = _float_value(event.get("output_time"), None)
        if output_time is None:
            continue
        nearest = min(boundaries, key=lambda item: abs(item[1] - output_time), default=None)
        if not nearest:
            continue
        boundary_index, boundary_time = nearest
        if boundary_index in used_boundaries:
            continue
        tolerance = max(0.05, float(event.get("duration_seconds") or 0.0) + 0.05)
        if abs(boundary_time - output_time) > tolerance:
            continue
        specs.append({
            "boundary_index": boundary_index,
            "transition": str(event.get("transition") or "crossfade").lower(),
            "duration_seconds": event.get("duration_seconds") or 0.35,
            "output_time": output_time,
            "cue_id": event.get("cue_id"),
        })
        used_boundaries.add(boundary_index)

    return specs


def _is_supported_concat_transition(transition: str) -> bool:
    return str(transition or "").lower() in {
        "crossfade",
        "wipe",
        "wipe_left",
        "wipe_right",
        "wipe_up",
        "wipe_down",
    }


def _cue_sync_offset(cue: dict | None, role: str, asset: ProjectAsset | None) -> float:
    source = _dict_value(_dict_value(cue).get("sources")).get(role)
    source_offset = _float_value(_dict_value(source).get("sync_offset_seconds"), None)
    asset_offset = float(asset.sync_offset_seconds or 0.0) if asset else 0.0
    if asset_offset:
        return asset_offset
    return source_offset or 0.0


def _selected_export_preset(plan_payload: dict) -> dict:
    metadata = _dict_value(plan_payload.get("export_metadata"))
    selected = _dict_value(metadata.get("selected_preset"))
    if selected:
        return selected

    target_presets = metadata.get("target_presets") or []
    if isinstance(target_presets, list) and target_presets:
        try:
            return get_export_preset(str(target_presets[0]))
        except ValueError:
            return {}
    try:
        return get_export_preset(None)
    except ValueError:
        return {}


def _is_audio_only_export(selected_preset: dict) -> bool:
    return bool(_dict_value(selected_preset).get("audio_only"))


def _audio_export_source(video: Video, layout_context: LayoutRenderContext | None) -> dict:
    if layout_context:
        for cue in layout_context.cues:
            asset = _cue_asset(cue, "audio", layout_context)
            if asset:
                return _audio_source_payload(asset, "layout_audio")

        for key in ("audio", "audio_master", "audio_reference", "separate_audio"):
            asset = layout_context.assets_by_track.get(key) or layout_context.assets_by_role.get(key)
            if asset:
                return _audio_source_payload(asset, "project_audio_asset")

        if layout_context.fallback_audio_asset:
            return _audio_source_payload(layout_context.fallback_audio_asset, "project_audio_asset")

    return {
        "source": "legacy_video_audio",
        "path": video.file_path,
        "asset_id": str(video.project_asset_id) if getattr(video, "project_asset_id", None) else None,
        "sync_offset_seconds": 0.0,
    }


def _audio_source_payload(asset: ProjectAsset, source: str) -> dict:
    return {
        "source": source,
        "path": asset.file_path,
        "asset_id": str(asset.id) if getattr(asset, "id", None) else None,
        "sync_offset_seconds": round(float(getattr(asset, "sync_offset_seconds", 0.0) or 0.0), 3),
    }


def _ffmpeg_audio_bitrate(value: object) -> str:
    text = str(value or "192k").strip().lower().replace(" ", "")
    if text.endswith("kbps"):
        return f"{text[:-4]}k"
    if text.endswith("mbps"):
        return f"{text[:-4]}M"
    if text.endswith("k"):
        return text
    if text.endswith("m"):
        return text
    if text.isdigit():
        return f"{text}k"
    return "192k"


def _ffmpeg_video_bitrate(value: object) -> str | None:
    text = str(value or "").strip().lower().replace(" ", "")
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


def _preset_fps(selected_preset: dict) -> int:
    try:
        return int(selected_preset.get("fps") or 30)
    except (TypeError, ValueError):
        return 30


def _preset_output_dimensions(selected_preset: dict, plan_payload: dict) -> tuple[int, int]:
    try:
        width = int(selected_preset.get("width") or 0)
        height = int(selected_preset.get("height") or 0)
    except (TypeError, ValueError):
        width = 0
        height = 0
    if width > 0 and height > 0:
        return width, height
    return _annotation_canvas_dimensions(plan_payload)


def _expected_concat_duration(clip_durations: list[float], transition_events: list[dict]) -> float:
    total = sum(max(0.0, float(duration or 0.0)) for duration in clip_durations)
    transition_duration = sum(
        max(0.0, float(event.get("duration_seconds") or 0.0))
        for event in transition_events
        if event.get("render_strategy") == "concat_transition"
    )
    return round(max(0.0, total - transition_duration), 3)


def _validate_rendered_video_output(*, metadata: dict, expected_duration: float, output_path: str) -> None:
    if not metadata.get("has_video"):
        raise RuntimeError("Render validation failed: output has no video stream")

    duration = float(metadata.get("duration") or 0.0)
    video_duration = float(metadata.get("video_duration") or metadata.get("duration") or 0.0)
    audio_duration = float(metadata.get("audio_duration") or 0.0)
    frame_count = int(metadata.get("video_frame_count") or 0)
    expected = max(0.0, float(expected_duration or 0.0))
    tolerance = max(1.5, expected * 0.035)

    if expected > 0 and video_duration + tolerance < expected:
        raise RuntimeError(
            "Render validation failed: video stream is too short "
            f"({video_duration:.2f}s video for {expected:.2f}s timeline) in {output_path}"
        )

    if audio_duration > 0 and video_duration > 0 and abs(audio_duration - video_duration) > tolerance:
        raise RuntimeError(
            "Render validation failed: video/audio duration mismatch "
            f"({video_duration:.2f}s video vs {audio_duration:.2f}s audio) in {output_path}"
        )

    if duration > 0 and video_duration > 0 and duration - video_duration > tolerance:
        raise RuntimeError(
            "Render validation failed: container duration exceeds actual video stream "
            f"({duration:.2f}s container vs {video_duration:.2f}s video) in {output_path}"
        )

    if expected > 1.0 and frame_count == 0:
        raise RuntimeError("Render validation failed: output video stream has no counted frames")


def _render_source_duration(video: Video, assets: list[ProjectAsset], plan_payload: dict) -> float:
    candidates: list[float] = []

    def add(value: object) -> None:
        try:
            parsed = float(value or 0.0)
        except (TypeError, ValueError):
            parsed = 0.0
        if parsed > 0:
            candidates.append(parsed)

    add(getattr(video, "duration_seconds", None))
    metadata = _dict_value(plan_payload.get("metadata"))
    add(metadata.get("original_duration"))
    add(metadata.get("duration_seconds"))
    add(_dict_value(plan_payload.get("export_metadata")).get("source_duration_seconds"))
    for cue in _list_of_dicts(plan_payload.get("layout_cues")):
        add(_dict_value(cue).get("end_time"))
    for segment in _list_of_dicts(plan_payload.get("segments")):
        add(_dict_value(segment).get("end_time"))
    for asset in assets:
        add(getattr(asset, "duration_seconds", None))
        add(_dict_value(getattr(asset, "metadata_json", None)).get("duration_seconds"))

    return round(max(candidates or [0.0]), 3)


def _audio_output_extension(selected_preset: dict) -> str:
    extension = str(selected_preset.get("extension") or "").strip()
    if extension.startswith(".") and len(extension) <= 8:
        return extension
    container = str(selected_preset.get("container") or "m4a").strip().lower()
    return ".mp3" if container == "mp3" else ".m4a"


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


def _structure_backed_primary_asset(assets: list[ProjectAsset]) -> ProjectAsset | None:
    has_structure_reference = any(
        _enum_value(getattr(asset, "role", None)) in {"slides", "notes", "supporting_material"}
        or _enum_value(getattr(asset, "kind", None)) in {"slide_deck", "pdf_notes", "text_notes"}
        or _enum_value(getattr(asset, "sync_role", None)) == "structure_reference"
        for asset in assets
    )
    if not has_structure_reference:
        return None
    return _first_asset_with_role(assets, {"primary"})


def _asset_is_generated_slides(asset: object | None) -> bool:
    if not asset:
        return False
    metadata = _dict_value(getattr(asset, "metadata_json", None))
    return bool(metadata.get("generated")) and any(
        _enum_value(value) == "generated_slides"
        for value in (
            getattr(asset, "kind", None),
            getattr(asset, "source_type", None),
            metadata.get("track"),
            metadata.get("timeline_track"),
        )
    )


def _enum_value(value) -> str:
    return str(value.value if hasattr(value, "value") else value or "").lower()


def _dict_value(value) -> dict:
    return dict(value) if isinstance(value, dict) else {}


def _list_of_dicts(value) -> list[dict]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


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


def _annotation_events_for_render_ranges(annotations: list[dict], render_ranges: List[dict]) -> list[dict]:
    events = []
    for annotation in annotations:
        if str(annotation.get("status") or "active") not in {"active", "planned", "applied"}:
            continue
        start = _float_value(annotation.get("start_time"), None)
        end = _float_value(annotation.get("end_time"), None)
        if start is None or end is None or end <= start:
            continue
        for render_range in render_ranges:
            source_start = float(render_range["source_start_time"])
            source_end = float(render_range["source_end_time"])
            overlap_start = max(start, source_start)
            overlap_end = min(end, source_end)
            if overlap_end <= overlap_start:
                continue
            output_start = float(render_range["output_start_time"]) + (overlap_start - source_start)
            output_end = float(render_range["output_start_time"]) + (overlap_end - source_start)
            events.append({
                **annotation,
                "output_start_time": round(output_start, 3),
                "output_end_time": round(output_end, 3),
            })
    return sorted(events, key=lambda item: (item["output_start_time"], item["output_end_time"], item["id"]))


async def _render_end_card_clip(
    *,
    end_card: dict,
    output_path: str,
    clip_dir: str,
    width: int,
    height: int,
    index: int,
    cancel_check=None,
) -> str:
    """Render one appended end-card CTA as a silent video clip."""
    duration = max(2.0, min(15.0, float(end_card.get("duration_seconds") or 6.0)))
    style = _dict_value(end_card.get("style"))
    base_path = os.path.join(clip_dir, f"end_card_base_{index:02d}.mp4")
    ass_path = os.path.join(clip_dir, f"end_card_{index:02d}.ass")
    await ffmpeg_service.create_solid_color_clip(
        base_path,
        duration_seconds=duration,
        width=width,
        height=height,
        background_color=str(style.get("background_color") or "#111827"),
        cancel_check=cancel_check,
    )
    ass_content = _generate_annotation_ass([
        {
            **end_card,
            "output_start_time": 0.0,
            "output_end_time": duration,
            "position": "center",
            "x_percent": 50.0,
            "y_percent": 50.0,
        }
    ], width=width, height=height)
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(ass_content)
    await ffmpeg_service.burn_ass_overlay(base_path, ass_path, output_path, cancel_check=cancel_check)
    return output_path


def _generate_annotation_ass(events: list[dict], *, width: int = 1920, height: int = 1080) -> str:
    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {int(width)}",
        f"PlayResY: {int(height)}",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        "Style: Default,Arial,28,&H00FFFFFF,&H00FFFFFF,&H0038BDF8,&H66111827,0,0,0,0,100,100,0,0,3,2,0,7,20,20,20,1",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for event in events:
        style = _dict_value(event.get("style"))
        is_educational = str(event.get("kind") or "") == "educational_overlay"
        is_end_card = str(event.get("kind") or "") == "end_card"
        font_size = int(_float_value(style.get("font_size"), 28) or 28)
        text_color = _ass_color(style.get("text_color"), "FFFFFF")
        border_color = _ass_color(
            style.get("accent_color") if (is_educational or is_end_card) else style.get("border_color"),
            "38BDF8",
        )
        background_color = _ass_back_color(style.get("background_color"), style.get("opacity"))
        x = int((float(event.get("x_percent") or 50.0) / 100.0) * width)
        y = int((float(event.get("y_percent") or 50.0) / 100.0) * height)
        align = _ass_alignment_for_position(str(event.get("position") or ("center" if (is_educational or is_end_card) else "top_right")))
        if is_end_card:
            label = _end_card_label_text(event)
        else:
            label = _educational_overlay_label_text(event) if is_educational else _annotation_label_text(event)
        border_width = 3 if is_end_card or str(event.get("overlay_type") or "") in {"intro_card", "section_title_card"} else 2
        position_tag, animation_tags = _ass_animation_override(event, x, y)
        override = (
            f"{{\\an{align}{position_tag}\\fs{font_size}\\1c{text_color}"
            f"\\3c{border_color}\\4c{background_color}\\bord{border_width}\\shad0"
            f"{animation_tags}}}"
        )
        lines.append(
            "Dialogue: 0,"
            f"{_format_ass_time(float(event['output_start_time']))},"
            f"{_format_ass_time(float(event['output_end_time']))},"
            f"Default,,0,0,0,,{override}{label}"
        )
    return "\n".join(lines) + "\n"


def _annotation_canvas_dimensions(plan_payload: dict) -> tuple[int, int]:
    for cue in plan_payload.get("layout_cues") or []:
        output = _dict_value(_dict_value(cue).get("output"))
        if output.get("aspect_ratio"):
            return FFmpegService.output_dimensions_for_aspect_ratio(str(output["aspect_ratio"]))
    return FFmpegService.output_dimensions_for_aspect_ratio("16:9")


def _annotation_label_text(event: dict) -> str:
    text = _escape_ass_text(str(event.get("text") or ""))
    pointer = _dict_value(event.get("pointer"))
    if bool(pointer.get("enabled")) and str(event.get("annotation_type") or "") == "callout":
        direction = str(pointer.get("direction") or "left")
        prefix = {"left": "<- ", "right": "-> ", "up": "^ ", "down": "v "}.get(direction, "")
        return f"{prefix}{text}"
    return text


def _educational_overlay_label_text(event: dict) -> str:
    overlay_type = str(event.get("overlay_type") or "chapter_label")
    title = _escape_ass_text(str(event.get("title") or event.get("text") or ""))
    subtitle = _escape_ass_text(str(event.get("subtitle") or ""))
    step_number = event.get("step_number")
    chapter_index = event.get("chapter_index")

    prefix = ""
    if overlay_type == "step_label" and step_number:
        prefix = f"STEP {step_number}: "
    elif overlay_type == "chapter_label" and chapter_index is not None:
        try:
            prefix = f"CHAPTER {int(chapter_index) + 1}: "
        except (TypeError, ValueError):
            prefix = "CHAPTER: "
    elif overlay_type == "section_title_card":
        prefix = "SECTION: "

    if subtitle:
        subtitle_size = int(_float_value(_dict_value(event.get("style")).get("subtitle_font_size"), 22) or 22)
        return f"{prefix}{title}\\N{{\\fs{subtitle_size}}}{subtitle}"
    return f"{prefix}{title}"


def _end_card_label_text(event: dict) -> str:
    style = _dict_value(event.get("style"))
    title = _escape_ass_text(str(event.get("title") or "Lecture Summary"))
    message = _escape_ass_text(str(event.get("message") or ""))
    next_topic = _escape_ass_text(str(event.get("next_topic") or ""))
    course_url = _escape_ass_text(str(event.get("course_url") or ""))
    button_text = _escape_ass_text(str(event.get("button_text") or "Continue"))
    body_size = int(_float_value(style.get("body_font_size"), 24) or 24)
    body_color = _ass_color(style.get("body_color"), "CBD5E1")
    accent_color = _ass_color(style.get("accent_color"), "38BDF8")

    body_lines = []
    for point in event.get("summary_points") or []:
        text = _escape_ass_text(str(point))
        if text:
            body_lines.append(f"{{\\fs{body_size}\\1c{body_color}}}- {text}")
    if message:
        body_lines.append(f"{{\\fs{body_size}\\1c{body_color}}}{message}")
    if next_topic:
        body_lines.append(f"{{\\fs{body_size}\\1c{accent_color}}}Next: {next_topic}")
    if course_url:
        label = f"{button_text}: {course_url}" if button_text else course_url
        body_lines.append(f"{{\\fs{body_size}\\1c{accent_color}}}{label}")

    if body_lines:
        return f"{title}\\N" + "\\N".join(body_lines)
    return title


def _ass_animation_override(event: dict, x: int, y: int) -> tuple[str, str]:
    animation = _dict_value(event.get("animation"))
    preset = str(animation.get("preset") or "fade").lower()
    if preset == "none":
        return f"\\pos({x},{y})", ""

    duration = _float_value(animation.get("duration_seconds"), 0.35) or 0.35
    duration_ms = int(max(80, min(2000, round(duration * 1000))))
    event_duration = max(0.1, float(event.get("output_end_time", 0)) - float(event.get("output_start_time", 0)))
    fade_ms = int(min(duration_ms, max(80, round(event_duration * 1000 / 3))))

    if preset in {"slide_up", "slide_down", "slide_left", "slide_right"}:
        offset = 70
        start_x, start_y = x, y
        if preset == "slide_up":
            start_y = y + offset
        elif preset == "slide_down":
            start_y = y - offset
        elif preset == "slide_left":
            start_x = x + offset
        elif preset == "slide_right":
            start_x = x - offset
        return f"\\move({start_x},{start_y},{x},{y},0,{duration_ms})", f"\\fad({fade_ms},{fade_ms})"

    scale_tags = ""
    if preset == "pop":
        scale_tags = f"\\fscx88\\fscy88\\t(0,{duration_ms},\\fscx100\\fscy100)"
    elif preset == "zoom":
        scale_tags = f"\\fscx96\\fscy96\\t(0,{duration_ms},\\fscx100\\fscy100)"
    return f"\\pos({x},{y})", f"{scale_tags}\\fad({fade_ms},{fade_ms})"


def _ass_alignment_for_position(position: str) -> int:
    return {
        "center": 5,
        "top_left": 7,
        "top_center": 8,
        "top_right": 9,
        "middle_left": 4,
        "middle_center": 5,
        "middle_right": 6,
        "bottom_left": 1,
        "bottom_center": 2,
        "bottom_right": 3,
    }.get(position, 9)


def _format_ass_time(seconds: float) -> str:
    value = max(0.0, float(seconds or 0.0))
    hours = int(value // 3600)
    minutes = int((value % 3600) // 60)
    secs = int(value % 60)
    centis = int(round((value - int(value)) * 100))
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


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


def _ass_back_color(value: object, opacity: object) -> str:
    rgb = _ass_color(value, "111827")
    try:
        opacity_value = float(opacity)
    except (TypeError, ValueError):
        opacity_value = 0.88
    alpha = int(round((1.0 - min(1.0, max(0.2, opacity_value))) * 255))
    return f"&H{alpha:02X}{rgb[4:]}"


def _escape_ass_text(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", "\\N")


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

    artifacts = artifact_records(artifact_paths or {})
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
        "exported_at": _utc_now_iso(),
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

async def _write_evaluation_artifacts(
    *,
    video: Video,
    plan: EditPlan,
    segments: List[Segment],
    transcript: Transcript | None,
    db: AsyncSession,
    plan_export: dict,
    plan_path: str,
    artifact_paths: dict[str, str | None],
    render_metadata: dict | None,
) -> dict:
    quality_report_path = artifact_paths.get("quality_report")
    evidence_json_path = artifact_paths.get("academic_evidence_json")
    evidence_markdown_path = artifact_paths.get("academic_evidence_markdown")

    quality_report = await generate_quality_report(str(video.id), db)
    if quality_report_path:
        write_json_artifact(quality_report_path, quality_report)

    plan_payload = plan_export.get("edit_plan_payload", {})
    before_after_path = artifact_paths.get("before_after_comparison_json")
    timeline_json_path = artifact_paths.get("timeline_decisions_json")
    timeline_csv_path = artifact_paths.get("timeline_decisions_csv")
    provider_mode_path = artifact_paths.get("provider_mode_trace_json")
    metrics_summary_path = artifact_paths.get("metrics_summary_json")
    evidence_index_path = artifact_paths.get("generated_evidence_index_json")
    if before_after_path:
        write_json_artifact(
            before_after_path,
            build_before_after_comparison(
                video=video,
                plan=plan,
                segments=segments,
                plan_payload=plan_payload,
                quality_report=quality_report,
            ),
        )
    if timeline_json_path:
        write_json_artifact(
            timeline_json_path,
            build_timeline_decisions_artifact(
                segments=segments,
                plan_payload=plan_payload,
                quality_report=quality_report,
            ),
        )
    if timeline_csv_path:
        write_csv_artifact(
            timeline_csv_path,
            build_timeline_decision_rows(
                segments=segments,
                plan_payload=plan_payload,
                quality_report=quality_report,
            ),
            TIMELINE_DECISION_CSV_FIELDS,
        )
    if provider_mode_path:
        write_json_artifact(
            provider_mode_path,
            build_provider_mode_trace(
                transcript=transcript,
                plan_payload=plan_payload,
                quality_report=quality_report,
            ),
        )
    if metrics_summary_path:
        write_json_artifact(metrics_summary_path, build_metrics_summary_artifact(quality_report))

    manifest = artifact_records(artifact_paths)
    if evidence_index_path:
        write_json_artifact(evidence_index_path, build_generated_evidence_index(manifest))
        manifest = artifact_records(artifact_paths)
    evidence = build_academic_evidence_artifact(
        video=video,
        plan=plan,
        segments=segments,
        transcript=transcript,
        plan_payload=plan_payload,
        quality_report=quality_report,
        artifact_manifest=manifest,
        render_metadata=render_metadata,
    )
    if evidence_json_path:
        write_json_artifact(evidence_json_path, evidence)
    if evidence_markdown_path:
        write_text_artifact(evidence_markdown_path, build_evidence_markdown(evidence))

    final_manifest = artifact_records(artifact_paths)
    if evidence_index_path:
        write_json_artifact(evidence_index_path, build_generated_evidence_index(final_manifest))
        final_manifest = artifact_records(artifact_paths)
    evidence["artifact_manifest"] = final_manifest
    evidence["generated_evidence_files"] = build_generated_evidence_index(final_manifest)
    if evidence_json_path:
        write_json_artifact(evidence_json_path, evidence)
    if evidence_markdown_path:
        write_text_artifact(evidence_markdown_path, build_evidence_markdown(evidence))

    plan_payload = update_export_metadata(
        plan_export.get("edit_plan_payload", {}),
        artifacts=final_manifest,
        render=render_metadata,
    )
    plan.plan_json = plan_payload
    plan_export["edit_plan_payload"] = plan_payload
    plan_export["export_metadata"] = plan_payload.get("export_metadata", {})
    write_json_artifact(plan_path, plan_export)

    return {
        "quality_report": quality_report,
        "academic_evidence": evidence,
        "artifact_manifest": final_manifest,
    }


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

    result = await db.execute(
        select(Transcript).where(Transcript.video_id == video_id)
    )
    transcript = result.scalar_one_or_none()

    if not plan or not segments:
        return {"error": "No data available"}

    sync_plan = build_synced_timeline_plan(
        plan=plan,
        segments=segments,
        duration_seconds=video.duration_seconds if video else None,
    )
    plan_payload = normalize_plan_payload(plan.plan_json)

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

    evaluation_metrics = build_evaluation_metrics(
        video=video,
        plan=plan,
        segments=segments,
        transcript=transcript,
        plan_payload=plan_payload,
        actual_output_duration_seconds=output_duration,
    )
    evaluation_summary = evaluation_metrics["summary"]

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
        "teacher_override_rate": evaluation_summary["teacher_override_rate"],
        "processing_time_seconds": evaluation_summary["processing_time_seconds"],
        "estimated_cost_usd": evaluation_summary["estimated_cost_usd"],
        "evaluation_metrics": evaluation_metrics,
        "transcript_edit_sync": sync_plan["export_plan"],
        "is_rendered": video.status == VideoStatus.COMPLETED if video else False,
        "output_files": {
            "video": video.processed_video_path if video else None,
            "srt": os.path.join(settings.VIDEO_STORAGE_PATH, f"{video_id}_subtitles.srt"),
            "vtt": os.path.join(settings.VIDEO_STORAGE_PATH, f"{video_id}_subtitles.vtt"),
            "chapters": os.path.join(settings.VIDEO_STORAGE_PATH, f"{video_id}_chapters.txt"),
            "plan_json": os.path.join(settings.VIDEO_STORAGE_PATH, f"{video_id}_edit_plan.json"),
            "quality_report": os.path.join(settings.VIDEO_STORAGE_PATH, f"{video_id}_quality_report.json"),
            "academic_evidence_json": os.path.join(settings.VIDEO_STORAGE_PATH, f"{video_id}_academic_evidence.json"),
            "academic_evidence_markdown": os.path.join(settings.VIDEO_STORAGE_PATH, f"{video_id}_academic_evidence.md"),
            "before_after_comparison": os.path.join(settings.VIDEO_STORAGE_PATH, f"{video_id}_before_after_comparison.json"),
            "timeline_decisions_json": os.path.join(settings.VIDEO_STORAGE_PATH, f"{video_id}_timeline_decisions.json"),
            "timeline_decisions_csv": os.path.join(settings.VIDEO_STORAGE_PATH, f"{video_id}_timeline_decisions.csv"),
            "provider_mode_trace": os.path.join(settings.VIDEO_STORAGE_PATH, f"{video_id}_provider_mode_trace.json"),
            "metrics_summary": os.path.join(settings.VIDEO_STORAGE_PATH, f"{video_id}_metrics_summary.json"),
            "generated_evidence_index": os.path.join(settings.VIDEO_STORAGE_PATH, f"{video_id}_generated_evidence_index.json"),
        },
    }
