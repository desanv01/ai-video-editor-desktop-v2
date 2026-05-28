"""Structured layout cue model for Phase 7 edit plans."""

from __future__ import annotations

from enum import Enum
from typing import Any


LAYOUT_SCHEMA_VERSION = "phase7.layout.v1"


class LayoutSourceRole(str, Enum):
    SCREEN = "screen"
    CAMERA = "camera"
    AUDIO = "audio"
    PRIMARY_TIMELINE = "primary_timeline"


class LayoutMode(str, Enum):
    PICTURE_IN_PICTURE = "picture_in_picture"
    SIDE_BY_SIDE = "side_by_side"
    FULL_SCREEN_SOURCE = "full_screen_source"
    FULL_CAMERA_SOURCE = "full_camera_source"


class LayoutAspectRatio(str, Enum):
    LANDSCAPE_16_9 = "16:9"
    STANDARD_4_3 = "4:3"
    SQUARE_1_1 = "1:1"
    VERTICAL_9_16 = "9:16"


class CameraShape(str, Enum):
    RECTANGLE = "rectangle"
    ROUNDED_RECTANGLE = "rounded_rectangle"
    CIRCLE = "circle"


class CameraCorner(str, Enum):
    TOP_LEFT = "top_left"
    TOP_RIGHT = "top_right"
    BOTTOM_LEFT = "bottom_left"
    BOTTOM_RIGHT = "bottom_right"


LAYOUT_ALIASES = {
    "single_source_fullscreen": LayoutMode.FULL_SCREEN_SOURCE.value,
    "fullscreen": LayoutMode.FULL_SCREEN_SOURCE.value,
    "full_screen": LayoutMode.FULL_SCREEN_SOURCE.value,
    "full_camera": LayoutMode.FULL_CAMERA_SOURCE.value,
    "pip": LayoutMode.PICTURE_IN_PICTURE.value,
}
LAYOUT_TRANSITIONS = {
    "cut",
    "crossfade",
    "fade",
    "dip_to_black",
    "wipe_left",
    "wipe_right",
}


def build_layout_cue(
    *,
    cue_id: str,
    layout: LayoutMode | str = LayoutMode.FULL_SCREEN_SOURCE,
    start_time: float = 0.0,
    end_time: float | None = None,
    output_aspect_ratio: LayoutAspectRatio | str = LayoutAspectRatio.LANDSCAPE_16_9,
    camera_shape: CameraShape | str = CameraShape.ROUNDED_RECTANGLE,
    camera_corner: CameraCorner | str = CameraCorner.BOTTOM_RIGHT,
    screen_source_id: str | None = None,
    camera_source_id: str | None = None,
    audio_source_id: str | None = None,
    reason: str = "",
) -> dict[str, Any]:
    """Build a complete layout cue suitable for storage in edit-plan JSON."""
    layout_value = _enum_value(layout, LayoutMode, LayoutMode.FULL_SCREEN_SOURCE.value)
    start = _non_negative_float(start_time, 0.0)
    end = _optional_non_negative_float(end_time)
    duration = round(end - start, 3) if end is not None and end >= start else None

    camera_enabled = layout_value in {
        LayoutMode.PICTURE_IN_PICTURE.value,
        LayoutMode.SIDE_BY_SIDE.value,
        LayoutMode.FULL_CAMERA_SOURCE.value,
    }
    screen_enabled = layout_value != LayoutMode.FULL_CAMERA_SOURCE.value

    return {
        "id": cue_id,
        "kind": "layout_cue",
        "schema_version": LAYOUT_SCHEMA_VERSION,
        "status": "planned",
        "layout": layout_value,
        "start_time": start,
        "end_time": end,
        "timing": {
            "start_time": start,
            "end_time": end,
            "duration_seconds": duration,
            "transition_in": "crossfade",
            "transition_out": "crossfade",
            "transition_duration_seconds": 0.35,
        },
        "sources": {
            "screen": _source_ref(
                LayoutSourceRole.SCREEN,
                screen_source_id,
                enabled=screen_enabled,
                track="screen",
            ),
            "camera": _source_ref(
                LayoutSourceRole.CAMERA,
                camera_source_id,
                enabled=camera_enabled,
                track="camera",
            ),
            "audio": _source_ref(
                LayoutSourceRole.AUDIO,
                audio_source_id,
                enabled=True,
                track="audio",
            ),
        },
        "output": {
            "aspect_ratio": _enum_value(
                output_aspect_ratio,
                LayoutAspectRatio,
                LayoutAspectRatio.LANDSCAPE_16_9.value,
            ),
        },
        "camera": {
            "enabled": camera_enabled,
            "shape": _enum_value(
                camera_shape,
                CameraShape,
                CameraShape.ROUNDED_RECTANGLE.value,
            ),
            "corner": _enum_value(
                camera_corner,
                CameraCorner,
                CameraCorner.BOTTOM_RIGHT.value,
            ),
            "size": "medium",
            "margin_percent": 4,
        },
        "reason": reason,
    }


def default_layout_cues(duration_seconds: float | None = None) -> list[dict[str, Any]]:
    """Return the conservative default cue used before layout planning runs."""
    return [
        build_layout_cue(
            cue_id="layout-default-full-screen-source",
            layout=LayoutMode.FULL_SCREEN_SOURCE,
            end_time=duration_seconds,
            reason=(
                "Default full-screen source layout until timed layout planning "
                "selects screen, camera, side-by-side, or picture-in-picture cues."
            ),
        )
    ]


def normalize_layout_cues(
    raw_cues: Any,
    *,
    duration_seconds: float | None = None,
) -> list[dict[str, Any]]:
    """Normalize stored layout cues while preserving future/unknown fields."""
    if not isinstance(raw_cues, list):
        return []

    normalized = []
    for index, raw in enumerate(raw_cues):
        if not isinstance(raw, dict):
            continue
        normalized.append(_normalize_layout_cue(raw, index, duration_seconds))
    return normalized


def _normalize_layout_cue(
    raw: dict[str, Any],
    index: int,
    duration_seconds: float | None,
) -> dict[str, Any]:
    cue = dict(raw)
    original_layout = cue.get("layout")
    layout_value = _layout_value(original_layout)
    start = _non_negative_float(
        cue.get("start_time", _dict_value(cue.get("timing")).get("start_time")),
        0.0,
    )
    end = _optional_non_negative_float(
        cue.get("end_time", _dict_value(cue.get("timing")).get("end_time", duration_seconds))
    )
    duration = round(end - start, 3) if end is not None and end >= start else None

    cue.setdefault("id", f"layout-cue-{index + 1}")
    cue["kind"] = cue.get("kind") or "layout_cue"
    cue["schema_version"] = LAYOUT_SCHEMA_VERSION
    cue["status"] = cue.get("status") or "planned"
    cue["layout"] = layout_value
    cue["start_time"] = start
    cue["end_time"] = end

    if original_layout and str(original_layout) != layout_value:
        cue.setdefault("compatible_from_layout", str(original_layout))

    timing = _dict_value(cue.get("timing"))
    timing["transition_in"] = _transition_value(timing.get("transition_in"), "crossfade")
    timing["transition_out"] = _transition_value(timing.get("transition_out"), "crossfade")
    timing["transition_duration_seconds"] = _bounded_float(
        timing.get("transition_duration_seconds"),
        default=0.35,
        minimum=0.0,
        maximum=2.0,
    )
    timing["start_time"] = start
    timing["end_time"] = end
    timing["duration_seconds"] = duration
    cue["timing"] = timing

    sources = _dict_value(cue.get("sources"))
    source_role = str(cue.get("source_role") or LayoutSourceRole.SCREEN.value)
    sources["screen"] = _normalize_source_ref(
        sources.get("screen"),
        LayoutSourceRole.SCREEN,
        enabled=layout_value != LayoutMode.FULL_CAMERA_SOURCE.value,
        fallback_track="screen" if source_role != LayoutSourceRole.PRIMARY_TIMELINE.value else "primary_timeline",
    )
    sources["camera"] = _normalize_source_ref(
        sources.get("camera"),
        LayoutSourceRole.CAMERA,
        enabled=layout_value in {
            LayoutMode.PICTURE_IN_PICTURE.value,
            LayoutMode.SIDE_BY_SIDE.value,
            LayoutMode.FULL_CAMERA_SOURCE.value,
        },
        fallback_track="camera",
    )
    sources["audio"] = _normalize_source_ref(
        sources.get("audio"),
        LayoutSourceRole.AUDIO,
        enabled=True,
        fallback_track="audio",
    )
    cue["sources"] = sources

    output = _dict_value(cue.get("output"))
    output["aspect_ratio"] = _enum_value(
        output.get("aspect_ratio", cue.get("aspect_ratio")),
        LayoutAspectRatio,
        LayoutAspectRatio.LANDSCAPE_16_9.value,
    )
    cue["output"] = output

    camera = _dict_value(cue.get("camera"))
    camera["enabled"] = bool(sources["camera"].get("enabled"))
    camera["shape"] = _enum_value(
        camera.get("shape", cue.get("shape")),
        CameraShape,
        CameraShape.ROUNDED_RECTANGLE.value,
    )
    camera["corner"] = _enum_value(
        camera.get("corner", cue.get("corner")),
        CameraCorner,
        CameraCorner.BOTTOM_RIGHT.value,
    )
    camera.setdefault("size", "medium")
    camera.setdefault("margin_percent", 4)
    cue["camera"] = camera

    cue.setdefault("reason", "")
    return cue


def _normalize_source_ref(
    raw: Any,
    role: LayoutSourceRole,
    *,
    enabled: bool,
    fallback_track: str,
) -> dict[str, Any]:
    source = _dict_value(raw)
    source["role"] = role.value
    source["enabled"] = bool(source.get("enabled", enabled))
    source.setdefault("asset_id", None)
    source.setdefault("track", fallback_track)
    source.setdefault("sync_offset_seconds", 0.0)
    return source


def _source_ref(
    role: LayoutSourceRole,
    asset_id: str | None,
    *,
    enabled: bool,
    track: str,
) -> dict[str, Any]:
    return {
        "role": role.value,
        "asset_id": asset_id,
        "enabled": enabled,
        "track": track,
        "sync_offset_seconds": 0.0,
    }


def _layout_value(value: Any) -> str:
    raw = _enum_value(value, LayoutMode, LayoutMode.FULL_SCREEN_SOURCE.value)
    return LAYOUT_ALIASES.get(raw, raw)


def _enum_value(value: Any, enum_class: type[Enum], default: str) -> str:
    if isinstance(value, enum_class):
        return str(value.value)
    if isinstance(value, str):
        normalized = LAYOUT_ALIASES.get(value, value)
        if normalized in {item.value for item in enum_class}:
            return normalized
    return default


def _transition_value(value: Any, default: str) -> str:
    candidate = str(value or "").lower()
    return candidate if candidate in LAYOUT_TRANSITIONS else default


def _dict_value(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _bounded_float(value: Any, *, default: float, minimum: float, maximum: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return min(maximum, max(minimum, number))


def _non_negative_float(value: Any, default: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, number)


def _optional_non_negative_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, number)
