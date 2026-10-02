"""Runtime tool resolution shared by media-processing services."""

from __future__ import annotations

import os
from pathlib import Path
import stat

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


def libreoffice_binary() -> str:
    """Resolve only an explicitly activated, confined native document binary."""
    if not getattr(settings, "is_native_desktop", False):
        return "libreoffice"

    root_value = str(getattr(settings, "LIBREOFFICE_COMPONENT_ROOT", "") or "").strip()
    binary_value = str(getattr(settings, "LIBREOFFICE_BINARY_PATH", "") or "").strip()
    if not root_value or not binary_value:
        raise RuntimeError("Managed LibreOffice is not configured; prepare the document component and retry.")
    root = Path(root_value)
    binary = Path(binary_value)
    if not root.is_absolute() or not binary.is_absolute():
        raise RuntimeError("Managed LibreOffice requires absolute activated component and binary paths.")
    root = Path(os.path.abspath(root))
    binary = Path(os.path.abspath(binary))
    try:
        binary.relative_to(root)
        # Inspect every existing path component before resolution; no junction or
        # symlink may silently redirect the activated root or its executable.
        for target in (root, binary):
            for part in reversed((target, *target.parents)):
                info = part.lstat()
                if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
                    raise RuntimeError("Managed LibreOffice paths cannot contain symlinks or reparse points.")
        actual_root = root.resolve(strict=True)
        actual_binary = binary.resolve(strict=True)
        actual_binary.relative_to(actual_root)
        if not actual_root.is_dir() or not stat.S_ISREG(actual_binary.stat().st_mode):
            raise RuntimeError("Managed LibreOffice binary must be a regular file in its activated installation.")
    except (OSError, ValueError) as exc:
        raise RuntimeError("Managed LibreOffice installation is missing or outside its activated root; repair the document component.") from exc
    if os.name == "nt" and actual_binary.relative_to(actual_root).as_posix().lower() != "program/soffice.com":
        raise RuntimeError("Managed Windows LibreOffice must use the activated program/soffice.com CLI.")
    return str(actual_binary)
