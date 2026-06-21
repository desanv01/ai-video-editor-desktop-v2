"""Rule-based lecture topic and section segmentation."""

from __future__ import annotations

import re
from typing import Any, Iterable


SECTION_SCHEMA_VERSION = "phase6.slide-aware-segmentation.v2"

PAUSE_BOUNDARY_SECONDS = 2.0
STRONG_PAUSE_SECONDS = 4.0
CONTENT_SHIFT_THRESHOLD = 0.72
MIN_BOUNDARY_SPACING_SECONDS = 30.0
SLIDE_BOUNDARY_SPACING_SECONDS = 8.0
STRUCTURE_MATCH_THRESHOLD = 0.18
PROJECT_TYPE_SECTION_PROFILES = {
    "lecture": {
        "label": "Lecture",
        "max_section_duration_seconds": 10 * 60,
        "duration_boundary_confidence": 0.58,
    },
    "mooc": {
        "label": "MOOC",
        "max_section_duration_seconds": 8 * 60,
        "duration_boundary_confidence": 0.68,
    },
    "tutorial": {
        "label": "Tutorial",
        "max_section_duration_seconds": 5 * 60,
        "duration_boundary_confidence": 0.66,
    },
    "workshop": {
        "label": "Workshop",
        "max_section_duration_seconds": 12 * 60,
        "duration_boundary_confidence": 0.52,
    },
}

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
    structure_references: Iterable[dict[str, Any]] | None = None,
    project_type: str | None = None,
) -> dict[str, Any]:
    """Generate suggested lecture sections from transcript, visual, and teaching material cues."""
    profile = _project_type_profile(project_type)
    segment_list = [
        segment
        for segment in sorted(list(segments or []), key=lambda item: item.segment_index)
        if _final_action(segment) != "cut"
    ]
    words = list(timeline_words or [])
    references = _normalize_structure_references(structure_references)
    if not segment_list:
        return {
            "schema_version": SECTION_SCHEMA_VERSION,
            "summary": _summary([]),
            "sections": [],
            "chapters": [],
            "youtube_format": "",
        }

    boundaries = _detect_boundaries(segment_list, words, references)
    boundaries = _enforce_project_type_duration_boundaries(segment_list, boundaries, profile)
    sections = _build_sections(segment_list, boundaries, duration_seconds, words, references)
    chapters = [_chapter_from_section(section) for section in sections]

    return {
        "schema_version": SECTION_SCHEMA_VERSION,
        "summary": _summary(sections, references, profile),
        "sections": sections,
        "chapters": chapters,
        "youtube_format": "\n".join(
            f"{chapter['formatted']} {chapter['label']}" for chapter in chapters
        ),
    }


def _detect_boundaries(
    segments: list[Any],
    words: list[dict[str, Any]],
    references: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    start_match = _best_structure_match(segments[0], words, references)
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
                "slide_change": bool(getattr(segments[0], "has_slide_change", False)),
                "structure_title_change": False,
                "pause_seconds": 0.0,
                "content_shift_score": 0.0,
                "structure_match_confidence": start_match["confidence"] if start_match else 0.0,
                "structure_title": start_match["title"] if start_match else None,
                "structure_reference_role": start_match["reference_role"] if start_match else None,
            },
            "structure_match": start_match,
        }
    ]
    last_boundary_time = float(segments[0].start_time or 0.0)

    for previous, current in zip(segments, segments[1:]):
        candidate = _boundary_candidate(previous, current, words, references)
        if not candidate["is_boundary"]:
            continue

        elapsed = float(current.start_time or 0.0) - last_boundary_time
        is_slide_structure_boundary = (
            candidate["signals"]["slide_change"]
            and candidate["signals"]["structure_title_change"]
            and elapsed >= SLIDE_BOUNDARY_SPACING_SECONDS
        )
        if (
            elapsed < MIN_BOUNDARY_SPACING_SECONDS
            and candidate["confidence"] < 0.72
            and not is_slide_structure_boundary
        ):
            continue

        boundaries.append({
            "segment_index": current.segment_index,
            "confidence": candidate["confidence"],
            "reason": candidate["reason"],
            "signals": candidate["signals"],
            "structure_match": candidate["structure_match"],
        })
        last_boundary_time = float(current.start_time or 0.0)

    return boundaries


def _project_type_profile(project_type: str | None) -> dict[str, Any]:
    key = str(project_type or "lecture").strip().lower().replace("-", "_")
    profile = PROJECT_TYPE_SECTION_PROFILES.get(key) or PROJECT_TYPE_SECTION_PROFILES["lecture"]
    return {"id": key if key in PROJECT_TYPE_SECTION_PROFILES else "lecture", **profile}


def _enforce_project_type_duration_boundaries(
    segments: list[Any],
    boundaries: list[dict[str, Any]],
    profile: dict[str, Any],
) -> list[dict[str, Any]]:
    max_duration = float(profile["max_section_duration_seconds"])
    if max_duration <= 0 or len(segments) < 2:
        return boundaries

    boundaries_by_index = {int(boundary["segment_index"]): dict(boundary) for boundary in boundaries}
    ordered = sorted(segments, key=lambda segment: segment.segment_index)
    section_start = ordered[0]

    for segment in ordered[1:]:
        segment_index = int(segment.segment_index)
        if segment_index in boundaries_by_index:
            section_start = segment
            continue

        elapsed = float(segment.start_time or 0.0) - float(section_start.start_time or 0.0)
        if elapsed < max_duration:
            continue

        boundaries_by_index[segment_index] = {
            "segment_index": segment.segment_index,
            "confidence": profile["duration_boundary_confidence"],
            "reason": (
                f"{profile['label']} target section duration reached "
                f"({int(max_duration // 60)} min)"
            ),
            "signals": {
                "topic_change": False,
                "long_pause": False,
                "content_shift": False,
                "transition_cue": False,
                "slide_change": bool(getattr(segment, "has_slide_change", False)),
                "structure_title_change": False,
                "pause_seconds": 0.0,
                "content_shift_score": 0.0,
                "structure_match_confidence": 0.0,
                "structure_title": None,
                "structure_reference_role": None,
                "duration_target": True,
                "project_type": profile["id"],
                "max_section_duration_seconds": max_duration,
            },
            "structure_match": None,
        }
        section_start = segment

    return [boundaries_by_index[index] for index in sorted(boundaries_by_index)]


def _boundary_candidate(
    previous: Any,
    current: Any,
    words: list[dict[str, Any]],
    references: list[dict[str, Any]],
) -> dict[str, Any]:
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
    slide_change = _has_slide_change(previous, current)
    previous_structure = _best_structure_match(previous, words, references)
    current_structure = _best_structure_match(current, words, references)
    structure_title_change = _structure_title_changed(previous_structure, current_structure)

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
    if slide_change:
        score += 0.2
        reasons.append("slide changed")
    if structure_title_change and current_structure:
        score += 0.28
        reasons.append(f"teaching material title changed to {_clean_label(current_structure['title'])}")

    is_boundary = (
        score >= 0.46
        or strong_pause
        or (slide_change and structure_title_change)
        or (topic_change and (long_pause or content_shift))
    )
    return {
        "is_boundary": is_boundary,
        "confidence": round(min(0.96, max(0.35, score)), 3),
        "reason": "; ".join(reasons) if reasons else "continued topic",
        "signals": {
            "topic_change": topic_change,
            "long_pause": long_pause,
            "content_shift": content_shift,
            "transition_cue": transition_cue,
            "slide_change": slide_change,
            "structure_title_change": structure_title_change,
            "pause_seconds": round(pause_seconds, 3),
            "content_shift_score": round(content_shift_score, 3),
            "structure_match_confidence": current_structure["confidence"] if current_structure else 0.0,
            "structure_title": current_structure["title"] if current_structure else None,
            "structure_reference_role": current_structure["reference_role"] if current_structure else None,
        },
        "structure_match": current_structure,
    }


def _build_sections(
    segments: list[Any],
    boundaries: list[dict[str, Any]],
    duration_seconds: float | None,
    words: list[dict[str, Any]],
    references: list[dict[str, Any]],
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
        structure_match = _section_structure_match(
            section_segments,
            boundary.get("structure_match"),
            words,
            references,
        )
        label = _section_label(section_segments, keywords, index + 1, structure_match)

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
            "label_source": "teaching_material" if structure_match else "transcript",
            "structure_reference": structure_match,
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
        "structure_reference": section.get("structure_reference"),
    }


def _summary(
    sections: list[dict[str, Any]],
    references: list[dict[str, Any]] | None = None,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    profile_payload = profile or _project_type_profile(None)
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
        "structure_reference_count": len(references or []),
        "slide_aware_sections": sum(
            1
            for section in sections
            if section.get("structure_reference")
            or (section.get("source_signals") or {}).get("slide_change")
        ),
        "project_type": profile_payload["id"],
        "target_section_duration_seconds": profile_payload["max_section_duration_seconds"],
    }


def _section_end_time(section_segments: list[Any], duration_seconds: float | None) -> float:
    end_time = max(float(segment.end_time or 0.0) for segment in section_segments)
    if duration_seconds is None:
        return end_time
    return min(max(end_time, 0.0), float(duration_seconds))


def _section_label(
    section_segments: list[Any],
    keywords: list[str],
    index: int,
    structure_match: dict[str, Any] | None = None,
) -> str:
    if structure_match and structure_match.get("title"):
        return _clean_label(structure_match["title"])

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


def _section_structure_match(
    section_segments: list[Any],
    boundary_match: dict[str, Any] | None,
    words: list[dict[str, Any]],
    references: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if boundary_match:
        return boundary_match

    matches = [
        match
        for segment in section_segments
        if (match := _best_structure_match(segment, words, references))
    ]
    if not matches:
        return None
    return max(matches, key=lambda item: item.get("confidence", 0.0))


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


def _normalize_structure_references(
    structure_references: Iterable[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    for reference in structure_references or []:
        if not isinstance(reference, dict):
            continue
        items = []
        for item in reference.get("items") or reference.get("titles") or []:
            normalized = _normalize_structure_item(item, reference)
            if normalized:
                items.append(normalized)
        if items:
            references.append({
                "asset_id": reference.get("asset_id"),
                "source_filename": reference.get("source_filename") or reference.get("filename"),
                "reference_role": reference.get("reference_role")
                or reference.get("structure_reference_role")
                or reference.get("role")
                or "teaching_material",
                "document_format": reference.get("document_format") or reference.get("file_type"),
                "title": _clean_label(reference.get("title")),
                "items": items,
            })
    return references


def _normalize_structure_item(
    item: Any,
    reference: dict[str, Any],
) -> dict[str, Any] | None:
    if isinstance(item, str):
        raw = {"title": item}
    elif isinstance(item, dict):
        raw = item
    else:
        return None

    title = _first_non_empty(
        raw.get("title"),
        raw.get("heading"),
        raw.get("label"),
        _first_line(raw.get("text")),
    )
    text = _first_non_empty(raw.get("text"), raw.get("summary"), title)
    if not title and not text:
        return None

    index = raw.get("index", raw.get("slide_index", raw.get("page_num", raw.get("page"))))
    try:
        item_index = int(index) if index is not None else None
    except (TypeError, ValueError):
        item_index = None

    tokens = _content_tokens(" ".join(str(value or "") for value in (title, text)))
    if not tokens:
        return None

    return {
        "asset_id": reference.get("asset_id"),
        "source_filename": reference.get("source_filename") or reference.get("filename"),
        "reference_role": reference.get("reference_role")
        or reference.get("structure_reference_role")
        or reference.get("role")
        or "teaching_material",
        "document_format": reference.get("document_format") or reference.get("file_type"),
        "index": item_index,
        "title": _clean_label(title),
        "text": _clip_text(text, 260),
        "tokens": tokens,
    }


def _best_structure_match(
    segment: Any,
    words: list[dict[str, Any]],
    references: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not references:
        return None

    segment_index = getattr(segment, "segment_index", None)
    segment_words = " ".join(
        str(word.get("text") or "")
        for word in words
        if word.get("segment_index") == segment_index
    )
    segment_text = " ".join(
        str(value or "")
        for value in (
            getattr(segment, "topic_label", None),
            getattr(segment, "summary", None),
            getattr(segment, "text", None),
            segment_words,
        )
    )
    segment_tokens = _content_tokens(segment_text)
    slide_index = getattr(segment, "slide_index", None)

    best: dict[str, Any] | None = None
    best_score = 0.0
    for reference in references:
        for item in reference["items"]:
            index_score = _structure_index_score(slide_index, item.get("index"))
            overlap_score = _structure_overlap_score(segment_tokens, item["tokens"])
            score = max(index_score, overlap_score)
            if index_score and overlap_score:
                score = min(1.0, score + 0.12)
            if score > best_score:
                best_score = score
                best = item

    if not best or best_score < STRUCTURE_MATCH_THRESHOLD:
        return None

    return {
        "asset_id": best.get("asset_id"),
        "source_filename": best.get("source_filename"),
        "reference_role": best.get("reference_role"),
        "document_format": best.get("document_format"),
        "index": best.get("index"),
        "title": best.get("title"),
        "confidence": round(min(0.98, best_score), 3),
    }


def _structure_index_score(slide_index: Any, structure_index: int | None) -> float:
    if slide_index is None or structure_index is None:
        return 0.0
    try:
        slide = int(slide_index)
    except (TypeError, ValueError):
        return 0.0
    if slide == structure_index:
        return 0.95
    if slide + 1 == structure_index:
        return 0.9
    return 0.0


def _structure_overlap_score(segment_tokens: set[str], item_tokens: set[str]) -> float:
    if not segment_tokens or not item_tokens:
        return 0.0
    overlap = len(segment_tokens & item_tokens)
    if overlap == 0:
        return 0.0
    return min(0.86, overlap / max(3, min(len(item_tokens), 8)))


def _has_slide_change(previous: Any, current: Any) -> bool:
    if bool(getattr(current, "has_slide_change", False)):
        return True
    previous_index = getattr(previous, "slide_index", None)
    current_index = getattr(current, "slide_index", None)
    return previous_index is not None and current_index is not None and previous_index != current_index


def _structure_title_changed(
    previous: dict[str, Any] | None,
    current: dict[str, Any] | None,
) -> bool:
    if not current:
        return False
    if not previous:
        return True
    return (
        current.get("asset_id"),
        current.get("index"),
        _normalize_topic(current.get("title")),
    ) != (
        previous.get("asset_id"),
        previous.get("index"),
        _normalize_topic(previous.get("title")),
    )


def _has_transition_cue(text: str) -> bool:
    normalized = " ".join(str(text or "").lower().split())
    return any(normalized.startswith(cue) or f" {cue} " in f" {normalized} " for cue in TRANSITION_CUES)


def _normalize_topic(value: Any) -> str:
    topic = _clean_label(value).lower()
    return "" if topic in GENERIC_TOPICS else topic


def _clean_label(value: Any) -> str:
    text = " ".join(str(value or "").strip().split())
    return text[:80]


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = " ".join(str(value or "").strip().split())
        if text:
            return text
    return ""


def _first_line(value: Any) -> str:
    for line in str(value or "").splitlines():
        text = line.strip()
        if text:
            return text
    return ""


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
