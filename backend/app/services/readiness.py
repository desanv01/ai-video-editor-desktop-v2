"""Deterministic project preflight/readiness checks.

The checks intentionally report configured versus usable capabilities without
making network calls or returning secrets.  A provider warning does not block
manual transcript/segment editing; source and storage blockers do.
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.product_workflow import WorkflowState, map_legacy_status, workflow_label
from services.upload_limits import max_upload_size_bytes, upload_limit_label


SUPPORTED_VIDEO_EXTENSIONS = frozenset(
    {".mp4", ".mpeg", ".mpg", ".mov", ".avi", ".webm", ".mkv"}
)


def _issue(code: str, message: str, remediation: str, *, severity: str = "blocker") -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "remediation": remediation,
        "severity": severity,
    }


def _path_capability(value: object, *, label: str) -> dict[str, Any]:
    path = str(value or "").strip()
    configured = bool(path)
    usable = configured and Path(path).is_file()
    return {
        "id": label.lower().replace(" ", "_"),
        "label": label,
        "configured": configured,
        "usable": usable,
        "status": "usable" if usable else "configured" if configured else "unavailable",
        "detail": str(Path(path)) if configured else f"{label} is not configured",
    }


def _api_capability(provider_id: str, label: str, key: object, model: object) -> dict[str, Any]:
    configured = bool(str(key or "").strip())
    return {
        "id": provider_id,
        "label": label,
        "configured": configured,
        "usable": configured,
        "status": "usable" if configured else "unavailable",
        "model": str(model or "") or None,
        "detail": "API key is present; live connection is tested only on explicit user request."
        if configured
        else "No API key is configured.",
    }


def build_system_readiness(settings: Any) -> dict[str, Any]:
    storage_root = Path(str(getattr(settings, "APP_STORAGE_ROOT", "") or getattr(settings, "UPLOAD_PATH", ".")))
    storage_root.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(storage_root)
    min_free = int(getattr(settings, "UPLOAD_MIN_FREE_SPACE_BYTES", 0) or 0)
    storage = {
        "root": str(storage_root),
        "exists": storage_root.exists(),
        "writable": os.access(storage_root, os.W_OK),
        "free_bytes": usage.free,
        "total_bytes": usage.total,
        "required_free_bytes": min_free,
        "enough_free_space": usage.free >= min_free,
    }
    capabilities = {
        "transcription_api": _api_capability(
            str(getattr(settings, "ASR_PROVIDER", "transcription")),
            "Transcription API",
            getattr(settings, "MISTRAL_API_KEY", "") or getattr(settings, "OPENAI_API_KEY", ""),
            getattr(settings, "VOXTRAL_MODEL", "") or getattr(settings, "WHISPER_MODEL", ""),
        ),
        "chat_api": _api_capability(
            "chat",
            "Chat / planning API",
            getattr(settings, "DEEPSEEK_API_KEY", "") or getattr(settings, "OPENAI_API_KEY", ""),
            getattr(settings, "AGENT5_MODEL", ""),
        ),
        "embedding_api": _api_capability(
            "embeddings",
            "Embedding API",
            getattr(settings, "OPENAI_API_KEY", ""),
            getattr(settings, "EMBEDDING_MODEL", ""),
        ),
        "ffmpeg": {
            "id": "ffmpeg",
            "label": "FFmpeg media tools",
            "configured": True,
            "usable": bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))
            or bool(getattr(settings, "FFMPEG_BINARY_PATH", "") and getattr(settings, "FFPROBE_BINARY_PATH", "")),
            "status": "usable" if (shutil.which("ffmpeg") and shutil.which("ffprobe")) or (getattr(settings, "FFMPEG_BINARY_PATH", "") and getattr(settings, "FFPROBE_BINARY_PATH", "")) else "unavailable",
            "detail": "FFmpeg and FFprobe are available."
            if (shutil.which("ffmpeg") and shutil.which("ffprobe"))
            else "FFmpeg/FFprobe are not available on the configured runtime path.",
        },
        "local_transcription": _path_capability(
            getattr(settings, "WHISPER_CPP_MODEL_PATH", "")
            or getattr(settings, "LOCAL_TRANSCRIPTION_MODEL_PATH", ""),
            label="Local transcription model",
        ),
        "local_runtime": _path_capability(
            getattr(settings, "WHISPER_CPP_BINARY_PATH", ""),
            label="Local model runtime",
        ),
    }
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if not storage["writable"]:
        blockers.append(_issue("STORAGE_NOT_WRITABLE", "Application storage is not writable.", "Choose a writable per-user storage location."))
    if not storage["enough_free_space"]:
        warnings.append(_issue("LOW_DISK_SPACE", "Available storage is below the recommended safety margin.", "Free disk space before importing a large source.", severity="warning"))
    if not capabilities["ffmpeg"]["usable"]:
        warnings.append(_issue("MEDIA_TOOLS_UNAVAILABLE", "Media tools are not ready for analysis/export.", "Activate the desktop media component or install FFmpeg in the Docker environment.", severity="warning"))
    if not any(cap["usable"] for key, cap in capabilities.items() if key not in {"ffmpeg", "local_runtime"}):
        warnings.append(_issue("AI_PROVIDER_UNAVAILABLE", "No AI provider is currently usable.", "Configure a cloud provider or local transcription/model runtime. Manual editing remains available.", severity="warning"))
    return {
        "schema_version": "phase8.product-readiness.v1",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "mode": "native" if getattr(settings, "is_native_desktop", False) else "docker",
        "ready": not blockers,
        "storage": storage,
        "capabilities": capabilities,
        "required_actions": [issue["remediation"] for issue in blockers],
        "blockers": blockers,
        "warnings": warnings,
    }


def build_project_readiness(
    project: Any,
    *,
    video: Any | None,
    assets: list[Any] | None,
    settings: Any,
) -> dict[str, Any]:
    assets = list(assets or [])
    primary_asset = next((asset for asset in assets if getattr(asset, "is_primary", False)), None)
    primary_asset = primary_asset or next((asset for asset in assets if str(getattr(asset, "role", "")) in {"primary", "ProjectAssetRole.PRIMARY"}), None)
    source_path = getattr(video, "file_path", None) or getattr(primary_asset, "file_path", None)
    filename = getattr(video, "original_filename", None) or getattr(primary_asset, "original_filename", None)
    extension = Path(filename or source_path or "").suffix.lower()
    file_size = getattr(video, "file_size_bytes", None) or getattr(primary_asset, "file_size_bytes", None)
    duration = getattr(video, "duration_seconds", None) or getattr(primary_asset, "duration_seconds", None)
    metadata = dict(getattr(primary_asset, "metadata_json", None) or {})
    blockers: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []
    if not source_path:
        blockers.append(_issue("SOURCE_REQUIRED", "Add a primary video source before analysis.", "Import a video or create a native import session."))
    elif not Path(str(source_path)).is_file():
        blockers.append(_issue("SOURCE_MISSING", "The primary source file is not available at its stored path.", "Repair the source or import it again."))
    if extension and extension not in SUPPORTED_VIDEO_EXTENSIONS:
        blockers.append(_issue("SOURCE_FORMAT_UNSUPPORTED", f"{extension} is not a supported video format.", f"Use one of: {', '.join(sorted(SUPPORTED_VIDEO_EXTENSIONS))}."))
    if file_size is not None and int(file_size) > max_upload_size_bytes(settings):
        blockers.append(_issue("SOURCE_TOO_LARGE", f"The source exceeds the {upload_limit_label(settings)} upload limit.", "Choose a smaller source or adjust the configured upload limit."))
    if duration is not None and float(duration) <= 0:
        warnings.append(_issue("MEDIA_DURATION_UNKNOWN", "The source duration has not been detected yet.", "Run media validation before analysis.", severity="warning"))
    if duration is not None and float(duration) > 24 * 60 * 60:
        warnings.append(_issue("MEDIA_LONG_SOURCE", "This source is longer than 24 hours.", "Consider splitting it into smaller project sources.", severity="warning"))

    system = build_system_readiness(settings)
    warnings.extend(system["warnings"])
    workflow_state = map_legacy_status(
        video_status=getattr(video, "status", None),
        project_status=getattr(project, "status", None),
        has_source=bool(source_path),
        has_edit_plan=bool(getattr(video, "edit_plan", None)),
        has_render_output=bool(getattr(video, "processed_video_path", None)),
    )
    if blockers and workflow_state not in {WorkflowState.FAILED, WorkflowState.CANCELLED}:
        workflow_state = WorkflowState.SOURCE_REQUIRED if not source_path else WorkflowState.VALIDATING
    if not blockers and source_path and workflow_state == WorkflowState.SOURCE_REQUIRED:
        workflow_state = WorkflowState.READY_FOR_ANALYSIS
    required_actions: list[str] = [item["remediation"] for item in blockers]
    if not blockers and workflow_state == WorkflowState.READY_FOR_ANALYSIS:
        required_actions.append("Start analysis when the source and provider choices are ready.")
    if workflow_state == WorkflowState.REVIEW_SUGGESTIONS:
        required_actions.append("Review the suggestions, then choose an export preset.")
    if workflow_state in {WorkflowState.EXPORT_READY, WorkflowState.EDITING}:
        required_actions.append("Review the preview and export when satisfied.")

    duplicate_names = [
        str(getattr(asset, "original_filename", ""))
        for asset in assets
        if filename and getattr(asset, "original_filename", None) == filename
        and getattr(asset, "file_size_bytes", None) == file_size
    ]
    if len(duplicate_names) > 1:
        warnings.append(_issue("DUPLICATE_SOURCE", "A source with the same name and size is already in this project.", "Keep one copy or deliberately replace the primary source.", severity="warning"))

    return {
        "schema_version": "phase8.project-readiness.v1",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "project_id": str(getattr(project, "id", "")),
        "video_id": str(getattr(video, "id", "")) if video else None,
        "workflow_state": workflow_state.value,
        "workflow_label": workflow_label(workflow_state),
        "ready": not blockers,
        "source": {
            "required": True,
            "valid": bool(source_path) and not any(item["code"].startswith("SOURCE_") for item in blockers),
            "filename": filename,
            "path_available": bool(source_path and Path(str(source_path)).is_file()),
            "extension": extension or None,
            "file_size_bytes": file_size,
            "supported_extensions": sorted(SUPPORTED_VIDEO_EXTENSIONS),
        },
        "media": {
            "duration_seconds": duration,
            "resolution": getattr(video, "resolution", None) or metadata.get("resolution"),
            "fps": getattr(video, "fps", None) or metadata.get("fps"),
            "metadata": metadata,
        },
        "capabilities": system["capabilities"],
        "storage": system["storage"],
        "required_actions": required_actions,
        "blockers": blockers,
        "warnings": warnings,
        "manual_operations_available": True,
    }
