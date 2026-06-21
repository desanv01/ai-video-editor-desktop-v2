"""Agent 4 - visual structure analysis for slide/scene cues."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, List, Tuple

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.models import (
    ProjectAsset,
    ProjectAssetStatus,
    Scene,
    Segment,
    Transcript,
    Video,
)
from services.ffmpeg import ffmpeg_service
from services.decision_values import normalize_confidence, normalize_slide_relation
from services.editorial_plan import editorial_blocks_from_slide_timeline

logger = logging.getLogger(__name__)

SCREEN_VALUES = {"screen", "screen_reference", "screen_recording", "screen_video"}
CAMERA_VALUES = {"camera", "camera_overlay", "camera_recording", "webcam_recording", "camera_video"}
STRUCTURE_VALUES = {"slides", "notes", "slide_deck", "pdf_notes", "text_notes", "structure_reference"}
LONG_FORM_PLANNING_SECONDS = 180.0
PLANNING_WINDOW_SECONDS = 120.0
PLANNING_WINDOW_OVERLAP_SECONDS = 25.0
PLANNING_PAGE_CANDIDATES = 5


@dataclass(frozen=True)
class VisualContext:
    assets: list[Any]
    source_roles: set[str]
    structure_reference_count: int
    has_screen_reference: bool
    has_camera_reference: bool
    has_structure_reference: bool


async def run_visual_structure_agent(video_id: str, db: AsyncSession) -> dict:
    """Detect slide/scene changes without letting local CV stall processing."""
    video = await db.get(Video, video_id)
    if not video:
        raise ValueError(f"Video {video_id} not found")
    if not os.path.exists(video.file_path):
        raise FileNotFoundError(f"Video file not found: {video.file_path}")

    context = await _load_visual_context(video, db)

    # ── Scenario A: Camera Video + PDF Slides → semantic slide alignment ──
    if video.project_id and _detect_camera_with_slides(context):
        slide_result = await _run_slide_alignment(video_id, video, db, context)
        if slide_result is not None:
            await _clear_previous_visual_marks(video_id, db)
            await db.flush()
            logger.info(
                "Agent 4: Used PDF slide alignment for video %s — %s",
                video_id,
                slide_result.get("analysis_source", "pdf_slide_alignment"),
            )
            return slide_result
        # If slide alignment returned None (no usable slide deck or pages),
        # fall through to PySceneDetect path below.

    await _clear_previous_visual_marks(video_id, db)

    skip_reason = _scene_detection_skip_reason(video, context)
    if skip_reason:
        await _clear_segment_slide_flags(video_id, db)
        logger.info("Agent 4: Skipped local scene detection for %s: %s", video_id, skip_reason)
        await db.flush()
        return _visual_result(
            status="success",
            scenes_detected=0,
            scene_timestamps=[],
            analysis_source="structure_reference_skip",
            skip_reason=skip_reason,
            context=context,
        )

    logger.info("Agent 4: Starting local scene detection for video %s", video_id)
    scene_list, timed_out = await _detect_scenes_with_timeout(video.file_path)
    if timed_out:
        await _clear_segment_slide_flags(video_id, db)
        await db.flush()
        return _visual_result(
            status="success",
            scenes_detected=0,
            scene_timestamps=[],
            analysis_source="pyscenedetect_timeout_fallback",
            skip_reason="Local PySceneDetect exceeded the Agent 4 timeout and was treated as no detected slide changes.",
            context=context,
        )

    if not scene_list:
        await _clear_segment_slide_flags(video_id, db)
        await db.flush()
        logger.info("Agent 4: No scene changes detected for video %s", video_id)
        return _visual_result(
            status="success",
            scenes_detected=0,
            scene_timestamps=[],
            analysis_source="pyscenedetect",
            context=context,
        )

    scenes_created = await _create_scene_records(video, scene_list, db)
    segments_with_changes = await _mark_segments_for_scenes(video_id, scenes_created, db)
    await db.flush()

    logger.info(
        "Agent 4 complete: %s scenes, %s segment slide marks",
        len(scenes_created),
        segments_with_changes,
    )
    return _visual_result(
        status="success",
        scenes_detected=len(scenes_created),
        scene_timestamps=[round(scene.timestamp, 2) for scene in scenes_created],
        analysis_source="pyscenedetect",
        context=context,
    )


# ─────────────────────────────────────────────────────────────────────
#  Scenario A: PDF Slide Alignment (camera video + uploaded slide deck)
# ─────────────────────────────────────────────────────────────────────


def _detect_camera_with_slides(context: VisualContext) -> bool:
    """Return True when the project looks like camera video + uploaded slides.

    Matches two scenarios:
    1. Camera-style upload: asset has sync_role=camera_overlay or similar
    2. Legacy video upload: asset has role=PRIMARY + a slide deck exists
    """
    has_camera = context.has_camera_reference
    has_primary_video = "primary" in context.source_roles
    has_slides = context.has_structure_reference

    if has_slides:
        return has_camera or has_primary_video
    return False


def _find_slide_deck_asset(context: VisualContext) -> Any | None:
    """Return the first ProjectAsset that can serve as a slide deck (PDF or PPTX)."""
    for asset in context.assets:
        if _asset_matches(asset, STRUCTURE_VALUES):
            # Only consider assets that have a file_path and look like a PDF or PPTX
            path = str(getattr(asset, "file_path", "") or "")
            if path and (path.lower().endswith(".pdf") or path.lower().endswith(".pptx")):
                return asset
    return None


async def _run_slide_alignment(
    video_id: str,
    video: Video,
    db: AsyncSession,
    context: VisualContext,
) -> dict | None:
    """Match transcript segments to PDF slide pages via semantic similarity.

    Returns None when slide alignment is not possible (no usable slide deck,
    no pages extracted, no segments, etc.) so the caller can fall back to
    PySceneDetect.
    """
    # 1. Find the slide deck asset ------------------------------------------
    slide_asset = _find_slide_deck_asset(context)
    if slide_asset is None:
        logger.debug("Agent 4: No usable slide deck asset found for video %s", video_id)
        return None

    file_path = str(getattr(slide_asset, "file_path", "") or "")
    if not file_path or not os.path.isfile(file_path):
        logger.warning("Agent 4: Slide deck file not found at %s", file_path)
        return None

    is_pptx = file_path.lower().endswith(".pptx")

    # 2. Extract pages (PDF or PPTX) ----------------------------------------
    output_dir = os.path.join(settings.VIDEO_STORAGE_PATH, f"slides_{video.id}")
    os.makedirs(output_dir, exist_ok=True)

    try:
        if is_pptx:
            from services.pptx_slides import pptx_slide_service

            pages = await pptx_slide_service.extract_pptx_pages(file_path, output_dir, dpi=300)
        else:
            from services.pdf_slides import pdf_slide_service

            pages = await pdf_slide_service.extract_pdf_pages(file_path, output_dir, dpi=300)
    except Exception as exc:
        logger.error("Agent 4: Slide extraction failed for %s: %s", file_path, exc)
        return None

    if not pages:
        logger.info("Agent 4: No pages extracted from slide deck %s", file_path)
        return None

    ext_label = "PPTX" if is_pptx else "PDF"
    document_preflight = _document_preflight(pages, document_format=ext_label.lower())
    if document_preflight["status"] != "ready":
        logger.warning("Agent 4: %s preflight warning for %s: %s", ext_label, file_path, document_preflight)
    logger.info("Agent 4: Extracted %d pages from %s slide deck for video %s", len(pages), ext_label, video_id)

    # 3. Load transcript segments and word timestamps ------------------------
    result = await db.execute(
        select(Segment)
        .where(Segment.video_id == video_id)
        .order_by(Segment.segment_index)
    )
    segments = list(result.scalars().all())
    for segment in segments:
        segment.has_slide_change = False
        segment.slide_index = None
        segment.scene_id = None

    transcript_result = await db.execute(
        select(Transcript).where(Transcript.video_id == video_id)
    )
    transcript = transcript_result.scalar_one_or_none()
    timed_words = list(transcript.words_json or []) if transcript else []

    if not segments:
        logger.info("Agent 4: No transcript segments found for video %s — skipping alignment", video_id)
        return {
            "status": "success",
            "scenes_detected": 0,
            "scene_timestamps": [],
            "analysis_source": "pdf_slide_alignment",
            "slides_detected": len(pages),
            "segments_matched": 0,
            "document_preflight": document_preflight,
            "structure_reference_count": context.structure_reference_count,
            "vision_provider": _vision_provider_id(),
        }

    # ── LLM-based matching (attempted first) ────────────────────────────────
    try:
        manual_scope = _page_scope_from_asset(slide_asset, len(pages))
        llm_result = await _llm_slide_matching(
            segments,
            pages,
            video_id,
            timed_words=timed_words,
            manual_scope=manual_scope,
        )
        if llm_result and isinstance(llm_result.get("slide_timeline"), list) and len(llm_result["slide_timeline"]) > 0:
            resolved_scope = manual_scope or _scope_from_llm_result(llm_result, len(pages))
            timeline = _normalize_llm_slide_timeline(
                llm_result["slide_timeline"],
                duration=max(float(segment.end_time or 0.0) for segment in segments),
                slide_count=len(pages),
                allowed_slide_indices=_scope_indices(resolved_scope),
            )
            chunks = _semantic_chunks(segments, timed_words=timed_words)
            if resolved_scope is None:
                resolved_scope = _infer_contiguous_scope(timeline, len(pages))
            editorial_blocks = editorial_blocks_from_slide_timeline(
                timeline,
                duration_seconds=max(float(segment.end_time or 0.0) for segment in segments),
                slide_count=len(pages),
            )
            timeline = _slide_timeline_from_editorial_blocks(editorial_blocks)
            # ── Enforce monotonic slide progression ──────────────────────
            timeline.sort(key=lambda x: x.get("start_time", 0))
            # Build per-segment primary slide from timeline
            current_page: int | None = None
            matched_count = 0

            for segment in segments:
                # Find all timeline entries that fall within this segment's time range
                seg_start = segment.start_time
                seg_end = segment.end_time

                relevant = [
                    item for item in timeline
                    if max(seg_start, item["start_time"]) < min(seg_end, item["end_time"])
                ]

                if relevant:
                    # Use the LAST timeline entry in the segment — ensures
                    # every entry maps to SOME segment and no slide is lost
                    primary_slide = max(
                        relevant,
                        key=lambda item: min(seg_end, item["end_time"]) - max(seg_start, item["start_time"]),
                    )["slide_index"]
                elif timeline:
                    # Segment has no direct timeline entries — use closest previous time point
                    before = [item for item in timeline if item["start_time"] <= seg_start]
                    primary_slide = before[-1]["slide_index"] if before else None
                else:
                    primary_slide = None

                if primary_slide is not None:
                    primary_slide = max(0, min(int(primary_slide), len(pages) - 1))
                    if primary_slide != current_page:
                        segment.has_slide_change = True if current_page is not None else False
                        current_page = primary_slide
                    else:
                        segment.has_slide_change = False

                    segment.slide_index = current_page
                    segment.scene_id = f"slide_{current_page}"
                    matched_count += 1

            await db.flush()
            logger.info(
                "Agent 4: LLM slide timeline matched %d/%d segments for video %s",
                matched_count,
                len(segments),
                video_id,
            )
            # ── Distribute any unused slides ────────────────────────────
            return {
                "status": "success",
                "scenes_detected": 0,
                "scene_timestamps": [],
                "analysis_source": "llm_slide_timeline",
                "planning_status": str(llm_result.get("planning_status") or "verified"),
                "planning_warnings": list(llm_result.get("planning_warnings") or []),
                "degraded_reason": llm_result.get("degraded_reason"),
                "slides_detected": len(pages),
                "segments_matched": matched_count,
                "slide_timeline": timeline,
                "editorial_blocks": editorial_blocks,
                "slide_scope": _scope_payload(resolved_scope, source="manual" if manual_scope else "automatic"),
                "document_preflight": document_preflight,
                "slide_assets": [
                    {"slide_index": index, "image_path": page.get("image_path"), "text": page.get("text", "")}
                    for index, page in enumerate(pages)
                ],
                "structure_reference_count": context.structure_reference_count,
                "vision_provider": _vision_provider_id(),
            }
    except Exception as exc:
        logger.warning(
            "Agent 4: LLM slide matching attempt failed, falling back to linear: %s", exc
        )

    # 4. Linear fallback — evenly distribute slides across segments
    #    Simple but guaranteed to cover all slides in order.
    #    Never regresses, never bounces, never skips pages entirely.
    manual_scope = _page_scope_from_asset(slide_asset, len(pages))
    fallback_timeline = _token_slide_timeline(
        segments,
        pages,
        timed_words=timed_words,
        allowed_slide_indices=_scope_indices(manual_scope),
    )
    inferred_scope = manual_scope or _infer_contiguous_scope(fallback_timeline, len(pages))
    fallback_timeline = _stabilize_slide_timeline(
        fallback_timeline,
        chunks=_semantic_chunks(segments, timed_words=timed_words),
        allowed_slide_indices=_scope_indices(inferred_scope),
    )
    fallback_blocks = editorial_blocks_from_slide_timeline(
        fallback_timeline,
        duration_seconds=max(float(segment.end_time or 0.0) for segment in segments),
        slide_count=len(pages),
    )
    fallback_timeline = _slide_timeline_from_editorial_blocks(fallback_blocks)
    matched_count = 0
    current_page = None

    for segment in segments:
        candidates = [
            item for item in fallback_timeline
            if max(segment.start_time, item["start_time"]) < min(segment.end_time, item["end_time"])
        ]
        slide_idx = max(candidates, key=lambda item: item["confidence"])["slide_index"] if candidates else None

        if slide_idx is not None:
            if slide_idx != current_page:
                segment.has_slide_change = True if current_page is not None else False
                current_page = slide_idx
            else:
                segment.has_slide_change = False

            segment.slide_index = slide_idx
            segment.scene_id = f"slide_{slide_idx}"
            matched_count += 1

    await db.flush()

    logger.info(
        "Agent 4: Linear fallback matched %d/%d segments for video %s",
        matched_count, len(segments), video_id,
    )

    return {
        "status": "success",
        "scenes_detected": 0,
        "scene_timestamps": [],
        "analysis_source": "agent4_semantic_fallback",
        "planning_status": "degraded",
        "planning_warnings": ["DeepSeek slide planning failed; local semantic matching needs teacher review."],
        "degraded_reason": "deepseek_slide_planning_unavailable",
        "slides_detected": len(pages),
        "segments_matched": matched_count,
        "slide_timeline": fallback_timeline,
        "editorial_blocks": fallback_blocks,
        "slide_scope": _scope_payload(inferred_scope, source="manual" if manual_scope else "automatic"),
        "document_preflight": document_preflight,
        "slide_assets": [
            {"slide_index": index, "image_path": page.get("image_path"), "text": page.get("text", "")}
            for index, page in enumerate(pages)
        ],
        "structure_reference_count": context.structure_reference_count,
        "vision_provider": _vision_provider_id(),
    }


async def _llm_slide_matching(
    segments: list,
    pages: list[dict],
    video_id: str,
    *,
    timed_words: list[dict[str, Any]] | None = None,
    manual_scope: tuple[int, int] | None = None,
) -> dict | None:
    """Match speech to slides, using resumable rolling windows for long lectures."""
    from services.llm import llm_service

    if not segments or not pages:
        logger.warning("Agent 4: LLM matching aborted — empty segments or slides for video %s", video_id)
        return None

    system_msg = (
        "You are matching lecture slides to specific TIMESTAMPS in a recorded lecture video. "
        "Your task: create a timeline of when each slide should appear.\n\n"
        "The video has transcript SEGMENTS with start/end times and text content.\n"
        "The lecture has SLIDES with text content.\n\n"
        "Rules:\n"
        "1. Every slide (0 through N-1) MUST appear at least once — do NOT skip any slide.\n"
        "2. A slide CAN appear for multiple time ranges (lecturer refers back to it).\n"
        "3. Slide transitions should happen at NATURAL topic boundaries in the lecture.\n"
        "4. Time values must be in seconds, from 0.0 to the video total duration.\n"
        "5. The first time point should be at 0.0 seconds.\n"
        "6. Cover the ENTIRE lecture — slides should change as the lecturer moves through topics.\n"
        "7. When a segment covers multiple topics, insert slide transitions mid-segment.\n\n"
        "Output format (valid JSON only):\n"
        '{"slide_timeline": [{"time_seconds": 0.0, "slide_index": 0, "reason": "brief reason"}, ...]}'
    )

    scope_rule = (
        f"Only slides {manual_scope[0]} through {manual_scope[1]} are assigned to this video. "
        if manual_scope is not None
        else "First identify the smallest contiguous slide range that belongs to this video; the deck may be shared by several recordings. "
    )
    system_msg = (
        "You create a semantic editorial plan from a lecturer's timestamped speech and slide deck. "
        + scope_rule
        + "Create coherent blocks that follow complete sentences and topic boundaries. First decide whether the speech "
        "is genuinely related to any slide. Greetings, scheduling, attendance, housekeeping, and unrelated examples "
        "must use slide_index null unless a candidate page explicitly covers them. Use neighboring speech and explicit "
        "navigation phrases as context, but do not expose anchor/excursion state as the plan. Merge adjacent speech chunks "
        "when they form one teaching idea and keep the same slide and layout. Blocks may last 20-90 seconds when coherent. "
        "Do not force every page to appear and never reuse a previous slide because no better page exists. Use slide_index "
        "null and layout full_camera_source when no page is relevant. Choose picture_in_picture for most slide-related "
        "teaching, side_by_side only when lecturer and slide need equal attention, and full_screen_source sparingly for "
        "visually critical content. confidence MUST be a JSON number from 0.0 to 1.0, never a word such as high or low. "
        "slide_relation MUST be related, unrelated, or uncertain. Return JSON only with page_scope and slide_timeline. Each item must include start_time, "
        "end_time, block_title, summary, transcript_excerpt, slide_index, slide_relevance (none, partial, direct, critical), "
        "slide_relation, layout (full_camera_source, picture_in_picture, side_by_side, full_screen_source), confidence, cue_type, and reason."
    )

    video_duration = max(s.end_time for s in segments) if segments else 0

    chunks = _semantic_chunks(segments, timed_words=timed_words)
    if video_duration > LONG_FORM_PLANNING_SECONDS or len(chunks) > 12:
        return await _llm_slide_matching_rolling(
            llm_service,
            chunks,
            pages,
            video_id,
            duration=video_duration,
            manual_scope=manual_scope,
        )
    segment_lines = [
        f"  [{chunk['id']}] {chunk['start_time']:.1f}s-{chunk['end_time']:.1f}s\n"
        f"    CURRENT: {chunk['text']}\n"
        f"    BEFORE: {chunk.get('context_before') or '(none)'}\n"
        f"    LOOKAHEAD: {chunk.get('context_after') or '(none)'}\n"
        f"    SIGNALS: {', '.join(chunk.get('signals') or []) or 'none'}"
        for chunk in chunks
    ]

    user_msg = (
        f"LECTURE DURATION: 0.0 to {video_duration:.0f} seconds\n\n"
        f"SPEECH CHUNKS ({len(chunks)}):\n" + "\n".join(segment_lines) + "\n\n"
        f"SLIDES ({len(pages)}):\n" + "\n".join(
            f"  Slide [{i}]: {(p.get('text') or '')[:1800]}"
            for i, p in enumerate(pages)
        ) + "\n\n"
        "Create coherent sentence/topic editorial blocks. Slide indexes are zero-based. Return JSON only."
    )

    messages: list[dict] = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": user_msg},
    ]

    last_issues: list[str] = []
    for attempt in range(2):
        try:
            attempt_messages = list(messages)
            if attempt and last_issues:
                attempt_messages.append({
                    "role": "user",
                    "content": "Correct the previous plan. Problems: " + "; ".join(last_issues[:6]) + ". Return complete valid JSON only.",
                })
            result = await llm_service.chat_json(
                messages=attempt_messages,
                temperature=0.1,
                max_tokens=8192,
            )
            timeline = result.get("slide_timeline") if isinstance(result, dict) else None
            last_issues = _timeline_response_issues(
                timeline,
                duration=video_duration,
                slide_count=len(pages),
                allowed_slide_indices=_scope_indices(manual_scope),
            )
            if isinstance(timeline, list) and timeline and not last_issues:
                result["planning_status"] = "verified"
                result["planning_warnings"] = []
                logger.info("Agent 4: LLM returned verified slide timeline with %d entries for video %s", len(timeline), video_id)
                return result
            logger.warning("Agent 4: LLM plan validation attempt %d failed for video %s: %s", attempt + 1, video_id, last_issues)
        except Exception as exc:
            last_issues = [str(exc)]
            logger.warning("Agent 4: LLM slide matching attempt %d failed for video %s: %s", attempt + 1, video_id, exc)
    return None


# ─────────────────────────────────────────────────────────────────────
#  Scenario B: Original PySceneDetect fallback (unchanged below)
# ─────────────────────────────────────────────────────────────────────


async def _llm_slide_matching_rolling(
    llm_service: Any,
    chunks: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    video_id: str,
    *,
    duration: float,
    manual_scope: tuple[int, int] | None,
) -> dict | None:
    """Plan long lectures in resumable windows instead of one oversized request."""
    windows = _planning_windows(chunks)
    if not windows:
        return None

    signature = _planning_signature(chunks, pages, manual_scope)
    checkpoint = _load_planning_checkpoint(video_id, signature)
    merged = list(checkpoint.get("slide_timeline") or []) if checkpoint else []
    completed_window = int(checkpoint.get("completed_window", -1)) if checkpoint else -1
    anchor = checkpoint.get("anchor_slide_index") if checkpoint else None
    degraded_windows: list[int] = []
    allowed = _scope_indices(manual_scope) or set(range(len(pages)))
    system_msg = _rolling_planner_system_message(manual_scope)

    for window_index, window in enumerate(windows):
        if window_index <= completed_window:
            continue
        candidates = _shortlist_pages_for_window(window["chunks"], pages, allowed, anchor)
        result: dict[str, Any] | None = None
        for attempt in range(2):
            try:
                candidate_result = await llm_service.chat_json(
                    messages=[
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": _window_user_message(window, pages, candidates, anchor, duration)},
                    ],
                    temperature=0.1,
                    max_tokens=4096,
                )
                timeline = candidate_result.get("slide_timeline") if isinstance(candidate_result, dict) else None
                issues = _timeline_response_issues(
                    timeline,
                    duration=float(window["end_time"]),
                    slide_count=len(pages),
                    allowed_slide_indices=set(candidates),
                )
                if isinstance(timeline, list) and timeline and not issues:
                    result = candidate_result
                    break
                logger.warning(
                    "Agent 4: rolling window %d validation attempt %d failed: %s",
                    window_index + 1,
                    attempt + 1,
                    issues,
                )
            except Exception as exc:
                logger.warning(
                    "Agent 4: rolling window %d attempt %d failed for video %s: %s",
                    window_index + 1,
                    attempt + 1,
                    video_id,
                    exc,
                )

        raw_window = list(result.get("slide_timeline") or []) if result else []
        if not raw_window:
            degraded_windows.append(window_index + 1)
            raw_window = _token_match_window_timeline(window["chunks"], pages, candidates)
        cutover = (
            float(window["start_time"])
            if window_index == 0
            else float(window["start_time"]) + (PLANNING_WINDOW_OVERLAP_SECONDS / 2)
        )
        merged = _merge_window_timelines(merged, raw_window, cutover=cutover)
        anchor = _last_slide_index(merged, anchor)
        _save_planning_checkpoint(
            video_id,
            {
                "signature": signature,
                "completed_window": window_index,
                "anchor_slide_index": anchor,
                "slide_timeline": merged,
            },
        )

    if not merged:
        return None
    scope = manual_scope or _infer_contiguous_scope(merged, len(pages))
    logger.info(
        "Agent 4: rolling planner completed %d windows and %d cues for video %s",
        len(windows),
        len(merged),
        video_id,
    )
    return {
        "page_scope": _scope_payload(scope, source="manual" if manual_scope else "automatic"),
        "slide_timeline": merged,
        "planning_status": "degraded" if degraded_windows else "verified",
        "planning_warnings": [f"Local semantic fallback used for planning window {index}." for index in degraded_windows],
        "degraded_reason": "deepseek_window_fallback" if degraded_windows else None,
    }


def _rolling_planner_system_message(manual_scope: tuple[int, int] | None) -> str:
    scope_rule = (
        f"Only slides {manual_scope[0]} through {manual_scope[1]} are assigned to this video. "
        if manual_scope is not None
        else "Use only genuinely relevant candidate slides from the shared deck. "
    )
    return (
        "You create coherent editorial blocks for one rolling window of timestamped lecture speech. "
        + scope_rule
        + "Follow complete sentence and topic boundaries. First apply a relevance gate. Greetings, scheduling, attendance, housekeeping, and unrelated examples use "
        "slide_index null unless a candidate slide explicitly covers the speech. Never keep a stale slide visible. "
        "Use neighboring speech for context, but do not expose anchor/excursion state. Merge adjacent chunks when topic, "
        "slide, and layout remain coherent. Choose full_camera_source for unrelated speech, picture_in_picture for most "
        "matched teaching, side_by_side occasionally, and full_screen_source only for critical visual detail. Preserve "
        "timestamps. Return JSON only with slide_timeline entries containing start_time, end_time, block_title, summary, "
        "transcript_excerpt, slide_index, slide_relevance, slide_relation, layout, confidence, cue_type, and reason. "
        "confidence must be a JSON number from 0.0 to 1.0, never a label."
    )


def _planning_windows(
    chunks: list[dict[str, Any]],
    *,
    window_seconds: float = PLANNING_WINDOW_SECONDS,
    overlap_seconds: float = PLANNING_WINDOW_OVERLAP_SECONDS,
) -> list[dict[str, Any]]:
    if not chunks:
        return []
    start = float(chunks[0]["start_time"])
    final_end = float(chunks[-1]["end_time"])
    windows: list[dict[str, Any]] = []
    while start < final_end:
        end = min(final_end, start + window_seconds)
        selected = [
            chunk for chunk in chunks
            if float(chunk["end_time"]) > start and float(chunk["start_time"]) < end
        ]
        if selected:
            windows.append({"start_time": start, "end_time": end, "chunks": selected})
        if end >= final_end:
            break
        start = max(start + 1.0, end - overlap_seconds)
    return windows


def _shortlist_pages_for_window(
    chunks: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    allowed: set[int],
    anchor: int | None,
    *,
    limit: int = PLANNING_PAGE_CANDIDATES,
) -> list[int]:
    speech_terms = _semantic_terms(" ".join(str(chunk.get("text") or "") for chunk in chunks))
    ranked = sorted(
        (
            (len(speech_terms & _semantic_terms(page.get("text") or "")), index)
            for index, page in enumerate(pages)
            if index in allowed
        ),
        reverse=True,
    )
    selected = [index for score, index in ranked if score > 0][:limit]
    neighbors = (anchor, anchor - 1 if anchor is not None else None, anchor + 1 if anchor is not None else None)
    for index in neighbors:
        if index is not None and index in allowed and index not in selected:
            selected.append(index)
    if not selected:
        selected = sorted(allowed)[:limit]
    return selected[: max(limit, 3)]


def _window_user_message(
    window: dict[str, Any],
    pages: list[dict[str, Any]],
    candidates: list[int],
    anchor: int | None,
    duration: float,
) -> str:
    chunk_lines = [
        f"[{chunk['id']}] {chunk['start_time']:.1f}-{chunk['end_time']:.1f}s CURRENT: {chunk['text']} "
        f"BEFORE: {chunk.get('context_before') or '(none)'} LOOKAHEAD: {chunk.get('context_after') or '(none)'} "
        f"SIGNALS: {', '.join(chunk.get('signals') or []) or 'none'}"
        for chunk in window["chunks"]
    ]
    page_lines = [f"Slide [{index}]: {(pages[index].get('text') or '')[:2400]}" for index in candidates]
    return (
        f"LECTURE DURATION: 0-{duration:.1f}s\nWINDOW: {window['start_time']:.1f}-{window['end_time']:.1f}s\n"
        f"CURRENT ANCHOR: {anchor if anchor is not None else 'none'}\n\nSPEECH CHUNKS:\n"
        + "\n".join(chunk_lines)
        + "\n\nCANDIDATE SLIDES:\n"
        + "\n".join(page_lines)
        + "\n\nReturn coherent editorial blocks only for this window. Candidate indexes are absolute deck indexes. "
        "Use null plus full_camera_source for unrelated speech."
    )


def _token_match_window_timeline(
    chunks: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    candidates: list[int],
) -> list[dict[str, Any]]:
    page_terms = {index: _semantic_terms(pages[index].get("text") or "") for index in candidates}
    timeline: list[dict[str, Any]] = []
    for chunk in chunks:
        terms = _semantic_terms(chunk.get("text") or "")
        scored = sorted(
            ((len(terms & page_terms[index]) / max(6, len(terms)), index) for index in candidates),
            reverse=True,
        )
        score, slide_index = scored[0] if scored else (0.0, None)
        overlap_count = len(terms & page_terms[slide_index]) if slide_index is not None else 0
        relevant = slide_index is not None and score >= 0.075 and overlap_count >= 2
        timeline.append({
            "id": f"rolling-fallback-{chunk['id']}",
            "start_time": chunk["start_time"],
            "end_time": chunk["end_time"],
            "slide_index": slide_index if relevant else None,
            "confidence": round(score, 3),
            "cue_type": "semantic_block" if relevant else "lecturer_only",
            "reason": "Local shortlist match" if relevant else "No relevant shortlisted slide",
            "strategy": "rolling_token_fallback",
            "block_title": "Matched lecture topic" if relevant else "Lecturer context",
            "summary": str(chunk.get("text") or "")[:900],
            "transcript_excerpt": str(chunk.get("text") or "")[:1800],
            "slide_relevance": "direct" if relevant else "none",
            "slide_relation": "related" if relevant else "unrelated",
            "review_required": True,
            "planning_status": "degraded",
            "layout": "picture_in_picture" if relevant else "full_camera_source",
        })
    return timeline


def _merge_window_timelines(
    existing: list[dict[str, Any]],
    incoming: list[dict[str, Any]],
    *,
    cutover: float,
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for item in existing:
        start = float(item.get("start_time", item.get("time_seconds", 0.0)) or 0.0)
        end = float(item.get("end_time", start) or start)
        if start < cutover:
            copied = dict(item)
            copied["end_time"] = min(end, cutover)
            if copied["end_time"] - start >= 0.05:
                merged.append(copied)
    for item in incoming:
        start = float(item.get("start_time", item.get("time_seconds", 0.0)) or 0.0)
        end = float(item.get("end_time", start) or start)
        if end > cutover:
            copied = dict(item)
            copied["start_time"] = max(start, cutover)
            if end - copied["start_time"] >= 0.05:
                merged.append(copied)
    return sorted(merged, key=lambda item: float(item.get("start_time", 0.0) or 0.0))


def _last_slide_index(timeline: list[dict[str, Any]], fallback: int | None) -> int | None:
    for item in reversed(timeline):
        if item.get("slide_index") is not None:
            try:
                return int(item["slide_index"])
            except (TypeError, ValueError):
                continue
    return fallback


def _planning_signature(
    chunks: list[dict[str, Any]],
    pages: list[dict[str, Any]],
    manual_scope: tuple[int, int] | None,
) -> str:
    payload = {
        "chunks": [(chunk.get("start_time"), chunk.get("end_time"), chunk.get("text")) for chunk in chunks],
        "pages": [page.get("text") or "" for page in pages],
        "scope": manual_scope,
        "version": 3,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def _planning_checkpoint_path(video_id: str) -> str:
    safe_id = re.sub(r"[^a-zA-Z0-9_.-]", "_", str(video_id))
    return os.path.join(settings.TEMP_PATH, "slide_planning", f"{safe_id}.json")


def _load_planning_checkpoint(video_id: str, signature: str) -> dict[str, Any] | None:
    path = _planning_checkpoint_path(video_id)
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        return payload if payload.get("signature") == signature else None
    except (OSError, ValueError, TypeError):
        return None


def _save_planning_checkpoint(video_id: str, payload: dict[str, Any]) -> None:
    path = _planning_checkpoint_path(video_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=True)
    os.replace(temp_path, path)


def _semantic_chunks(
    segments: list,
    *,
    timed_words: list[dict[str, Any]] | None = None,
    target_seconds: float = 30.0,
    min_seconds: float = 8.0,
    max_seconds: float = 45.0,
) -> list[dict[str, Any]]:
    """Build sentence-aware speech chunks and attach neighboring context.

    Word timestamps are authoritative when available. The segment-based path is
    retained for providers that only return coarse transcript timestamps.
    """
    words = _normalized_timed_words(timed_words or [])
    if words:
        chunks = _chunks_from_timed_words(
            words,
            target_seconds=target_seconds,
            min_seconds=min_seconds,
            max_seconds=max_seconds,
        )
    else:
        chunks = _chunks_from_segments(segments, target_seconds=target_seconds)
    return _attach_chunk_context(chunks)


def _normalized_timed_words(raw_words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    words: list[dict[str, Any]] = []
    for item in raw_words:
        if not isinstance(item, dict):
            continue
        text = str(item.get("word", item.get("text", "")) or "").strip()
        if not text:
            continue
        try:
            start = float(item.get("start", item.get("start_time", 0.0)) or 0.0)
            end = float(item.get("end", item.get("end_time", start)) or start)
        except (TypeError, ValueError):
            continue
        if end < start:
            end = start
        words.append({"text": text, "start": start, "end": end})
    return sorted(words, key=lambda item: (item["start"], item["end"]))


def _chunks_from_timed_words(
    words: list[dict[str, Any]],
    *,
    target_seconds: float,
    min_seconds: float,
    max_seconds: float,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    for word_index, word in enumerate(words):
        current.append(word)
        duration = current[-1]["end"] - current[0]["start"]
        sentence_end = bool(re.search(r"[.!?][\"')\]]?$", current[-1]["text"]))
        next_word = words[word_index + 1] if word_index + 1 < len(words) else None
        next_gap = max(0.0, next_word["start"] - current[-1]["end"]) if next_word else max_seconds
        natural_boundary = sentence_end or next_gap >= 0.65
        soft_boundary = sentence_end or next_gap >= 0.28
        should_close = (
            duration >= max_seconds
            or (duration >= min_seconds and natural_boundary)
            or (duration >= target_seconds and soft_boundary)
        )
        if should_close:
            chunks.append(_timed_word_chunk(current, len(chunks) + 1))
            current = []
    if current:
        if chunks and current[-1]["end"] - current[0]["start"] < min_seconds:
            previous = chunks.pop()
            combined = previous.pop("_words") + current
            chunks.append(_timed_word_chunk(combined, len(chunks) + 1))
        else:
            chunks.append(_timed_word_chunk(current, len(chunks) + 1))
    for chunk in chunks:
        chunk.pop("_words", None)
    return chunks


def _timed_word_chunk(words: list[dict[str, Any]], index: int) -> dict[str, Any]:
    text = " ".join(word["text"] for word in words).strip()
    return {
        "id": f"word-{index:04d}",
        "start_time": round(words[0]["start"], 3),
        "end_time": round(words[-1]["end"], 3),
        "text": text[:1800],
        "signals": _navigation_signals(text),
        "_words": list(words),
    }


def _chunks_from_segments(segments: list, *, target_seconds: float) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for segment in segments:
        start = float(segment.start_time or 0.0)
        end = float(segment.end_time or start)
        if end <= start:
            continue
        words = str(segment.text or segment.summary or "").split()
        count = max(1, int(((end - start) + target_seconds - 0.001) // target_seconds))
        chunk_duration = (end - start) / count
        for index in range(count):
            chunk_start = start + chunk_duration * index
            chunk_end = end if index == count - 1 else start + chunk_duration * (index + 1)
            word_start = int(len(words) * index / count)
            word_end = int(len(words) * (index + 1) / count)
            text = " ".join(words[word_start:word_end])[:1800]
            chunks.append({
                "id": f"{segment.segment_index}-{index + 1}",
                "start_time": round(chunk_start, 3),
                "end_time": round(chunk_end, 3),
                "text": text,
                "signals": _navigation_signals(text),
            })
    return chunks


def _attach_chunk_context(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    for index, chunk in enumerate(chunks):
        chunk["context_before"] = chunks[index - 1]["text"][-700:] if index > 0 else ""
        chunk["context_after"] = chunks[index + 1]["text"][:900] if index + 1 < len(chunks) else ""
    return chunks


def _navigation_signals(text: str) -> list[str]:
    lowered = text.lower()
    patterns = {
        "advance": ("next slide", "moving on", "move on", "next page", "now we will", "after this"),
        "return": ("go back", "back to", "return to", "as shown earlier", "previous slide", "previous page"),
        "reference": ("later", "we will see", "we will discuss", "as you can see"),
    }
    return [name for name, phrases in patterns.items() if any(phrase in lowered for phrase in phrases)]


def _normalize_llm_slide_timeline(
    raw: list,
    *,
    duration: float,
    slide_count: int,
    allowed_slide_indices: set[int] | None = None,
) -> list[dict[str, Any]]:
    items = [dict(item) for item in raw if isinstance(item, dict)]
    items.sort(key=lambda item: _safe_float(item.get("start_time", item.get("time_seconds", 0.0)), 0.0))
    normalized: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        start = max(0.0, _safe_float(item.get("start_time", item.get("time_seconds", 0.0)), 0.0))
        next_start = (
            _safe_float(items[index + 1].get("start_time", items[index + 1].get("time_seconds", duration)), duration)
            if index + 1 < len(items)
            else duration
        )
        end = min(duration, max(start, _safe_float(item.get("end_time", next_start), next_start)))
        raw_slide = item.get("slide_index")
        try:
            slide_index = int(raw_slide) if raw_slide is not None else None
        except (TypeError, ValueError):
            slide_index = None
        if slide_index is not None and (
            not 0 <= slide_index < slide_count
            or (allowed_slide_indices is not None and slide_index not in allowed_slide_indices)
        ):
            slide_index = None
        confidence = normalize_confidence(item.get("confidence"), 0.5)
        relevance = str(item.get("slide_relevance") or ("direct" if slide_index is not None else "none")).lower()
        relation = normalize_slide_relation(item.get("slide_relation"), slide_index=slide_index, relevance=relevance)
        candidate_slide_index = slide_index
        review_required = relation == "uncertain"
        if relation != "related":
            slide_index = None
        if end - start >= 0.05:
            normalized.append({
                "id": str(item.get("id") or f"agent4-slide-cue-{index + 1:04d}"),
                "start_time": round(start, 3),
                "end_time": round(end, 3),
                "slide_index": slide_index,
                "candidate_slide_index": candidate_slide_index if review_required else None,
                "confidence": round(confidence, 3),
                "strategy": "deepseek_semantic_rerank",
                "reason": str(item.get("reason") or "Semantic page match"),
                "cue_type": "lecturer_only" if slide_index is None else "semantic_block",
                "block_title": str(item.get("block_title") or item.get("title") or "Lecture content")[:160],
                "summary": str(item.get("summary") or "")[:900],
                "transcript_excerpt": str(item.get("transcript_excerpt") or item.get("text") or "")[:1800],
                "slide_relevance": relevance if slide_index is not None else "none",
                "slide_relation": relation,
                "review_required": review_required,
                "planning_status": "needs_review" if review_required else "verified",
                "layout": str(item.get("layout") or ("picture_in_picture" if slide_index is not None else "full_camera_source")).lower(),
            })
    return normalized


def _timeline_response_issues(
    raw: Any,
    *,
    duration: float,
    slide_count: int,
    allowed_slide_indices: set[int] | None = None,
) -> list[str]:
    if not isinstance(raw, list) or not raw:
        return ["slide_timeline must be a non-empty array"]
    issues: list[str] = []
    valid_ranges = 0
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            issues.append(f"entry {index} is not an object")
            continue
        start = _safe_float(item.get("start_time", item.get("time_seconds")), -1.0)
        end = _safe_float(item.get("end_time"), -1.0)
        if start < 0 or end <= start or start > duration + 1 or end > duration + 5:
            issues.append(f"entry {index} has invalid timing")
            continue
        valid_ranges += 1
        raw_slide = item.get("slide_index")
        if raw_slide is not None:
            try:
                slide_index = int(raw_slide)
            except (TypeError, ValueError):
                issues.append(f"entry {index} has invalid slide_index")
                continue
            if not 0 <= slide_index < slide_count or (
                allowed_slide_indices is not None and slide_index not in allowed_slide_indices
            ):
                issues.append(f"entry {index} selects a slide outside the allowed scope")
    if valid_ranges < max(1, len(raw) // 2):
        issues.append("too few valid timed entries")
    return issues[:8]


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _slide_timeline_from_editorial_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "id": f"editorial-slide-{index + 1:04d}",
            "start_time": block["start_time"],
            "end_time": block["end_time"],
            "slide_index": block.get("slide_index"),
            "confidence": block.get("confidence", 1.0),
            "strategy": "editorial_block_projection",
            "reason": block.get("reason", "Semantic editorial block"),
            "cue_type": "lecturer_only" if block.get("slide_index") is None else "semantic_block",
            "source": block.get("source", "agent4_editorial_plan"),
            "editorial_block_id": block.get("id"),
            "slide_relation": block.get("slide_relation", "related" if block.get("slide_index") is not None else "unrelated"),
            "review_required": bool(block.get("review_required", False)),
            "planning_status": block.get("planning_status", "verified"),
        }
        for index, block in enumerate(blocks)
    ]


def _token_slide_timeline(
    segments: list,
    pages: list[dict],
    *,
    timed_words: list[dict[str, Any]] | None = None,
    allowed_slide_indices: set[int] | None = None,
) -> list[dict[str, Any]]:
    page_terms = [_semantic_terms(page.get("text") or "") for page in pages]
    timeline: list[dict[str, Any]] = []
    for chunk in _semantic_chunks(segments, timed_words=timed_words):
        terms = _semantic_terms(chunk["text"])
        scores = [
            len(terms & candidates) / max(6, len(terms)) if allowed_slide_indices is None or index in allowed_slide_indices else 0.0
            for index, candidates in enumerate(page_terms)
        ]
        best_score = max(scores, default=0.0)
        best_index = scores.index(best_score) if scores and best_score >= 0.055 else None
        timeline.append({
            "id": f"fallback-{chunk['id']}",
            "start_time": chunk["start_time"],
            "end_time": chunk["end_time"],
            "slide_index": best_index,
            "confidence": round(min(1.0, best_score), 3),
            "strategy": "token_overlap_fallback",
            "reason": "Matched speech chunk to page text" if best_index is not None else "No relevant page",
            "cue_type": "semantic_block" if best_index is not None else "lecturer_only",
            "block_title": "Matched lecture topic" if best_index is not None else "Lecturer context",
            "summary": str(chunk.get("text") or "")[:900],
            "transcript_excerpt": str(chunk.get("text") or "")[:1800],
            "slide_relevance": "direct" if best_index is not None else "none",
            "slide_relation": "related" if best_index is not None else "unrelated",
            "review_required": True,
            "planning_status": "degraded",
            "layout": "picture_in_picture" if best_index is not None else "full_camera_source",
        })
    return timeline


def _page_scope_from_asset(asset: Any, slide_count: int) -> tuple[int, int] | None:
    metadata = dict(getattr(asset, "metadata_json", None) or {})
    user_metadata = metadata.get("user_metadata")
    if isinstance(user_metadata, dict):
        metadata = {**metadata, **user_metadata}
    raw_start = metadata.get("slide_page_start", metadata.get("page_start"))
    raw_end = metadata.get("slide_page_end", metadata.get("page_end"))
    if raw_start in (None, "") or raw_end in (None, ""):
        return None
    try:
        start = int(raw_start) - 1
        end = int(raw_end) - 1
    except (TypeError, ValueError):
        return None
    if slide_count <= 0 or start < 0 or end < start or end >= slide_count:
        return None
    return start, end


def _scope_from_llm_result(result: dict[str, Any], slide_count: int) -> tuple[int, int] | None:
    raw = result.get("page_scope")
    if not isinstance(raw, dict):
        return None
    try:
        start = int(raw.get("start_slide_index"))
        end = int(raw.get("end_slide_index"))
    except (TypeError, ValueError):
        return None
    if slide_count <= 0 or start < 0 or end < start or end >= slide_count:
        return None
    return start, end


def _infer_contiguous_scope(timeline: list[dict[str, Any]], slide_count: int) -> tuple[int, int] | None:
    selected = sorted({
        int(item["slide_index"])
        for item in timeline
        if item.get("slide_index") is not None and 0 <= int(item["slide_index"]) < slide_count
    })
    if not selected:
        return None
    start, end = selected[0], selected[-1]
    # A title page is commonly omitted from speech while still belonging to the recording.
    if start > 0 and any(item.get("slide_index") is None for item in timeline[:2]):
        start -= 1
    return start, end


def _scope_indices(scope: tuple[int, int] | None) -> set[int] | None:
    return set(range(scope[0], scope[1] + 1)) if scope is not None else None


def _scope_payload(scope: tuple[int, int] | None, *, source: str) -> dict[str, Any] | None:
    if scope is None:
        return None
    return {
        "start_slide_index": scope[0],
        "end_slide_index": scope[1],
        "start_page": scope[0] + 1,
        "end_page": scope[1] + 1,
        "source": source,
    }


def _document_preflight(pages: list[dict[str, Any]], *, document_format: str) -> dict[str, Any]:
    missing_images: list[int] = []
    empty_text_pages: list[int] = []
    rendered_images = 0
    for index, page in enumerate(pages):
        image_path = str(page.get("image_path") or "")
        if image_path and os.path.isfile(image_path):
            rendered_images += 1
        else:
            missing_images.append(index + 1)
        if not str(page.get("text") or "").strip():
            empty_text_pages.append(index + 1)
    return {
        "status": "ready" if not missing_images else "warning",
        "document_format": document_format,
        "expected_pages": len(pages),
        "extracted_pages": len(pages),
        "rendered_images": rendered_images,
        "missing_image_pages": missing_images,
        "empty_text_pages": empty_text_pages,
    }


def _stabilize_slide_timeline(
    timeline: list[dict[str, Any]],
    *,
    chunks: list[dict[str, Any]],
    allowed_slide_indices: set[int] | None = None,
    min_excursion_seconds: float = 8.0,
    sustained_advance_seconds: float = 30.0,
) -> list[dict[str, Any]]:
    """Apply anchor/excursion rules so LLM candidates cannot flicker slides."""
    cues = [dict(item) for item in timeline]
    cues.sort(key=lambda item: float(item.get("start_time", 0.0) or 0.0))
    chunk_by_time = sorted(chunks, key=lambda item: float(item.get("start_time", 0.0)))
    anchor: int | None = None
    stabilized: list[dict[str, Any]] = []
    index = 0

    while index < len(cues):
        cue = cues[index]
        candidate = cue.get("slide_index")
        candidate = int(candidate) if candidate is not None else None
        if allowed_slide_indices is not None and candidate not in allowed_slide_indices:
            candidate = None
        start = float(cue.get("start_time", 0.0) or 0.0)
        end = float(cue.get("end_time", start) or start)
        duration = max(0.0, end - start)
        chunk = _chunk_at_time(chunk_by_time, start)
        signals = set(chunk.get("signals") or []) if chunk else set()
        requested_type = str(cue.get("cue_type") or "candidate").lower()

        run_end = index + 1
        run_duration = duration
        while run_end < len(cues) and cues[run_end].get("slide_index") == candidate:
            run_duration += max(
                0.0,
                float(cues[run_end].get("end_time", 0.0) or 0.0)
                - float(cues[run_end].get("start_time", 0.0) or 0.0),
            )
            run_end += 1
        next_candidate = cues[run_end].get("slide_index") if run_end < len(cues) else None

        if candidate is None:
            if anchor is not None and duration < min_excursion_seconds:
                cue.update(slide_index=anchor, cue_type="anchor_hold", reason="Brief unmatched speech kept the current anchor slide")
            else:
                cue.update(slide_index=None, cue_type="lecturer_only")
        elif anchor is None:
            anchor = candidate
            cue["cue_type"] = "anchor"
        elif candidate == anchor:
            cue["cue_type"] = "return" if requested_type == "return" or "return" in signals else "anchor"
        else:
            explicit_advance = requested_type == "advance" or "advance" in signals
            sustained = run_end - index >= 2 or run_duration >= sustained_advance_seconds
            returns_to_anchor = next_candidate == anchor or _returns_to_anchor_within(
                cues,
                start_index=run_end,
                anchor=anchor,
                from_time=end,
                lookahead_seconds=60.0,
            )
            if returns_to_anchor and run_duration >= min_excursion_seconds:
                cue["cue_type"] = "excursion"
            elif sustained or (explicit_advance and duration >= min_excursion_seconds):
                anchor = candidate
                cue["cue_type"] = "advance"
            else:
                cue.update(
                    slide_index=anchor,
                    cue_type="anchor_hold",
                    reason="Short or uncertain page reference suppressed to prevent slide flicker",
                )
        cue["anchor_slide_index"] = anchor
        cue["source"] = str(cue.get("source") or "agent4_anchor_planner")
        stabilized.append(cue)
        index += 1

    return _merge_stable_slide_cues(stabilized)


def _returns_to_anchor_within(
    cues: list[dict[str, Any]],
    *,
    start_index: int,
    anchor: int,
    from_time: float,
    lookahead_seconds: float,
) -> bool:
    deadline = from_time + lookahead_seconds
    for cue in cues[start_index:]:
        start = float(cue.get("start_time", 0.0) or 0.0)
        if start > deadline:
            break
        candidate = cue.get("slide_index")
        try:
            candidate = int(candidate) if candidate is not None else None
        except (TypeError, ValueError):
            candidate = None
        if candidate == anchor:
            return True
    return False


def _chunk_at_time(chunks: list[dict[str, Any]], time_seconds: float) -> dict[str, Any] | None:
    return next(
        (
            chunk for chunk in chunks
            if float(chunk.get("start_time", 0.0)) <= time_seconds < float(chunk.get("end_time", 0.0))
        ),
        None,
    )


def _merge_stable_slide_cues(cues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for cue in cues:
        if (
            merged
            and merged[-1].get("slide_index") == cue.get("slide_index")
            and merged[-1].get("cue_type") == cue.get("cue_type")
            and abs(float(merged[-1].get("end_time", 0.0)) - float(cue.get("start_time", 0.0))) < 0.1
        ):
            merged[-1]["end_time"] = cue.get("end_time")
            merged[-1]["confidence"] = round(
                min(float(merged[-1].get("confidence", 0.0)), float(cue.get("confidence", 0.0))),
                3,
            )
            continue
        merged.append(dict(cue))
    for index, cue in enumerate(merged):
        cue["id"] = str(cue.get("id") or f"agent4-slide-cue-{index + 1:04d}")
    return merged


def _semantic_terms(value: Any) -> set[str]:
    stop = {"the", "and", "for", "with", "that", "this", "from", "are", "you", "your", "will", "have"}
    return {word for word in re.findall(r"[a-z0-9]{3,}", str(value or "").lower()) if word not in stop}


async def _detect_scenes_with_timeout(video_path: str) -> tuple[List[Tuple], bool]:
    timeout_seconds = max(1.0, float(getattr(settings, "AGENT4_SCENE_DETECTION_TIMEOUT_SECONDS", 90.0) or 90.0))
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_detect_scenes, video_path),
            timeout=timeout_seconds,
        ), False
    except asyncio.TimeoutError:
        logger.warning("Agent 4: Scene detection timed out after %.1fs for %s", timeout_seconds, video_path)
        return [], True


async def _load_visual_context(video: Video, db: AsyncSession) -> VisualContext:
    if not video.project_id:
        return VisualContext([], set(), 0, False, False, False)

    result = await db.execute(
        select(ProjectAsset)
        .where(ProjectAsset.project_id == video.project_id)
        .where(ProjectAsset.status != ProjectAssetStatus.ARCHIVED)
    )
    assets = list(result.scalars().all())
    source_roles = {
        _asset_value(value)
        for asset in assets
        for value in (
            getattr(asset, "kind", None),
            getattr(asset, "role", None),
            getattr(asset, "source_type", None),
            getattr(asset, "sync_role", None),
        )
    }
    source_roles.discard("")
    return VisualContext(
        assets=assets,
        source_roles=source_roles,
        structure_reference_count=sum(1 for asset in assets if _asset_matches(asset, STRUCTURE_VALUES)),
        has_screen_reference=any(_asset_matches(asset, SCREEN_VALUES) for asset in assets),
        has_camera_reference=any(_asset_matches(asset, CAMERA_VALUES) for asset in assets),
        has_structure_reference=any(_asset_matches(asset, STRUCTURE_VALUES) for asset in assets),
    )


def _scene_detection_skip_reason(video: Video, context: VisualContext) -> str | None:
    size_mb = _file_size_mb(video)
    skip_mb = max(0, int(getattr(settings, "AGENT4_STRUCTURE_REFERENCE_SKIP_MB", 768) or 768))
    if context.has_structure_reference and not context.has_screen_reference:
        if size_mb >= skip_mb:
            return (
                f"Large camera/mixed source ({size_mb:.0f} MB) already has uploaded teaching structure; "
                "using the uploaded structure reference instead of scanning video frames."
            )
        if _video_asset_is_camera(video, context):
            return "Camera-style source has uploaded teaching structure; no embedded slide changes need local frame scanning."
    return None


async def _clear_previous_visual_marks(video_id: str, db: AsyncSession) -> None:
    await db.execute(delete(Scene).where(Scene.video_id == video_id))


async def _clear_segment_slide_flags(video_id: str, db: AsyncSession) -> None:
    result = await db.execute(select(Segment).where(Segment.video_id == video_id))
    for segment in result.scalars().all():
        segment.has_slide_change = False
        segment.slide_index = None
        segment.scene_id = None


async def _create_scene_records(video: Video, scene_list: list[tuple[Any, Any]], db: AsyncSession) -> list[Scene]:
    thumb_dir = os.path.join(settings.VIDEO_STORAGE_PATH, f"thumbnails_{video.id}")
    os.makedirs(thumb_dir, exist_ok=True)

    thumbnail_limit = max(0, int(getattr(settings, "AGENT4_MAX_SCENE_THUMBNAILS", 40) or 40))
    scenes_created: list[Scene] = []
    for i, (scene_start, scene_end) in enumerate(scene_list):
        start_sec = float(scene_start.get_seconds())
        end_sec = float(scene_end.get_seconds())
        duration = end_sec - start_sec
        thumb_path = None

        if i < thumbnail_limit:
            candidate_path = os.path.join(thumb_dir, f"scene_{i:04d}.jpg")
            try:
                await ffmpeg_service.extract_frame(
                    video_path=video.file_path,
                    timestamp=start_sec + 0.5,
                    output_path=candidate_path,
                )
                thumb_path = candidate_path
            except Exception as exc:
                logger.warning("Agent 4: Thumbnail extraction failed for scene %s: %s", i, exc)

        scene = Scene(
            id=uuid.uuid4(),
            video_id=video.id,
            timestamp=start_sec,
            scene_index=i,
            scene_type=_classify_scene_type(i, len(scene_list), duration),
            thumbnail_path=thumb_path,
            confidence=0.8,
        )
        db.add(scene)
        scenes_created.append(scene)

    return scenes_created


async def _mark_segments_for_scenes(video_id: str, scenes: list[Scene], db: AsyncSession) -> int:
    result = await db.execute(
        select(Segment)
        .where(Segment.video_id == video_id)
        .order_by(Segment.segment_index)
    )
    segments = list(result.scalars().all())
    scene_times = [scene.timestamp for scene in scenes]
    segments_with_changes = 0

    for segment in segments:
        segment.has_slide_change = False
        segment.slide_index = None
        segment.scene_id = None
        changes_in_segment = [
            time for time in scene_times
            if segment.start_time <= time <= segment.end_time
        ]
        if not changes_in_segment:
            continue

        closest_time = min(changes_in_segment)
        closest_scene = next((scene for scene in scenes if scene.timestamp == closest_time), None)
        if closest_scene:
            segment.has_slide_change = True
            segment.slide_index = closest_scene.scene_index
            segment.scene_id = str(closest_scene.id)
            segments_with_changes += 1

    return segments_with_changes


def _detect_scenes(video_path: str) -> List[Tuple]:
    """Run PySceneDetect locally and return scene boundaries."""
    from scenedetect import AdaptiveDetector, ContentDetector, detect

    try:
        scene_list = detect(
            video_path,
            AdaptiveDetector(
                adaptive_threshold=3.0,
                min_scene_len=30,
            ),
        )
        logger.info("Agent 4: AdaptiveDetector found %s scenes", len(scene_list))
        if len(scene_list) >= 2:
            return scene_list

        scene_list = detect(
            video_path,
            ContentDetector(
                threshold=25.0,
                min_scene_len=30,
            ),
        )
        logger.info("Agent 4: ContentDetector threshold 25 found %s scenes", len(scene_list))
        if len(scene_list) >= 2:
            return scene_list

        scene_list = detect(
            video_path,
            ContentDetector(
                threshold=15.0,
                min_scene_len=15,
            ),
        )
        logger.info("Agent 4: ContentDetector threshold 15 found %s scenes", len(scene_list))
        return scene_list
    except Exception as exc:
        logger.error("Agent 4: Scene detection failed: %s", exc)
        return []


def _classify_scene_type(scene_index: int, total_scenes: int, duration: float) -> str:
    if scene_index == 0:
        return "intro"
    if scene_index == total_scenes - 1:
        return "outro"
    if duration < 5.0:
        return "transition"
    return "slide"


def _video_asset_is_camera(video: Video, context: VisualContext) -> bool:
    target_asset_id = str(video.project_asset_id or "")
    for asset in context.assets:
        if target_asset_id and str(getattr(asset, "id", "") or "") != target_asset_id:
            continue
        if _asset_matches(asset, CAMERA_VALUES):
            return True
    return bool(context.has_camera_reference and not context.has_screen_reference)


def _file_size_mb(video: Video) -> float:
    size = getattr(video, "file_size_bytes", None)
    if not size:
        try:
            size = os.path.getsize(video.file_path)
        except OSError:
            size = 0
    return float(size or 0) / (1024 * 1024)


def _asset_matches(asset: Any, values: set[str]) -> bool:
    return bool({
        _asset_value(getattr(asset, "kind", None)),
        _asset_value(getattr(asset, "role", None)),
        _asset_value(getattr(asset, "source_type", None)),
        _asset_value(getattr(asset, "sync_role", None)),
    } & values)


def _asset_value(value: Any) -> str:
    if isinstance(value, Enum):
        return str(value.value).lower()
    if value is None:
        return ""
    return str(value).lower()


def _visual_result(
    *,
    status: str,
    scenes_detected: int,
    scene_timestamps: list[float],
    analysis_source: str,
    context: VisualContext,
    skip_reason: str | None = None,
) -> dict[str, Any]:
    result = {
        "status": status,
        "scenes_detected": scenes_detected,
        "scene_timestamps": scene_timestamps,
        "analysis_source": analysis_source,
        "structure_reference_count": context.structure_reference_count,
        "vision_provider": _vision_provider_id(),
    }
    if skip_reason:
        result["skip_reason"] = skip_reason
    return result


def _vision_provider_id() -> str:
    try:
        from providers.interfaces import ProviderKind
        from services.llm import llm_service

        return llm_service.provider_id_for_kind(ProviderKind.VISION)
    except Exception:
        return "vision-unconfigured"
