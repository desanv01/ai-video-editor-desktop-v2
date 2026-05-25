"""
Agent 5 — Edit Planner Agent

Phase E: The decision-making brain of the system.

Goal: Fuse ALL analysis signals from Agents 2, 3, 4 into a structured edit plan
where every segment gets one of: KEEP / CUT / SHORTEN / HIGHLIGHT.

Inputs (from previous agents):
  - Importance scores + topic labels + segment types (Agent 2)
  - Filler counts + fluency scores + pause durations (Agent 3)
  - Scene boundaries + slide change flags (Agent 4)
  - Speaker labels (from Voxtral diarization)

Outputs:
  - JSON edit plan with per-segment action, confidence, reason
  - Quality metrics (time saved, fillers removed, etc.)
  - Auto-generated chapter markers
  - Coherence warnings (if cutting a segment breaks logical flow)

Supports:
  - Batched LLM calls for long lectures (>30 segments)
  - Rule-based fallback if LLM fails
  - Re-validation after teacher modifications
  - Consequence warnings ("cutting this removes the quicksort example")
"""

import uuid
import json
import logging
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from db.models import Video, Segment, EditPlan, SegmentAction, SegmentType, VideoStatus
from services.edit_plan_payload import build_edit_plan_payload
from services.llm import llm_service
from config import settings

logger = logging.getLogger(__name__)

EDIT_PLANNER_SYSTEM = """You are an expert educational video editor. Your task is to decide what to do with each segment of a lecture video to produce a clean, engaging educational video.

ACTIONS (pick exactly one per segment):
  - keep: Important content — include as-is
  - cut: Remove entirely — filler, long pauses, off-topic tangents, pure repetition
  - shorten: Trim dead space (pauses, hesitations) but preserve the core content
  - highlight: Especially important — flag for visual emphasis (key concept, crucial definition, critical example)

DECISION RULES (apply in order):
  1. HIGHLIGHT segments with importance >= 0.85 AND type = core_content or example
  2. KEEP all segments with importance >= 0.6
  3. KEEP segments where has_slide_change = true (visual transitions help learners)
  4. KEEP Q&A segments (type = "qa") if importance >= 0.4 (student questions add engagement)
  5. SHORTEN segments with importance 0.3-0.6 AND fluency_score < 0.5 (salvageable but disfluent)
  6. CUT segments with importance < 0.3 AND type = filler/pause/repetition
  7. CUT segments where pause_duration > 50% of segment duration
  8. NEVER cut a segment that introduces a topic referenced by a later KEEP segment
  9. When two adjacent segments have the same topic, prefer keeping the one with higher fluency
  10. Preserve natural pacing — don't cut every single pause; short pauses between important content are natural

COHERENCE CHECK:
  After making decisions, verify the remaining (non-cut) segments form a logical narrative.
  Flag any concerns as "warnings" in your response.

RESPOND WITH ONLY VALID JSON:
{
  "decisions": [
    {
      "segment_index": 0,
      "action": "keep",
      "confidence": 0.95,
      "reason": "Core concept introduction — bubble sort mechanism"
    }
  ],
  "warnings": [
    "Cutting segment 5 removes the only example of quicksort. Consider keeping it."
  ]
}"""


async def run_edit_planner_agent(video_id: str, db: AsyncSession) -> dict:
    """
    Generate the edit plan by fusing all analysis signals.

    Steps:
        1. Load all segments with their complete analysis data
        2. Send to LLM in batches for edit decisions
        3. Apply decisions + run coherence check
        4. Create/update EditPlan record with rich metadata
        5. Generate chapter markers

    Returns:
        {
            "status": "success",
            "plan_id": "...",
            "segments_keep": N, "segments_cut": N,
            "original_duration": N, "estimated_duration": N,
            "chapters": [...], "warnings": [...]
        }
    """
    video = await db.get(Video, video_id)
    if not video:
        raise ValueError(f"Video {video_id} not found")

    video.status = VideoStatus.PLANNING
    await db.flush()

    # ── Step 1: Load all segments ──
    result = await db.execute(
        select(Segment)
        .where(Segment.video_id == video_id)
        .order_by(Segment.segment_index)
    )
    segments = list(result.scalars().all())

    if not segments:
        return {"status": "error", "message": "No segments found. Run Agents 2-4 first."}

    logger.info(f"Agent 5: Planning edits for {len(segments)} segments, video {video_id}")

    # ── Step 2: Get LLM decisions (batched for long lectures) ──
    all_decisions = []
    all_warnings = []

    batch_size = 15  # ~15 segments per LLM call to stay within token limits
    for batch_start in range(0, len(segments), batch_size):
        batch = segments[batch_start:batch_start + batch_size]
        batch_end = min(batch_start + batch_size, len(segments))

        # Build compact segment descriptions
        segment_data = []
        for seg in batch:
            segment_data.append({
                "index": seg.segment_index,
                "time": f"{seg.start_time:.1f}-{seg.end_time:.1f}s",
                "duration": round(seg.duration or 0, 1),
                "topic": seg.topic_label or "Unknown",
                "summary": (seg.summary or "")[:120],
                "type": seg.segment_type.value if seg.segment_type else "unknown",
                "speaker": seg.speaker or "Instructor",
                "importance": round(seg.importance_score or 0.5, 2),
                "fluency": round(seg.fluency_score or 1.0, 2),
                "fillers": seg.filler_count or 0,
                "pause_sec": round(seg.pause_duration_total or 0, 1),
                "has_slide_change": seg.has_slide_change or False,
                "has_repetition": seg.has_repetition or False,
            })

        user_msg = (
            f"Video duration: {video.duration_seconds:.1f}s\n"
            f"Segments {batch_start} to {batch_end - 1} of {len(segments)} total:\n\n"
            f"{json.dumps(segment_data, indent=1)}\n\n"
            f"Decide action for each segment. Return JSON only."
        )

        messages = [
            {"role": "system", "content": EDIT_PLANNER_SYSTEM},
            {"role": "user", "content": user_msg},
        ]

        try:
            response = await llm_service.chat_json(
                messages,
                model=settings.AGENT5_MODEL,
                temperature=0.1,
                max_tokens=4096,
            )
            batch_decisions = response.get("decisions", [])
            batch_warnings = response.get("warnings", [])
            all_decisions.extend(batch_decisions)
            all_warnings.extend(batch_warnings)
            logger.info(
                f"  Batch {batch_start//batch_size + 1}: "
                f"{len(batch_decisions)} decisions, {len(batch_warnings)} warnings"
            )
        except Exception as e:
            logger.warning(f"  Batch {batch_start//batch_size + 1} LLM failed: {e}, using fallback rules")
            fallback = _fallback_decisions(batch)
            all_decisions.extend(fallback)

    # ── Step 3: Apply decisions to segments ──
    action_map = {
        "keep": SegmentAction.KEEP,
        "cut": SegmentAction.CUT,
        "shorten": SegmentAction.SHORTEN,
        "highlight": SegmentAction.HIGHLIGHT,
    }

    counts = {"keep": 0, "cut": 0, "shorten": 0, "highlight": 0}
    total_fillers_removed = 0
    silence_removed = 0.0

    for seg in segments:
        decision = next(
            (d for d in all_decisions if d.get("segment_index") == seg.segment_index),
            None,
        )

        if decision:
            action_str = decision.get("action", "keep").lower().strip()
            seg.action = action_map.get(action_str, SegmentAction.KEEP)
            seg.action_confidence = min(1.0, max(0.0, float(decision.get("confidence", 0.5))))
            seg.action_reason = decision.get("reason", "")
        else:
            # Segment missing from LLM response — use fallback
            fb = _fallback_single(seg)
            seg.action = action_map.get(fb["action"], SegmentAction.KEEP)
            seg.action_confidence = fb["confidence"]
            seg.action_reason = fb["reason"]

        counts[seg.action.value] += 1

        if seg.action == SegmentAction.CUT:
            total_fillers_removed += seg.filler_count or 0
            silence_removed += seg.pause_duration_total or 0

    # ── Step 4: Coherence post-check ──
    counts, total_fillers_removed, silence_removed = _ensure_actionable_plan(segments, counts)

    coherence_warnings = _check_coherence(segments)
    all_warnings.extend(coherence_warnings)

    # ── Step 5: Compute stats ──
    original_duration = video.duration_seconds or 0
    cut_duration = sum((seg.duration or 0) for seg in segments if seg.action == SegmentAction.CUT)
    shorten_savings = sum(
        (seg.pause_duration_total or 0) for seg in segments if seg.action == SegmentAction.SHORTEN
    )
    estimated_duration = max(0, original_duration - cut_duration - shorten_savings)

    # ── Step 6: Build rich plan_json for the desktop app ──
    plan_entries = []
    for seg in segments:
        plan_entries.append({
            "segment_id": str(seg.id),
            "segment_index": seg.segment_index,
            "start": seg.start_time,
            "end": seg.end_time,
            "duration": seg.duration,
            "action": seg.action.value,
            "confidence": seg.action_confidence,
            "reason": seg.action_reason,
            # Rich data for desktop app display
            "topic": seg.topic_label,
            "summary": seg.summary,
            "type": seg.segment_type.value if seg.segment_type else None,
            "speaker": seg.speaker,
            "importance": seg.importance_score,
            "fluency": seg.fluency_score,
            "fillers": seg.filler_count,
            "pause_seconds": seg.pause_duration_total,
            "has_slide_change": seg.has_slide_change,
        })

    plan_payload = build_edit_plan_payload(
        segments=plan_entries,
        original_duration=original_duration,
        estimated_duration=round(estimated_duration, 1),
        warnings=all_warnings,
    )

    # ── Step 7: Create or update EditPlan ──
    existing_plan = await db.execute(
        select(EditPlan).where(EditPlan.video_id == video_id)
    )
    plan = existing_plan.scalar_one_or_none()

    if plan:
        # Update existing plan (re-run scenario)
        plan.plan_json = plan_payload
        plan.original_duration = original_duration
        plan.estimated_duration = round(estimated_duration, 1)
        plan.segments_total = len(segments)
        plan.segments_keep = counts["keep"]
        plan.segments_cut = counts["cut"]
        plan.segments_highlight = counts["highlight"]
        plan.filler_words_removed = total_fillers_removed
        plan.silence_removed_seconds = round(silence_removed, 2)
        plan.is_approved = False  # Reset approval on re-plan
        plan.approved_at = None
    else:
        plan = EditPlan(
            id=uuid.uuid4(),
            video_id=video.id,
            plan_json=plan_payload,
            original_duration=original_duration,
            estimated_duration=round(estimated_duration, 1),
            segments_total=len(segments),
            segments_keep=counts["keep"],
            segments_cut=counts["cut"],
            segments_highlight=counts["highlight"],
            filler_words_removed=total_fillers_removed,
            silence_removed_seconds=round(silence_removed, 2),
        )
        db.add(plan)

    # ── Step 8: Generate chapter markers ──
    chapters = _generate_chapters(segments)

    video.status = VideoStatus.AWAITING_REVIEW
    await db.flush()

    reduction_pct = round((cut_duration + shorten_savings) / max(original_duration, 1) * 100, 1)

    logger.info(
        f"Agent 5 complete: {counts} | "
        f"{original_duration:.0f}s → {estimated_duration:.0f}s ({reduction_pct}% reduction) | "
        f"{len(all_warnings)} warnings | {len(chapters)} chapters"
    )

    return {
        "status": "success",
        "plan_id": str(plan.id),
        "segments_total": len(segments),
        "segments_keep": counts["keep"],
        "segments_cut": counts["cut"],
        "segments_shorten": counts["shorten"],
        "segments_highlight": counts["highlight"],
        "original_duration": round(original_duration, 1),
        "estimated_duration": round(estimated_duration, 1),
        "time_saved_seconds": round(cut_duration + shorten_savings, 1),
        "reduction_percent": reduction_pct,
        "filler_words_removed": total_fillers_removed,
        "silence_removed_seconds": round(silence_removed, 2),
        "chapters": chapters,
        "warnings": all_warnings,
    }


# ═══════════════════════════════════════════
#  RE-VALIDATION (after teacher modifications)
# ═══════════════════════════════════════════

async def revalidate_edit_plan(video_id: str, db: AsyncSession) -> dict:
    """
    Re-validate the edit plan after teacher modifications.

    Called when the teacher changes segment actions in the desktop app.
    Checks for logical inconsistencies and generates warnings.

    Returns:
        {"warnings": [...], "consequence_alerts": [...]}
    """
    result = await db.execute(
        select(Segment)
        .where(Segment.video_id == video_id)
        .order_by(Segment.segment_index)
    )
    segments = list(result.scalars().all())

    if not segments:
        return {"warnings": [], "consequence_alerts": []}

    warnings = _check_coherence(segments, use_teacher_actions=True)
    alerts = _check_consequences(segments)

    logger.info(f"Re-validation: {len(warnings)} warnings, {len(alerts)} alerts")

    return {
        "warnings": warnings,
        "consequence_alerts": alerts,
    }


# ═══════════════════════════════════════════
#  COHERENCE CHECKING
# ═══════════════════════════════════════════

def _check_coherence(segments: List[Segment], use_teacher_actions: bool = False) -> List[str]:
    """
    Check if the edit decisions create logical flow issues.

    Detects:
      - Cutting a topic-introduction segment while keeping later references
      - Cutting all examples of a concept
      - Creating jarring jumps (two kept segments with a large time gap)
      - Cutting Q&A that provides important clarification
    """
    warnings = []

    def get_action(seg):
        if use_teacher_actions and seg.is_teacher_modified and seg.teacher_action:
            return seg.teacher_action
        return seg.action

    # Track which topics are kept vs cut
    kept_topics = set()
    cut_topics = set()
    for seg in segments:
        topic = seg.topic_label or "Unknown"
        action = get_action(seg)
        if action in (SegmentAction.KEEP, SegmentAction.HIGHLIGHT, SegmentAction.SHORTEN):
            kept_topics.add(topic)
        elif action == SegmentAction.CUT:
            cut_topics.add(topic)

    # Warn about topics that are partially cut
    for topic in cut_topics:
        if topic in kept_topics and topic != "Unknown":
            # Find cut segments for this topic
            cut_segs = [
                s for s in segments
                if (s.topic_label == topic
                    and get_action(s) == SegmentAction.CUT
                    and (s.importance_score or 0) >= 0.5)
            ]
            if cut_segs:
                indices = [str(s.segment_index) for s in cut_segs]
                warnings.append(
                    f"Segment(s) {', '.join(indices)} about \"{topic}\" are marked as CUT "
                    f"but have importance >= 0.5. Review these — they may contain important content."
                )

    # Check for large time gaps between kept segments
    kept_segments = [s for s in segments if get_action(s) != SegmentAction.CUT]
    for i in range(len(kept_segments) - 1):
        gap = kept_segments[i + 1].start_time - kept_segments[i].end_time
        if gap > 120:  # >2 minutes gap
            warnings.append(
                f"Large gap ({gap:.0f}s) between segments "
                f"{kept_segments[i].segment_index} and {kept_segments[i+1].segment_index}. "
                f"This may create a jarring jump in the edited video."
            )

    # Check if ALL Q&A segments are cut
    qa_segments = [s for s in segments if s.segment_type == SegmentType.QA]
    qa_cut = [s for s in qa_segments if get_action(s) == SegmentAction.CUT]
    if qa_segments and len(qa_cut) == len(qa_segments):
        warnings.append(
            "All Q&A segments are marked as CUT. "
            "Student questions often provide valuable clarification. Consider keeping some."
        )

    # Check for cutting the first segment (likely intro)
    if segments and get_action(segments[0]) == SegmentAction.CUT:
        if (segments[0].importance_score or 0) >= 0.3:
            warnings.append(
                "The first segment (likely the introduction) is marked as CUT. "
                "Consider keeping it for context."
            )

    return warnings


def _check_consequences(segments: List[Segment]) -> List[dict]:
    """
    Generate consequence alerts for teacher-modified segments.

    Each alert explains what happens if a specific teacher change is applied.
    """
    alerts = []

    for seg in segments:
        if not seg.is_teacher_modified or not seg.teacher_action:
            continue

        ai_action = seg.action
        teacher_action = seg.teacher_action

        # Teacher overrode AI's KEEP → CUT
        if ai_action in (SegmentAction.KEEP, SegmentAction.HIGHLIGHT) and teacher_action == SegmentAction.CUT:
            detail = ""
            if seg.segment_type == SegmentType.CORE_CONTENT:
                detail = f" This segment covers \"{seg.topic_label}\" which is core curriculum content."
            elif seg.segment_type == SegmentType.EXAMPLE:
                detail = f" This is an example illustrating \"{seg.topic_label}\"."
            elif seg.segment_type == SegmentType.QA:
                detail = " This is a Q&A segment with student interaction."

            alerts.append({
                "segment_index": seg.segment_index,
                "type": "cut_important",
                "message": (
                    f"Cutting segment {seg.segment_index} "
                    f"(importance: {seg.importance_score:.2f}, "
                    f"AI recommended: {ai_action.value}).{detail}"
                ),
            })

        # Teacher overrode AI's CUT → KEEP
        elif ai_action == SegmentAction.CUT and teacher_action in (SegmentAction.KEEP, SegmentAction.HIGHLIGHT):
            alerts.append({
                "segment_index": seg.segment_index,
                "type": "keep_low_quality",
                "message": (
                    f"Keeping segment {seg.segment_index} "
                    f"(fluency: {seg.fluency_score:.2f}, "
                    f"fillers: {seg.filler_count or 0}). "
                    f"AI recommended cutting due to low content quality."
                ),
            })

    return alerts


# ═══════════════════════════════════════════
#  FALLBACK RULES (if LLM fails)
# ═══════════════════════════════════════════

def _fallback_decisions(segments: List[Segment]) -> List[dict]:
    """Batch rule-based fallback for when LLM call fails."""
    return [_fallback_single(seg) for seg in segments]


def _fallback_single(seg: Segment) -> dict:
    """
    Rule-based decision for a single segment.

    Uses a weighted scoring approach combining all signals.
    """
    importance = seg.importance_score or 0.5
    fluency = seg.fluency_score or 1.0
    filler_count = seg.filler_count or 0
    pause_ratio = (seg.pause_duration_total or 0) / max(seg.duration or 1, 1)
    has_slide = seg.has_slide_change or False
    has_repetition = seg.has_repetition or False
    seg_type = seg.segment_type
    text_word_count = len((seg.text or "").split())

    # Cut obvious non-content even if upstream analysis was unavailable.
    if text_word_count < 8 or (seg.duration or 0) <= 2:
        return {
            "segment_index": seg.segment_index,
            "action": "cut",
            "confidence": 0.85,
            "reason": "Very little transcribed content",
        }

    if pause_ratio > 0.55 and importance < 0.6:
        return {
            "segment_index": seg.segment_index,
            "action": "cut",
            "confidence": 0.8,
            "reason": f"Mostly silence ({pause_ratio*100:.0f}% pause)",
        }

    if pause_ratio > 0.25 and importance < 0.75:
        return {
            "segment_index": seg.segment_index,
            "action": "shorten",
            "confidence": 0.72,
            "reason": f"Contains removable pauses ({pause_ratio*100:.0f}% pause)",
        }

    # Highlight: very important core content
    if importance >= 0.85 and seg_type in (SegmentType.CORE_CONTENT, SegmentType.EXAMPLE):
        return {
            "segment_index": seg.segment_index,
            "action": "highlight",
            "confidence": 0.9,
            "reason": f"High importance ({importance:.2f}) + {seg_type.value if seg_type else 'core'} content",
        }

    # Keep: important content OR slide changes
    if importance >= 0.6 or (has_slide and importance >= 0.4):
        return {
            "segment_index": seg.segment_index,
            "action": "keep",
            "confidence": 0.8,
            "reason": f"Important content (importance={importance:.2f})" + (" + slide change" if has_slide else ""),
        }

    # Keep: Q&A with reasonable importance
    if seg_type == SegmentType.QA and importance >= 0.4:
        return {
            "segment_index": seg.segment_index,
            "action": "keep",
            "confidence": 0.7,
            "reason": "Student Q&A with educational value",
        }

    # Shorten: medium importance but poor delivery
    if 0.3 <= importance < 0.6 and fluency < 0.5:
        return {
            "segment_index": seg.segment_index,
            "action": "shorten",
            "confidence": 0.65,
            "reason": f"Useful content but poor delivery (fluency={fluency:.2f}, fillers={filler_count})",
        }

    # Cut: filler, pause, or repetition with low importance
    if importance < 0.3 or seg_type in (SegmentType.FILLER, SegmentType.PAUSE):
        return {
            "segment_index": seg.segment_index,
            "action": "cut",
            "confidence": 0.8,
            "reason": f"Low importance ({importance:.2f}), type={seg_type.value if seg_type else 'unknown'}",
        }

    # Cut: repetition with low importance
    if has_repetition and importance < 0.5:
        return {
            "segment_index": seg.segment_index,
            "action": "cut",
            "confidence": 0.7,
            "reason": f"Repetitive content (importance={importance:.2f})",
        }

    # Default: keep with low confidence
    return {
        "segment_index": seg.segment_index,
        "action": "keep",
        "confidence": 0.5,
        "reason": "Default keep — no strong signal either way",
    }


# ═══════════════════════════════════════════
#  CHAPTER MARKERS
# ═══════════════════════════════════════════

def _ensure_actionable_plan(segments: List[Segment], counts: dict) -> tuple[dict, int, float]:
    """
    Apply clear mechanical edits if the model kept every segment.

    This avoids a no-op render for lectures with obvious silence/filler sections
    while preserving high-importance educational content.
    """
    if counts.get("cut", 0) or counts.get("shorten", 0):
        total_fillers_removed = sum(s.filler_count or 0 for s in segments if s.action == SegmentAction.CUT)
        silence_removed = sum(
            s.pause_duration_total or 0
            for s in segments
            if s.action in (SegmentAction.CUT, SegmentAction.SHORTEN)
        )
        return counts, total_fillers_removed, round(silence_removed, 2)

    updated = False
    for seg in segments:
        fallback = _fallback_single(seg)
        fallback_action = fallback["action"]
        if fallback_action not in ("cut", "shorten"):
            continue

        importance = seg.importance_score or 0.5
        if importance >= 0.75:
            continue

        seg.action = SegmentAction(fallback_action)
        seg.action_confidence = max(float(seg.action_confidence or 0), fallback["confidence"])
        seg.action_reason = f"{seg.action_reason or 'Kept by model'}; fallback edit: {fallback['reason']}"
        updated = True

    if not updated:
        return counts, 0, 0.0

    recalculated = {"keep": 0, "cut": 0, "shorten": 0, "highlight": 0}
    for seg in segments:
        recalculated[(seg.action or SegmentAction.KEEP).value] += 1

    total_fillers_removed = sum(s.filler_count or 0 for s in segments if s.action == SegmentAction.CUT)
    silence_removed = sum(
        s.pause_duration_total or 0
        for s in segments
        if s.action in (SegmentAction.CUT, SegmentAction.SHORTEN)
    )

    if recalculated["cut"] or recalculated["shorten"]:
        logger.info(
            "Applied fallback mechanical edits after model kept all segments: "
            f"{recalculated['cut']} cut, {recalculated['shorten']} shorten"
        )

    return recalculated, total_fillers_removed, round(silence_removed, 2)


def _generate_chapters(segments: List[Segment]) -> List[dict]:
    """
    Generate YouTube-style chapter markers from kept segments.

    A new chapter starts when:
      - Topic changes from previous kept segment
      - Segment has reasonable importance (>= 0.3)
    """
    chapters = []
    current_topic = None

    for seg in segments:
        # Only generate chapters from kept/highlighted segments
        if seg.action == SegmentAction.CUT:
            continue

        topic = seg.topic_label or "Unknown"
        if topic != current_topic and (seg.importance_score or 0) >= 0.3:
            minutes = int(seg.start_time // 60)
            seconds = int(seg.start_time % 60)

            chapters.append({
                "timestamp": seg.start_time,
                "timestamp_formatted": f"{minutes:02d}:{seconds:02d}",
                "label": topic,
                "segment_index": seg.segment_index,
                "importance": seg.importance_score,
            })
            current_topic = topic

    return chapters
