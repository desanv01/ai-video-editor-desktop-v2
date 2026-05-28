"""Build word-level transcript timelines from stored ASR output.

The database already stores raw provider words and transcript segments as JSON.
This module turns those provider-shaped payloads into stable app structures
that can be used by transcript editing without changing the existing
segment-level review model.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Optional


WORD_RE = re.compile(r"\S+")


def build_transcript_timeline(
    *,
    video_id: Any,
    transcript: Any,
    review_segments: Iterable[Any],
    duration_seconds: Optional[float] = None,
) -> dict[str, Any]:
    """Return a word timeline mapped onto the existing review segments."""
    stored_segments = list(transcript.segments_json or [])
    segments = sorted(list(review_segments), key=lambda segment: segment.start_time)
    words = normalize_transcript_words(
        transcript.words_json or [],
        stored_segments,
        duration_seconds=duration_seconds,
    )

    _attach_review_segment_refs(words, segments)
    timeline_segments = _build_review_segment_ranges(segments, words)

    return {
        "video_id": video_id,
        "transcript_id": transcript.id,
        "full_text": transcript.full_text,
        "language": transcript.language,
        "asr_provider": transcript.asr_provider,
        "duration_seconds": duration_seconds,
        "word_count": len(words),
        "words": words,
        "segments": timeline_segments,
    }


def normalize_transcript_words(
    raw_words: Iterable[dict[str, Any]],
    transcript_segments: Iterable[dict[str, Any]],
    *,
    duration_seconds: Optional[float] = None,
) -> list[dict[str, Any]]:
    """Normalize provider words, estimating from segments only when needed."""
    words = [
        normalized
        for index, raw_word in enumerate(raw_words or [])
        if (normalized := _normalize_word(raw_word, index)) is not None
    ]

    if not words:
        words = _estimate_words_from_segments(transcript_segments)

    words.sort(key=lambda item: (item["start_time"], item["end_time"], item["word_index"]))
    for next_index, word in enumerate(words):
        word["word_index"] = next_index
        _clamp_word_bounds(word, duration_seconds)

    _attach_transcript_segment_refs(words, list(transcript_segments or []))
    return words


def _normalize_word(raw_word: dict[str, Any], index: int) -> Optional[dict[str, Any]]:
    text = str(raw_word.get("word") or raw_word.get("text") or "").strip()
    if not text:
        return None

    start = _float_or_none(raw_word.get("start", raw_word.get("start_time")))
    end = _float_or_none(raw_word.get("end", raw_word.get("end_time")))
    if start is None and end is None:
        return None

    start_time = max(float(start or 0.0), 0.0)
    end_time = max(float(end if end is not None else start_time), start_time)
    return {
        "word_index": index,
        "text": text,
        "start_time": start_time,
        "end_time": end_time,
        "duration": end_time - start_time,
        "speaker": raw_word.get("speaker"),
        "confidence": raw_word.get("confidence"),
        "is_estimated": False,
        "source": "asr_word",
        "transcript_segment_index": _int_or_none(raw_word.get("segment_index")),
        "segment_id": None,
        "segment_index": None,
    }


def _estimate_words_from_segments(
    transcript_segments: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    estimated: list[dict[str, Any]] = []

    for transcript_segment_index, segment in enumerate(transcript_segments or []):
        text = str(segment.get("text") or "").strip()
        tokens = [match.group(0) for match in WORD_RE.finditer(text)]
        if not tokens:
            continue

        start = max(_float_or_none(segment.get("start")) or 0.0, 0.0)
        end = _float_or_none(segment.get("end"))
        end = max(float(end if end is not None else start), start)
        step = (end - start) / len(tokens) if end > start else 0.0

        for token_index, token in enumerate(tokens):
            token_start = start + (step * token_index)
            token_end = token_start + step
            estimated.append({
                "word_index": len(estimated),
                "text": token,
                "start_time": token_start,
                "end_time": token_end,
                "duration": token_end - token_start,
                "speaker": segment.get("speaker"),
                "confidence": None,
                "is_estimated": True,
                "source": "transcript_segment_estimate",
                "transcript_segment_index": transcript_segment_index,
                "segment_id": None,
                "segment_index": None,
            })

    return estimated


def _attach_review_segment_refs(words: list[dict[str, Any]], segments: list[Any]) -> None:
    if not words or not segments:
        return

    cursor = 0
    for word in words:
        midpoint = (word["start_time"] + word["end_time"]) / 2
        while cursor < len(segments) - 1 and midpoint > segments[cursor].end_time:
            cursor += 1

        matched = _segment_if_contains(segments[cursor], midpoint)
        if matched is None:
            matched = _best_overlap_segment(word, segments)

        if matched is not None:
            word["segment_id"] = str(matched.id)
            word["segment_index"] = matched.segment_index


def _attach_transcript_segment_refs(
    words: list[dict[str, Any]],
    transcript_segments: list[dict[str, Any]],
) -> None:
    if not words or not transcript_segments:
        return

    for word in words:
        if word.get("transcript_segment_index") is not None:
            continue
        midpoint = (word["start_time"] + word["end_time"]) / 2
        for index, segment in enumerate(transcript_segments):
            start = _float_or_none(segment.get("start")) or 0.0
            end = _float_or_none(segment.get("end"))
            if end is not None and start <= midpoint <= end:
                word["transcript_segment_index"] = index
                break


def _build_review_segment_ranges(
    segments: list[Any],
    words: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    word_ranges: dict[int, list[int]] = {}
    for word in words:
        segment_index = word.get("segment_index")
        if segment_index is not None:
            word_ranges.setdefault(segment_index, []).append(word["word_index"])

    timeline_segments = []
    for segment in segments:
        indexes = word_ranges.get(segment.segment_index, [])
        timeline_segments.append({
            "segment_id": str(segment.id),
            "segment_index": segment.segment_index,
            "start_time": segment.start_time,
            "end_time": segment.end_time,
            "duration": segment.duration,
            "text": segment.text,
            "speaker": segment.speaker,
            "word_start_index": min(indexes) if indexes else None,
            "word_end_index": max(indexes) if indexes else None,
            "word_count": len(indexes),
        })

    return timeline_segments


def _segment_if_contains(segment: Any, timestamp: float) -> Optional[Any]:
    if segment.start_time <= timestamp <= segment.end_time:
        return segment
    return None


def _best_overlap_segment(word: dict[str, Any], segments: list[Any]) -> Optional[Any]:
    best_segment = None
    best_overlap = 0.0

    for segment in segments:
        overlap = min(word["end_time"], segment.end_time) - max(word["start_time"], segment.start_time)
        if overlap > best_overlap:
            best_overlap = overlap
            best_segment = segment

    return best_segment


def _clamp_word_bounds(word: dict[str, Any], duration_seconds: Optional[float]) -> None:
    if duration_seconds is not None and duration_seconds >= 0:
        word["start_time"] = min(word["start_time"], duration_seconds)
        word["end_time"] = min(word["end_time"], duration_seconds)
    word["end_time"] = max(word["end_time"], word["start_time"])
    word["duration"] = word["end_time"] - word["start_time"]


def _float_or_none(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value: Any) -> Optional[int]:
    try:
        if value is None or value == "":
            return None
        return int(value)
    except (TypeError, ValueError):
        return None
