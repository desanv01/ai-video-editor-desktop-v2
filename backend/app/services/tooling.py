"""Runtime tool resolution shared by media-processing services."""

from __future__ import annotations

from pathlib import Path

from config import settings


def ffmpeg_binary() -> str:
    """Return the explicit native component binary or Docker's legacy name."""
    if getattr(settings, "is_native_desktop", False):
        path = str(getattr(settings, "FFMPEG_BINARY_PATH", "") or "").strip()
        if not path:
            raise RuntimeError(
                "Native desktop FFmpeg is not configured; activate a pinned FFmpeg component first."
            )
        if not Path(path).is_absolute():
            raise RuntimeError("Native desktop FFmpeg must be an absolute path from the activated component root.")
        return path
    return "ffmpeg"


def ffprobe_binary() -> str:
    """Return the explicit native component probe binary or Docker's legacy name."""
    if getattr(settings, "is_native_desktop", False):
        path = str(getattr(settings, "FFPROBE_BINARY_PATH", "") or "").strip()
        if not path:
            raise RuntimeError(
                "Native desktop FFprobe is not configured; activate a pinned FFmpeg component first."
            )
        if not Path(path).is_absolute():
            raise RuntimeError("Native desktop FFprobe must be an absolute path from the activated component root.")
        return path
    return "ffprobe"
