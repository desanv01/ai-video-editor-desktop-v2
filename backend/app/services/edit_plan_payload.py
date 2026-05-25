"""Compatibility helpers for the structured edit-plan JSON payload."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Iterable


EDIT_PLAN_SCHEMA_VERSION = "phase6.edit-plan.v2"


def normalize_plan_payload(plan_json: Any) -> dict[str, Any]:
    """Return a v2 edit-plan envelope while preserving legacy segment arrays."""
    if isinstance(plan_json, dict):
        payload = dict(plan_json)
        legacy_version = payload.get("schema_version")
        if "segments" not in payload:
            payload["segments"] = _legacy_segments_from_dict(payload)
        payload.setdefault("metadata", {})
    else:
        legacy_version = "legacy.segment-array.v1" if isinstance(plan_json, list) else None
        payload = {
            "metadata": {},
            "segments": list(plan_json or []) if isinstance(plan_json, list) else [],
        }

    metadata = _dict_value(payload.get("metadata"))
    if legacy_version and legacy_version != EDIT_PLAN_SCHEMA_VERSION:
        metadata.setdefault("compatible_from_schema_version", legacy_version)
    metadata.setdefault("created_by", "ai-video-editor")
    payload["metadata"] = metadata

    payload["schema_version"] = EDIT_PLAN_SCHEMA_VERSION
    payload.setdefault("segments", [])
    payload.setdefault("edit_decisions", [])
    payload.setdefault("cleaning_suggestions", [])
    payload.setdefault("sections", [])
    payload.setdefault("chapters", [])
    payload.setdefault("layout_cues", [])
    payload.setdefault("polish_actions", [])
    payload.setdefault("export_metadata", _default_export_metadata())
    payload["export_metadata"] = _dict_value(payload.get("export_metadata"))
    payload["export_metadata"].setdefault("schema_version", EDIT_PLAN_SCHEMA_VERSION)
    payload["export_metadata"].setdefault("artifacts", [])
    payload["export_metadata"].setdefault("target_presets", [])
    payload["export_metadata"].setdefault("updated_at", None)

    return payload


def build_edit_plan_payload(
    *,
    segments: Iterable[dict[str, Any]],
    original_duration: float | None,
    estimated_duration: float | None,
    warnings: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Create a fresh v2 edit-plan payload from generated segment decisions."""
    payload = normalize_plan_payload(None)
    payload["metadata"].update({
        "generated_at": _utc_now(),
        "plan_kind": "lecture_edit_plan",
        "source": "agent5_edit_planner",
    })
    payload["summary"] = {
        "original_duration_seconds": original_duration,
        "estimated_duration_seconds": estimated_duration,
        "warnings": list(warnings or []),
    }
    payload["segments"] = list(segments)
    payload["layout_cues"] = default_layout_cues(original_duration)
    payload["polish_actions"] = default_polish_actions()
    payload["export_metadata"] = {
        **_default_export_metadata(),
        "source_duration_seconds": original_duration,
        "estimated_output_duration_seconds": estimated_duration,
        "target_presets": ["youtube_1080p", "lms_compatible"],
        "updated_at": _utc_now(),
    }
    return payload


def default_layout_cues(duration_seconds: float | None = None) -> list[dict[str, Any]]:
    """Return conservative layout placeholders for Phase 7 to refine."""
    return [
        {
            "id": "layout-default-full-source",
            "kind": "layout_cue",
            "status": "planned",
            "layout": "single_source_fullscreen",
            "source_role": "primary_timeline",
            "start_time": 0.0,
            "end_time": duration_seconds,
            "reason": "Default single-source lecture layout until timed layout planning is available.",
        }
    ]


def default_polish_actions() -> list[dict[str, Any]]:
    """Return non-destructive polish defaults for later guided workflow steps."""
    return [
        {
            "id": "polish-default-captions",
            "kind": "caption_policy",
            "status": "planned",
            "caption_mode": "export_sidecar",
            "reason": "Keep captions available as SRT/VTT without forcing burn-in.",
        }
    ]


def update_cleaning_payload(
    payload: dict[str, Any],
    *,
    profile: str,
    summary: dict[str, Any],
    suggestions: Iterable[dict[str, Any]],
    applied: bool,
) -> dict[str, Any]:
    """Store clean-step suggestions in the v2 envelope."""
    normalized = normalize_plan_payload(payload)
    status = "applied" if applied else "suggested"
    normalized["cleaning_suggestions"] = [
        {**suggestion, "status": status}
        for suggestion in suggestions
    ]
    normalized["clean_summary"] = {
        "schema_version": EDIT_PLAN_SCHEMA_VERSION,
        "profile": profile,
        "status": status,
        "updated_at": _utc_now(),
        **summary,
    }
    return normalized


def update_sections_payload(payload: dict[str, Any], analysis: dict[str, Any]) -> dict[str, Any]:
    """Store section/chapter analysis in the v2 envelope."""
    normalized = normalize_plan_payload(payload)
    normalized["sections"] = list(analysis.get("sections", []))
    normalized["chapters"] = list(analysis.get("chapters", []))
    normalized["section_summary"] = {
        "schema_version": analysis.get("schema_version"),
        **_dict_value(analysis.get("summary")),
        "youtube_format": analysis.get("youtube_format", ""),
        "updated_at": _utc_now(),
    }
    return normalized


def update_export_metadata(
    payload: dict[str, Any],
    *,
    artifacts: Iterable[dict[str, Any]] | None = None,
    render: dict[str, Any] | None = None,
    target_presets: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Refresh export metadata without disturbing future layout/polish fields."""
    normalized = normalize_plan_payload(payload)
    export_metadata = _dict_value(normalized.get("export_metadata"))
    if artifacts is not None:
        export_metadata["artifacts"] = list(artifacts)
    if render is not None:
        export_metadata["render"] = render
    if target_presets is not None:
        export_metadata["target_presets"] = list(target_presets)
    export_metadata["schema_version"] = EDIT_PLAN_SCHEMA_VERSION
    export_metadata["updated_at"] = _utc_now()
    normalized["export_metadata"] = export_metadata
    return normalized


def _legacy_segments_from_dict(payload: dict[str, Any]) -> list[Any]:
    for key in ("plan", "plan_entries", "decisions"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
    return []


def _default_export_metadata() -> dict[str, Any]:
    return {
        "schema_version": EDIT_PLAN_SCHEMA_VERSION,
        "target_presets": [],
        "artifacts": [],
        "updated_at": None,
    }


def _dict_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
