"""Rule-based lecture topic and section segmentation."""

from __future__ import annotations

import re
from typing import Any, Iterable


SECTION_SCHEMA_VERSION = "phase6.topic-segmentation.v1"

PAUSE_BOUNDARY_SECONDS = 2.0
STRONG_PAUSE_SECONDS = 4.0
CONTENT_SHIFT_THRESHOLD = 0.72
MIN_BOUNDARY_SPACING_SECONDS = 30.0

GENERIC_TOPICS = {"", "unknown", "general", "topic", "lecture", "content"}
TRANSITION_CUES = (
    "next",
    "now",
    "moving on",
    "let's move",
    "lets move",
    "let us move",
    "in this section",
    "the next part",
    "we will now",
    "to summarize",
    "finally",
)
STOPWORDS = {
    "a",
    "about",
    "after",
    "again",
    "all",
    "also",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "because",
    "by",
    "can",
    "for",
    "from",
    "how",
    "if",
    "in",
    "into",
    "is",
    "it",
    "let",
    "now",
    "of",
    "on",
    "or",
    "our",
    "so",
    "that",
    "the",
    "then",
    "this",
    "to",
    "today",
    "we",
    "what",
    "when",
    "with",
    "you",
    "your",
}


def analyze_topic_sections(
    *,
    segments: Iterable[Any],
    timeline_words: Iterable[dict[str, Any]] | None = None,
    duration_seconds: float | None = None,
) -> dict[str, Any]:
    """Generate suggested lecture sections from transcript content and pauses."""
    segment_list = [
        segment
        for segment in sorted(list(segments or []), key=lambda item: item.segment_index)
        if _final_action(segment) != "cut"
    ]
    words = list(timeline_words or [])
    if not segment_list:
        return {
            "schema_version": SECTION_SCHEMA_VERSION,
            "summary": _summary([]),
            "sections": [],
            "chapters": [],
            "youtube_format": "",
        }

    boundaries = _detect_boundaries(segment_list, words)
    sections = _build_sections(segment_list, boundaries, duration_seconds, words)
    chapters = [_chapter_from_section(section) for section in sections]

    return {
        "schema_version": SECTION_SCHEMA_VERSION,
        "summary": _summary(sections),
        "sections": sections,
        "chapters": chapters,
        "youtube_format": "\n".join(
            f"{chapter['formatted']} {chapter['label']}" for chapter in chapters
        ),
    }


def _detect_boundaries(segments: list[Any], words: list[dict[str, Any]]) -> list[dict[str, Any]]:
    boundaries: list[dict[str, Any]] = [
        {
            "segment_index": segments[0].segment_index,
            "confidence": 1.0,
            "reason": "Lecture start",
            "signals": {
                "topic_change": False,
                "long_pause": False,
                "content_shift": False,
                "transition_cue": False,
                "pause_seconds": 0.0,
                "content_shift_score": 0.0,
            },
        }
    ]
    last_boundary_time = float(segments[0].start_time or 0.0)

    for previous, current in zip(segments, segments[1:]):
        candidate = _boundary_candidate(previous, current, words)
        if not candidate["is_boundary"]:
            continue

        elapsed = float(current.start_time or 0.0) - last_boundary_time
        if elapsed < MIN_BOUNDARY_SPACING_SECONDS and candidate["confidence"] < 0.72:
            continue

        boundaries.append({
            "segment_index": current.segment_index,
            "confidence": candidate["confidence"],
            "reason": candidate["reason"],
            "signals": candidate["signals"],
        })
        last_boundary_time = float(current.start_time or 0.0)

    return boundaries


def _boundary_candidate(previous: Any, current: Any, words: list[dict[str, Any]]) -> dict[str, Any]:
    previous_topic = _normalize_topic(getattr(previous, "topic_label", None))
    current_topic = _normalize_topic(getattr(current, "topic_label", None))
    topic_change = bool(current_topic and previous_topic and current_topic != previous_topic)

    speech_gap = max(0.0, float(current.start_time or 0.0) - float(previous.end_time or 0.0))
    pause_seconds = max(speech_gap, float(getattr(previous, "pause_duration_total", 0.0) or 0.0))
    long_pause = pause_seconds >= PAUSE_BOUNDARY_SECONDS
    strong_pause = pause_seconds >= STRONG_PAUSE_SECONDS

    previous_tokens = _segment_tokens(previous, words)
    current_tokens = _segment_tokens(current, words)
    content_shift_score = _content_shift(previous_tokens, current_tokens)
    content_shift = (
        len(previous_tokens) >= 3
        and len(current_tokens) >= 3
        and content_shift_score >= CONTENT_SHIFT_THRESHOLD
    )
    transition_cue = _has_transition_cue(getattr(current, "text", "") or "")

    score = 0.0
    reasons: list[str] = []
    if topic_change:
        score += 0.38
        reasons.append("topic label changed")
    if long_pause:
        score += 0.22 if strong_pause else 0.14
        reasons.append(f"{pause_seconds:.1f}s pause")
    if content_shift:
        score += min(0.28, content_shift_score * 0.28)
        reasons.append("transcript vocabulary shifted")
    if transition_cue:
        score += 0.2
        reasons.append("teacher transition phrase")

    is_boundary = score >= 0.46 or strong_pause or (topic_change and (long_pause or content_shift))
    return {
        "is_boundary": is_boundary,
        "confidence": round(min(0.96, max(0.35, score)), 3),
        "reason": "; ".join(reasons) if reasons else "continued topic",
        "signals": {
            "topic_change": topic_change,
            "long_pause": long_pause,
            "content_shift": content_shift,
            "transition_cue": transition_cue,
            "pause_seconds": round(pause_seconds, 3),
            "content_shift_score": round(content_shift_score, 3),
        },
    }


def _build_sections(
    segments: list[Any],
    boundaries: list[dict[str, Any]],
    duration_seconds: float | None,
    words: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    segment_by_index = {segment.segment_index: segment for segment in segments}
    sections: list[dict[str, Any]] = []

    for index, boundary in enumerate(boundaries):
        start_segment = segment_by_index[boundary["segment_index"]]
        next_boundary = boundaries[index + 1] if index + 1 < len(boundaries) else None
        end_index = next_boundary["segment_index"] if next_boundary else None
        section_segments = [
            segment
            for segment in segments
            if segment.segment_index >= start_segment.segment_index
            and (end_index is None or segment.segment_index < end_index)
        ]
        if not section_segments:
            continue

        start_time = float(section_segments[0].start_time or 0.0)
        end_time = _section_end_time(section_segments, duration_seconds)
        keywords = _section_keywords(section_segments, words)
        label = _section_label(section_segments, keywords, index + 1)

        sections.append({
            "id": f"section-{index + 1:02d}-{section_segments[0].segment_index}",
            "chapter_index": index + 1,
            "timestamp": round(start_time, 3),
            "formatted": _format_timestamp(start_time),
            "label": label,
            "title": label,
            "summary": _section_summary(section_segments),
            "start_time": round(start_time, 3),
            "end_time": round(end_time, 3),
            "duration": round(max(0.0, end_time - start_time), 3),
            "segment_start_index": section_segments[0].segment_index,
            "segment_end_index": section_segments[-1].segment_index,
            "segment_index": section_segments[0].segment_index,
            "segment_indexes": [segment.segment_index for segment in section_segments],
            "segment_count": len(section_segments),
            "keywords": keywords,
            "confidence": boundary["confidence"],
            "boundary_reason": boundary["reason"],
            "source_signals": boundary["signals"],
        })

    return sections


def _chapter_from_section(section: dict[str, Any]) -> dict[str, Any]:
    return {
        "timestamp": section["timestamp"],
        "formatted": section["formatted"],
        "label": section["label"],
        "segment_index": section["segment_index"],
        "duration": section["duration"],
        "confidence": section["confidence"],
        "boundary_reason": section["boundary_reason"],
        "keywords": section["keywords"],
        "segment_count": section["segment_count"],
    }


def _summary(sections: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "sections_total": len(sections),
        "chapters_total": len(sections),
        "average_confidence": round(
            sum(float(section.get("confidence") or 0.0) for section in sections) / len(sections),
            3,
        )
        if sections
        else 0.0,
        "estimated_total_duration_seconds": round(
            sum(float(section.get("duration") or 0.0) for section in sections),
            3,
        ),
    }


def _section_end_time(section_segments: list[Any], duration_seconds: float | None) -> float:
    end_time = max(float(segment.end_time or 0.0) for segment in section_segments)
    if duration_seconds is None:
        return end_time
    return min(max(end_time, 0.0), float(duration_seconds))


def _section_label(section_segments: list[Any], keywords: list[str], index: int) -> str:
    topic_counts: dict[str, int] = {}
    for segment in section_segments:
        topic = _normalize_topic(getattr(segment, "topic_label", None))
        if topic:
            label = _clean_label(getattr(segment, "topic_label", "") or "")
            topic_counts[label] = topic_counts.get(label, 0) + 1

    if topic_counts:
        return max(topic_counts.items(), key=lambda item: (item[1], len(item[0])))[0]
    if keywords:
        return " ".join(word.capitalize() for word in keywords[:3])
    return f"Section {index}"


def _section_summary(section_segments: list[Any]) -> str:
    summaries = [
        str(getattr(segment, "summary", "") or "").strip()
        for segment in section_segments
        if str(getattr(segment, "summary", "") or "").strip()
    ]
    if summaries:
        return _clip_text(summaries[0], 180)
    return _clip_text(" ".join(str(getattr(segment, "text", "") or "") for segment in section_segments), 180)


def _section_keywords(section_segments: list[Any], words: list[dict[str, Any]]) -> list[str]:
    counts: dict[str, int] = {}
    section_indexes = {segment.segment_index for segment in section_segments}
    for word in words:
        if word.get("segment_index") not in section_indexes:
            continue
        for token in _content_tokens(word.get("text")):
            counts[token] = counts.get(token, 0) + 2

    for segment in section_segments:
        for token in _content_tokens(
            " ".join(
                str(value or "")
                for value in (
                    getattr(segment, "topic_label", None),
                    getattr(segment, "summary", None),
                    getattr(segment, "text", None),
                )
            )
        ):
            counts[token] = counts.get(token, 0) + 1

    return [
        token
        for token, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:6]
    ]


def _segment_tokens(segment: Any, words: list[dict[str, Any]]) -> set[str]:
    segment_words = [
        word.get("text")
        for word in words
        if word.get("segment_index") == getattr(segment, "segment_index", None)
    ]
    if segment_words:
        return _content_tokens(" ".join(str(word) for word in segment_words))

    return _content_tokens(
        " ".join(
            str(value or "")
            for value in (
                getattr(segment, "topic_label", None),
                getattr(segment, "summary", None),
                getattr(segment, "text", None),
            )
        )
    )


def _content_tokens(value: Any) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9']+", str(value or "").lower())
        if token not in STOPWORDS and len(token) > 2
    }


def _content_shift(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    overlap = len(left & right) / len(left | right)
    return 1.0 - overlap


def _has_transition_cue(text: str) -> bool:
    normalized = " ".join(str(text or "").lower().split())
    return any(normalized.startswith(cue) or f" {cue} " in f" {normalized} " for cue in TRANSITION_CUES)


def _normalize_topic(value: Any) -> str:
    topic = _clean_label(value).lower()
    return "" if topic in GENERIC_TOPICS else topic


def _clean_label(value: Any) -> str:
    text = " ".join(str(value or "").strip().split())
    return text[:80]


def _clip_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def _format_timestamp(seconds: float) -> str:
    safe_seconds = max(0, int(seconds))
    hours = safe_seconds // 3600
    minutes = (safe_seconds % 3600) // 60
    remaining = safe_seconds % 60
    if hours:
        return f"{hours:02d}:{minutes:02d}:{remaining:02d}"
    return f"{minutes:02d}:{remaining:02d}"


def _final_action(segment: Any) -> str:
    action = getattr(segment, "teacher_action", None) if getattr(segment, "is_teacher_modified", False) else None
    action = action or getattr(segment, "action", None)
    return getattr(action, "value", action) or "keep"
