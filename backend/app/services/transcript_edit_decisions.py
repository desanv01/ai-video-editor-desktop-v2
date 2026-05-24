"""Manage transcript word selections as structured edit decisions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, Iterable, Optional


TRANSCRIPT_DECISION_SCHEMA_VERSION = "phase5.transcript-decisions.v1"


def list_transcript_cut_decisions(plan: Any) -> list[dict[str, Any]]:
    """Return active transcript cut decisions stored on an edit plan."""
    if not plan:
        return []
    payload = normalize_plan_payload(plan.plan_json)
    return [
        decision
        for decision in payload.get("edit_decisions", [])
        if decision.get("kind") == "transcript_cut" and decision.get("status") == "active"
    ]


def list_active_transcript_cut_intervals(plan: Any) -> list[dict[str, Any]]:
    """Return merged active transcript cut intervals for playback/render sync."""
    decisions = sorted(
        list_transcript_cut_decisions(plan),
        key=lambda decision: (float(decision.get("start_time", 0.0)), float(decision.get("end_time", 0.0))),
    )
    intervals: list[dict[str, Any]] = []

    for decision in decisions:
        start_time = _float_value(decision.get("start_time"))
        end_time = _float_value(decision.get("end_time"))
        if end_time <= start_time:
            continue

        interval = {
            "start_time": round(start_time, 3),
            "end_time": round(end_time, 3),
            "duration": round(end_time - start_time, 3),
            "decision_ids": [decision.get("id")],
            "texts": [decision.get("text") or ""],
            "word_start_index": decision.get("word_start_index"),
            "word_end_index": decision.get("word_end_index"),
            "source": "transcript_cut",
        }

        if intervals and start_time <= intervals[-1]["end_time"]:
            current = intervals[-1]
            current["end_time"] = round(max(current["end_time"], end_time), 3)
            current["duration"] = round(current["end_time"] - current["start_time"], 3)
            current["decision_ids"].append(decision.get("id"))
            if decision.get("text"):
                current["texts"].append(decision.get("text"))
            current["word_start_index"] = _min_optional(current.get("word_start_index"), decision.get("word_start_index"))
            current["word_end_index"] = _max_optional(current.get("word_end_index"), decision.get("word_end_index"))
            continue

        intervals.append(interval)

    return intervals


def subtract_cut_intervals(
    start_time: float,
    end_time: float,
    cut_intervals: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Split a source range into playable ranges after transcript cuts."""
    start = max(float(start_time), 0.0)
    end = max(float(end_time), start)
    cursor = start
    playable: list[dict[str, Any]] = []

    for interval in sorted(cut_intervals, key=lambda item: item.get("start_time", 0.0)):
        cut_start = max(float(interval.get("start_time", 0.0)), start)
        cut_end = min(float(interval.get("end_time", 0.0)), end)
        if cut_end <= cursor or cut_start >= end:
            continue

        if cut_start > cursor:
            playable.append(_range_payload(cursor, cut_start))
        cursor = max(cursor, cut_end)

    if cursor < end:
        playable.append(_range_payload(cursor, end))

    return playable


def build_synced_timeline_plan(
    *,
    plan: Any,
    segments: Iterable[Any],
    duration_seconds: Optional[float] = None,
) -> dict[str, Any]:
    """Build one synchronized view for timeline, preview, and export planning."""
    segment_list = sorted(list(segments or []), key=lambda segment: segment.start_time)
    cut_intervals = list_active_transcript_cut_intervals(plan)
    playable_ranges: list[dict[str, Any]] = []
    segment_overlays: list[dict[str, Any]] = []
    cumulative_output_time = 0.0

    for segment in segment_list:
        final_action = _segment_final_action(segment)
        segment_start = float(segment.start_time)
        segment_end = float(segment.end_time)

        overlapping_cuts = [
            interval
            for interval in cut_intervals
            if interval["end_time"] > segment_start and interval["start_time"] < segment_end
        ]
        if overlapping_cuts:
            segment_overlays.append({
                "segment_id": str(segment.id),
                "segment_index": segment.segment_index,
                "cut_intervals": overlapping_cuts,
                "covered_duration": round(_union_duration(
                    (
                        max(segment_start, interval["start_time"]),
                        min(segment_end, interval["end_time"]),
                    )
                    for interval in overlapping_cuts
                ), 3),
            })

        if final_action == "cut":
            continue

        for playable in subtract_cut_intervals(segment_start, segment_end, cut_intervals):
            duration = playable["duration"]
            if duration <= 0:
                continue
            playable_ranges.append({
                "segment_id": str(segment.id),
                "segment_index": segment.segment_index,
                "source_start_time": playable["start_time"],
                "source_end_time": playable["end_time"],
                "duration": duration,
                "output_start_time": round(cumulative_output_time, 3),
                "output_end_time": round(cumulative_output_time + duration, 3),
                "action": final_action,
            })
            cumulative_output_time += duration

    total_cut_duration = _union_duration(
        (interval["start_time"], interval["end_time"])
        for interval in cut_intervals
    )
    base_duration = duration_seconds
    if base_duration is None and plan:
        base_duration = plan.original_duration

    return {
        "schema_version": TRANSCRIPT_DECISION_SCHEMA_VERSION,
        "cut_intervals": cut_intervals,
        "playable_ranges": playable_ranges,
        "segment_overlays": segment_overlays,
        "export_plan": {
            "source_duration_seconds": base_duration,
            "estimated_output_duration_seconds": round(cumulative_output_time, 3),
            "transcript_cut_count": len(list_transcript_cut_decisions(plan)),
            "merged_cut_interval_count": len(cut_intervals),
            "transcript_cut_duration_seconds": round(total_cut_duration, 3),
            "playable_range_count": len(playable_ranges),
        },
    }


def create_transcript_cut_decision(
    *,
    plan: Any,
    timeline_words: list[dict[str, Any]],
    word_start_index: int,
    word_end_index: int,
    teacher_note: Optional[str] = None,
) -> dict[str, Any]:
    """Create and persist a transcript cut decision from inclusive word indexes."""
    if word_start_index > word_end_index:
        word_start_index, word_end_index = word_end_index, word_start_index

    if word_start_index < 0 or word_end_index >= len(timeline_words):
        raise ValueError("Word selection is outside the transcript timeline")

    selected_words = timeline_words[word_start_index:word_end_index + 1]
    if not selected_words:
        raise ValueError("Select at least one transcript word")

    start_time = min(float(word["start_time"]) for word in selected_words)
    end_time = max(float(word["end_time"]) for word in selected_words)
    text = " ".join(str(word.get("text") or "").strip() for word in selected_words).strip()
    segment_ids = _unique_values(word.get("segment_id") for word in selected_words if word.get("segment_id"))
    segment_indexes = _unique_values(
        word.get("segment_index") for word in selected_words if word.get("segment_index") is not None
    )

    decision = {
        "id": str(uuid.uuid4()),
        "kind": "transcript_cut",
        "action": "cut",
        "source": "manual_text_selection",
        "status": "active",
        "text": text,
        "start_time": round(start_time, 3),
        "end_time": round(end_time, 3),
        "duration": round(max(0.0, end_time - start_time), 3),
        "word_start_index": word_start_index,
        "word_end_index": word_end_index,
        "segment_ids": segment_ids,
        "segment_indexes": segment_indexes,
        "teacher_note": teacher_note,
        "created_at": _utc_now(),
    }

    payload = normalize_plan_payload(plan.plan_json)
    payload.setdefault("edit_decisions", []).append(decision)
    _refresh_transcript_cut_summary(payload, plan)
    plan.plan_json = payload
    return decision


def remove_transcript_cut_decision(*, plan: Any, decision_id: str) -> bool:
    """Mark a transcript cut decision inactive and refresh summary metrics."""
    payload = normalize_plan_payload(plan.plan_json)
    removed = False
    for decision in payload.get("edit_decisions", []):
        if decision.get("id") == decision_id and decision.get("kind") == "transcript_cut":
            decision["status"] = "removed"
            decision["removed_at"] = _utc_now()
            removed = True
            break

    if removed:
        _refresh_transcript_cut_summary(payload, plan)
        plan.plan_json = payload

    return removed


def normalize_plan_payload(plan_json: Any) -> dict[str, Any]:
    """Preserve legacy list-shaped plans while adding decision metadata."""
    if isinstance(plan_json, dict):
        payload = dict(plan_json)
        payload.setdefault("schema_version", TRANSCRIPT_DECISION_SCHEMA_VERSION)
        payload.setdefault("segments", [])
        payload.setdefault("edit_decisions", [])
        return payload

    return {
        "schema_version": TRANSCRIPT_DECISION_SCHEMA_VERSION,
        "segments": list(plan_json or []) if isinstance(plan_json, list) else [],
        "edit_decisions": [],
    }


def _refresh_transcript_cut_summary(payload: dict[str, Any], plan: Any) -> None:
    active_cuts = [
        decision
        for decision in payload.get("edit_decisions", [])
        if decision.get("kind") == "transcript_cut" and decision.get("status") == "active"
    ]
    total_duration = _union_duration(
        (float(cut.get("start_time", 0.0)), float(cut.get("end_time", 0.0)))
        for cut in active_cuts
    )

    summary = payload.get("transcript_edit_summary") or {}
    base_estimated = summary.get("base_estimated_duration_seconds")
    if base_estimated is None:
        base_estimated = plan.estimated_duration if plan.estimated_duration is not None else plan.original_duration

    summary.update({
        "cut_count": len(active_cuts),
        "total_cut_duration_seconds": round(total_duration, 3),
        "base_estimated_duration_seconds": base_estimated,
        "updated_at": _utc_now(),
    })
    payload["transcript_edit_summary"] = summary

    if base_estimated is not None:
        plan.estimated_duration = round(max(0.0, float(base_estimated) - total_duration), 1)


def _union_duration(intervals: Iterable[tuple[float, float]]) -> float:
    normalized = sorted((start, end) for start, end in intervals if end > start)
    if not normalized:
        return 0.0

    merged: list[tuple[float, float]] = []
    for start, end in normalized:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
            continue
        merged[-1] = (merged[-1][0], max(merged[-1][1], end))

    return sum(end - start for start, end in merged)


def _range_payload(start_time: float, end_time: float) -> dict[str, Any]:
    return {
        "start_time": round(start_time, 3),
        "end_time": round(end_time, 3),
        "duration": round(max(0.0, end_time - start_time), 3),
    }


def _segment_final_action(segment: Any) -> str:
    action = segment.teacher_action if segment.is_teacher_modified and segment.teacher_action else segment.action
    return getattr(action, "value", action or "keep")


def _float_value(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _min_optional(left: Any, right: Any) -> Any:
    if left is None:
        return right
    if right is None:
        return left
    return min(left, right)


def _max_optional(left: Any, right: Any) -> Any:
    if left is None:
        return right
    if right is None:
        return left
    return max(left, right)


def _unique_values(values: Iterable[Any]) -> list[Any]:
    seen = set()
    unique = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
