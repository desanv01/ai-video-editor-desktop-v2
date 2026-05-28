"""Phase 10 evaluation metrics for demo and thesis evidence reports."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Iterable

from services.layout_model import normalize_layout_cues


EVALUATION_METRICS_SCHEMA_VERSION = "phase10.evaluation-metrics.v1"

LOCAL_TRANSCRIPTION_PROVIDERS = {"local", "whisper-cpp", "synthetic"}
API_TRANSCRIPTION_COST_PER_MINUTE = {
    "voxtral": 0.003,
    "mistral": 0.003,
    "whisper": 0.006,
    "openai": 0.006,
    "openai-whisper": 0.006,
    "whisper-api": 0.006,
}


def build_evaluation_metrics(
    *,
    video: Any | None,
    plan: Any,
    segments: Iterable[Any],
    transcript: Any | None = None,
    plan_payload: dict[str, Any] | None = None,
    actual_output_duration_seconds: float | None = None,
) -> dict[str, Any]:
    """Build the compact Phase 10 metric set from persisted processing data."""
    segment_list = list(segments or [])
    payload = dict(plan_payload or {})
    original_duration = _first_number(
        getattr(plan, "original_duration", None),
        getattr(video, "duration_seconds", None),
        _segment_duration_total(segment_list),
    )
    estimated_duration = _first_number(
        getattr(plan, "estimated_duration", None),
        _estimated_duration_from_actions(segment_list),
    )
    duration_reduction = _duration_reduction(
        original_duration=original_duration,
        estimated_duration=estimated_duration,
        actual_output_duration_seconds=actual_output_duration_seconds,
    )
    filler_dead_air = _filler_dead_air_removal(plan, segment_list)
    segment_quality = _segment_quality(segment_list)
    override_rate = _user_override_rate(segment_list)

    return {
        "schema_version": EVALUATION_METRICS_SCHEMA_VERSION,
        "transcription_accuracy_proxy": _transcription_accuracy_proxy(
            transcript=transcript,
            segments=segment_list,
            original_duration=original_duration,
        ),
        "processing_time": _processing_time(video, plan),
        "cost": _cost_estimate(
            transcript=transcript,
            plan_payload=payload,
            duration_seconds=original_duration,
        ),
        "duration_reduction": duration_reduction,
        "filler_dead_air_removal": filler_dead_air,
        "segment_quality": segment_quality,
        "layout_correctness": _layout_correctness(payload, original_duration),
        "user_override_rate": override_rate,
        "summary": {
            "transcription_accuracy_proxy_score": _score_value(_transcription_accuracy_proxy(
                transcript=transcript,
                segments=segment_list,
                original_duration=original_duration,
            )),
            "processing_time_seconds": _nullable_round(_processing_time(video, plan).get("total_seconds"), 3),
            "estimated_cost_usd": _nullable_round(_cost_estimate(
                transcript=transcript,
                plan_payload=payload,
                duration_seconds=original_duration,
            ).get("estimated_total_usd"), 5),
            "duration_reduction_percent": duration_reduction["reduction_percent"],
            "filler_removal_rate": filler_dead_air["filler_removal_rate"],
            "dead_air_removal_rate": filler_dead_air["dead_air_removal_rate"],
            "segment_quality_score": segment_quality["score"],
            "layout_correctness_score": _layout_correctness(payload, original_duration)["score"],
            "teacher_override_rate": override_rate["override_rate"],
        },
    }


def _transcription_accuracy_proxy(
    *,
    transcript: Any | None,
    segments: list[Any],
    original_duration: float | None,
) -> dict[str, Any]:
    full_text = str(getattr(transcript, "full_text", "") or "")
    transcript_tokens = _tokens(full_text)
    segment_tokens = _tokens(" ".join(str(getattr(segment, "text", "") or "") for segment in segments))
    transcript_word_count = _positive_int(getattr(transcript, "word_count", None), len(transcript_tokens))

    words_json = getattr(transcript, "words_json", None) if transcript else None
    if isinstance(words_json, list) and words_json:
        timed_words = sum(1 for item in words_json if isinstance(item, dict) and _has_number(item.get("start")) and _has_number(item.get("end")))
        word_timestamp_coverage = _rate(timed_words, len(words_json))
    elif transcript_word_count:
        word_timestamp_coverage = 0.0
    else:
        word_timestamp_coverage = None

    segment_text_coverage = _token_coverage(segment_tokens, transcript_tokens)
    segment_timing_coverage = _rate(_segment_duration_total(segments), original_duration)
    available_scores = [
        value
        for value in (word_timestamp_coverage, segment_text_coverage, segment_timing_coverage)
        if value is not None
    ]
    score = _average(available_scores) if available_scores else 0.0

    return {
        "score": _bounded_round(score),
        "is_proxy": True,
        "ground_truth_required_for_true_accuracy": True,
        "word_timestamp_coverage": _nullable_round(word_timestamp_coverage, 4),
        "segment_text_coverage": _nullable_round(segment_text_coverage, 4),
        "segment_timing_coverage": _nullable_round(segment_timing_coverage, 4),
        "transcript_word_count": transcript_word_count,
        "segment_text_word_count": len(segment_tokens),
        "asr_provider": getattr(transcript, "asr_provider", None) if transcript else None,
        "notes": "Proxy combines timestamp coverage, transcript/segment token overlap, and segment timing coverage.",
    }


def _processing_time(video: Any | None, plan: Any) -> dict[str, Any]:
    started_at = _datetime_value(getattr(video, "created_at", None))
    candidates = [
        _datetime_value(getattr(plan, "updated_at", None)),
        _datetime_value(getattr(plan, "created_at", None)),
        _datetime_value(getattr(video, "updated_at", None) if video else None),
    ]
    ended_at = max((item for item in candidates if item is not None), default=None)
    total_seconds = (ended_at - started_at).total_seconds() if started_at and ended_at and ended_at >= started_at else None
    return {
        "started_at": started_at.isoformat() if started_at else None,
        "ended_at": ended_at.isoformat() if ended_at else None,
        "total_seconds": _nullable_round(total_seconds, 3),
        "source": "video_created_to_latest_plan_or_video_update",
    }


def _cost_estimate(
    *,
    transcript: Any | None,
    plan_payload: dict[str, Any],
    duration_seconds: float | None,
) -> dict[str, Any]:
    provider = str(getattr(transcript, "asr_provider", "") or "").lower()
    minutes = max(0.0, float(duration_seconds or 0.0) / 60.0)
    provider_key = _provider_key(provider)
    cost_per_minute = 0.0 if provider_key in LOCAL_TRANSCRIPTION_PROVIDERS else API_TRANSCRIPTION_COST_PER_MINUTE.get(provider_key, 0.0)
    transcription_cost = minutes * cost_per_minute
    metadata = _dict_value(plan_payload.get("metadata"))
    export_metadata = _dict_value(plan_payload.get("export_metadata"))
    processing_mode = metadata.get("processing_mode") or export_metadata.get("processing_mode")
    if not processing_mode:
        processing_mode = "local" if cost_per_minute == 0 else "api"

    return {
        "estimated_total_usd": round(transcription_cost, 5),
        "currency": "USD",
        "processing_mode": processing_mode,
        "duration_minutes": round(minutes, 3),
        "breakdown": {
            "transcription": {
                "provider": provider or None,
                "cost_per_minute_usd": cost_per_minute,
                "estimated_cost_usd": round(transcription_cost, 5),
            },
            "analysis_and_planning": {
                "estimated_cost_usd": None,
                "notes": "No token usage is persisted yet; Phase 10 reports transcription cost and leaves LLM token cost explicit as unavailable.",
            },
        },
    }


def _duration_reduction(
    *,
    original_duration: float | None,
    estimated_duration: float | None,
    actual_output_duration_seconds: float | None,
) -> dict[str, Any]:
    baseline = float(original_duration or 0.0)
    edited = float(estimated_duration or 0.0)
    actual = float(actual_output_duration_seconds) if actual_output_duration_seconds is not None else None
    saved = max(0.0, baseline - edited) if baseline else 0.0
    actual_saved = max(0.0, baseline - actual) if baseline and actual is not None else None
    return {
        "original_duration_seconds": _nullable_round(original_duration, 3),
        "estimated_duration_seconds": _nullable_round(estimated_duration, 3),
        "actual_output_duration_seconds": _nullable_round(actual, 3),
        "time_saved_seconds": round(saved, 3),
        "reduction_percent": round((saved / baseline * 100.0), 3) if baseline else 0.0,
        "actual_time_saved_seconds": _nullable_round(actual_saved, 3),
        "actual_reduction_percent": round((actual_saved / baseline * 100.0), 3) if baseline and actual_saved is not None else None,
    }


def _filler_dead_air_removal(plan: Any, segments: list[Any]) -> dict[str, Any]:
    detected_fillers = sum(_positive_int(getattr(segment, "filler_count", 0), 0) for segment in segments)
    detected_dead_air = sum(float(getattr(segment, "pause_duration_total", 0.0) or 0.0) for segment in segments)
    planned_filler_removed = _first_number(getattr(plan, "filler_words_removed", None))
    planned_dead_air_removed = _first_number(getattr(plan, "silence_removed_seconds", None))

    if planned_filler_removed is None:
        planned_filler_removed = sum(
            _positive_int(getattr(segment, "filler_count", 0), 0)
            for segment in segments
            if _final_action(segment) in {"cut", "shorten"}
        )
    if planned_dead_air_removed is None:
        planned_dead_air_removed = sum(
            float(getattr(segment, "pause_duration_total", 0.0) or 0.0)
            for segment in segments
            if _final_action(segment) in {"cut", "shorten"}
        )

    return {
        "detected_filler_words": detected_fillers,
        "removed_filler_words": int(planned_filler_removed or 0),
        "filler_removal_rate": _bounded_round(_rate(planned_filler_removed, detected_fillers)),
        "detected_dead_air_seconds": round(detected_dead_air, 3),
        "removed_dead_air_seconds": round(float(planned_dead_air_removed or 0.0), 3),
        "dead_air_removal_rate": _bounded_round(_rate(planned_dead_air_removed, detected_dead_air)),
    }


def _segment_quality(segments: list[Any]) -> dict[str, Any]:
    avg_importance = _average(_numbers(getattr(segment, "importance_score", None) for segment in segments))
    avg_fluency = _average(_numbers(getattr(segment, "fluency_score", None) for segment in segments))
    avg_confidence = _average(_numbers(getattr(segment, "action_confidence", None) for segment in segments))
    content_segments = [segment for segment in segments if _enum_value(getattr(segment, "segment_type", None)) in {"core_content", "example", "qa"}]
    low_value_segments = [segment for segment in segments if _enum_value(getattr(segment, "segment_type", None)) in {"filler", "pause", "repetition"}]
    kept_content = sum(1 for segment in content_segments if _final_action(segment) in {"keep", "highlight", "shorten"})
    removed_low_value = sum(1 for segment in low_value_segments if _final_action(segment) in {"cut", "shorten"})
    content_keep_rate = _rate(kept_content, len(content_segments))
    low_value_removal_rate = _rate(removed_low_value, len(low_value_segments))
    components = [
        value
        for value in (avg_importance, avg_fluency, avg_confidence, content_keep_rate, low_value_removal_rate)
        if value is not None
    ]
    score = _average(components) if components else 0.0

    return {
        "score": _bounded_round(score),
        "average_importance_score": _nullable_round(avg_importance, 4),
        "average_fluency_score": _nullable_round(avg_fluency, 4),
        "average_action_confidence": _nullable_round(avg_confidence, 4),
        "content_keep_rate": _nullable_round(content_keep_rate, 4),
        "low_value_removal_rate": _nullable_round(low_value_removal_rate, 4),
        "content_segment_count": len(content_segments),
        "low_value_segment_count": len(low_value_segments),
    }


def _layout_correctness(plan_payload: dict[str, Any], duration_seconds: float | None) -> dict[str, Any]:
    cues = normalize_layout_cues(plan_payload.get("layout_cues", []), duration_seconds=duration_seconds)
    warnings: list[str] = []
    if not cues:
        warnings.append("no_layout_cues")
        return {
            "score": 0.0,
            "cue_count": 0,
            "timeline_coverage_rate": 0.0,
            "valid_timing_rate": 0.0,
            "enabled_source_reference_rate": None,
            "warnings": warnings,
        }

    coverage = _cue_coverage(cues, duration_seconds)
    valid_timing_count = sum(1 for cue in cues if _valid_cue_timing(cue))
    source_rate = _enabled_source_reference_rate(cues)
    if coverage < 0.95 and duration_seconds:
        warnings.append("layout_timeline_coverage_below_95_percent")
    if valid_timing_count < len(cues):
        warnings.append("invalid_layout_cue_timing")
    if source_rate is not None and source_rate < 1.0:
        warnings.append("missing_enabled_source_asset_reference")

    components = [coverage, _rate(valid_timing_count, len(cues))]
    if source_rate is not None:
        components.append(source_rate)

    return {
        "score": _bounded_round(_average(components)),
        "cue_count": len(cues),
        "timeline_coverage_rate": _bounded_round(coverage),
        "valid_timing_rate": _bounded_round(_rate(valid_timing_count, len(cues))),
        "enabled_source_reference_rate": _nullable_round(source_rate, 4),
        "layout_modes": sorted({_enum_value(cue.get("layout")) for cue in cues}),
        "warnings": warnings,
    }


def _user_override_rate(segments: list[Any]) -> dict[str, Any]:
    teacher_modified = sum(1 for segment in segments if bool(getattr(segment, "is_teacher_modified", False)))
    teacher_overrides = sum(
        1
        for segment in segments
        if bool(getattr(segment, "is_teacher_modified", False))
        and _enum_value(getattr(segment, "teacher_action", None)) != _enum_value(getattr(segment, "action", None))
    )
    return {
        "total_segments": len(segments),
        "teacher_modifications": teacher_modified,
        "teacher_overrides": teacher_overrides,
        "override_rate": _bounded_round(_rate(teacher_overrides, len(segments))),
        "modification_rate": _bounded_round(_rate(teacher_modified, len(segments))),
    }


def _cue_coverage(cues: list[dict[str, Any]], duration_seconds: float | None) -> float:
    duration = float(duration_seconds or 0.0)
    if duration <= 0:
        return 1.0 if cues else 0.0
    intervals: list[tuple[float, float]] = []
    for cue in cues:
        start = max(0.0, float(cue.get("start_time") or 0.0))
        end_raw = cue.get("end_time")
        end = duration if end_raw is None else min(duration, max(0.0, float(end_raw or 0.0)))
        if end > start:
            intervals.append((start, end))
    if not intervals:
        return 0.0
    intervals.sort()
    merged: list[list[float]] = []
    for start, end in intervals:
        if not merged or start > merged[-1][1]:
            merged.append([start, end])
        else:
            merged[-1][1] = max(merged[-1][1], end)
    covered = sum(end - start for start, end in merged)
    return _rate(covered, duration)


def _valid_cue_timing(cue: dict[str, Any]) -> bool:
    start = _first_number(cue.get("start_time"))
    end = _first_number(cue.get("end_time"))
    return start is not None and (end is None or end >= start)


def _enabled_source_reference_rate(cues: list[dict[str, Any]]) -> float | None:
    enabled_refs = 0
    refs_with_asset = 0
    for cue in cues:
        for source in _dict_value(cue.get("sources")).values():
            if not isinstance(source, dict) or not source.get("enabled"):
                continue
            if source.get("role") == "audio":
                continue
            enabled_refs += 1
            if source.get("asset_id"):
                refs_with_asset += 1
    if enabled_refs == 0:
        return None
    return _rate(refs_with_asset, enabled_refs)


def _estimated_duration_from_actions(segments: list[Any]) -> float:
    return sum(
        _segment_duration(segment)
        for segment in segments
        if _final_action(segment) in {"keep", "highlight", "shorten"}
    )


def _segment_duration_total(segments: list[Any]) -> float:
    return sum(_segment_duration(segment) for segment in segments)


def _segment_duration(segment: Any) -> float:
    duration = _first_number(getattr(segment, "duration", None))
    if duration is not None:
        return duration
    start = _first_number(getattr(segment, "start_time", None))
    end = _first_number(getattr(segment, "end_time", None))
    if start is None or end is None:
        return 0.0
    return max(0.0, end - start)


def _final_action(segment: Any) -> str:
    teacher_action = getattr(segment, "teacher_action", None)
    return _enum_value(teacher_action or getattr(segment, "action", None))


def _provider_key(provider: str) -> str:
    if not provider:
        return ""
    for key in sorted(LOCAL_TRANSCRIPTION_PROVIDERS, key=len, reverse=True):
        if key in provider:
            return key
    for key in sorted(API_TRANSCRIPTION_COST_PER_MINUTE, key=len, reverse=True):
        if key in provider:
            return key
    return provider


def _token_coverage(source_tokens: list[str], reference_tokens: list[str]) -> float | None:
    if not source_tokens:
        return None
    reference = set(reference_tokens)
    if not reference:
        return 0.0
    matches = sum(1 for token in source_tokens if token in reference)
    return _rate(matches, len(source_tokens))


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-z0-9']+", text.lower())


def _numbers(values: Iterable[Any]) -> list[float]:
    numbers = []
    for value in values:
        number = _first_number(value)
        if number is not None:
            numbers.append(number)
    return numbers


def _average(values: Iterable[float]) -> float:
    items = list(values)
    return sum(items) / len(items) if items else 0.0


def _rate(numerator: Any, denominator: Any) -> float:
    try:
        den = float(denominator or 0.0)
        num = float(numerator or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if den <= 0:
        return 0.0
    return max(0.0, min(1.0, num / den))


def _first_number(*values: Any) -> float | None:
    for value in values:
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _positive_int(value: Any, default: int) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _has_number(value: Any) -> bool:
    return _first_number(value) is not None


def _datetime_value(value: Any) -> datetime | None:
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _enum_value(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "").lower()


def _dict_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _bounded_round(value: Any) -> float:
    return round(_rate(value, 1.0), 4)


def _nullable_round(value: Any, digits: int) -> float | None:
    number = _first_number(value)
    return round(number, digits) if number is not None else None


def _score_value(metric: dict[str, Any]) -> float:
    return float(metric.get("score") or 0.0)
