"""Compatibility helpers for the structured edit-plan JSON payload."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Iterable

from services.layout_model import default_layout_cues as default_phase7_layout_cues
from services.layout_model import normalize_layout_cues
from services.layout_planner import layout_planning_summary, plan_layout_cues


EDIT_PLAN_SCHEMA_VERSION = "phase6.edit-plan.v2"

CAPTION_APPEARANCE_MODES = {
    "always",
    "highlight_segments",
    "section_starts",
    "manual_ranges",
    "off",
}
CAPTION_PLACEMENTS = {
    "bottom_center",
    "bottom_left",
    "bottom_right",
    "top_center",
    "top_left",
    "top_right",
}
CAPTION_EXPORT_BEHAVIORS = {
    "sidecar",
    "burn_in",
    "sidecar_and_burn_in",
    "none",
}


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
    payload["layout_cues"] = normalize_layout_cues(
        payload.get("layout_cues", []),
        duration_seconds=_payload_duration_seconds(payload),
    )
    payload["polish_actions"] = normalize_polish_actions(payload.get("polish_actions", []))
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
    source_assets: Iterable[Any] | None = None,
    layout_segments: Iterable[Any] | None = None,
) -> dict[str, Any]:
    """Create a fresh v2 edit-plan payload from generated segment decisions."""
    segment_list = list(segments)
    source_asset_list = list(source_assets) if source_assets is not None else None
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
    payload["segments"] = segment_list
    if source_asset_list is None:
        payload["layout_cues"] = default_layout_cues(original_duration)
    else:
        payload["layout_cues"] = plan_layout_cues(
            source_asset_list,
            duration_seconds=original_duration,
            segments=layout_segments if layout_segments is not None else segment_list,
        )
        payload["metadata"]["layout_planning"] = layout_planning_summary(payload["layout_cues"])
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
    """Return conservative Phase 7 layout placeholders."""
    return default_phase7_layout_cues(duration_seconds)


def default_polish_actions() -> list[dict[str, Any]]:
    """Return non-destructive polish defaults for later guided workflow steps."""
    return [
        default_caption_policy()
    ]


def default_caption_policy() -> dict[str, Any]:
    """Return the editable caption policy used by the Polish step and renderer."""
    return {
        "id": "polish-default-captions",
        "kind": "caption_policy",
        "schema_version": EDIT_PLAN_SCHEMA_VERSION,
        "status": "planned",
        "enabled": True,
        "appearance": "always",
        "placement": "bottom_center",
        "export_behavior": "sidecar",
        "style": {
            "font_size": 24,
            "font_family": "Arial",
            "primary_color": "#FFFFFF",
            "outline_color": "#000000",
            "outline_width": 2,
            "background": "transparent",
            "max_chars_per_line": 80,
            "max_duration_per_cue": 5.0,
        },
        "ranges": [],
        "section_intro_seconds": 6.0,
        "reason": "Keep captions available as SRT/VTT without forcing burn-in.",
    }


def normalize_polish_actions(actions: Any) -> list[dict[str, Any]]:
    """Normalize known polish action records while preserving future action types."""
    action_list = list(actions or []) if isinstance(actions, list) else []
    normalized: list[dict[str, Any]] = []
    caption_seen = False
    for action in action_list:
        if not isinstance(action, dict):
            continue
        if action.get("kind") == "caption_policy":
            normalized.append(normalize_caption_policy(action))
            caption_seen = True
        else:
            normalized.append(dict(action))
    if not caption_seen:
        normalized.append(default_caption_policy())
    return normalized


def normalize_caption_policy(policy: Any) -> dict[str, Any]:
    """Normalize legacy caption placeholders and user-edited caption settings."""
    defaults = default_caption_policy()
    source = dict(policy) if isinstance(policy, dict) else {}
    legacy_mode = str(source.get("caption_mode") or "").lower()
    if legacy_mode == "export_sidecar":
        source.setdefault("export_behavior", "sidecar")
    elif legacy_mode == "burn_in":
        source.setdefault("export_behavior", "burn_in")

    normalized = {
        **defaults,
        **source,
        "kind": "caption_policy",
        "schema_version": EDIT_PLAN_SCHEMA_VERSION,
    }
    normalized["enabled"] = bool(source.get("enabled", defaults["enabled"]))
    normalized["appearance"] = _choice(
        source.get("appearance"),
        CAPTION_APPEARANCE_MODES,
        defaults["appearance"],
    )
    if not normalized["enabled"]:
        normalized["appearance"] = "off"
    normalized["placement"] = _choice(
        source.get("placement"),
        CAPTION_PLACEMENTS,
        defaults["placement"],
    )
    normalized["export_behavior"] = _choice(
        source.get("export_behavior"),
        CAPTION_EXPORT_BEHAVIORS,
        defaults["export_behavior"],
    )
    normalized["style"] = _normalize_caption_style(source.get("style"), defaults["style"])
    normalized["ranges"] = _normalize_caption_ranges(source.get("ranges"))
    normalized["section_intro_seconds"] = _bounded_float(
        source.get("section_intro_seconds"),
        default=defaults["section_intro_seconds"],
        minimum=1.0,
        maximum=30.0,
    )
    normalized["status"] = str(source.get("status") or defaults["status"])
    normalized["reason"] = str(source.get("reason") or defaults["reason"])
    return normalized


def update_caption_policy(payload: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    """Upsert the editable caption policy inside the v2 polish action list."""
    normalized = normalize_plan_payload(payload)
    existing_policy = get_caption_policy(normalized)
    patch = dict(policy or {})
    if isinstance(patch.get("style"), dict):
        patch["style"] = {**_dict_value(existing_policy.get("style")), **dict(patch["style"])}
    next_policy = normalize_caption_policy({**existing_policy, **patch})
    actions = [
        action for action in normalized.get("polish_actions", [])
        if not (isinstance(action, dict) and action.get("kind") == "caption_policy")
    ]
    actions.insert(0, {**next_policy, "status": "active"})
    normalized["polish_actions"] = actions
    normalized["export_metadata"] = {
        **_dict_value(normalized.get("export_metadata")),
        "caption_policy": {
            "enabled": next_policy["enabled"],
            "appearance": next_policy["appearance"],
            "placement": next_policy["placement"],
            "export_behavior": next_policy["export_behavior"],
        },
        "updated_at": _utc_now(),
    }
    return normalized


def get_caption_policy(payload: dict[str, Any] | None) -> dict[str, Any]:
    """Return the first normalized caption policy from a plan payload."""
    normalized = normalize_plan_payload(payload or {})
    for action in normalized.get("polish_actions", []):
        if isinstance(action, dict) and action.get("kind") == "caption_policy":
            return normalize_caption_policy(action)
    return default_caption_policy()


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


def _payload_duration_seconds(payload: dict[str, Any]) -> float | None:
    summary = _dict_value(payload.get("summary"))
    for value in (
        summary.get("original_duration_seconds"),
        summary.get("estimated_duration_seconds"),
        _dict_value(payload.get("export_metadata")).get("source_duration_seconds"),
    ):
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _dict_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _choice(value: Any, choices: set[str], default: str) -> str:
    candidate = str(value or "").lower()
    return candidate if candidate in choices else default


def _normalize_caption_style(value: Any, defaults: dict[str, Any]) -> dict[str, Any]:
    source = dict(value) if isinstance(value, dict) else {}
    return {
        "font_size": int(_bounded_float(source.get("font_size"), default=defaults["font_size"], minimum=14, maximum=72)),
        "font_family": str(source.get("font_family") or defaults["font_family"])[:80],
        "primary_color": _hex_color(source.get("primary_color"), defaults["primary_color"]),
        "outline_color": _hex_color(source.get("outline_color"), defaults["outline_color"]),
        "outline_width": int(_bounded_float(source.get("outline_width"), default=defaults["outline_width"], minimum=0, maximum=8)),
        "background": _choice(source.get("background"), {"transparent", "box"}, defaults["background"]),
        "max_chars_per_line": int(_bounded_float(
            source.get("max_chars_per_line"),
            default=defaults["max_chars_per_line"],
            minimum=32,
            maximum=120,
        )),
        "max_duration_per_cue": _bounded_float(
            source.get("max_duration_per_cue"),
            default=defaults["max_duration_per_cue"],
            minimum=1.5,
            maximum=10.0,
        ),
    }


def _normalize_caption_ranges(value: Any) -> list[dict[str, Any]]:
    ranges = []
    if not isinstance(value, list):
        return ranges
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            continue
        start = _bounded_float(item.get("start_time"), default=0.0, minimum=0.0, maximum=86400.0)
        end = _bounded_float(item.get("end_time"), default=start, minimum=0.0, maximum=86400.0)
        if end <= start:
            continue
        ranges.append({
            "id": str(item.get("id") or f"caption-range-{index + 1}"),
            "start_time": start,
            "end_time": end,
            "label": str(item.get("label") or "Caption range")[:120],
        })
    return ranges


def _hex_color(value: Any, default: str) -> str:
    text = str(value or default).strip()
    if len(text) == 7 and text.startswith("#"):
        try:
            int(text[1:], 16)
            return text.upper()
        except ValueError:
            return default
    return default


def _bounded_float(value: Any, *, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float(default)
    return min(maximum, max(minimum, number))


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()
