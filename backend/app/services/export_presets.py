"""Export preset catalog for platform and course delivery targets."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


EXPORT_PRESET_SCHEMA_VERSION = "phase9.export-presets.v1"
DEFAULT_EXPORT_PRESET_ID = "youtube_1080p"
DEFAULT_EXPORT_PRESET_IDS = ("youtube_1080p", "lms_compatible")


@dataclass(frozen=True)
class ExportPreset:
    id: str
    group_id: str
    group_label: str
    label: str
    description: str
    target: str
    container: str
    extension: str
    video_codec: str | None
    audio_codec: str
    width: int | None
    height: int | None
    aspect_ratio: str | None
    orientation: str
    fps: int | None
    video_bitrate: str | None
    audio_bitrate: str
    audio_only: bool
    caption_strategy: str
    delivery_notes: list[str]
    tags: list[str]

    def to_response(self) -> dict[str, Any]:
        return asdict(self)


EXPORT_PRESET_GROUPS: tuple[dict[str, str], ...] = (
    {
        "id": "social",
        "label": "Social",
        "description": "Platform-ready formats for public channels and short clips.",
    },
    {
        "id": "professional",
        "label": "Professional",
        "description": "Reusable MP4 and audio outputs for meetings, portfolios, and handoff.",
    },
    {
        "id": "education",
        "label": "Education",
        "description": "Course-friendly outputs for LMS upload, captions, and learner access.",
    },
)


EXPORT_PRESETS: tuple[ExportPreset, ...] = (
    ExportPreset(
        id="youtube_1080p",
        group_id="social",
        group_label="Social",
        label="YouTube 1080p",
        description="Full HD lecture video for standard YouTube publishing.",
        target="youtube",
        container="mp4",
        extension=".mp4",
        video_codec="h264",
        audio_codec="aac",
        width=1920,
        height=1080,
        aspect_ratio="16:9",
        orientation="landscape",
        fps=30,
        video_bitrate="8 Mbps",
        audio_bitrate="192 kbps",
        audio_only=False,
        caption_strategy="sidecar_srt_vtt",
        delivery_notes=["Keep chapter markers", "Include SRT and VTT sidecars"],
        tags=["youtube", "full_hd", "lecture"],
    ),
    ExportPreset(
        id="youtube_4k",
        group_id="social",
        group_label="Social",
        label="YouTube 4K",
        description="Ultra HD YouTube master for high-resolution screen recordings.",
        target="youtube",
        container="mp4",
        extension=".mp4",
        video_codec="h264",
        audio_codec="aac",
        width=3840,
        height=2160,
        aspect_ratio="16:9",
        orientation="landscape",
        fps=30,
        video_bitrate="35 Mbps",
        audio_bitrate="320 kbps",
        audio_only=False,
        caption_strategy="sidecar_srt_vtt",
        delivery_notes=["Preserve slide detail", "Use when source resolution supports 4K"],
        tags=["youtube", "4k", "master"],
    ),
    ExportPreset(
        id="tiktok_reels",
        group_id="social",
        group_label="Social",
        label="TikTok/Reels",
        description="Vertical short-form clip for TikTok, Instagram Reels, and Shorts.",
        target="short_form_social",
        container="mp4",
        extension=".mp4",
        video_codec="h264",
        audio_codec="aac",
        width=1080,
        height=1920,
        aspect_ratio="9:16",
        orientation="vertical",
        fps=30,
        video_bitrate="10 Mbps",
        audio_bitrate="128 kbps",
        audio_only=False,
        caption_strategy="burn_in_recommended",
        delivery_notes=["Prefer short highlighted sections", "Burn in captions for silent autoplay"],
        tags=["tiktok", "reels", "shorts", "vertical"],
    ),
    ExportPreset(
        id="instagram",
        group_id="social",
        group_label="Social",
        label="Instagram",
        description="Square feed-friendly export for lecture snippets and announcements.",
        target="instagram",
        container="mp4",
        extension=".mp4",
        video_codec="h264",
        audio_codec="aac",
        width=1080,
        height=1080,
        aspect_ratio="1:1",
        orientation="square",
        fps=30,
        video_bitrate="8 Mbps",
        audio_bitrate="128 kbps",
        audio_only=False,
        caption_strategy="burn_in_recommended",
        delivery_notes=["Use concise title cards", "Keep important content inside square safe area"],
        tags=["instagram", "square", "social"],
    ),
    ExportPreset(
        id="linkedin",
        group_id="professional",
        group_label="Professional",
        label="LinkedIn",
        description="Professional platform export for course previews and knowledge clips.",
        target="linkedin",
        container="mp4",
        extension=".mp4",
        video_codec="h264",
        audio_codec="aac",
        width=1920,
        height=1080,
        aspect_ratio="16:9",
        orientation="landscape",
        fps=30,
        video_bitrate="8 Mbps",
        audio_bitrate="192 kbps",
        audio_only=False,
        caption_strategy="burn_in_or_sidecar",
        delivery_notes=["Use readable captions", "Keep intro title concise"],
        tags=["linkedin", "professional", "preview"],
    ),
    ExportPreset(
        id="mp4_1080p",
        group_id="professional",
        group_label="Professional",
        label="MP4 1080p",
        description="General-purpose Full HD MP4 for sharing, archiving, or review.",
        target="generic_mp4",
        container="mp4",
        extension=".mp4",
        video_codec="h264",
        audio_codec="aac",
        width=1920,
        height=1080,
        aspect_ratio="16:9",
        orientation="landscape",
        fps=30,
        video_bitrate="10 Mbps",
        audio_bitrate="192 kbps",
        audio_only=False,
        caption_strategy="sidecar_optional",
        delivery_notes=["Balanced quality and file size", "Works with most players"],
        tags=["mp4", "1080p", "handoff"],
    ),
    ExportPreset(
        id="mp4_720p",
        group_id="professional",
        group_label="Professional",
        label="MP4 720p",
        description="Smaller HD MP4 for fast review, email handoff, or low bandwidth.",
        target="generic_mp4",
        container="mp4",
        extension=".mp4",
        video_codec="h264",
        audio_codec="aac",
        width=1280,
        height=720,
        aspect_ratio="16:9",
        orientation="landscape",
        fps=30,
        video_bitrate="5 Mbps",
        audio_bitrate="128 kbps",
        audio_only=False,
        caption_strategy="sidecar_optional",
        delivery_notes=["Smaller upload size", "Good for draft review"],
        tags=["mp4", "720p", "review"],
    ),
    ExportPreset(
        id="podcast_audio",
        group_id="professional",
        group_label="Professional",
        label="Podcast Audio-only",
        description="Cleaned lecture audio for podcast feeds or audio revision notes.",
        target="podcast_audio",
        container="m4a",
        extension=".m4a",
        video_codec=None,
        audio_codec="aac",
        width=None,
        height=None,
        aspect_ratio=None,
        orientation="audio_only",
        fps=None,
        video_bitrate=None,
        audio_bitrate="192 kbps",
        audio_only=True,
        caption_strategy="transcript_export",
        delivery_notes=["Export transcript with audio", "No video stream"],
        tags=["podcast", "audio", "lecture"],
    ),
    ExportPreset(
        id="lms_compatible",
        group_id="education",
        group_label="Education",
        label="LMS Compatible",
        description="Course-platform friendly MP4 for Moodle, Canvas, and LMS libraries.",
        target="lms",
        container="mp4",
        extension=".mp4",
        video_codec="h264",
        audio_codec="aac",
        width=1280,
        height=720,
        aspect_ratio="16:9",
        orientation="landscape",
        fps=30,
        video_bitrate="4 Mbps",
        audio_bitrate="128 kbps",
        audio_only=False,
        caption_strategy="required_sidecar_srt_vtt",
        delivery_notes=["Prioritize compatibility", "Include captions and chapter markers"],
        tags=["lms", "moodle", "canvas", "education"],
    ),
)


def list_export_presets() -> list[dict[str, Any]]:
    """Return all available export presets as serializable dictionaries."""
    return [preset.to_response() for preset in EXPORT_PRESETS]


def list_grouped_export_presets() -> dict[str, Any]:
    """Return the preset catalog grouped for the desktop export UI."""
    presets_by_group: dict[str, list[dict[str, Any]]] = {
        group["id"]: [] for group in EXPORT_PRESET_GROUPS
    }
    for preset in EXPORT_PRESETS:
        presets_by_group.setdefault(preset.group_id, []).append(preset.to_response())

    return {
        "schema_version": EXPORT_PRESET_SCHEMA_VERSION,
        "default_preset_id": DEFAULT_EXPORT_PRESET_ID,
        "groups": [
            {
                **group,
                "presets": presets_by_group.get(group["id"], []),
            }
            for group in EXPORT_PRESET_GROUPS
        ],
    }


def get_export_preset(preset_id: str | None) -> dict[str, Any]:
    """Return one preset or raise ValueError for an unknown id."""
    normalized_id = normalize_export_preset_id(preset_id)
    for preset in EXPORT_PRESETS:
        if preset.id == normalized_id:
            return preset.to_response()
    raise ValueError(f"Unknown export preset '{preset_id}'.")


def normalize_export_preset_id(preset_id: str | None) -> str:
    candidate = str(preset_id or DEFAULT_EXPORT_PRESET_ID).strip().lower()
    known_ids = {preset.id for preset in EXPORT_PRESETS}
    if candidate not in known_ids:
        raise ValueError(f"Unknown export preset '{preset_id}'.")
    return candidate
