"""Evaluation and demo artifact helpers for rendered lecture exports."""

from __future__ import annotations

import json
import os
import csv
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable


EXPORT_ARTIFACT_SCHEMA_VERSION = "phase9.evaluation-artifacts.v1"

ARTIFACT_LABELS = {
    "edited_video": "Edited video",
    "audio_only": "Audio-only export",
    "subtitles_srt": "Captions (SRT)",
    "subtitles_vtt": "Captions (VTT)",
    "transcript_srt": "Transcript captions (SRT)",
    "transcript_vtt": "Transcript captions (VTT)",
    "chapters": "Chapter markers",
    "plan_json": "Edit plan JSON",
    "quality_report": "Quality report JSON",
    "mode_comparison_json": "API/local/hybrid comparison JSON",
    "mode_comparison_markdown": "API/local/hybrid comparison summary",
    "academic_evidence_json": "Academic evidence JSON",
    "academic_evidence_markdown": "Academic evidence summary",
    "before_after_comparison_json": "Before/after comparison JSON",
    "timeline_decisions_json": "Timeline decisions JSON",
    "timeline_decisions_csv": "Timeline decisions CSV",
    "provider_mode_trace_json": "AI provider mode trace JSON",
    "metrics_summary_json": "Metrics summary JSON",
    "generated_evidence_index_json": "Generated evidence file index JSON",
}

MEDIA_TYPES = {
    ".csv": "text/csv",
    ".json": "application/json",
    ".md": "text/markdown",
    ".mp4": "video/mp4",
    ".m4a": "audio/mp4",
    ".mp3": "audio/mpeg",
    ".srt": "application/x-subrip",
    ".txt": "text/plain",
    ".vtt": "text/vtt",
    ".wav": "audio/wav",
    ".zip": "application/zip",
}


def artifact_records(artifact_paths: dict[str, str | None]) -> list[dict[str, Any]]:
    """Return stable artifact metadata for export manifests and edit-plan JSON."""
    records: list[dict[str, Any]] = []
    for kind, path in artifact_paths.items():
        exists = bool(path and os.path.exists(path))
        records.append(
            {
                "kind": kind,
                "label": ARTIFACT_LABELS.get(kind, kind.replace("_", " ").title()),
                "path": path,
                "filename": os.path.basename(path) if path else None,
                "media_type": media_type_for_path(path),
                "available": exists,
                "size_bytes": os.path.getsize(path) if exists and path else None,
            }
        )
    return records


def media_type_for_path(path: str | None) -> str:
    if not path:
        return "application/octet-stream"
    return MEDIA_TYPES.get(Path(path).suffix.lower(), "application/octet-stream")


def write_json_artifact(path: str, payload: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, default=str)


def write_text_artifact(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(content)


def write_csv_artifact(path: str, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def build_academic_evidence_artifact(
    *,
    video: Any,
    plan: Any,
    segments: Iterable[Any],
    transcript: Any | None,
    plan_payload: dict[str, Any],
    quality_report: dict[str, Any],
    artifact_manifest: list[dict[str, Any]],
    render_metadata: dict[str, Any] | None = None,
    mode_comparison: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a compact evidence payload for demos, evaluation, and thesis notes."""
    segment_list = list(segments)
    teacher_modified = sum(1 for segment in segment_list if bool(getattr(segment, "is_teacher_modified", False)))
    teacher_overrides = sum(
        1
        for segment in segment_list
        if bool(getattr(segment, "is_teacher_modified", False))
        and getattr(segment, "teacher_action", None) != getattr(segment, "action", None)
    )
    total_segments = len(segment_list)
    override_rate = round(teacher_overrides / total_segments, 4) if total_segments else 0.0

    export_metadata = dict_value(plan_payload.get("export_metadata"))
    selected_preset = dict_value(export_metadata.get("selected_preset"))
    evaluation_metrics = dict_value(quality_report.get("evaluation_metrics"))
    evaluation_summary = dict_value(evaluation_metrics.get("summary"))
    before_after = build_before_after_comparison(
        video=video,
        plan=plan,
        segments=segment_list,
        plan_payload=plan_payload,
        quality_report=quality_report,
    )
    timeline_decisions = build_timeline_decisions_artifact(
        segments=segment_list,
        plan_payload=plan_payload,
        quality_report=quality_report,
    )
    metrics_summary = build_metrics_summary_artifact(quality_report)
    provider_trace = build_provider_mode_trace(
        transcript=transcript,
        plan_payload=plan_payload,
        quality_report=quality_report,
        mode_comparison=mode_comparison,
    )

    return {
        "schema_version": EXPORT_ARTIFACT_SCHEMA_VERSION,
        "generated_at": utc_now(),
        "purpose": "evaluation_demo_academic_evidence",
        "video": {
            "id": str(getattr(video, "id", "")),
            "filename": getattr(video, "original_filename", None),
            "duration_seconds": getattr(video, "duration_seconds", None),
            "resolution": getattr(video, "resolution", None),
            "fps": getattr(video, "fps", None),
            "status": enum_value(getattr(video, "status", None)),
        },
        "provider_trace": provider_trace,
        "metrics_summary": {
            "original_duration_seconds": quality_report.get("original_duration_seconds"),
            "estimated_duration_seconds": quality_report.get("estimated_duration_seconds"),
            "actual_output_duration_seconds": quality_report.get("actual_output_duration_seconds"),
            "time_saved_seconds": quality_report.get("time_saved_seconds"),
            "reduction_percent": quality_report.get("reduction_percent"),
            "total_segments": total_segments,
            "teacher_modifications": teacher_modified,
            "teacher_overrides": teacher_overrides,
            "teacher_override_rate": override_rate,
            "transcript_cut_count": dict_value(quality_report.get("transcript_edit_sync")).get("transcript_cut_count"),
            "transcription_accuracy_proxy_score": evaluation_summary.get("transcription_accuracy_proxy_score"),
            "processing_time_seconds": evaluation_summary.get("processing_time_seconds"),
            "estimated_cost_usd": evaluation_summary.get("estimated_cost_usd"),
            "filler_removal_rate": evaluation_summary.get("filler_removal_rate"),
            "dead_air_removal_rate": evaluation_summary.get("dead_air_removal_rate"),
            "segment_quality_score": evaluation_summary.get("segment_quality_score"),
            "layout_correctness_score": evaluation_summary.get("layout_correctness_score"),
        },
        "before_after_comparison": before_after,
        "timeline_decisions": timeline_decisions,
        "thesis_metrics_summary": metrics_summary,
        "evaluation_metrics": evaluation_metrics,
        "decision_audit": [
            {
                "segment_index": getattr(segment, "segment_index", None),
                "start_time": getattr(segment, "start_time", None),
                "end_time": getattr(segment, "end_time", None),
                "topic": getattr(segment, "topic_label", None),
                "ai_action": enum_value(getattr(segment, "action", None)),
                "ai_confidence": getattr(segment, "action_confidence", None),
                "ai_reason": getattr(segment, "action_reason", None),
                "teacher_action": enum_value(getattr(segment, "teacher_action", None)),
                "teacher_note": getattr(segment, "teacher_note", None),
                "final_action": enum_value(getattr(segment, "teacher_action", None) or getattr(segment, "action", None)),
            }
            for segment in segment_list
        ],
        "chapters": list(plan_payload.get("chapters") or []),
        "sections": list(plan_payload.get("sections") or []),
        "caption_policy": next(
            (
                action
                for action in plan_payload.get("polish_actions", [])
                if isinstance(action, dict) and action.get("kind") == "caption_policy"
            ),
            {},
        ),
        "render_metadata": render_metadata or dict_value(dict_value(plan_payload.get("export_metadata")).get("render")),
        "quality_report": quality_report,
        "artifact_manifest": artifact_manifest,
        "generated_evidence_files": build_generated_evidence_index(artifact_manifest),
        "reproducibility": {
            "edit_plan_id": str(getattr(plan, "id", "")),
            "edit_plan_schema_version": plan_payload.get("schema_version"),
            "export_metadata": export_metadata,
        },
    }


def build_evidence_markdown(evidence: dict[str, Any]) -> str:
    """Build a human-readable summary for demos and supervisor review."""
    video = dict_value(evidence.get("video"))
    metrics = dict_value(evidence.get("metrics_summary"))
    provider = dict_value(evidence.get("provider_trace"))
    before_after = dict_value(evidence.get("before_after_comparison"))
    artifacts = list(evidence.get("artifact_manifest") or [])
    chapters = list(evidence.get("chapters") or [])

    lines = [
        "# AI Video Editor Evidence Summary",
        "",
        f"Generated: {evidence.get('generated_at')}",
        "",
        "## Source",
        "",
        f"- Video: {video.get('filename') or video.get('id')}",
        f"- Duration: {format_seconds(metrics.get('original_duration_seconds'))}",
        f"- Resolution: {video.get('resolution') or 'unknown'}",
        f"- Processing mode used: {provider.get('processing_mode') or 'unknown'}",
        "",
        "## Editing Outcome",
        "",
        f"- Estimated edited duration: {format_seconds(metrics.get('estimated_duration_seconds'))}",
        f"- Actual output duration: {format_seconds(metrics.get('actual_output_duration_seconds'))}",
        f"- Time saved: {format_seconds(metrics.get('time_saved_seconds'))}",
        f"- Reduction: {metrics.get('reduction_percent', 0)}%",
        f"- Kept timeline: {format_seconds(dict_value(before_after.get('after')).get('kept_duration_seconds'))}",
        f"- Removed timeline: {format_seconds(dict_value(before_after.get('after')).get('removed_duration_seconds'))}",
        f"- Teacher overrides: {metrics.get('teacher_overrides', 0)} of {metrics.get('total_segments', 0)} segments",
        f"- Transcript cuts: {metrics.get('transcript_cut_count') or 0}",
        f"- Transcription accuracy proxy: {format_score(metrics.get('transcription_accuracy_proxy_score'))}",
        f"- Processing time: {format_seconds(metrics.get('processing_time_seconds'))}",
        f"- Estimated cost: {format_usd(metrics.get('estimated_cost_usd'))}",
        f"- Segment quality score: {format_score(metrics.get('segment_quality_score'))}",
        f"- Layout correctness score: {format_score(metrics.get('layout_correctness_score'))}",
        "",
        "## AI Trace",
        "",
        f"- Processing mode: {provider.get('processing_mode') or 'unknown'}",
        f"- Transcription provider: {provider.get('transcription_provider') or 'unknown'}",
        f"- Transcript language: {provider.get('transcript_language') or 'unknown'}",
        f"- Plan source: {provider.get('plan_source') or 'unknown'}",
        f"- Export preset: {provider.get('selected_preset_id') or 'unknown'}",
        "",
        "## Chapters",
        "",
    ]

    if chapters:
        for chapter in chapters[:20]:
            if isinstance(chapter, dict):
                label = chapter.get("label") or chapter.get("title") or "Chapter"
                timestamp = chapter.get("formatted") or format_seconds(chapter.get("timestamp"))
                lines.append(f"- {timestamp}: {label}")
    else:
        lines.append("- No chapter records were available in the edit plan.")

    lines.extend(["", "## Exported Artifacts", ""])
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        status = "available" if artifact.get("available") else "missing"
        lines.append(f"- {artifact.get('label') or artifact.get('kind')}: {artifact.get('filename') or 'not generated'} ({status})")

    lines.append("")
    return "\n".join(lines)


def build_before_after_comparison(
    *,
    video: Any,
    plan: Any,
    segments: Iterable[Any],
    plan_payload: dict[str, Any],
    quality_report: dict[str, Any],
) -> dict[str, Any]:
    """Summarize the source timeline versus the edited/exported timeline."""
    segment_list = list(segments or [])
    original_duration = first_number(
        quality_report.get("original_duration_seconds"),
        getattr(plan, "original_duration", None),
        getattr(video, "duration_seconds", None),
        sum(segment_duration(segment) for segment in segment_list),
    ) or 0.0
    estimated_duration = first_number(
        quality_report.get("estimated_duration_seconds"),
        getattr(plan, "estimated_duration", None),
        sum(segment_duration(segment) for segment in segment_list if final_action(segment) in {"keep", "highlight", "shorten"}),
    ) or 0.0
    actual_duration = first_number(quality_report.get("actual_output_duration_seconds"))
    removed_duration = max(0.0, original_duration - estimated_duration)
    action_summary = summarize_segment_actions(segment_list)
    transcript_sync = dict_value(quality_report.get("transcript_edit_sync"))

    return {
        "schema_version": EXPORT_ARTIFACT_SCHEMA_VERSION,
        "before": {
            "duration_seconds": round(original_duration, 3),
            "segment_count": len(segment_list),
            "filename": getattr(video, "original_filename", None),
            "resolution": getattr(video, "resolution", None),
            "fps": getattr(video, "fps", None),
        },
        "after": {
            "estimated_duration_seconds": round(estimated_duration, 3),
            "actual_output_duration_seconds": round(actual_duration, 3) if actual_duration is not None else None,
            "kept_duration_seconds": round(action_summary["kept_duration_seconds"], 3),
            "removed_duration_seconds": round(removed_duration, 3),
            "reduction_percent": round((removed_duration / original_duration * 100.0), 3) if original_duration else 0.0,
            "segments_kept": action_summary["segments_kept"],
            "segments_cut": action_summary["segments_cut"],
            "segments_shortened": action_summary["segments_shortened"],
            "segments_highlighted": action_summary["segments_highlighted"],
            "transcript_cut_count": transcript_sync.get("transcript_cut_count"),
            "transcript_cut_duration_seconds": transcript_sync.get("transcript_cut_duration_seconds"),
        },
        "comparison": {
            "time_saved_seconds": quality_report.get("time_saved_seconds"),
            "reduction_percent": quality_report.get("reduction_percent"),
            "teacher_override_rate": quality_report.get("teacher_override_rate"),
            "caption_policy": next(
                (
                    action
                    for action in plan_payload.get("polish_actions", [])
                    if isinstance(action, dict) and action.get("kind") == "caption_policy"
                ),
                {},
            ),
            "selected_preset": dict_value(dict_value(plan_payload.get("export_metadata")).get("selected_preset")),
        },
    }


def build_timeline_decisions_artifact(
    *,
    segments: Iterable[Any],
    plan_payload: dict[str, Any],
    quality_report: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a thesis-friendly timeline decision audit from AI and teacher actions."""
    rows = build_timeline_decision_rows(segments=segments, plan_payload=plan_payload, quality_report=quality_report)
    counts: dict[str, int] = {}
    for row in rows:
        action = str(row.get("final_action") or "unknown")
        counts[action] = counts.get(action, 0) + 1
    return {
        "schema_version": EXPORT_ARTIFACT_SCHEMA_VERSION,
        "decision_count": len(rows),
        "action_distribution": counts,
        "edit_decision_count": len([item for item in plan_payload.get("edit_decisions", []) if isinstance(item, dict)]),
        "rows": rows,
    }


def build_timeline_decision_rows(
    *,
    segments: Iterable[Any],
    plan_payload: dict[str, Any],
    quality_report: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    ranges_by_segment: dict[str, list[dict[str, Any]]] = {}
    transcript_sync = dict_value(dict_value(quality_report or {}).get("transcript_edit_sync"))
    for overlay in transcript_sync.get("segment_overlays") or []:
        if isinstance(overlay, dict) and overlay.get("segment_id"):
            ranges_by_segment[str(overlay["segment_id"])] = list(overlay.get("output_ranges") or [])

    rows = [
        {
            "kind": "segment",
            "decision_id": str(getattr(segment, "id", "")),
            "segment_index": getattr(segment, "segment_index", None),
            "start_time": getattr(segment, "start_time", None),
            "end_time": getattr(segment, "end_time", None),
            "duration_seconds": segment_duration(segment),
            "topic": getattr(segment, "topic_label", None),
            "summary": getattr(segment, "summary", None),
            "ai_action": enum_value(getattr(segment, "action", None)),
            "ai_confidence": getattr(segment, "action_confidence", None),
            "ai_reason": getattr(segment, "action_reason", None),
            "teacher_action": enum_value(getattr(segment, "teacher_action", None)),
            "teacher_note": getattr(segment, "teacher_note", None),
            "final_action": final_action(segment),
            "included_in_output": final_action(segment) in {"keep", "highlight", "shorten"},
            "output_ranges_json": json.dumps(ranges_by_segment.get(str(getattr(segment, "id", "")), [])),
        }
        for segment in segments
    ]

    for decision in plan_payload.get("edit_decisions", []) or []:
        if not isinstance(decision, dict):
            continue
        rows.append(
            {
                "kind": decision.get("kind") or "edit_decision",
                "decision_id": decision.get("id"),
                "segment_index": ",".join(str(item) for item in decision.get("segment_indexes", [])),
                "start_time": decision.get("start_time"),
                "end_time": decision.get("end_time"),
                "duration_seconds": decision.get("duration"),
                "topic": None,
                "summary": decision.get("text"),
                "ai_action": decision.get("source"),
                "ai_confidence": None,
                "ai_reason": decision.get("trim_source"),
                "teacher_action": decision.get("action"),
                "teacher_note": decision.get("teacher_note"),
                "final_action": decision.get("action"),
                "included_in_output": decision.get("action") not in {"cut", "remove"},
                "output_ranges_json": "[]",
            }
        )
    return rows


TIMELINE_DECISION_CSV_FIELDS = [
    "kind",
    "decision_id",
    "segment_index",
    "start_time",
    "end_time",
    "duration_seconds",
    "topic",
    "summary",
    "ai_action",
    "ai_confidence",
    "ai_reason",
    "teacher_action",
    "teacher_note",
    "final_action",
    "included_in_output",
    "output_ranges_json",
]


def build_provider_mode_trace(
    *,
    transcript: Any | None,
    plan_payload: dict[str, Any],
    quality_report: dict[str, Any],
    mode_comparison: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = dict_value(plan_payload.get("metadata"))
    export_metadata = dict_value(plan_payload.get("export_metadata"))
    evaluation_metrics = dict_value(quality_report.get("evaluation_metrics"))
    cost = dict_value(evaluation_metrics.get("cost"))
    selected_preset = dict_value(export_metadata.get("selected_preset"))
    mode = first_text(
        dict_value(mode_comparison).get("current_mode"),
        metadata.get("processing_mode"),
        export_metadata.get("processing_mode"),
        cost.get("processing_mode"),
    )
    provider_name = str(getattr(transcript, "asr_provider", "") or "").lower()
    if not mode and any(key in provider_name for key in ("local", "whisper-cpp", "synthetic")):
        mode = "local"
    elif not mode and provider_name:
        mode = "api"
    mode = mode or "unknown"

    return {
        "schema_version": EXPORT_ARTIFACT_SCHEMA_VERSION,
        "processing_mode": mode,
        "transcription_provider": getattr(transcript, "asr_provider", None) if transcript else None,
        "transcript_language": getattr(transcript, "language", None) if transcript else None,
        "plan_source": metadata.get("source"),
        "created_by": metadata.get("created_by"),
        "selected_preset_id": selected_preset.get("id"),
        "provider_cost": cost,
        "mode_comparison_current_mode": dict_value(mode_comparison).get("current_mode"),
        "mode_comparison_recommendation": dict_value(dict_value(mode_comparison).get("comparison")).get("recommended_mode"),
        "stage_matrix": dict_value(mode_comparison).get("stage_matrix"),
        "workflow": dict_value(mode_comparison).get("workflow"),
    }


def build_metrics_summary_artifact(quality_report: dict[str, Any]) -> dict[str, Any]:
    metrics = dict_value(quality_report.get("evaluation_metrics"))
    summary = dict_value(metrics.get("summary"))
    return {
        "schema_version": EXPORT_ARTIFACT_SCHEMA_VERSION,
        "video_id": quality_report.get("video_id"),
        "video_filename": quality_report.get("video_filename"),
        "duration": {
            "original_seconds": quality_report.get("original_duration_seconds"),
            "estimated_output_seconds": quality_report.get("estimated_duration_seconds"),
            "actual_output_seconds": quality_report.get("actual_output_duration_seconds"),
            "time_saved_seconds": quality_report.get("time_saved_seconds"),
            "reduction_percent": quality_report.get("reduction_percent"),
        },
        "processing": {
            "processing_time_seconds": summary.get("processing_time_seconds") or quality_report.get("processing_time_seconds"),
            "estimated_cost_usd": summary.get("estimated_cost_usd") or quality_report.get("estimated_cost_usd"),
            "processing_mode": dict_value(metrics.get("cost")).get("processing_mode"),
        },
        "quality": {
            "transcription_accuracy_proxy_score": summary.get("transcription_accuracy_proxy_score"),
            "segment_quality_score": summary.get("segment_quality_score"),
            "layout_correctness_score": summary.get("layout_correctness_score"),
            "filler_removal_rate": summary.get("filler_removal_rate"),
            "dead_air_removal_rate": summary.get("dead_air_removal_rate"),
        },
        "teacher_review": {
            "teacher_modifications": quality_report.get("teacher_modifications"),
            "teacher_overrides": quality_report.get("teacher_overrides"),
            "teacher_override_rate": quality_report.get("teacher_override_rate"),
        },
        "source_metrics": metrics,
    }


def build_generated_evidence_index(artifact_manifest: Iterable[dict[str, Any]]) -> dict[str, Any]:
    artifacts = [artifact for artifact in artifact_manifest if isinstance(artifact, dict)]
    return {
        "schema_version": EXPORT_ARTIFACT_SCHEMA_VERSION,
        "total_files": len(artifacts),
        "available_files": sum(1 for artifact in artifacts if artifact.get("available")),
        "missing_files": sum(1 for artifact in artifacts if not artifact.get("available")),
        "files": [
            {
                "kind": artifact.get("kind"),
                "label": artifact.get("label"),
                "filename": artifact.get("filename"),
                "media_type": artifact.get("media_type"),
                "available": artifact.get("available"),
                "size_bytes": artifact.get("size_bytes"),
            }
            for artifact in artifacts
        ],
    }


def create_artifact_bundle(bundle_path: str, artifacts: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Create a ZIP bundle from available artifact records."""
    os.makedirs(os.path.dirname(bundle_path), exist_ok=True)
    included: list[dict[str, Any]] = []
    with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for artifact in artifacts:
            if not isinstance(artifact, dict):
                continue
            path = artifact.get("path")
            if not path or not os.path.exists(path):
                continue
            filename = artifact.get("filename") or os.path.basename(path)
            bundle.write(path, arcname=filename)
            included.append({**artifact, "bundle_filename": filename})

    return {
        "kind": "academic_evidence_bundle",
        "path": bundle_path,
        "filename": os.path.basename(bundle_path),
        "media_type": "application/zip",
        "available": os.path.exists(bundle_path),
        "size_bytes": os.path.getsize(bundle_path) if os.path.exists(bundle_path) else None,
        "included_artifacts": included,
    }


def summarize_segment_actions(segments: Iterable[Any]) -> dict[str, Any]:
    summary = {
        "segments_kept": 0,
        "segments_cut": 0,
        "segments_shortened": 0,
        "segments_highlighted": 0,
        "kept_duration_seconds": 0.0,
    }
    for segment in segments:
        action = final_action(segment)
        duration = segment_duration(segment)
        if action == "cut":
            summary["segments_cut"] += 1
            continue
        if action == "shorten":
            summary["segments_shortened"] += 1
            summary["kept_duration_seconds"] += duration
            continue
        if action == "highlight":
            summary["segments_highlighted"] += 1
            summary["kept_duration_seconds"] += duration
            continue
        if action == "keep":
            summary["segments_kept"] += 1
            summary["kept_duration_seconds"] += duration
    return summary


def segment_duration(segment: Any) -> float:
    duration = first_number(getattr(segment, "duration", None))
    if duration is not None:
        return round(max(0.0, duration), 3)
    start = first_number(getattr(segment, "start_time", None))
    end = first_number(getattr(segment, "end_time", None))
    if start is None or end is None:
        return 0.0
    return round(max(0.0, end - start), 3)


def final_action(segment: Any) -> str:
    return str(enum_value(getattr(segment, "teacher_action", None) or getattr(segment, "action", None)) or "unknown")


def first_number(*values: Any) -> float | None:
    for value in values:
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def first_text(*values: Any) -> str | None:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return None


def dict_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def enum_value(value: Any) -> Any:
    return getattr(value, "value", value)


def format_seconds(value: Any) -> str:
    try:
        seconds = max(0.0, float(value or 0.0))
    except (TypeError, ValueError):
        seconds = 0.0
    minutes = int(seconds // 60)
    remaining = int(round(seconds % 60))
    return f"{minutes}:{remaining:02d}"


def format_score(value: Any) -> str:
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "n/a"


def format_usd(value: Any) -> str:
    try:
        return f"${float(value):.5f}"
    except (TypeError, ValueError):
        return "n/a"


def utc_now() -> str:
    return datetime.now(UTC).isoformat()
