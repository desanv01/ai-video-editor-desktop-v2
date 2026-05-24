"""Rule-based Clean step tools for lecture editing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Iterable, Optional, TYPE_CHECKING

from services.transcript_edit_decisions import (
    create_transcript_cut_decision,
    list_active_transcript_cut_intervals,
    normalize_plan_payload,
)

if TYPE_CHECKING:
    from db.models import EditPlan


CLEAN_SCHEMA_VERSION = "phase6.clean-tools.v2"
ACTION_KEEP = "keep"
ACTION_CUT = "cut"
ACTION_SHORTEN = "shorten"
TYPE_FILLER = "filler"
TYPE_PAUSE = "pause"
TYPE_REPETITION = "repetition"


@dataclass(frozen=True)
class CleanProfile:
    id: str
    label: str
    description: str
    filler_phrases: tuple[tuple[str, ...], ...]
    filler_confidence: float
    filler_padding_seconds: float
    dead_air_min_seconds: float
    dead_air_pause_ratio: float
    dead_air_confidence: float
    bad_take_importance_max: float
    bad_take_fluency_max: float
    bad_take_filler_min: int
    bad_take_pause_ratio: float
    bad_take_confidence: float
    repeated_phrase_min_words: int
    repeated_phrase_max_words: int
    repeated_phrase_gap_words: int
    repeated_phrase_confidence: float
    restarted_sentence_min_words: int
    restarted_sentence_confidence: float
    repeated_explanation_similarity: float
    repeated_explanation_min_tokens: int
    repeated_explanation_confidence: float


CLEANING_PROFILES: dict[str, CleanProfile] = {
    "conservative": CleanProfile(
        id="conservative",
        label="Conservative",
        description="Only removes obvious fillers and high-confidence pacing problems.",
        filler_phrases=(("um",), ("uh",), ("erm",), ("er",), ("ah",), ("hmm",), ("mmm",)),
        filler_confidence=0.9,
        filler_padding_seconds=0.02,
        dead_air_min_seconds=1.2,
        dead_air_pause_ratio=0.35,
        dead_air_confidence=0.78,
        bad_take_importance_max=0.25,
        bad_take_fluency_max=0.35,
        bad_take_filler_min=5,
        bad_take_pause_ratio=0.65,
        bad_take_confidence=0.82,
        repeated_phrase_min_words=2,
        repeated_phrase_max_words=7,
        repeated_phrase_gap_words=2,
        repeated_phrase_confidence=0.78,
        restarted_sentence_min_words=5,
        restarted_sentence_confidence=0.84,
        repeated_explanation_similarity=0.72,
        repeated_explanation_min_tokens=7,
        repeated_explanation_confidence=0.76,
    ),
    "aggressive": CleanProfile(
        id="aggressive",
        label="Aggressive",
        description="Removes more delivery clutter while still preserving likely teaching content.",
        filler_phrases=(
            ("um",),
            ("uh",),
            ("erm",),
            ("er",),
            ("ah",),
            ("hmm",),
            ("mmm",),
            ("like",),
            ("basically",),
            ("actually",),
            ("you", "know"),
            ("i", "mean"),
            ("sort", "of"),
            ("kind", "of"),
            ("okay", "so"),
        ),
        filler_confidence=0.82,
        filler_padding_seconds=0.04,
        dead_air_min_seconds=0.7,
        dead_air_pause_ratio=0.22,
        dead_air_confidence=0.72,
        bad_take_importance_max=0.4,
        bad_take_fluency_max=0.5,
        bad_take_filler_min=3,
        bad_take_pause_ratio=0.55,
        bad_take_confidence=0.74,
        repeated_phrase_min_words=1,
        repeated_phrase_max_words=9,
        repeated_phrase_gap_words=4,
        repeated_phrase_confidence=0.7,
        restarted_sentence_min_words=4,
        restarted_sentence_confidence=0.78,
        repeated_explanation_similarity=0.62,
        repeated_explanation_min_tokens=5,
        repeated_explanation_confidence=0.68,
    ),
}


WORD_LEVEL_SUGGESTION_TYPES = {"filler_word", "false_start", "repeated_phrase", "restarted_sentence"}
REPETITION_SUGGESTION_TYPES = {
    "false_start",
    "repeated_phrase",
    "restarted_sentence",
    "repeated_explanation",
}
FALSE_START_LEADS = {
    "i",
    "we",
    "you",
    "let's",
    "lets",
    "this",
    "that",
    "the",
    "so",
    "now",
}
CONTENT_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "if",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "so",
    "that",
    "the",
    "then",
    "this",
    "to",
    "we",
    "with",
    "you",
}


def profile_catalog() -> list[dict[str, Any]]:
    return [
        {"id": profile.id, "label": profile.label, "description": profile.description}
        for profile in CLEANING_PROFILES.values()
    ]


def analyze_clean_suggestions(
    *,
    segments: Iterable[Any],
    timeline_words: Iterable[dict[str, Any]] | None = None,
    plan: Any = None,
    profile_id: str = "conservative",
) -> dict[str, Any]:
    """Build reviewable cleaning suggestions without mutating the edit state."""
    profile = _profile(profile_id)
    segment_list = sorted(list(segments or []), key=lambda segment: segment.segment_index)
    words = list(timeline_words or [])
    active_cut_keys = _active_cut_keys(plan)
    active_cut_ranges = _active_cut_ranges(plan)

    suggestions: list[dict[str, Any]] = []
    filler_suggestions = _filler_suggestions(profile, words, active_cut_keys, active_cut_ranges)
    suggestions.extend(filler_suggestions)
    suggestions.extend(_repetition_suggestions(profile, words, active_cut_ranges, _claimed_word_indexes(filler_suggestions)))
    suggestions.extend(_segment_suggestions(profile, segment_list))
    suggestions.extend(_repeated_explanation_suggestions(profile, segment_list))
    suggestions.sort(key=lambda item: (item["start_time"], item["type"], item["id"]))

    return {
        "schema_version": CLEAN_SCHEMA_VERSION,
        "profile": profile.id,
        "profiles": profile_catalog(),
        "summary": _summary(suggestions),
        "suggestions": suggestions,
    }


def apply_clean_suggestions(
    *,
    plan: "EditPlan",
    segments: Iterable[Any],
    timeline_words: Iterable[dict[str, Any]] | None = None,
    profile_id: str = "conservative",
    suggestion_ids: Optional[set[str]] = None,
) -> dict[str, Any]:
    """Apply Clean suggestions as transcript cuts and teacher overrides."""
    segment_list = sorted(list(segments or []), key=lambda segment: segment.segment_index)
    analysis = analyze_clean_suggestions(
        segments=segment_list,
        timeline_words=timeline_words,
        plan=plan,
        profile_id=profile_id,
    )
    selected = [
        suggestion
        for suggestion in analysis["suggestions"]
        if suggestion_ids is None or suggestion["id"] in suggestion_ids
    ]

    created_transcript_cuts: list[dict[str, Any]] = []
    updated_segments: list[dict[str, Any]] = []
    segments_by_id = {str(segment.id): segment for segment in segment_list}
    words = list(timeline_words or [])

    for suggestion in selected:
        if suggestion["type"] in WORD_LEVEL_SUGGESTION_TYPES:
            try:
                decision = create_transcript_cut_decision(
                    plan=plan,
                    timeline_words=words,
                    word_start_index=suggestion["word_start_index"],
                    word_end_index=suggestion["word_end_index"],
                    teacher_note=f"Auto-clean {analysis['profile']}: {suggestion['title']}",
                    source=f"auto_clean_{suggestion['type']}",
                    pre_roll_seconds=suggestion.get("padding_seconds", 0.0),
                    post_roll_seconds=suggestion.get("padding_seconds", 0.0),
                )
            except ValueError:
                continue
            created_transcript_cuts.append(decision)
            continue

        segment = segments_by_id.get(str(suggestion.get("segment_id")))
        if segment is None or segment.is_teacher_modified:
            continue

        target_action = _segment_action(suggestion["target_action"])
        segment.teacher_action = target_action
        segment.teacher_note = suggestion["reason"]
        segment.is_teacher_modified = True
        updated_segments.append({
            "segment_id": str(segment.id),
            "segment_index": segment.segment_index,
            "teacher_action": _enum_value(target_action) or str(target_action),
            "teacher_note": segment.teacher_note,
        })

    _refresh_clean_plan_summary(
        plan=plan,
        segments=segment_list,
        profile_id=analysis["profile"],
        suggestions=selected,
    )

    return {
        "schema_version": CLEAN_SCHEMA_VERSION,
        "profile": analysis["profile"],
        "summary": _summary(selected),
        "created_transcript_cuts": created_transcript_cuts,
        "updated_segments": updated_segments,
        "suggestions": selected,
    }


def _filler_suggestions(
    profile: CleanProfile,
    words: list[dict[str, Any]],
    active_cut_keys: set[tuple[int | None, int | None]],
    active_cut_ranges: list[tuple[int, int]],
) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    normalized = [_normalize_word(word.get("text")) for word in words]
    claimed_indexes: set[int] = set()

    for start_index, _ in enumerate(words):
        if start_index in claimed_indexes:
            continue

        for phrase in profile.filler_phrases:
            end_index = start_index + len(phrase) - 1
            if end_index >= len(words):
                continue
            if any(index in claimed_indexes for index in range(start_index, end_index + 1)):
                continue
            if tuple(normalized[start_index:end_index + 1]) != phrase:
                continue

            first_word = words[start_index]
            last_word = words[end_index]
            word_start_index = int(first_word["word_index"])
            word_end_index = int(last_word["word_index"])
            if (word_start_index, word_end_index) in active_cut_keys or _word_range_overlaps(
                word_start_index,
                word_end_index,
                active_cut_ranges,
            ):
                break

            text = " ".join(str(words[index].get("text") or "") for index in range(start_index, end_index + 1))
            start_time = max(0.0, float(first_word["start_time"]) - profile.filler_padding_seconds)
            end_time = float(last_word["end_time"]) + profile.filler_padding_seconds
            suggestions.append({
                "id": f"clean-filler-{word_start_index}-{word_end_index}",
                "type": "filler_word",
                "title": "Remove filler word",
                "text": text.strip(),
                "reason": f"Remove filler phrase: {text.strip()}",
                "confidence": profile.filler_confidence,
                "start_time": round(start_time, 3),
                "end_time": round(end_time, 3),
                "duration": round(max(0.0, end_time - start_time), 3),
                "word_start_index": word_start_index,
                "word_end_index": word_end_index,
                "segment_id": first_word.get("segment_id"),
                "segment_index": first_word.get("segment_index"),
                "target_action": "cut",
                "apply_kind": "transcript_cut",
                "padding_seconds": profile.filler_padding_seconds,
            })
            claimed_indexes.update(range(start_index, end_index + 1))
            break

    return suggestions


def _repetition_suggestions(
    profile: CleanProfile,
    words: list[dict[str, Any]],
    active_cut_ranges: list[tuple[int, int]],
    claimed_indexes: set[int],
) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    normalized = [_normalize_word(word.get("text")) for word in words]

    for start_index in range(len(words)):
        if start_index in claimed_indexes or not normalized[start_index]:
            continue

        match = _find_repetition_match(profile, normalized, start_index, claimed_indexes)
        if not match:
            continue

        phrase_length, next_start = match
        cut_start = start_index
        cut_end = start_index + phrase_length - 1
        first_word = words[cut_start]
        last_word = words[cut_end]
        word_start_index = int(first_word["word_index"])
        word_end_index = int(last_word["word_index"])
        if _word_range_overlaps(word_start_index, word_end_index, active_cut_ranges):
            continue

        repeated_text = _join_words(words, cut_start, cut_end)
        resumed_text = _join_words(words, next_start, next_start + phrase_length - 1)
        suggestion_type, title, confidence = _repetition_kind(profile, normalized, start_index, phrase_length)
        reason = _repetition_reason(suggestion_type, repeated_text, resumed_text)
        padding = profile.filler_padding_seconds
        start_time = max(0.0, float(first_word["start_time"]) - padding)
        end_time = float(last_word["end_time"]) + padding

        suggestions.append({
            "id": f"clean-{suggestion_type}-{word_start_index}-{word_end_index}",
            "type": suggestion_type,
            "title": title,
            "text": repeated_text,
            "reason": reason,
            "confidence": confidence,
            "start_time": round(start_time, 3),
            "end_time": round(end_time, 3),
            "duration": round(max(0.0, end_time - start_time), 3),
            "word_start_index": word_start_index,
            "word_end_index": word_end_index,
            "segment_id": first_word.get("segment_id"),
            "segment_index": first_word.get("segment_index"),
            "target_action": "cut",
            "apply_kind": "transcript_cut",
            "padding_seconds": padding,
            "matched_text": resumed_text,
        })
        claimed_indexes.update(range(cut_start, next_start + phrase_length))

    suggestions.extend(_partial_word_false_starts(profile, words, normalized, active_cut_ranges, claimed_indexes))
    return suggestions


def _find_repetition_match(
    profile: CleanProfile,
    normalized: list[str],
    start_index: int,
    claimed_indexes: set[int],
) -> tuple[int, int] | None:
    max_len = min(profile.repeated_phrase_max_words, (len(normalized) - start_index) // 2)
    for phrase_length in range(max_len, profile.repeated_phrase_min_words - 1, -1):
        phrase = normalized[start_index:start_index + phrase_length]
        if any(not token for token in phrase):
            continue
        if any(index in claimed_indexes for index in range(start_index, start_index + phrase_length)):
            continue

        latest_next_start = min(
            len(normalized) - phrase_length,
            start_index + phrase_length + profile.repeated_phrase_gap_words,
        )
        for next_start in range(start_index + phrase_length, latest_next_start + 1):
            if any(index in claimed_indexes for index in range(next_start, next_start + phrase_length)):
                continue
            if normalized[next_start:next_start + phrase_length] == phrase:
                return phrase_length, next_start

    return None


def _partial_word_false_starts(
    profile: CleanProfile,
    words: list[dict[str, Any]],
    normalized: list[str],
    active_cut_ranges: list[tuple[int, int]],
    claimed_indexes: set[int],
) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    for index, word in enumerate(words):
        if index in claimed_indexes:
            continue
        raw_text = str(word.get("text") or "").strip()
        normalized_text = normalized[index]
        if len(normalized_text) < 2 or not raw_text.endswith("-"):
            continue

        word_start_index = int(word["word_index"])
        if _word_range_overlaps(word_start_index, word_start_index, active_cut_ranges):
            continue

        padding = profile.filler_padding_seconds
        start_time = max(0.0, float(word["start_time"]) - padding)
        end_time = float(word["end_time"]) + padding
        suggestions.append({
            "id": f"clean-false-start-{word_start_index}-{word_start_index}",
            "type": "false_start",
            "title": "Remove false start",
            "text": raw_text,
            "reason": f"Remove abandoned word fragment before the sentence continues: {raw_text}",
            "confidence": profile.repeated_phrase_confidence,
            "start_time": round(start_time, 3),
            "end_time": round(end_time, 3),
            "duration": round(max(0.0, end_time - start_time), 3),
            "word_start_index": word_start_index,
            "word_end_index": word_start_index,
            "segment_id": word.get("segment_id"),
            "segment_index": word.get("segment_index"),
            "target_action": "cut",
            "apply_kind": "transcript_cut",
            "padding_seconds": padding,
        })
        claimed_indexes.add(index)

    return suggestions


def _repeated_explanation_suggestions(profile: CleanProfile, segments: list[Any]) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    claimed_segment_ids: set[str] = set()

    for index, segment in enumerate(segments):
        if segment.is_teacher_modified or str(segment.id) in claimed_segment_ids:
            continue
        segment_tokens = _content_tokens(segment.text)
        if len(segment_tokens) < profile.repeated_explanation_min_tokens:
            continue

        for next_segment in segments[index + 1:index + 3]:
            if next_segment.is_teacher_modified or str(next_segment.id) in claimed_segment_ids:
                continue
            next_tokens = _content_tokens(next_segment.text)
            if len(next_tokens) < profile.repeated_explanation_min_tokens:
                continue

            similarity = _jaccard_similarity(segment_tokens, next_tokens)
            if similarity < profile.repeated_explanation_similarity:
                continue

            duplicate = _less_useful_segment(segment, next_segment)
            original = next_segment if duplicate is segment else segment
            duration = float(duplicate.duration or max(0.0, duplicate.end_time - duplicate.start_time) or 0.0)
            suggestions.append({
                "id": f"clean-repeated-explanation-{duplicate.id}",
                "type": "repeated_explanation",
                "title": "Review repeated explanation",
                "text": _clip_text(duplicate.text),
                "reason": (
                    "Cut likely repeated explanation "
                    f"(similar to segment {original.segment_index}, {similarity * 100:.0f}% token overlap)"
                ),
                "confidence": profile.repeated_explanation_confidence,
                "start_time": round(float(duplicate.start_time), 3),
                "end_time": round(float(duplicate.end_time), 3),
                "duration": round(duration, 3),
                "segment_id": str(duplicate.id),
                "segment_index": duplicate.segment_index,
                "target_action": "cut",
                "apply_kind": "segment_override",
                "duplicate_of_segment_id": str(original.id),
                "duplicate_of_segment_index": original.segment_index,
            })
            claimed_segment_ids.add(str(duplicate.id))
            break

    return suggestions


def _segment_suggestions(profile: CleanProfile, segments: list[Any]) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    for segment in segments:
        if segment.is_teacher_modified:
            continue

        duration = float(segment.duration or max(0.0, segment.end_time - segment.start_time) or 0.0)
        pause_seconds = float(segment.pause_duration_total or 0.0)
        pause_ratio = pause_seconds / max(duration, 0.1)
        importance = float(segment.importance_score if segment.importance_score is not None else 0.5)
        fluency = float(segment.fluency_score if segment.fluency_score is not None else 1.0)
        filler_count = int(segment.filler_count or 0)
        segment_type = _enum_value(segment.segment_type)

        if _is_bad_take(profile, segment, pause_ratio, importance, fluency, filler_count, segment_type):
            suggestions.append({
                "id": f"clean-bad-take-{segment.id}",
                "type": "bad_take",
                "title": "Cut bad take",
                "text": _clip_text(segment.text),
                "reason": _bad_take_reason(segment_type, importance, fluency, filler_count, pause_ratio),
                "confidence": profile.bad_take_confidence,
                "start_time": round(float(segment.start_time), 3),
                "end_time": round(float(segment.end_time), 3),
                "duration": round(duration, 3),
                "segment_id": str(segment.id),
                "segment_index": segment.segment_index,
                "target_action": "cut",
                "apply_kind": "segment_override",
            })
            continue

        if pause_seconds >= profile.dead_air_min_seconds and pause_ratio >= profile.dead_air_pause_ratio:
            suggestions.append({
                "id": f"clean-dead-air-{segment.id}",
                "type": "dead_air",
                "title": "Trim dead air",
                "text": _clip_text(segment.text),
                "reason": f"Trim {pause_seconds:.1f}s of pause from this segment",
                "confidence": profile.dead_air_confidence,
                "start_time": round(float(segment.start_time), 3),
                "end_time": round(float(segment.end_time), 3),
                "duration": round(pause_seconds, 3),
                "segment_id": str(segment.id),
                "segment_index": segment.segment_index,
                "target_action": "shorten",
                "apply_kind": "segment_override",
            })

    return suggestions


def _is_bad_take(
    profile: CleanProfile,
    segment: Any,
    pause_ratio: float,
    importance: float,
    fluency: float,
    filler_count: int,
    segment_type: str | None,
) -> bool:
    if segment_type in {TYPE_FILLER, TYPE_PAUSE, TYPE_REPETITION}:
        return importance <= profile.bad_take_importance_max + 0.1
    if getattr(segment, "has_repetition", False) and importance <= profile.bad_take_importance_max:
        return True
    if pause_ratio >= profile.bad_take_pause_ratio and importance <= profile.bad_take_importance_max + 0.15:
        return True
    return (
        importance <= profile.bad_take_importance_max
        and fluency <= profile.bad_take_fluency_max
        and filler_count >= profile.bad_take_filler_min
    )


def _active_cut_keys(plan: Any) -> set[tuple[int | None, int | None]]:
    if not plan:
        return set()
    payload = normalize_plan_payload(plan.plan_json)
    return {
        (decision.get("word_start_index"), decision.get("word_end_index"))
        for decision in payload.get("edit_decisions", [])
        if decision.get("kind") == "transcript_cut" and decision.get("status") == "active"
    }


def _active_cut_ranges(plan: Any) -> list[tuple[int, int]]:
    if not plan:
        return []
    payload = normalize_plan_payload(plan.plan_json)
    ranges: list[tuple[int, int]] = []
    for decision in payload.get("edit_decisions", []):
        if decision.get("kind") != "transcript_cut" or decision.get("status") != "active":
            continue
        start = decision.get("word_start_index")
        end = decision.get("word_end_index")
        if start is None or end is None:
            continue
        ranges.append((int(start), int(end)))
    return ranges


def _summary(suggestions: list[dict[str, Any]]) -> dict[str, Any]:
    by_type = {
        "filler_word": 0,
        "dead_air": 0,
        "bad_take": 0,
        "false_start": 0,
        "repeated_phrase": 0,
        "restarted_sentence": 0,
        "repeated_explanation": 0,
    }
    estimated_time_saved = 0.0
    for suggestion in suggestions:
        by_type[suggestion["type"]] = by_type.get(suggestion["type"], 0) + 1
        estimated_time_saved += float(suggestion.get("duration") or 0.0)

    return {
        "suggestions_total": len(suggestions),
        "filler_word_count": by_type.get("filler_word", 0),
        "dead_air_count": by_type.get("dead_air", 0),
        "bad_take_count": by_type.get("bad_take", 0),
        "false_start_count": by_type.get("false_start", 0),
        "repeated_phrase_count": by_type.get("repeated_phrase", 0),
        "restarted_sentence_count": by_type.get("restarted_sentence", 0),
        "repeated_explanation_count": by_type.get("repeated_explanation", 0),
        "repetition_suggestion_count": sum(by_type.get(kind, 0) for kind in REPETITION_SUGGESTION_TYPES),
        "estimated_time_saved_seconds": round(estimated_time_saved, 3),
    }


def _refresh_clean_plan_summary(
    *,
    plan: "EditPlan",
    segments: list[Any],
    profile_id: str,
    suggestions: list[dict[str, Any]],
) -> None:
    payload = normalize_plan_payload(plan.plan_json)
    payload["clean_summary"] = {
        "schema_version": CLEAN_SCHEMA_VERSION,
        "profile": profile_id,
        "applied_at": datetime.now(UTC).isoformat(),
        **_summary(suggestions),
    }
    plan.plan_json = payload

    counts = {"keep": 0, "cut": 0, "shorten": 0, "highlight": 0}
    segment_savings = 0.0
    filler_words_removed = 0
    silence_removed = 0.0
    for segment in segments:
        action = _final_action(segment)
        counts[action] = counts.get(action, 0) + 1
        if action == ACTION_CUT:
            segment_savings += float(segment.duration or 0.0)
            filler_words_removed += int(segment.filler_count or 0)
            silence_removed += float(segment.pause_duration_total or 0.0)
        elif action == ACTION_SHORTEN:
            silence_removed += float(segment.pause_duration_total or 0.0)
            segment_savings += float(segment.pause_duration_total or 0.0)

    transcript_cut_duration = sum(
        float(interval.get("duration") or 0.0)
        for interval in list_active_transcript_cut_intervals(plan)
    )
    original = float(plan.original_duration or 0.0)
    plan.estimated_duration = round(max(0.0, original - segment_savings - transcript_cut_duration), 1)
    plan.segments_total = len(segments)
    plan.segments_keep = counts["keep"]
    plan.segments_cut = counts["cut"]
    plan.segments_highlight = counts["highlight"]
    plan.filler_words_removed = filler_words_removed + _summary(suggestions)["filler_word_count"]
    plan.silence_removed_seconds = round(silence_removed, 2)


def _profile(profile_id: str) -> CleanProfile:
    try:
        return CLEANING_PROFILES[profile_id]
    except KeyError as exc:
        raise ValueError(f"Unknown cleaning profile: {profile_id}") from exc


def _normalize_word(value: Any) -> str:
    text = str(value or "").lower()
    return re.sub(r"^[^\w']+|[^\w']+$", "", text)


def _claimed_word_indexes(suggestions: list[dict[str, Any]]) -> set[int]:
    indexes: set[int] = set()
    for suggestion in suggestions:
        start = suggestion.get("word_start_index")
        end = suggestion.get("word_end_index")
        if start is None or end is None:
            continue
        indexes.update(range(int(start), int(end) + 1))
    return indexes


def _word_range_overlaps(start: int, end: int, ranges: list[tuple[int, int]]) -> bool:
    return any(end >= range_start and start <= range_end for range_start, range_end in ranges)


def _join_words(words: list[dict[str, Any]], start: int, end: int) -> str:
    return " ".join(str(words[index].get("text") or "").strip() for index in range(start, end + 1)).strip()


def _repetition_kind(
    profile: CleanProfile,
    normalized: list[str],
    start_index: int,
    phrase_length: int,
) -> tuple[str, str, float]:
    if phrase_length >= profile.restarted_sentence_min_words:
        return "restarted_sentence", "Remove restarted sentence", profile.restarted_sentence_confidence
    if normalized[start_index] in FALSE_START_LEADS and phrase_length <= 4:
        return "false_start", "Remove false start", profile.repeated_phrase_confidence
    return "repeated_phrase", "Remove repeated phrase", profile.repeated_phrase_confidence


def _repetition_reason(suggestion_type: str, repeated_text: str, resumed_text: str) -> str:
    if suggestion_type == "restarted_sentence":
        return f"Remove the first attempt at a sentence that restarts as: {resumed_text}"
    if suggestion_type == "false_start":
        return f"Remove the false start before the speaker resumes: {resumed_text}"
    return f"Remove repeated phrase: {repeated_text}"


def _content_tokens(value: Any) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9']+", str(value or "").lower())
        if token and token not in CONTENT_STOPWORDS and len(token) > 2
    }


def _jaccard_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _less_useful_segment(left: Any, right: Any) -> Any:
    left_importance = float(left.importance_score if left.importance_score is not None else 0.5)
    right_importance = float(right.importance_score if right.importance_score is not None else 0.5)
    if abs(left_importance - right_importance) >= 0.1:
        return left if left_importance < right_importance else right

    left_fluency = float(left.fluency_score if left.fluency_score is not None else 1.0)
    right_fluency = float(right.fluency_score if right.fluency_score is not None else 1.0)
    if abs(left_fluency - right_fluency) >= 0.1:
        return left if left_fluency < right_fluency else right

    return right


def _clip_text(value: Any, limit: int = 140) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "..."


def _bad_take_reason(
    segment_type: str | None,
    importance: float,
    fluency: float,
    filler_count: int,
    pause_ratio: float,
) -> str:
    if segment_type in {TYPE_FILLER, TYPE_PAUSE, TYPE_REPETITION}:
        return f"Cut low-value {segment_type.replace('_', ' ')} segment"
    if pause_ratio >= 0.55:
        return f"Cut mostly dead air ({pause_ratio * 100:.0f}% pause)"
    return f"Cut low-importance bad take (importance {importance:.2f}, fluency {fluency:.2f}, {filler_count} fillers)"


def _final_action(segment: Any) -> str:
    action = segment.teacher_action if segment.is_teacher_modified and segment.teacher_action else segment.action
    return _enum_value(action) or ACTION_KEEP


def _enum_value(value: Any) -> str | None:
    return getattr(value, "value", value) if value is not None else None


def _segment_action(value: str) -> Any:
    try:
        from db.models import SegmentAction

        return SegmentAction(value)
    except Exception:
        return value
