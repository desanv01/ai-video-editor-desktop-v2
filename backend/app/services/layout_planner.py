"""Rule-based layout planning for lecture edit plans."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable

from services.layout_model import LayoutMode, build_layout_cue, normalize_layout_cues


LAYOUT_PLANNER_VERSION = "phase7.layout-rules.v1"

SCREEN_VALUES = {
    "screen",
    "screen_video",
    "screen_recording",
    "screen_reference",
}
CAMERA_VALUES = {
    "camera",
    "camera_video",
    "camera_recording",
    "webcam_recording",
    "phone_camera_recording",
    "camera_overlay",
}
AUDIO_VALUES = {
    "audio",
    "separate_audio",
    "audio_master",
    "audio_reference",
}
PRIMARY_VALUES = {
    "primary",
    "mixed_video",
    "primary_timeline",
}
STRUCTURE_REFERENCE_VALUES = {
    "slides",
    "slide_deck",
    "pdf_notes",
    "text_notes",
    "structure_reference",
}
CAMERA_FIRST_SEGMENT_TYPES = {"intro_outro", "qa", "transition"}
SCREEN_FOCUS_SEGMENT_TYPES = {"example", "core_content"}


@dataclass(frozen=True)
class LayoutSourceChoice:
    asset_id: str | None
    track: str
    sync_offset_seconds: float
    role_hint: str = ""


@dataclass(frozen=True)
class LayoutSourceSelection:
    screen: LayoutSourceChoice | None = None
    camera: LayoutSourceChoice | None = None
    audio: LayoutSourceChoice | None = None
    structure_reference_count: int = 0

    @property
    def has_screen(self) -> bool:
        return self.screen is not None and self.screen.asset_id is not None

    @property
    def has_camera(self) -> bool:
        return self.camera is not None and self.camera.asset_id is not None

    @property
    def has_audio(self) -> bool:
        return self.audio is not None and self.audio.asset_id is not None


def plan_layout_cues(
    assets: Iterable[Any] | None,
    *,
    duration_seconds: float | None = None,
    segments: Iterable[Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Plan lecture layout cues from available project sources and segment signals.

    Defaults are deliberately conservative:
    - one mixed/screen source: full-screen source
    - camera-only source: full-camera source
    - screen plus camera: screen-first picture-in-picture with timed emphasis
    - separate audio: selected as the audio source for every cue
    """
    asset_list = list(assets or [])
    raw_segment_list = list(segments or [])
    selection = select_layout_sources(asset_list)
    base_layout = _base_layout(selection)
    total_duration = _duration_seconds(duration_seconds, asset_list, raw_segment_list)
    segment_list = _usable_segments(raw_segment_list)

    if not (selection.has_screen and selection.has_camera) or not segment_list:
        return normalize_layout_cues(
            [
                _build_planned_cue(
                    index=1,
                    layout=base_layout,
                    start_time=0.0,
                    end_time=total_duration,
                    selection=selection,
                    reason=_default_reason(selection, base_layout),
                )
            ],
            duration_seconds=total_duration,
        )

    intervals = _screen_camera_intervals(segment_list, base_layout, total_duration)
    cues = [
        _build_planned_cue(
            index=index,
            layout=layout,
            start_time=start,
            end_time=end,
            selection=selection,
            reason=reason,
        )
        for index, (start, end, layout, reason) in enumerate(intervals, start=1)
    ]
    return normalize_layout_cues(cues, duration_seconds=total_duration)


def select_layout_sources(assets: Iterable[Any]) -> LayoutSourceSelection:
    """Choose the screen, camera, and audio sources that should anchor layout cues."""
    asset_list = list(assets or [])
    screen_asset = _first_asset(asset_list, SCREEN_VALUES)
    primary_asset = _first_asset(asset_list, PRIMARY_VALUES)
    camera_asset = _first_asset(asset_list, CAMERA_VALUES)
    audio_asset = _first_asset(asset_list, AUDIO_VALUES)
    structure_count = sum(1 for asset in asset_list if _asset_matches(asset, STRUCTURE_REFERENCE_VALUES))

    screen_choice = None
    if screen_asset is not None:
        screen_choice = _choice(screen_asset, "screen")
    elif primary_asset is not None:
        screen_choice = _choice(primary_asset, "primary_timeline")

    camera_choice = _choice(camera_asset, "camera") if camera_asset is not None else None

    audio_choice = None
    if audio_asset is not None:
        audio_choice = _choice(audio_asset, "audio")
    elif screen_asset is not None:
        audio_choice = _choice(screen_asset, "audio")
    elif primary_asset is not None:
        audio_choice = _choice(primary_asset, "audio")
    elif camera_asset is not None:
        audio_choice = _choice(camera_asset, "audio")

    return LayoutSourceSelection(
        screen=screen_choice,
        camera=camera_choice,
        audio=audio_choice,
        structure_reference_count=structure_count,
    )


def layout_planning_summary(cues: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Return a compact metadata block for edit-plan payloads."""
    cue_list = list(cues or [])
    return {
        "schema_version": LAYOUT_PLANNER_VERSION,
        "strategy": "rule_based",
        "cues_total": len(cue_list),
        "layouts": sorted({str(cue.get("layout")) for cue in cue_list if cue.get("layout")}),
    }


def _screen_camera_intervals(
    segments: list[Any],
    base_layout: LayoutMode,
    duration_seconds: float | None,
) -> list[tuple[float, float | None, LayoutMode, str]]:
    intervals: list[tuple[float, float | None, LayoutMode, str]] = []
    cursor = 0.0

    for segment in segments:
        start = _number(_segment_value(segment, "start_time", "start"), cursor) or cursor
        end = _number(_segment_value(segment, "end_time", "end"), start) or start
        start = max(0.0, start)
        end = max(start, end)
        if end <= cursor:
            continue

        if start > cursor:
            intervals.append((cursor, start, base_layout, "Maintain the default lecture layout between analyzed segments."))

        layout, reason = _segment_layout(segment, base_layout)
        intervals.append((max(cursor, start), end, layout, reason))
        cursor = end

    if duration_seconds is None:
        intervals.append((cursor, None, base_layout, "Continue the default lecture layout until the source ends."))
    elif cursor < duration_seconds:
        intervals.append((cursor, duration_seconds, base_layout, "Continue the default lecture layout after the analyzed content."))

    return _merge_intervals(intervals)


def _segment_layout(segment: Any, base_layout: LayoutMode) -> tuple[LayoutMode, str]:
    action = str(_segment_value(segment, "action", "teacher_action") or "").lower()
    segment_type = str(_segment_value(segment, "segment_type", "type") or "").lower()
    importance = _number(_segment_value(segment, "importance_score", "importance"), 0.5) or 0.5
    has_slide_change = bool(_segment_value(segment, "has_slide_change") or False)
    slide_index = _segment_value(segment, "slide_index")
    start_time = _number(_segment_value(segment, "start_time", "start"), 0.0) or 0.0

    if has_slide_change or slide_index is not None:
        return (
            LayoutMode.FULL_SCREEN_SOURCE,
            "Slide or screen transition detected; prioritize source legibility.",
        )

    if segment_type in CAMERA_FIRST_SEGMENT_TYPES or start_time <= 20.0:
        return (
            LayoutMode.SIDE_BY_SIDE,
            "Instructor presence is useful for introductions, transitions, or Q&A.",
        )

    if action == "highlight" or (importance >= 0.85 and segment_type in SCREEN_FOCUS_SEGMENT_TYPES):
        return (
            LayoutMode.FULL_SCREEN_SOURCE,
            "High-importance teaching moment; keep the screen source unobstructed.",
        )

    return (
        base_layout,
        "Use the default screen-first lecture layout.",
    )


def _base_layout(selection: LayoutSourceSelection) -> LayoutMode:
    if selection.has_screen and selection.has_camera:
        return LayoutMode.PICTURE_IN_PICTURE
    if selection.has_camera and not selection.has_screen:
        return LayoutMode.FULL_CAMERA_SOURCE
    return LayoutMode.FULL_SCREEN_SOURCE


def _build_planned_cue(
    *,
    index: int,
    layout: LayoutMode,
    start_time: float,
    end_time: float | None,
    selection: LayoutSourceSelection,
    reason: str,
) -> dict[str, Any]:
    cue = build_layout_cue(
        cue_id=f"layout-rule-{index:03d}",
        layout=layout,
        start_time=start_time,
        end_time=end_time,
        screen_source_id=selection.screen.asset_id if selection.screen else None,
        camera_source_id=selection.camera.asset_id if selection.camera else None,
        audio_source_id=selection.audio.asset_id if selection.audio else None,
        reason=reason,
    )
    cue["planning"] = {
        "schema_version": LAYOUT_PLANNER_VERSION,
        "strategy": "rule_based",
        "source_summary": {
            "has_screen": selection.has_screen,
            "has_camera": selection.has_camera,
            "has_audio": selection.has_audio,
            "structure_reference_count": selection.structure_reference_count,
        },
    }
    _apply_source_choice(cue["sources"]["screen"], selection.screen)
    _apply_source_choice(cue["sources"]["camera"], selection.camera)
    _apply_source_choice(cue["sources"]["audio"], selection.audio)
    if not selection.has_screen and layout != LayoutMode.FULL_CAMERA_SOURCE:
        cue["sources"]["screen"]["enabled"] = False
    if not selection.has_camera:
        cue["sources"]["camera"]["enabled"] = False
        cue["camera"]["enabled"] = False
    return cue


def _apply_source_choice(target: dict[str, Any], choice: LayoutSourceChoice | None) -> None:
    if choice is None:
        target["asset_id"] = None
        target["sync_offset_seconds"] = 0.0
        return
    target["asset_id"] = choice.asset_id
    target["track"] = choice.track
    target["sync_offset_seconds"] = choice.sync_offset_seconds


def _merge_intervals(
    intervals: Iterable[tuple[float, float | None, LayoutMode, str]]
) -> list[tuple[float, float | None, LayoutMode, str]]:
    merged: list[tuple[float, float | None, LayoutMode, str]] = []
    for start, end, layout, reason in intervals:
        if end is not None and end <= start:
            continue
        if not merged:
            merged.append((start, end, layout, reason))
            continue
        prev_start, prev_end, prev_layout, prev_reason = merged[-1]
        if prev_layout == layout and _same_boundary(prev_end, start):
            merged[-1] = (prev_start, end, prev_layout, prev_reason)
        else:
            merged.append((start, end, layout, reason))
    return merged


def _same_boundary(left: float | None, right: float) -> bool:
    if left is None:
        return False
    return abs(left - right) < 0.001


def _usable_segments(segments: Iterable[Any] | None) -> list[Any]:
    usable = []
    for segment in segments or []:
        action = str(_segment_value(segment, "action", "teacher_action") or "").lower()
        if action == "cut":
            continue
        start = _number(_segment_value(segment, "start_time", "start"), None)
        end = _number(_segment_value(segment, "end_time", "end"), None)
        if start is None or end is None or end <= start:
            continue
        usable.append(segment)
    return sorted(usable, key=lambda item: _number(_segment_value(item, "start_time", "start"), 0.0) or 0.0)


def _duration_seconds(
    duration_seconds: float | None,
    assets: Iterable[Any] | None,
    segments: Iterable[Any] | None,
) -> float | None:
    explicit = _number(duration_seconds, None)
    if explicit is not None and explicit > 0:
        return explicit

    candidates = []
    for segment in segments or []:
        end = _number(_segment_value(segment, "end_time", "end"), None)
        if end is not None:
            candidates.append(end)
    for asset in assets or []:
        duration = _number(_attr(asset, "duration_seconds"), None)
        if duration is not None:
            candidates.append(duration)
    return max(candidates) if candidates else None


def _default_reason(selection: LayoutSourceSelection, layout: LayoutMode) -> str:
    if layout == LayoutMode.PICTURE_IN_PICTURE:
        return "Screen and camera sources are available; default to screen-first picture-in-picture."
    if layout == LayoutMode.FULL_CAMERA_SOURCE:
        return "Only a camera-style visual source is available; use full-camera layout."
    if selection.has_screen:
        return "Use the available screen or mixed-video source full-screen for lecture clarity."
    return "No separate visual source was detected; keep a conservative full-source layout placeholder."


def _first_asset(assets: list[Any], value_set: set[str]) -> Any | None:
    candidates = [asset for asset in assets if _asset_matches(asset, value_set)]
    if not candidates:
        return None
    return sorted(candidates, key=_asset_priority)[0]


def _asset_matches(asset: Any, value_set: set[str]) -> bool:
    values = {
        _value(_attr(asset, "kind")),
        _value(_attr(asset, "role")),
        _value(_attr(asset, "source_type")),
        _value(_attr(asset, "sync_role")),
    }
    return bool(values & value_set)


def _asset_priority(asset: Any) -> tuple[int, int, str]:
    is_primary = bool(_attr(asset, "is_primary") or False)
    status = _value(_attr(asset, "status"))
    return (
        0 if is_primary else 1,
        0 if status == "ready" else 1,
        str(_attr(asset, "created_at") or ""),
    )


def _choice(asset: Any, track: str) -> LayoutSourceChoice:
    return LayoutSourceChoice(
        asset_id=str(_attr(asset, "id")) if _attr(asset, "id") is not None else None,
        track=track,
        sync_offset_seconds=_number(_attr(asset, "sync_offset_seconds"), 0.0) or 0.0,
        role_hint=_value(_attr(asset, "role")),
    )


def _segment_value(segment: Any, *names: str) -> Any:
    for name in names:
        value = _attr(segment, name)
        if isinstance(value, Enum):
            return value.value
        if value is not None:
            return value
    return None


def _attr(item: Any, name: str) -> Any:
    if isinstance(item, dict):
        return item.get(name)
    return getattr(item, name, None)


def _value(value: Any) -> str:
    if isinstance(value, Enum):
        return str(value.value)
    if value is None:
        return ""
    return str(value).lower()


def _number(value: Any, default: float | None) -> float | None:
    if isinstance(value, bool) or value is None:
        return default
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return default
