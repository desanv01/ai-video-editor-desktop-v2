"""Evaluation and demo artifact helpers for rendered lecture exports."""

from __future__ import annotations

import json
import os
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
    "academic_evidence_json": "Academic evidence JSON",
    "academic_evidence_markdown": "Academic evidence summary",
}

MEDIA_TYPES = {
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
        "provider_trace": {
            "transcription_provider": getattr(transcript, "asr_provider", None) if transcript else None,
            "transcript_language": getattr(transcript, "language", None) if transcript else None,
            "plan_source": dict_value(plan_payload.get("metadata")).get("source"),
            "created_by": dict_value(plan_payload.get("metadata")).get("created_by"),
            "selected_preset_id": selected_preset.get("id"),
        },
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
        "",
        "## Editing Outcome",
        "",
        f"- Estimated edited duration: {format_seconds(metrics.get('estimated_duration_seconds'))}",
        f"- Actual output duration: {format_seconds(metrics.get('actual_output_duration_seconds'))}",
        f"- Time saved: {format_seconds(metrics.get('time_saved_seconds'))}",
        f"- Reduction: {metrics.get('reduction_percent', 0)}%",
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
