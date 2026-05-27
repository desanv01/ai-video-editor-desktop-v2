"""API/local/hybrid comparison reports for Phase 10 evaluation."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any, Iterable


MODE_COMPARISON_SCHEMA_VERSION = "phase10.mode-comparison.v1"

MODE_ORDER = ("api", "local", "hybrid")
STAGE_ORDER = ("transcription", "analysis", "edit_planning", "rendering")

CAPABILITY_TRANSCRIPTION = "transcription"
CAPABILITY_CHAT = "chat"
CAPABILITY_LOCAL_RUNTIME = "local_runtime"

STAGE_LABELS = {
    "transcription": "Transcription",
    "analysis": "Analysis",
    "edit_planning": "Edit planning",
    "rendering": "Rendering",
}

MODE_LABELS = {
    "api": "API mode",
    "local": "Local mode",
    "hybrid": "Hybrid mode",
}

MODE_TRADEOFFS = {
    "api": [
        "Best accuracy and easiest demo setup when keys are configured.",
        "Highest estimated external cost and lowest privacy posture.",
        "Rendering still runs locally through FFmpeg in this prototype.",
    ],
    "local": [
        "Best privacy and zero API spend after models are available.",
        "Quality depends heavily on local model availability and hardware.",
        "Useful baseline for offline/private lecture material.",
    ],
    "hybrid": [
        "Balances private local passes with API help for high-value reasoning.",
        "Recommended academic demo default because it shows fallback behavior.",
        "Keeps deterministic cleaning and rendering local while using API planning where it matters.",
    ],
}

STAGE_PROFILES: dict[str, dict[str, dict[str, Any]]] = {
    "api": {
        "transcription": {
            "provider_strategy": "api_asr",
            "capability": CAPABILITY_TRANSCRIPTION,
            "duration_factor": 0.35,
            "fixed_seconds": 8.0,
            "cost_per_minute_usd": 0.006,
            "quality_delta": 0.05,
            "privacy_score": 0.35,
            "notes": "Uses a hosted ASR provider such as Voxtral, Mistral, or Whisper API.",
        },
        "analysis": {
            "provider_strategy": "api_reasoning_and_embeddings",
            "capability": CAPABILITY_CHAT,
            "duration_factor": 0.12,
            "per_segment_seconds": 0.8,
            "fixed_seconds": 10.0,
            "cost_per_minute_usd": 0.012,
            "quality_delta": 0.04,
            "privacy_score": 0.30,
            "notes": "Uses hosted reasoning, embeddings, and optional vision for content understanding.",
        },
        "edit_planning": {
            "provider_strategy": "api_json_planner",
            "capability": CAPABILITY_CHAT,
            "duration_factor": 0.06,
            "per_segment_seconds": 0.5,
            "fixed_seconds": 7.0,
            "cost_per_minute_usd": 0.006,
            "quality_delta": 0.04,
            "privacy_score": 0.30,
            "notes": "Uses a hosted planner for structured edit decisions and rationale.",
        },
        "rendering": {
            "provider_strategy": "local_ffmpeg_renderer",
            "capability": None,
            "output_duration_factor": 0.60,
            "fixed_seconds": 12.0,
            "cost_per_minute_usd": 0.0,
            "quality_delta": 0.0,
            "privacy_score": 0.95,
            "notes": "Rendering is local in all modes; comparison tracks the same FFmpeg export path.",
        },
    },
    "local": {
        "transcription": {
            "provider_strategy": "local_whisper_cpp",
            "capability": CAPABILITY_TRANSCRIPTION,
            "duration_factor": 1.20,
            "fixed_seconds": 12.0,
            "cost_per_minute_usd": 0.0,
            "quality_delta": -0.04,
            "privacy_score": 1.0,
            "notes": "Uses a local Whisper model when downloaded and configured.",
        },
        "analysis": {
            "provider_strategy": "local_rules_and_llm",
            "capability": CAPABILITY_CHAT,
            "duration_factor": 0.55,
            "per_segment_seconds": 1.4,
            "fixed_seconds": 15.0,
            "cost_per_minute_usd": 0.0,
            "quality_delta": -0.08,
            "privacy_score": 0.95,
            "notes": "Uses deterministic passes plus an optional local LLM/runtime.",
        },
        "edit_planning": {
            "provider_strategy": "local_planner_or_rules",
            "capability": CAPABILITY_CHAT,
            "duration_factor": 0.32,
            "per_segment_seconds": 1.0,
            "fixed_seconds": 12.0,
            "cost_per_minute_usd": 0.0,
            "quality_delta": -0.10,
            "privacy_score": 0.95,
            "notes": "Uses local model/rules for edit decisions; strongest as an offline baseline.",
        },
        "rendering": {
            "provider_strategy": "local_ffmpeg_renderer",
            "capability": None,
            "output_duration_factor": 0.60,
            "fixed_seconds": 12.0,
            "cost_per_minute_usd": 0.0,
            "quality_delta": 0.0,
            "privacy_score": 0.95,
            "notes": "Rendering is local in all modes; this is the native renderer path.",
        },
    },
    "hybrid": {
        "transcription": {
            "provider_strategy": "local_first_api_fallback_asr",
            "capability": CAPABILITY_TRANSCRIPTION,
            "duration_factor": 0.95,
            "fixed_seconds": 12.0,
            "cost_per_minute_usd": 0.0012,
            "quality_delta": 0.01,
            "privacy_score": 0.85,
            "notes": "Uses local transcription first with API fallback for failure or low confidence.",
        },
        "analysis": {
            "provider_strategy": "local_deterministic_api_reasoning",
            "capability": CAPABILITY_CHAT,
            "duration_factor": 0.22,
            "per_segment_seconds": 0.7,
            "fixed_seconds": 10.0,
            "cost_per_minute_usd": 0.005,
            "quality_delta": 0.03,
            "privacy_score": 0.70,
            "notes": "Keeps cheap deterministic analysis local and calls API for nuanced reasoning.",
        },
        "edit_planning": {
            "provider_strategy": "api_planner_with_local_validation",
            "capability": CAPABILITY_CHAT,
            "duration_factor": 0.07,
            "per_segment_seconds": 0.45,
            "fixed_seconds": 8.0,
            "cost_per_minute_usd": 0.006,
            "quality_delta": 0.04,
            "privacy_score": 0.65,
            "notes": "Uses API planning with local validation and deterministic edit-plan checks.",
        },
        "rendering": {
            "provider_strategy": "local_ffmpeg_renderer",
            "capability": None,
            "output_duration_factor": 0.60,
            "fixed_seconds": 12.0,
            "cost_per_minute_usd": 0.0,
            "quality_delta": 0.0,
            "privacy_score": 0.95,
            "notes": "Rendering remains local while AI stages can mix API/local providers.",
        },
    },
}


def build_mode_comparison_report(
    *,
    video: Any,
    plan: Any,
    segments: Iterable[Any],
    transcript: Any | None,
    plan_payload: dict[str, Any] | None,
    quality_report: dict[str, Any] | None = None,
    settings_record: Any | None = None,
    render_job: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a deterministic mode comparison from persisted evaluation data."""
    segment_list = list(segments or [])
    payload = dict_value(plan_payload)
    quality = dict_value(quality_report)
    evaluation_metrics = dict_value(quality.get("evaluation_metrics"))
    evaluation_summary = dict_value(evaluation_metrics.get("summary"))
    duration_seconds = first_number(
        quality.get("original_duration_seconds"),
        getattr(plan, "original_duration", None),
        getattr(video, "duration_seconds", None),
        segment_duration_total(segment_list),
    ) or 0.0
    output_duration_seconds = first_number(
        quality.get("actual_output_duration_seconds"),
        getattr(plan, "estimated_duration", None),
        quality.get("estimated_duration_seconds"),
        duration_seconds,
    ) or 0.0
    current_mode = current_processing_mode(payload, evaluation_metrics, settings_record)
    mode_reports = [
        build_mode_profile(
            mode=mode,
            video=video,
            plan=plan,
            segments=segment_list,
            transcript=transcript,
            duration_seconds=duration_seconds,
            output_duration_seconds=output_duration_seconds,
            evaluation_summary=evaluation_summary,
            evaluation_metrics=evaluation_metrics,
            settings_record=settings_record,
            render_job=render_job,
        )
        for mode in MODE_ORDER
    ]
    comparison = build_comparison(mode_reports, current_mode)

    return {
        "schema_version": MODE_COMPARISON_SCHEMA_VERSION,
        "generated_at": utc_now(),
        "video_id": str(getattr(video, "id", "")),
        "project_id": str(getattr(video, "project_id", "") or "") or None,
        "current_mode": current_mode,
        "baseline": {
            "duration_seconds": round(duration_seconds, 3),
            "estimated_output_duration_seconds": round(output_duration_seconds, 3),
            "segment_count": len(segment_list),
            "transcript_provider": getattr(transcript, "asr_provider", None) if transcript else None,
            "quality_summary": evaluation_summary,
            "render_job": render_job,
        },
        "workflow": build_workflow(current_mode),
        "stage_matrix": build_stage_matrix(settings_record),
        "modes": mode_reports,
        "comparison": comparison,
    }


def build_mode_profile(
    *,
    mode: str,
    video: Any,
    plan: Any,
    segments: list[Any],
    transcript: Any | None,
    duration_seconds: float,
    output_duration_seconds: float,
    evaluation_summary: dict[str, Any],
    evaluation_metrics: dict[str, Any],
    settings_record: Any | None,
    render_job: dict[str, Any] | None,
) -> dict[str, Any]:
    stages = [
        build_stage_report(
            mode=mode,
            stage=stage,
            profile=STAGE_PROFILES[mode][stage],
            duration_seconds=duration_seconds,
            output_duration_seconds=output_duration_seconds,
            segment_count=len(segments),
            evaluation_summary=evaluation_summary,
            evaluation_metrics=evaluation_metrics,
            settings_record=settings_record,
            transcript=transcript,
            render_job=render_job,
        )
        for stage in STAGE_ORDER
    ]
    total_seconds = sum(float(stage["estimated_runtime_seconds"]) for stage in stages)
    total_cost = sum(float(stage["estimated_cost_usd"]) for stage in stages)
    quality_score = weighted_average(
        [
            (stages[0]["estimated_quality_score"], 0.30),
            (stages[1]["estimated_quality_score"], 0.25),
            (stages[2]["estimated_quality_score"], 0.30),
            (stages[3]["estimated_quality_score"], 0.15),
        ]
    )
    privacy_score = average(stage["privacy_score"] for stage in stages)
    readiness_issues = [
        issue
        for stage in stages
        for issue in stage.get("readiness", {}).get("issues", [])
    ]

    return {
        "mode": mode,
        "label": MODE_LABELS[mode],
        "summary": {
            "estimated_total_runtime_seconds": round(total_seconds, 3),
            "estimated_total_cost_usd": round(total_cost, 5),
            "estimated_quality_score": round(clamp01(quality_score), 4),
            "privacy_score": round(clamp01(privacy_score), 4),
            "readiness": "ready" if not readiness_issues else "needs_setup",
            "stage_count": len(stages),
        },
        "stages": stages,
        "tradeoffs": MODE_TRADEOFFS[mode],
    }


def build_stage_report(
    *,
    mode: str,
    stage: str,
    profile: dict[str, Any],
    duration_seconds: float,
    output_duration_seconds: float,
    segment_count: int,
    evaluation_summary: dict[str, Any],
    evaluation_metrics: dict[str, Any],
    settings_record: Any | None,
    transcript: Any | None,
    render_job: dict[str, Any] | None,
) -> dict[str, Any]:
    runtime_seconds = estimate_stage_runtime(
        profile=profile,
        duration_seconds=duration_seconds,
        output_duration_seconds=output_duration_seconds,
        segment_count=segment_count,
        render_job=render_job if stage == "rendering" else None,
    )
    cost = estimate_stage_cost(
        profile=profile,
        duration_seconds=duration_seconds,
        segment_count=segment_count,
    )
    provider = provider_snapshot(
        mode=mode,
        stage=stage,
        profile=profile,
        settings_record=settings_record,
        transcript=transcript,
    )
    base_quality = stage_quality_baseline(stage, evaluation_summary, evaluation_metrics)
    quality = clamp01(base_quality + float(profile.get("quality_delta") or 0.0))

    return {
        "stage": stage,
        "label": STAGE_LABELS[stage],
        "mode": provider["stage_mode"],
        "provider_strategy": profile["provider_strategy"],
        "provider": provider,
        "estimated_runtime_seconds": round(runtime_seconds, 3),
        "estimated_cost_usd": round(cost, 5),
        "estimated_quality_score": round(quality, 4),
        "privacy_score": round(float(profile.get("privacy_score") or 0.0), 4),
        "readiness": readiness_for_stage(
            mode=mode,
            stage=stage,
            profile=profile,
            settings_record=settings_record,
        ),
        "notes": profile["notes"],
    }


def build_comparison(mode_reports: list[dict[str, Any]], current_mode: str) -> dict[str, Any]:
    summaries = {report["mode"]: report["summary"] for report in mode_reports}
    fastest_mode = min(
        summaries,
        key=lambda mode: summaries[mode]["estimated_total_runtime_seconds"],
    )
    lowest_cost_mode = min(
        summaries,
        key=lambda mode: summaries[mode]["estimated_total_cost_usd"],
    )
    highest_quality_mode = max(
        summaries,
        key=lambda mode: summaries[mode]["estimated_quality_score"],
    )
    ranking = []
    for report in mode_reports:
        summary = report["summary"]
        score = overall_mode_score(summary, summaries)
        ranking.append(
            {
                "mode": report["mode"],
                "label": report["label"],
                "score": round(score, 4),
                "readiness": summary["readiness"],
                "estimated_total_runtime_seconds": summary["estimated_total_runtime_seconds"],
                "estimated_total_cost_usd": summary["estimated_total_cost_usd"],
                "estimated_quality_score": summary["estimated_quality_score"],
            }
        )
    ranking.sort(key=lambda item: item["score"], reverse=True)
    current_summary = summaries.get(current_mode) or summaries["hybrid"]

    return {
        "fastest_mode": fastest_mode,
        "lowest_cost_mode": lowest_cost_mode,
        "highest_quality_mode": highest_quality_mode,
        "recommended_mode": ranking[0]["mode"],
        "ranking": ranking,
        "delta_vs_current_mode": {
            mode: {
                "runtime_seconds": round(
                    summaries[mode]["estimated_total_runtime_seconds"]
                    - current_summary["estimated_total_runtime_seconds"],
                    3,
                ),
                "cost_usd": round(
                    summaries[mode]["estimated_total_cost_usd"]
                    - current_summary["estimated_total_cost_usd"],
                    5,
                ),
                "quality_score": round(
                    summaries[mode]["estimated_quality_score"]
                    - current_summary["estimated_quality_score"],
                    4,
                ),
            }
            for mode in summaries
        },
    }


def build_workflow(current_mode: str) -> list[dict[str, Any]]:
    return [
        {
            "step": "capture_baseline",
            "title": "Capture current processed-video baseline",
            "status": "available",
            "modes": [current_mode],
            "output": "quality_report",
        },
        {
            "step": "compare_transcription",
            "title": "Compare ASR provider strategy and cost",
            "status": "planned",
            "modes": list(MODE_ORDER),
            "output": "transcription_stage_matrix",
        },
        {
            "step": "compare_analysis_and_planning",
            "title": "Compare analysis and edit-planning quality/time/cost",
            "status": "planned",
            "modes": list(MODE_ORDER),
            "output": "stage_quality_and_cost_estimates",
        },
        {
            "step": "compare_rendering",
            "title": "Confirm local renderer impact across all modes",
            "status": "planned",
            "modes": list(MODE_ORDER),
            "output": "rendering_stage_matrix",
        },
        {
            "step": "export_report",
            "title": "Export API/local/hybrid comparison evidence",
            "status": "available",
            "modes": list(MODE_ORDER),
            "output": "mode_comparison_json_and_markdown",
        },
    ]


def build_stage_matrix(settings_record: Any | None) -> dict[str, Any]:
    return {
        stage: {
            mode: {
                "provider_strategy": STAGE_PROFILES[mode][stage]["provider_strategy"],
                "provider": provider_snapshot(
                    mode=mode,
                    stage=stage,
                    profile=STAGE_PROFILES[mode][stage],
                    settings_record=settings_record,
                    transcript=None,
                ),
            }
            for mode in MODE_ORDER
        }
        for stage in STAGE_ORDER
    }


def build_mode_comparison_markdown(report: dict[str, Any]) -> str:
    """Build a compact Markdown summary for thesis/demo evidence."""
    baseline = dict_value(report.get("baseline"))
    comparison = dict_value(report.get("comparison"))
    lines = [
        "# API vs Local vs Hybrid Comparison",
        "",
        f"Generated: {report.get('generated_at')}",
        f"Video ID: {report.get('video_id')}",
        f"Current mode: {report.get('current_mode')}",
        "",
        "## Baseline",
        "",
        f"- Duration: {format_seconds(baseline.get('duration_seconds'))}",
        f"- Estimated output: {format_seconds(baseline.get('estimated_output_duration_seconds'))}",
        f"- Segments: {baseline.get('segment_count', 0)}",
        f"- Transcript provider: {baseline.get('transcript_provider') or 'unknown'}",
        "",
        "## Recommendation",
        "",
        f"- Recommended mode: {comparison.get('recommended_mode')}",
        f"- Fastest mode: {comparison.get('fastest_mode')}",
        f"- Lowest cost mode: {comparison.get('lowest_cost_mode')}",
        f"- Highest quality mode: {comparison.get('highest_quality_mode')}",
        "",
        "## Mode Summary",
        "",
        "| Mode | Runtime | Cost | Quality | Privacy | Readiness |",
        "| --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for mode_report in report.get("modes") or []:
        if not isinstance(mode_report, dict):
            continue
        summary = dict_value(mode_report.get("summary"))
        lines.append(
            "| {label} | {runtime} | {cost} | {quality:.2f} | {privacy:.2f} | {readiness} |".format(
                label=mode_report.get("label") or mode_report.get("mode"),
                runtime=format_seconds(summary.get("estimated_total_runtime_seconds")),
                cost=format_usd(summary.get("estimated_total_cost_usd")),
                quality=float(summary.get("estimated_quality_score") or 0.0),
                privacy=float(summary.get("privacy_score") or 0.0),
                readiness=summary.get("readiness") or "unknown",
            )
        )

    lines.extend(["", "## Stage Notes", ""])
    for mode_report in report.get("modes") or []:
        if not isinstance(mode_report, dict):
            continue
        lines.extend(["", f"### {mode_report.get('label')}", ""])
        for stage in mode_report.get("stages") or []:
            if not isinstance(stage, dict):
                continue
            lines.append(
                "- {label}: {strategy}, {runtime}, {cost}, quality {quality:.2f}".format(
                    label=stage.get("label"),
                    strategy=stage.get("provider_strategy"),
                    runtime=format_seconds(stage.get("estimated_runtime_seconds")),
                    cost=format_usd(stage.get("estimated_cost_usd")),
                    quality=float(stage.get("estimated_quality_score") or 0.0),
                )
            )

    lines.append("")
    return "\n".join(lines)


def estimate_stage_runtime(
    *,
    profile: dict[str, Any],
    duration_seconds: float,
    output_duration_seconds: float,
    segment_count: int,
    render_job: dict[str, Any] | None,
) -> float:
    if render_job and first_number(render_job.get("elapsed_seconds")):
        return float(render_job["elapsed_seconds"])
    duration_base = output_duration_seconds if "output_duration_factor" in profile else duration_seconds
    factor = first_number(profile.get("duration_factor"), profile.get("output_duration_factor"), 0.0) or 0.0
    return max(
        0.0,
        (duration_base * factor)
        + (segment_count * float(profile.get("per_segment_seconds") or 0.0))
        + float(profile.get("fixed_seconds") or 0.0),
    )


def estimate_stage_cost(
    *,
    profile: dict[str, Any],
    duration_seconds: float,
    segment_count: int,
) -> float:
    duration_minutes = max(0.0, duration_seconds / 60.0)
    return (
        duration_minutes * float(profile.get("cost_per_minute_usd") or 0.0)
        + segment_count * float(profile.get("cost_per_segment_usd") or 0.0)
    )


def stage_quality_baseline(
    stage: str,
    evaluation_summary: dict[str, Any],
    evaluation_metrics: dict[str, Any],
) -> float:
    if stage == "transcription":
        return first_number(evaluation_summary.get("transcription_accuracy_proxy_score"), 0.72) or 0.72
    if stage == "analysis":
        return average(
            [
                first_number(evaluation_summary.get("segment_quality_score"), 0.72) or 0.72,
                first_number(evaluation_summary.get("layout_correctness_score"), 0.72) or 0.72,
                filler_dead_air_score(evaluation_summary),
            ]
        )
    if stage == "edit_planning":
        override_rate = first_number(evaluation_summary.get("teacher_override_rate"), 0.0) or 0.0
        return average(
            [
                first_number(evaluation_summary.get("segment_quality_score"), 0.72) or 0.72,
                clamp01(1.0 - override_rate),
                duration_reduction_score(evaluation_metrics),
            ]
        )
    if stage == "rendering":
        return first_number(evaluation_summary.get("layout_correctness_score"), 0.80) or 0.80
    return 0.72


def provider_snapshot(
    *,
    mode: str,
    stage: str,
    profile: dict[str, Any],
    settings_record: Any | None,
    transcript: Any | None,
) -> dict[str, Any]:
    if stage == "rendering":
        return {
            "stage_mode": "local",
            "api_provider_id": None,
            "local_provider_id": "ffmpeg",
            "actual_provider_id": "ffmpeg",
        }

    capability = str(profile.get("capability") or "")
    capability_settings = capability_payload(settings_record, capability)
    api_provider_id = capability_settings.get("api_provider_id")
    local_provider_id = capability_settings.get("local_provider_id")
    actual_provider_id = getattr(transcript, "asr_provider", None) if stage == "transcription" and transcript else None

    if mode == "api":
        stage_mode = "api"
    elif mode == "local":
        stage_mode = "local"
    else:
        stage_mode = "hybrid"

    return {
        "stage_mode": stage_mode,
        "capability": capability or None,
        "api_provider_id": api_provider_id,
        "local_provider_id": local_provider_id,
        "actual_provider_id": actual_provider_id,
        "fallback_order": capability_settings.get("hybrid_fallback_order") or [],
    }


def readiness_for_stage(
    *,
    mode: str,
    stage: str,
    profile: dict[str, Any],
    settings_record: Any | None,
) -> dict[str, Any]:
    if stage == "rendering":
        return {"status": "ready", "issues": [], "checks": ["ffmpeg_renderer"]}

    issues: list[str] = []
    checks: list[str] = []
    capability = str(profile.get("capability") or "")
    capability_settings = capability_payload(settings_record, capability)

    if mode in {"api", "hybrid"}:
        checks.append("api_key_configured")
        if not any_api_key_configured(settings_record):
            issues.append("api_key_not_configured")

    if mode in {"local", "hybrid"}:
        checks.append("local_model_path_configured")
        if capability == CAPABILITY_TRANSCRIPTION and not local_path_for(settings_record, capability):
            issues.append("local_transcription_model_not_configured")

    if mode == "local" and stage in {"analysis", "edit_planning"}:
        checks.append("local_reasoning_runtime")
        local_chat_path = local_path_for(settings_record, CAPABILITY_CHAT)
        local_runtime_path = local_path_for(settings_record, CAPABILITY_LOCAL_RUNTIME)
        if not local_chat_path and not local_runtime_path:
            issues.append("local_reasoning_runtime_not_configured")

    if not capability_settings and settings_record is None:
        checks.append("settings_record_unavailable")

    return {
        "status": "ready" if not issues else "needs_setup",
        "issues": issues,
        "checks": checks,
    }


def current_processing_mode(
    plan_payload: dict[str, Any],
    evaluation_metrics: dict[str, Any],
    settings_record: Any | None,
) -> str:
    metadata = dict_value(plan_payload.get("metadata"))
    export_metadata = dict_value(plan_payload.get("export_metadata"))
    cost = dict_value(evaluation_metrics.get("cost"))
    candidates = [
        metadata.get("processing_mode"),
        export_metadata.get("processing_mode"),
        cost.get("processing_mode"),
        getattr(settings_record, "preferred_processing_mode", None),
    ]
    for candidate in candidates:
        text = str(candidate or "").lower()
        if text in MODE_ORDER:
            return text
    return "hybrid"


def overall_mode_score(summary: dict[str, Any], all_summaries: dict[str, dict[str, Any]]) -> float:
    max_time = max(float(item["estimated_total_runtime_seconds"]) for item in all_summaries.values()) or 1.0
    max_cost = max(float(item["estimated_total_cost_usd"]) for item in all_summaries.values()) or 1.0
    speed_score = 1.0 - (float(summary["estimated_total_runtime_seconds"]) / max_time)
    cost_score = 1.0 - (float(summary["estimated_total_cost_usd"]) / max_cost if max_cost else 0.0)
    quality_score = float(summary["estimated_quality_score"])
    privacy_score = float(summary["privacy_score"])
    readiness_score = 1.0 if summary.get("readiness") == "ready" else 0.65
    return (
        quality_score * 0.42
        + privacy_score * 0.22
        + cost_score * 0.15
        + speed_score * 0.11
        + readiness_score * 0.10
    )


def capability_payload(settings_record: Any | None, capability: str) -> dict[str, Any]:
    if not settings_record or not capability:
        return {}
    capabilities = getattr(settings_record, "capabilities_json", None) or {}
    payload = capabilities.get(capability)
    return dict(payload) if isinstance(payload, dict) else {}


def local_path_for(settings_record: Any | None, capability: str) -> str | None:
    if not settings_record:
        return None
    paths = getattr(settings_record, "local_model_paths_json", None) or {}
    path = paths.get(capability)
    return str(path) if path else None


def any_api_key_configured(settings_record: Any | None) -> bool:
    if not settings_record:
        return False
    api_keys = getattr(settings_record, "api_keys_json", None) or {}
    for entry in api_keys.values():
        if not isinstance(entry, dict):
            continue
        if entry.get("source") == "encrypted_db" and entry.get("encrypted_value"):
            return True
        env_var = entry.get("env_var")
        if env_var and os.getenv(str(env_var)):
            return True
    return False


def filler_dead_air_score(evaluation_summary: dict[str, Any]) -> float:
    return average(
        [
            first_number(evaluation_summary.get("filler_removal_rate"), 0.0) or 0.0,
            first_number(evaluation_summary.get("dead_air_removal_rate"), 0.0) or 0.0,
        ]
    )


def duration_reduction_score(evaluation_metrics: dict[str, Any]) -> float:
    reduction = dict_value(evaluation_metrics.get("duration_reduction"))
    percent = first_number(reduction.get("reduction_percent"), 0.0) or 0.0
    if percent <= 0:
        return 0.55
    if percent <= 40:
        return 0.65 + (percent / 40.0 * 0.25)
    return max(0.65, 0.90 - ((percent - 40.0) / 100.0))


def segment_duration_total(segments: Iterable[Any]) -> float:
    total = 0.0
    for segment in segments:
        duration = first_number(getattr(segment, "duration", None))
        if duration is None:
            start = first_number(getattr(segment, "start_time", None), 0.0) or 0.0
            end = first_number(getattr(segment, "end_time", None), start) or start
            duration = max(0.0, end - start)
        total += duration
    return total


def weighted_average(values: Iterable[tuple[Any, float]]) -> float:
    weighted_sum = 0.0
    total_weight = 0.0
    for value, weight in values:
        number = first_number(value)
        if number is None:
            continue
        weighted_sum += number * weight
        total_weight += weight
    return weighted_sum / total_weight if total_weight else 0.0


def average(values: Iterable[Any]) -> float:
    numbers = [number for number in (first_number(value) for value in values) if number is not None]
    return sum(numbers) / len(numbers) if numbers else 0.0


def first_number(*values: Any) -> float | None:
    for value in values:
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def dict_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def clamp01(value: Any) -> float:
    number = first_number(value, 0.0) or 0.0
    return max(0.0, min(1.0, number))


def format_seconds(value: Any) -> str:
    seconds = max(0.0, first_number(value, 0.0) or 0.0)
    minutes = int(seconds // 60)
    remaining = int(round(seconds % 60))
    return f"{minutes}:{remaining:02d}"


def format_usd(value: Any) -> str:
    return f"${(first_number(value, 0.0) or 0.0):.5f}"


def utc_now() -> str:
    return datetime.now(UTC).isoformat()
