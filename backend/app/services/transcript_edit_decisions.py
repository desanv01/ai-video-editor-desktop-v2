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
