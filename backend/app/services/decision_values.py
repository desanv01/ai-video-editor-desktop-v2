"""Shared normalization helpers for AI editorial decisions."""

from __future__ import annotations

from typing import Any


CONFIDENCE_LABELS = {
    "very_low": 0.15,
    "very low": 0.15,
    "low": 0.3,
    "medium_low": 0.4,
    "medium low": 0.4,
    "medium": 0.5,
    "moderate": 0.5,
    "medium_high": 0.7,
    "medium high": 0.7,
    "high": 0.85,
    "very_high": 0.95,
    "very high": 0.95,
}

RELATED_VALUES = {"related", "partial", "direct", "critical", "matched", "yes"}
UNRELATED_VALUES = {"unrelated", "none", "no", "not_related", "not related"}
UNCERTAIN_VALUES = {"uncertain", "unknown", "review", "needs_review", "needs review"}


def normalize_confidence(value: Any, default: float = 0.5) -> float:
    """Accept numeric, percentage, and common LLM label confidence values."""
    if value is None or value == "":
        return _clamp(default)
    if isinstance(value, str):
        candidate = value.strip().lower()
        if candidate in CONFIDENCE_LABELS:
            return CONFIDENCE_LABELS[candidate]
        percentage = candidate.endswith("%")
        if percentage:
            candidate = candidate[:-1].strip()
        try:
            number = float(candidate)
        except ValueError:
            return _clamp(default)
        if percentage or number > 1:
            number /= 100
        return _clamp(number)
    try:
        number = float(value)
    except (TypeError, ValueError):
        return _clamp(default)
    if number > 1:
        number /= 100
    return _clamp(number)


def normalize_slide_relation(
    value: Any,
    *,
    slide_index: int | None,
    relevance: Any = None,
) -> str:
    """Normalize the semantic relation independently from confidence."""
    candidates = [value, relevance]
    for raw in candidates:
        candidate = str(raw or "").strip().lower()
        if candidate in RELATED_VALUES:
            return "related"
        if candidate in UNRELATED_VALUES:
            return "unrelated"
        if candidate in UNCERTAIN_VALUES:
            return "uncertain"
    return "related" if slide_index is not None else "unrelated"


def _clamp(value: float) -> float:
    return min(1.0, max(0.0, value))
