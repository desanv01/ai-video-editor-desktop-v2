"""Compatibility helpers for the structured edit-plan JSON payload."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Iterable

from services.layout_model import default_layout_cues as default_phase7_layout_cues
from services.layout_model import normalize_layout_cues
from services.layout_planner import layout_planning_summary, plan_layout_cues
from services.editorial_plan import (
    layout_cues_from_editorial_blocks,
    normalize_editorial_blocks,
    slide_cues_from_editorial_blocks,
)


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
ANNOTATION_TYPES = {"label", "callout", "note", "warning"}
ANNOTATION_POSITIONS = {
    "top_left",
    "top_center",
    "top_right",
    "middle_left",
    "middle_center",
    "middle_right",
    "bottom_left",
    "bottom_center",
    "bottom_right",
}
EDUCATIONAL_OVERLAY_TYPES = {
    "intro_card",
    "section_title_card",
    "chapter_label",
    "step_label",
}
END_CARD_TYPES = {
    "lecture_summary",
    "next_topic",
    "course_link",
    "custom_message",
}
EDUCATIONAL_OVERLAY_POSITIONS = {
    "center",
    "top_left",
    "top_center",
    "top_right",
    "bottom_left",
    "bottom_center",
    "bottom_right",
}
ANIMATION_PRESETS = {
    "none",
    "fade",
    "pop",
    "zoom",
    "slide_up",
    "slide_down",
    "slide_left",
    "slide_right",
}
ANIMATION_DIRECTIONS = {"none", "up", "down", "left", "right"}
ANIMATION_EASINGS = {"linear", "ease_in", "ease_out", "ease_in_out"}


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
    payload.setdefault("clean_cuts", [])
    payload.setdefault("sections", [])
    payload.setdefault("chapters", [])
    raw_editorial_blocks = payload.get("editorial_blocks", [])
    has_authoritative_editorial_blocks = isinstance(raw_editorial_blocks, list) and bool(raw_editorial_blocks)
    payload["editorial_blocks"] = (
        normalize_editorial_blocks(
            raw_editorial_blocks,
            duration_seconds=_payload_duration_seconds(payload),
        )
        if has_authoritative_editorial_blocks
        else []
    )
    slide_cues = payload.get("slide_cues")
    if not slide_cues:
        render_plan = _dict_value(payload.get("render_plan"))
        nested_slide_cues = render_plan.get("slide_cues")
        if isinstance(nested_slide_cues, list):
            payload["slide_cues"] = list(nested_slide_cues)
    payload.setdefault("slide_cues", [])
    payload.setdefault("visual_analysis", {})
    payload["layout_cues"] = normalize_layout_cues(
        payload.get("layout_cues", []),
        duration_seconds=_payload_duration_seconds(payload),
    )
    if not payload["editorial_blocks"]:
        visual_analysis = _dict_value(payload.get("visual_analysis"))
        legacy_blocks = visual_analysis.get("editorial_blocks")
        if not isinstance(legacy_blocks, list) or not legacy_blocks:
            legacy_blocks = payload.get("slide_cues", [])
        migrated_blocks = (
            normalize_editorial_blocks(
                legacy_blocks,
                duration_seconds=_payload_duration_seconds(payload),
            )
            if isinstance(legacy_blocks, list) and legacy_blocks
            else []
        )
        for block in migrated_blocks:
            if block.get("slide_index") is not None:
                cue = _layout_cue_at(payload["layout_cues"], float(block.get("start_time", 0.0) or 0.0))
                if cue:
                    block["layout"] = cue.get("layout", block["layout"])
        payload["editorial_blocks"] = migrated_blocks
        has_authoritative_editorial_blocks = bool(migrated_blocks)
    if has_authoritative_editorial_blocks and payload["editorial_blocks"]:
        payload["slide_cues"] = slide_cues_from_editorial_blocks(payload["editorial_blocks"])
        payload["layout_cues"] = layout_cues_from_editorial_blocks(
            payload["editorial_blocks"],
            base_cues=payload["layout_cues"],
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
    payload["segments"] = segment_list  # layout_mode from Agent 5 flows through per-segment data automatically
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


def get_layout_cues(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return normalized studio composition cues from the plan payload."""
    normalized = normalize_plan_payload(payload or {})
    return normalize_layout_cues(
        normalized.get("layout_cues", []),
        duration_seconds=_payload_duration_seconds(normalized),
    )


def update_layout_cues(
    payload: dict[str, Any],
    layout_cues: Iterable[dict[str, Any]],
    *,
    source: str = "teacher_layout_override",
) -> dict[str, Any]:
    """Replace the editable layout cue set while preserving the v2 edit-plan envelope."""
    normalized = normalize_plan_payload(payload)
    cues = normalize_layout_cues(
        list(layout_cues or []),
        duration_seconds=_payload_duration_seconds(normalized),
    )
    normalized["layout_cues"] = cues
    normalized["metadata"] = {
        **_dict_value(normalized.get("metadata")),
        "layout_planning": {
            **layout_planning_summary(cues),
            "last_updated_by": source,
            "updated_at": _utc_now(),
        },
    }
    normalized["export_metadata"] = {
        **_dict_value(normalized.get("export_metadata")),
        "layout_cues": {
            "count": len(cues),
            "picture_in_picture_count": sum(1 for cue in cues if cue.get("layout") == "picture_in_picture"),
            "side_by_side_count": sum(1 for cue in cues if cue.get("layout") == "side_by_side"),
            "full_screen_source_count": sum(1 for cue in cues if cue.get("layout") == "full_screen_source"),
            "full_camera_source_count": sum(1 for cue in cues if cue.get("layout") == "full_camera_source"),
            "manual_override": source == "teacher_layout_override",
        },
        "updated_at": _utc_now(),
    }
    return normalized


def update_slide_cues(
    payload: dict[str, Any],
    slide_cues: Iterable[dict[str, Any]],
    *,
    source: str = "teacher_slide_override",
) -> dict[str, Any]:
    """Replace timed slide choices while leaving layout and render settings intact."""
    normalized = normalize_plan_payload(payload)
    duration = _payload_duration_seconds(normalized)
    cues: list[dict[str, Any]] = []
    for index, raw in enumerate(slide_cues or []):
        if not isinstance(raw, dict):
            continue
        start = max(0.0, float(raw.get("start_time", 0.0) or 0.0))
        end = min(duration, float(raw.get("end_time", start) or start)) if duration else float(raw.get("end_time", start) or start)
        if end - start < 0.05:
            continue
        slide_index = raw.get("slide_index")
        try:
            slide_index = int(slide_index) if slide_index is not None else None
        except (TypeError, ValueError):
            slide_index = None
        cues.append({
            **raw,
            "id": str(raw.get("id") or f"teacher-slide-cue-{index + 1:04d}"),
            "start_time": round(start, 3),
            "end_time": round(end, 3),
            "slide_index": slide_index,
            "confidence": 1.0,
            "cue_type": str(raw.get("cue_type") or ("lecturer_only" if slide_index is None else "anchor")),
            "source": str(raw.get("source") or source),
            "strategy": str(raw.get("strategy") or ("teacher_slide_override" if str(raw.get("source") or source).startswith("teacher") else "semantic_slide_plan")),
            "reason": str(raw.get("reason") or "Teacher slide selection"),
        })
    cues.sort(key=lambda cue: cue["start_time"])
    normalized["slide_cues"] = cues
    metadata = _dict_value(normalized.get("metadata"))
    metadata["slide_planning"] = {
        "cue_count": len(cues),
        "last_updated_by": source,
        "updated_at": _utc_now(),
    }
    normalized["metadata"] = metadata
    return normalized


def update_editorial_blocks(
    payload: dict[str, Any],
    editorial_blocks: Iterable[dict[str, Any]],
    *,
    source: str = "teacher_editorial_override",
) -> dict[str, Any]:
    """Replace the authoritative semantic blocks and refresh compatibility cues."""
    normalized = normalize_plan_payload(payload)
    duration = _payload_duration_seconds(normalized)
    blocks = normalize_editorial_blocks(list(editorial_blocks or []), duration_seconds=duration)
    if source.startswith("teacher"):
        blocks = [
            {
                **block,
                "source": str(block.get("source") or source),
                "teacher_modified": bool(block.get("teacher_modified", False) or str(block.get("source") or "").startswith("teacher")),
            }
            for block in blocks
        ]
    normalized["editorial_blocks"] = blocks
    normalized["slide_cues"] = slide_cues_from_editorial_blocks(blocks)
    normalized["layout_cues"] = layout_cues_from_editorial_blocks(
        blocks,
        base_cues=normalized.get("layout_cues", []),
        duration_seconds=duration,
    )
    metadata = _dict_value(normalized.get("metadata"))
    metadata["editorial_planning"] = {
        "block_count": len(blocks),
        "lecturer_only_count": sum(1 for block in blocks if block.get("slide_index") is None),
        "slide_related_count": sum(1 for block in blocks if block.get("slide_index") is not None),
        "last_updated_by": source,
        "updated_at": _utc_now(),
    }
    normalized["metadata"] = metadata
    return normalized


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
        elif action.get("kind") == "annotation":
            annotation = normalize_annotation_action(action)
            if annotation:
                normalized.append(annotation)
        elif action.get("kind") == "educational_overlay":
            overlay = normalize_educational_overlay_action(action)
            if overlay:
                normalized.append(overlay)
        elif action.get("kind") == "end_card":
            end_card = normalize_end_card_action(action)
            if end_card:
                normalized.append(end_card)
        else:
            normalized.append(dict(action))
    if not caption_seen:
        normalized.append(default_caption_policy())
    return normalized


def default_end_card_style() -> dict[str, Any]:
    """Return readable defaults for appended lecture end cards."""
    return {
        "font_size": 42,
        "body_font_size": 24,
        "text_color": "#FFFFFF",
        "body_color": "#CBD5E1",
        "background_color": "#111827",
        "accent_color": "#38BDF8",
        "opacity": 1.0,
    }


def normalize_end_card_action(action: Any) -> dict[str, Any] | None:
    """Normalize one appended lecture end card or CTA action."""
    if not isinstance(action, dict):
        return None

    card_type = _choice(action.get("card_type"), END_CARD_TYPES, "lecture_summary")
    enabled = bool(action.get("enabled", True))
    title = str(action.get("title") or _default_end_card_title(card_type)).strip()[:140]
    message = str(action.get("message") or _default_end_card_message(card_type)).strip()[:420]
    summary_points = _normalize_string_list(action.get("summary_points"), max_items=5, max_chars=120)
    next_topic = str(action.get("next_topic") or "").strip()[:160]
    course_url = str(action.get("course_url") or "").strip()[:240]
    button_text = str(action.get("button_text") or _default_end_card_button_text(card_type)).strip()[:80]

    if not title and not message and not summary_points and not next_topic and not course_url:
        return None

    duration_seconds = _bounded_float(
        action.get("duration_seconds"),
        default=6.0,
        minimum=2.0,
        maximum=15.0,
    )

    normalized = {
        "id": str(action.get("id") or f"end-card-{card_type}"),
        "kind": "end_card",
        "schema_version": EDIT_PLAN_SCHEMA_VERSION,
        "status": str(action.get("status") or ("active" if enabled else "planned")),
        "enabled": enabled,
        "card_type": card_type,
        "title": title,
        "message": message,
        "summary_points": summary_points,
        "next_topic": next_topic,
        "course_url": course_url,
        "button_text": button_text,
        "duration_seconds": duration_seconds,
        "style": _normalize_end_card_style(action.get("style")),
        "animation": _normalize_animation_settings(
            action.get("animation"),
            default_preset="fade",
            default_direction="up",
            default_duration=0.45,
        ),
        "source": str(action.get("source") or "teacher_polish")[:80],
        "reason": str(action.get("reason") or "Teacher-added end card CTA.")[:500],
    }
    return normalized


def get_end_cards(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return normalized end-card CTA actions from the plan payload."""
    normalized = normalize_plan_payload(payload or {})
    end_cards = []
    for action in normalized.get("polish_actions", []):
        if isinstance(action, dict) and action.get("kind") == "end_card":
            end_card = normalize_end_card_action(action)
            if end_card:
                end_cards.append(end_card)
    return sorted(end_cards, key=lambda item: item["id"])


def update_end_cards(payload: dict[str, Any], end_cards: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Replace the editable end-card CTA action set in the v2 polish list."""
    normalized = normalize_plan_payload(payload)
    next_cards = [
        end_card for end_card in (
            normalize_end_card_action(item) for item in list(end_cards or [])
        )
        if end_card is not None
    ]
    actions = [
        action for action in normalized.get("polish_actions", [])
        if not (isinstance(action, dict) and action.get("kind") == "end_card")
    ]
    normalized["polish_actions"] = actions + next_cards
    enabled_cards = [item for item in next_cards if item.get("enabled")]
    normalized["export_metadata"] = {
        **_dict_value(normalized.get("export_metadata")),
        "end_cards": {
            "count": len(next_cards),
            "enabled_count": len(enabled_cards),
            "lecture_summary_count": sum(1 for item in next_cards if item.get("card_type") == "lecture_summary"),
            "next_topic_count": sum(1 for item in next_cards if item.get("card_type") == "next_topic"),
            "course_link_count": sum(1 for item in next_cards if item.get("card_type") == "course_link"),
            "custom_message_count": sum(1 for item in next_cards if item.get("card_type") == "custom_message"),
            "appended_to_output": len(enabled_cards) > 0,
        },
        "updated_at": _utc_now(),
    }
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


def default_annotation_style() -> dict[str, Any]:
    """Return readable defaults for text annotations and callouts."""
    return {
        "font_size": 28,
        "text_color": "#FFFFFF",
        "background_color": "#111827",
        "border_color": "#38BDF8",
        "opacity": 0.88,
    }


def normalize_annotation_action(action: Any) -> dict[str, Any] | None:
    """Normalize one timed annotation/callout polish action."""
    if not isinstance(action, dict):
        return None
    text = str(action.get("text") or "").strip()[:220]
    if not text:
        return None

    start = _bounded_float(action.get("start_time"), default=0.0, minimum=0.0, maximum=86400.0)
    end = _bounded_float(action.get("end_time"), default=start + 4.0, minimum=0.0, maximum=86400.0)
    if end <= start:
        end = min(86400.0, start + 4.0)

    annotation_type = _choice(action.get("annotation_type"), ANNOTATION_TYPES, "callout")
    position = _choice(action.get("position"), ANNOTATION_POSITIONS, "top_right")
    x_percent, y_percent = _position_to_percent(position)
    x_percent = _bounded_float(action.get("x_percent"), default=x_percent, minimum=2.0, maximum=98.0)
    y_percent = _bounded_float(action.get("y_percent"), default=y_percent, minimum=2.0, maximum=98.0)

    normalized = {
        "id": str(action.get("id") or f"annotation-{int(start * 1000)}"),
        "kind": "annotation",
        "schema_version": EDIT_PLAN_SCHEMA_VERSION,
        "status": str(action.get("status") or "active"),
        "annotation_type": annotation_type,
        "text": text,
        "start_time": start,
        "end_time": end,
        "position": position,
        "x_percent": x_percent,
        "y_percent": y_percent,
        "style": _normalize_annotation_style(action.get("style")),
        "pointer": _normalize_annotation_pointer(action.get("pointer"), annotation_type),
        "animation": _normalize_animation_settings(
            action.get("animation"),
            default_preset="pop" if annotation_type == "callout" else "fade",
            default_direction="left" if annotation_type == "callout" else "none",
            default_duration=0.35,
        ),
        "reason": str(action.get("reason") or "Teacher-added polish annotation.")[:500],
    }
    normalized["duration"] = round(normalized["end_time"] - normalized["start_time"], 3)
    return normalized


def get_annotations(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return normalized active timeline annotations from the plan payload."""
    normalized = normalize_plan_payload(payload or {})
    annotations = []
    for action in normalized.get("polish_actions", []):
        if isinstance(action, dict) and action.get("kind") == "annotation":
            annotation = normalize_annotation_action(action)
            if annotation:
                annotations.append(annotation)
    return sorted(annotations, key=lambda item: (item["start_time"], item["end_time"], item["id"]))


def update_annotations(payload: dict[str, Any], annotations: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Replace the editable annotation/callout action set in the v2 polish list."""
    normalized = normalize_plan_payload(payload)
    next_annotations = [
        annotation for annotation in (
            normalize_annotation_action(item) for item in list(annotations or [])
        )
        if annotation is not None
    ]
    actions = [
        action for action in normalized.get("polish_actions", [])
        if not (isinstance(action, dict) and action.get("kind") == "annotation")
    ]
    normalized["polish_actions"] = actions + next_annotations
    normalized["export_metadata"] = {
        **_dict_value(normalized.get("export_metadata")),
        "annotations": {
            "count": len(next_annotations),
            "callout_count": sum(1 for item in next_annotations if item.get("annotation_type") == "callout"),
            "animated_count": sum(1 for item in next_annotations if item.get("animation", {}).get("preset") != "none"),
            "burned_in": len(next_annotations) > 0,
        },
        "updated_at": _utc_now(),
    }
    return normalized


def default_educational_overlay_style(overlay_type: str = "chapter_label") -> dict[str, Any]:
    """Return readable defaults for educational step labels and title cards."""
    if overlay_type in {"intro_card", "section_title_card"}:
        return {
            "font_size": 44,
            "subtitle_font_size": 24,
            "text_color": "#FFFFFF",
            "subtitle_color": "#CBD5E1",
            "background_color": "#111827",
            "accent_color": "#38BDF8",
            "opacity": 0.92,
        }
    return {
        "font_size": 28,
        "subtitle_font_size": 18,
        "text_color": "#FFFFFF",
        "subtitle_color": "#CBD5E1",
        "background_color": "#0F172A",
        "accent_color": "#FACC15",
        "opacity": 0.88,
    }


def normalize_educational_overlay_action(action: Any) -> dict[str, Any] | None:
    """Normalize one educational title card, chapter label, or step label."""
    if not isinstance(action, dict):
        return None

    overlay_type = _choice(action.get("overlay_type"), EDUCATIONAL_OVERLAY_TYPES, "chapter_label")
    title = str(action.get("title") or action.get("text") or "").strip()[:160]
    if not title:
        return None
    subtitle = str(action.get("subtitle") or "").strip()[:220]

    start = _bounded_float(action.get("start_time"), default=0.0, minimum=0.0, maximum=86400.0)
    default_duration = 4.5 if overlay_type in {"intro_card", "section_title_card"} else 3.0
    end = _bounded_float(
        action.get("end_time"),
        default=start + default_duration,
        minimum=0.0,
        maximum=86400.0,
    )
    if end <= start:
        end = min(86400.0, start + default_duration)

    default_position = "center" if overlay_type in {"intro_card", "section_title_card"} else "top_left"
    position = _choice(action.get("position"), EDUCATIONAL_OVERLAY_POSITIONS, default_position)
    x_percent, y_percent = _educational_overlay_position_to_percent(position)
    x_percent = _bounded_float(action.get("x_percent"), default=x_percent, minimum=2.0, maximum=98.0)
    y_percent = _bounded_float(action.get("y_percent"), default=y_percent, minimum=2.0, maximum=98.0)

    chapter_index = action.get("chapter_index")
    try:
        chapter_index = int(chapter_index) if chapter_index is not None else None
    except (TypeError, ValueError):
        chapter_index = None
    step_number = action.get("step_number")
    try:
        step_number = int(step_number) if step_number is not None else None
    except (TypeError, ValueError):
        step_number = None

    normalized = {
        "id": str(action.get("id") or f"{overlay_type}-{int(start * 1000)}"),
        "kind": "educational_overlay",
        "schema_version": EDIT_PLAN_SCHEMA_VERSION,
        "status": str(action.get("status") or "active"),
        "overlay_type": overlay_type,
        "title": title,
        "subtitle": subtitle,
        "start_time": start,
        "end_time": end,
        "position": position,
        "x_percent": x_percent,
        "y_percent": y_percent,
        "style": _normalize_educational_overlay_style(action.get("style"), overlay_type),
        "animation": _normalize_animation_settings(
            action.get("animation"),
            default_preset="fade" if overlay_type in {"intro_card", "section_title_card"} else "slide_down",
            default_direction="up" if overlay_type in {"intro_card", "section_title_card"} else "down",
            default_duration=0.45 if overlay_type in {"intro_card", "section_title_card"} else 0.3,
        ),
        "chapter_index": chapter_index,
        "step_number": step_number,
        "source": str(action.get("source") or "teacher_polish")[:80],
        "reason": str(action.get("reason") or "Teacher-added educational polish overlay.")[:500],
    }
    normalized["duration"] = round(normalized["end_time"] - normalized["start_time"], 3)
    return normalized


def get_educational_overlays(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return normalized educational overlays from the plan payload."""
    normalized = normalize_plan_payload(payload or {})
    overlays = []
    for action in normalized.get("polish_actions", []):
        if isinstance(action, dict) and action.get("kind") == "educational_overlay":
            overlay = normalize_educational_overlay_action(action)
            if overlay:
                overlays.append(overlay)
    return sorted(overlays, key=lambda item: (item["start_time"], item["end_time"], item["id"]))


def update_educational_overlays(payload: dict[str, Any], overlays: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Replace the editable educational overlay action set in the v2 polish list."""
    normalized = normalize_plan_payload(payload)
    next_overlays = [
        overlay for overlay in (
            normalize_educational_overlay_action(item) for item in list(overlays or [])
        )
        if overlay is not None
    ]
    actions = [
        action for action in normalized.get("polish_actions", [])
        if not (isinstance(action, dict) and action.get("kind") == "educational_overlay")
    ]
    normalized["polish_actions"] = actions + next_overlays
    normalized["export_metadata"] = {
        **_dict_value(normalized.get("export_metadata")),
        "educational_overlays": {
            "count": len(next_overlays),
            "intro_card_count": sum(1 for item in next_overlays if item.get("overlay_type") == "intro_card"),
            "section_title_card_count": sum(1 for item in next_overlays if item.get("overlay_type") == "section_title_card"),
            "chapter_label_count": sum(1 for item in next_overlays if item.get("overlay_type") == "chapter_label"),
            "step_label_count": sum(1 for item in next_overlays if item.get("overlay_type") == "step_label"),
            "animated_count": sum(1 for item in next_overlays if item.get("animation", {}).get("preset") != "none"),
            "burned_in": len(next_overlays) > 0,
        },
        "updated_at": _utc_now(),
    }
    return normalized


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


def _layout_cue_at(cues: list[dict[str, Any]], time_seconds: float) -> dict[str, Any] | None:
    for cue in cues:
        start = float(cue.get("start_time", 0.0) or 0.0)
        end_raw = cue.get("end_time")
        if time_seconds >= start and (end_raw is None or time_seconds < float(end_raw)):
            return cue
    return cues[0] if cues else None


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


def _normalize_annotation_style(value: Any) -> dict[str, Any]:
    defaults = default_annotation_style()
    source = dict(value) if isinstance(value, dict) else {}
    return {
        "font_size": int(_bounded_float(source.get("font_size"), default=defaults["font_size"], minimum=16, maximum=64)),
        "text_color": _hex_color(source.get("text_color"), defaults["text_color"]),
        "background_color": _hex_color(source.get("background_color"), defaults["background_color"]),
        "border_color": _hex_color(source.get("border_color"), defaults["border_color"]),
        "opacity": _bounded_float(source.get("opacity"), default=defaults["opacity"], minimum=0.2, maximum=1.0),
    }


def _normalize_annotation_pointer(value: Any, annotation_type: str) -> dict[str, Any]:
    source = dict(value) if isinstance(value, dict) else {}
    return {
        "enabled": bool(source.get("enabled", annotation_type == "callout")),
        "direction": _choice(source.get("direction"), {"up", "down", "left", "right", "none"}, "left"),
    }


def _normalize_animation_settings(
    value: Any,
    *,
    default_preset: str,
    default_direction: str,
    default_duration: float,
) -> dict[str, Any]:
    source = dict(value) if isinstance(value, dict) else {}
    preset = _choice(source.get("preset"), ANIMATION_PRESETS, default_preset)
    if preset == "none":
        default_direction = "none"
        default_duration = 0.0
    return {
        "preset": preset,
        "direction": _choice(source.get("direction"), ANIMATION_DIRECTIONS, default_direction),
        "duration_seconds": _bounded_float(
            source.get("duration_seconds"),
            default=default_duration,
            minimum=0.0,
            maximum=2.0,
        ),
        "easing": _choice(source.get("easing"), ANIMATION_EASINGS, "ease_out"),
    }


def _normalize_educational_overlay_style(value: Any, overlay_type: str) -> dict[str, Any]:
    defaults = default_educational_overlay_style(overlay_type)
    source = dict(value) if isinstance(value, dict) else {}
    return {
        "font_size": int(_bounded_float(source.get("font_size"), default=defaults["font_size"], minimum=18, maximum=72)),
        "subtitle_font_size": int(_bounded_float(
            source.get("subtitle_font_size"),
            default=defaults["subtitle_font_size"],
            minimum=12,
            maximum=44,
        )),
        "text_color": _hex_color(source.get("text_color"), defaults["text_color"]),
        "subtitle_color": _hex_color(source.get("subtitle_color"), defaults["subtitle_color"]),
        "background_color": _hex_color(source.get("background_color"), defaults["background_color"]),
        "accent_color": _hex_color(source.get("accent_color"), defaults["accent_color"]),
        "opacity": _bounded_float(source.get("opacity"), default=defaults["opacity"], minimum=0.2, maximum=1.0),
    }


def _normalize_end_card_style(value: Any) -> dict[str, Any]:
    defaults = default_end_card_style()
    source = dict(value) if isinstance(value, dict) else {}
    return {
        "font_size": int(_bounded_float(source.get("font_size"), default=defaults["font_size"], minimum=24, maximum=72)),
        "body_font_size": int(_bounded_float(source.get("body_font_size"), default=defaults["body_font_size"], minimum=16, maximum=44)),
        "text_color": _hex_color(source.get("text_color"), defaults["text_color"]),
        "body_color": _hex_color(source.get("body_color"), defaults["body_color"]),
        "background_color": _hex_color(source.get("background_color"), defaults["background_color"]),
        "accent_color": _hex_color(source.get("accent_color"), defaults["accent_color"]),
        "opacity": _bounded_float(source.get("opacity"), default=defaults["opacity"], minimum=0.2, maximum=1.0),
    }


def _normalize_string_list(value: Any, *, max_items: int, max_chars: int) -> list[str]:
    if isinstance(value, str):
        raw_items = [line.strip() for line in value.splitlines()]
    elif isinstance(value, list):
        raw_items = [str(item).strip() for item in value]
    else:
        raw_items = []
    return [item[:max_chars] for item in raw_items if item][:max_items]


def _default_end_card_title(card_type: str) -> str:
    return {
        "lecture_summary": "Lecture Summary",
        "next_topic": "Next Topic",
        "course_link": "Continue Learning",
        "custom_message": "Thanks for Watching",
    }.get(card_type, "Lecture Summary")


def _default_end_card_message(card_type: str) -> str:
    return {
        "lecture_summary": "Review the key ideas before moving on.",
        "next_topic": "In the next lesson, we build on this concept.",
        "course_link": "Open the course page for notes, exercises, and resources.",
        "custom_message": "See you in the next lesson.",
    }.get(card_type, "Review the key ideas before moving on.")


def _default_end_card_button_text(card_type: str) -> str:
    return {
        "lecture_summary": "Review notes",
        "next_topic": "Watch next",
        "course_link": "Open course",
        "custom_message": "Continue",
    }.get(card_type, "Continue")


def _position_to_percent(position: str) -> tuple[float, float]:
    return {
        "top_left": (10.0, 12.0),
        "top_center": (50.0, 12.0),
        "top_right": (78.0, 12.0),
        "middle_left": (10.0, 50.0),
        "middle_center": (50.0, 50.0),
        "middle_right": (78.0, 50.0),
        "bottom_left": (10.0, 82.0),
        "bottom_center": (50.0, 82.0),
        "bottom_right": (78.0, 82.0),
    }.get(position, (78.0, 12.0))


def _educational_overlay_position_to_percent(position: str) -> tuple[float, float]:
    return {
        "center": (50.0, 50.0),
        "top_left": (9.0, 10.0),
        "top_center": (50.0, 10.0),
        "top_right": (91.0, 10.0),
        "bottom_left": (9.0, 87.0),
        "bottom_center": (50.0, 87.0),
        "bottom_right": (91.0, 87.0),
    }.get(position, (50.0, 50.0))


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
