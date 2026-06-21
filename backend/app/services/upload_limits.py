"""Shared upload limit helpers for video and source asset endpoints."""

from __future__ import annotations

from typing import Any


def max_upload_size_bytes(settings_obj: Any) -> int:
    """Return the configured upload limit in bytes."""
    return int(getattr(settings_obj, "MAX_VIDEO_SIZE_MB", 10240)) * 1024 * 1024


def upload_limit_label(settings_obj: Any) -> str:
    """Return a readable label for upload limit errors and UI messages."""
    size_mb = int(getattr(settings_obj, "MAX_VIDEO_SIZE_MB", 10240))
    if size_mb >= 1024 and size_mb % 1024 == 0:
        return f"{size_mb // 1024}GB"
    if size_mb >= 1024:
        return f"{size_mb / 1024:.1f}GB"
    return f"{size_mb}MB"
