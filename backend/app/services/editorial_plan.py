"""Authoritative semantic edit blocks for slide and layout planning."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable

from services.decision_values import normalize_confidence, normalize_slide_relation
from services.layout_model import LayoutMode, build_layout_cue, normalize_layout_cues


EDITORIAL_PLAN_VERSION = "phase7.editorial-blocks.v1"
MIN_AUTOMATIC_VISUAL_BLOCK_SECONDS = 3.0
VALID_LAYOUTS = {mode.value for mode in LayoutMode}
VALID_RELEVANCE = {"none", "partial", "direct", "critical"}
VALID_PLANNING_STATUS = {"verified", "needs_review", "degraded", "teacher_adjusted"}


def normalize_editorial_blocks(
    raw_blocks: Any,
    *,
    duration_seconds: float | None = None,
    slide_count: int | None = None,
) -> list[dict[str, Any]]:
    """Normalize combined semantic decisions without inventing stale slides."""
    if not isinstance(raw_blocks, list):
        return []

    duration = max(0.0, float(duration_seconds or 0.0))
    items = [dict(item) for item in raw_blocks if isinstance(item, dict)]
    items.sort(key=lambda item: _float(item.get("start_time", item.get("time_seconds", 0.0))))
    normalized: list[dict[str, Any]] = []

    for index, item in enumerate(items):
        start = max(0.0, _float(item.get("start_time", item.get("time_seconds", 0.0))))
        next_start = (
            max(start, _float(items[index + 1].get("start_time", items[index + 1].get("time_seconds", duration))))
            if index + 1 < len(items)
            else duration
        )
        end = max(start, _float(item.get("end_time", next_start)))
        if duration:
            end = min(duration, end)
        if end - start < 0.05:
            continue

        slide_index = _int_or_none(item.get("slide_index"))
        candidate_slide_index = _int_or_none(item.get("candidate_slide_index"))
        if slide_index is not None and (slide_index < 0 or (slide_count is not None and slide_index >= slide_count)):
            candidate_slide_index = slide_index
            slide_index = None

        confidence = normalize_confidence(item.get("confidence"), 0.5)
        relevance = str(item.get("slide_relevance") or ("direct" if slide_index is not None else "none")).lower()
        if relevance not in VALID_RELEVANCE:
            relevance = "direct" if slide_index is not None else "none"
        relation = normalize_slide_relation(
            item.get("slide_relation"),
            slide_index=slide_index,
            relevance=relevance,
        )
        review_required = bool(item.get("review_required", False))
        planning_status = str(item.get("planning_status") or "verified").lower()
        if planning_status not in VALID_PLANNING_STATUS:
            planning_status = "needs_review" if review_required else "verified"
        if relation == "unrelated":
            slide_index = None
            relevance = "none"
        elif relation == "uncertain":
            candidate_slide_index = slide_index if slide_index is not None else candidate_slide_index
            slide_index = None
            relevance = "none"
            review_required = True
            if planning_status == "verified":
                planning_status = "needs_review"

        layout = _layout_value(item.get("layout"), slide_index=slide_index, relevance=relevance)
        if slide_index is None:
            layout = LayoutMode.FULL_CAMERA_SOURCE.value

        normalized.append({
            **item,
            "id": str(item.get("id") or f"editorial-block-{index + 1:04d}"),
            "schema_version": EDITORIAL_PLAN_VERSION,
            "start_time": round(start, 3),
            "end_time": round(end, 3),
            "title": str(item.get("title") or item.get("block_title") or "Lecture content").strip()[:160],
            "summary": str(item.get("summary") or item.get("transcript_excerpt") or "").strip()[:900],
            "transcript_excerpt": str(item.get("transcript_excerpt") or item.get("text") or "").strip()[:1800],
            "slide_index": slide_index,
            "candidate_slide_index": candidate_slide_index,
            "slide_relevance": relevance,
            "slide_relation": relation,
            "layout": layout,
            "confidence": round(confidence, 3),
            "review_required": review_required,
            "planning_status": planning_status,
            "reason": str(item.get("reason") or _default_reason(slide_index, relevance)),
            "source": str(item.get("source") or item.get("strategy") or "agent4_editorial_plan"),
            "teacher_modified": bool(item.get("teacher_modified", False)),
        })

    covered = _cover_gaps(normalized, duration)
    stable = _stabilize_automatic_micro_blocks(covered)
    return _merge_adjacent_blocks(stable)


def editorial_blocks_from_slide_timeline(
    timeline: Iterable[dict[str, Any]],
    *,
    duration_seconds: float | None,
    slide_count: int | None = None,
) -> list[dict[str, Any]]:
    return normalize_editorial_blocks(
        list(timeline or []),
        duration_seconds=duration_seconds,
        slide_count=slide_count,
    )


def slide_cues_from_editorial_blocks(blocks: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    cues = []
    for index, block in enumerate(blocks or []):
        slide_index = _int_or_none(block.get("slide_index"))
        cues.append({
            "id": f"editorial-slide-{index + 1:04d}",
            "start_time": _float(block.get("start_time")),
            "end_time": _float(block.get("end_time")),
            "slide_id": None,
            "slide_index": slide_index,
            "confidence": min(1.0, max(0.0, _float(block.get("confidence", 1.0)))),
            "slide_relation": str(block.get("slide_relation") or ("related" if slide_index is not None else "unrelated")),
            "review_required": bool(block.get("review_required", False)),
            "planning_status": str(block.get("planning_status") or "verified"),
            "cue_type": "lecturer_only" if slide_index is None else "semantic_block",
            "source": str(block.get("source") or "agent4_editorial_plan"),
            "strategy": "editorial_block_projection",
            "reason": str(block.get("reason") or _default_reason(slide_index, str(block.get("slide_relevance") or "none"))),
            "editorial_block_id": str(block.get("id") or ""),
        })
    return cues


def layout_cues_from_editorial_blocks(
    blocks: Iterable[dict[str, Any]],
    *,
    base_cues: Iterable[dict[str, Any]] | None = None,
    duration_seconds: float | None = None,
) -> list[dict[str, Any]]:
    """Project visual modes while retaining existing source IDs and camera settings."""
    bases = normalize_layout_cues(list(base_cues or []), duration_seconds=duration_seconds)
    projected: list[dict[str, Any]] = []
    for index, block in enumerate(blocks or []):
        start = _float(block.get("start_time"))
        end = _float(block.get("end_time"))
        layout = _layout_value(
            block.get("layout"),
            slide_index=_int_or_none(block.get("slide_index")),
            relevance=str(block.get("slide_relevance") or "none"),
        )
        base = _cue_for_editorial_block(bases, block, start)
        if base:
            cue = deepcopy(base)
            cue["id"] = f"editorial-layout-{index + 1:04d}"
            cue["layout"] = layout
            cue["start_time"] = start
            cue["end_time"] = end
            timing = dict(cue.get("timing") or {})
            timing.update(start_time=start, end_time=end, duration_seconds=round(max(0.0, end - start), 3))
            cue["timing"] = timing
        else:
            cue = build_layout_cue(
                cue_id=f"editorial-layout-{index + 1:04d}",
                layout=layout,
                start_time=start,
                end_time=end,
            )
        cue["source"] = str(block.get("source") or "agent4_editorial_plan")
        cue["reason"] = str(block.get("reason") or "Semantic editorial block")
        cue["editorial_block_id"] = str(block.get("id") or "")
        sources = dict(cue.get("sources") or {})
        screen = dict(sources.get("screen") or {})
        camera_source = dict(sources.get("camera") or {})
        screen["enabled"] = layout != LayoutMode.FULL_CAMERA_SOURCE.value
        camera_source["enabled"] = layout in {
            LayoutMode.PICTURE_IN_PICTURE.value,
            LayoutMode.SIDE_BY_SIDE.value,
            LayoutMode.FULL_CAMERA_SOURCE.value,
        }
        sources["screen"] = screen
        sources["camera"] = camera_source
        cue["sources"] = sources
        camera = dict(cue.get("camera") or {})
        camera["enabled"] = camera_source["enabled"]
        cue["camera"] = camera
        projected.append(cue)
    return normalize_layout_cues(projected, duration_seconds=duration_seconds)


def _layout_value(value: Any, *, slide_index: int | None, relevance: str) -> str:
    aliases = {
        "pip_slide": LayoutMode.PICTURE_IN_PICTURE.value,
        "full_slide": LayoutMode.FULL_SCREEN_SOURCE.value,
        "half_half": LayoutMode.SIDE_BY_SIDE.value,
        "full_face": LayoutMode.FULL_CAMERA_SOURCE.value,
    }
    candidate = aliases.get(str(value or "").lower(), str(value or "").lower())
    if candidate in VALID_LAYOUTS:
        return candidate
    if slide_index is None:
        return LayoutMode.FULL_CAMERA_SOURCE.value
    if relevance == "critical":
        return LayoutMode.FULL_SCREEN_SOURCE.value
    return LayoutMode.PICTURE_IN_PICTURE.value


def _cover_gaps(blocks: list[dict[str, Any]], duration: float) -> list[dict[str, Any]]:
    if not duration:
        return blocks
    covered: list[dict[str, Any]] = []
    cursor = 0.0
    gap_index = 0
    for block in blocks:
        start = max(cursor, _float(block.get("start_time")))
        end = min(duration, max(start, _float(block.get("end_time"))))
        gap_duration = start - cursor
        if gap_duration >= MIN_AUTOMATIC_VISUAL_BLOCK_SECONDS:
            gap_index += 1
            covered.append(_lecturer_block(cursor, start, gap_index))
        elif gap_duration >= 0.05:
            if covered:
                covered[-1]["end_time"] = round(start, 3)
            else:
                start = 0.0
        if end - start >= 0.05:
            copied = dict(block)
            copied["start_time"] = round(start, 3)
            copied["end_time"] = round(end, 3)
            covered.append(copied)
            cursor = end
    trailing_gap = duration - cursor
    if trailing_gap >= MIN_AUTOMATIC_VISUAL_BLOCK_SECONDS:
        covered.append(_lecturer_block(cursor, duration, gap_index + 1))
    elif trailing_gap >= 0.05 and covered:
        covered[-1]["end_time"] = round(duration, 3)
    return covered


def _stabilize_automatic_micro_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Absorb generated visual flashes without changing teacher-authored ranges."""
    stable = [dict(block) for block in blocks]
    index = 0
    while index < len(stable):
        block = stable[index]
        duration = _float(block.get("end_time")) - _float(block.get("start_time"))
        if duration >= MIN_AUTOMATIC_VISUAL_BLOCK_SECONDS or not _is_automatic_coverage_block(block):
            index += 1
            continue

        previous = stable[index - 1] if index > 0 else None
        following = stable[index + 1] if index + 1 < len(stable) else None
        if previous is not None:
            previous["end_time"] = block["end_time"]
            if following is not None:
                following["start_time"] = block["end_time"]
        elif following is not None:
            following["start_time"] = block["start_time"]
        stable.pop(index)
    return stable


def _is_automatic_coverage_block(block: dict[str, Any]) -> bool:
    if block.get("teacher_modified"):
        return False
    block_id = str(block.get("id") or "")
    source = str(block.get("source") or "")
    return block_id.startswith("editorial-gap-") or (
        source == "semantic_relevance_gate"
        and not str(block.get("transcript_excerpt") or "").strip()
    )


def _lecturer_block(start: float, end: float, index: int) -> dict[str, Any]:
    return {
        "id": f"editorial-gap-{index:04d}",
        "schema_version": EDITORIAL_PLAN_VERSION,
        "start_time": round(start, 3),
        "end_time": round(end, 3),
        "title": "Lecturer context",
        "summary": "No slide is sufficiently relevant for this speech range.",
        "transcript_excerpt": "",
        "slide_index": None,
        "slide_relevance": "none",
        "slide_relation": "unrelated",
        "layout": LayoutMode.FULL_CAMERA_SOURCE.value,
        "confidence": 1.0,
        "reason": "No relevant teaching slide; keep the lecturer visible",
        "source": "semantic_relevance_gate",
        "review_required": False,
        "planning_status": "verified",
        "teacher_modified": False,
    }


def _merge_adjacent_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for block in blocks:
        can_merge = (
            merged
            and _same_visual_decision(merged[-1], block)
            and not merged[-1].get("teacher_modified")
            and not block.get("teacher_modified")
            and _float(block.get("end_time")) - _float(merged[-1].get("start_time")) <= 120.0
        )
        if can_merge:
            previous = merged[-1]
            previous["end_time"] = block["end_time"]
            previous["summary"] = _join_text(previous.get("summary"), block.get("summary"), 900)
            previous["transcript_excerpt"] = _join_text(previous.get("transcript_excerpt"), block.get("transcript_excerpt"), 1800)
            previous["confidence"] = round(min(_float(previous.get("confidence")), _float(block.get("confidence"))), 3)
        else:
            merged.append(dict(block))
    for index, block in enumerate(merged):
        block["id"] = str(block.get("id") or f"editorial-block-{index + 1:04d}")
    return merged


def _same_visual_decision(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return (
        left.get("slide_index") == right.get("slide_index")
        and left.get("layout") == right.get("layout")
        and left.get("slide_relation") == right.get("slide_relation")
        and left.get("review_required") == right.get("review_required")
        and left.get("planning_status") == right.get("planning_status")
    )


def _cue_at(cues: list[dict[str, Any]], time_seconds: float) -> dict[str, Any] | None:
    for cue in cues:
        start = _float(cue.get("start_time", (cue.get("timing") or {}).get("start_time")))
        end_raw = cue.get("end_time", (cue.get("timing") or {}).get("end_time"))
        if time_seconds >= start and (end_raw is None or time_seconds < _float(end_raw)):
            return cue
    return cues[0] if cues else None


def _cue_for_editorial_block(
    cues: list[dict[str, Any]],
    block: dict[str, Any],
    time_seconds: float,
) -> dict[str, Any] | None:
    block_id = str(block.get("id") or "")
    if block_id:
        exact = next(
            (cue for cue in cues if str(cue.get("editorial_block_id") or "") == block_id),
            None,
        )
        if exact is not None:
            return exact
    return _cue_at(cues, time_seconds)


def _default_reason(slide_index: int | None, relevance: str) -> str:
    if slide_index is None:
        return "No relevant teaching slide; keep the lecturer visible"
    return f"Speech is {relevance}ly related to slide {slide_index + 1}"


def _join_text(left: Any, right: Any, limit: int) -> str:
    return " ".join(part for part in (str(left or "").strip(), str(right or "").strip()) if part)[:limit]


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
