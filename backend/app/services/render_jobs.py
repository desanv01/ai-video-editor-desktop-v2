"""
Persistent render job tracker.

Rendering is still driven by FastAPI background tasks and durable Video.status,
but this module keeps the live progress/error/cancel state that the desktop UI
can poll while FFmpeg work is active. Job snapshots are also written to disk so
the latest render state survives backend restarts.
"""

from __future__ import annotations

import logging
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import settings

logger = logging.getLogger(__name__)


TERMINAL_RENDER_JOB_STATUSES = {"completed", "failed", "cancelled"}
ACTIVE_RENDER_JOB_STATUSES = {"queued", "running", "cancel_requested"}

_render_jobs_by_id: dict[str, dict[str, Any]] = {}
_active_job_id_by_video_id: dict[str, str] = {}
_render_job_store_path = Path(settings.TEMP_PATH) / "render_jobs.json"


class RenderCancelled(RuntimeError):
    """Raised when a user-requested cancellation is observed between render phases."""


def configure_render_job_store(path: str | os.PathLike[str]) -> None:
    """Set the render job store path and reload jobs. Intended for tests."""
    global _render_job_store_path
    _render_job_store_path = Path(path)
    load_render_jobs_from_store()


def load_render_jobs_from_store() -> None:
    """Load persisted job snapshots, marking previously active jobs as interrupted."""
    _render_jobs_by_id.clear()
    _active_job_id_by_video_id.clear()

    if not _render_job_store_path.exists():
        return

    try:
        with _render_job_store_path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not load render job store %s: %s", _render_job_store_path, exc)
        return

    raw_jobs = payload.get("jobs", {})
    if isinstance(raw_jobs, list):
        jobs = {str(item.get("job_id")): item for item in raw_jobs if isinstance(item, dict)}
    elif isinstance(raw_jobs, dict):
        jobs = {str(job_id): item for job_id, item in raw_jobs.items() if isinstance(item, dict)}
    else:
        jobs = {}

    active_map = {
        str(video_id): str(job_id)
        for video_id, job_id in dict(payload.get("active_job_id_by_video_id") or {}).items()
    }

    changed = False
    for job_id, job in jobs.items():
        job["job_id"] = str(job.get("job_id") or job_id)
        job["video_id"] = str(job.get("video_id") or "")
        if job.get("status") in ACTIVE_RENDER_JOB_STATUSES:
            _mark_interrupted_after_restart(job)
            changed = True
        _render_jobs_by_id[job["job_id"]] = job

    for video_id, job_id in active_map.items():
        job = _render_jobs_by_id.get(job_id)
        if job and job.get("status") in ACTIVE_RENDER_JOB_STATUSES:
            _active_job_id_by_video_id[video_id] = job_id

    if changed:
        _save_render_jobs_to_store()


def create_render_job(video_id: str, preset_id: str | None = None) -> dict[str, Any]:
    """Create or replace the active render job for a video."""
    video_id = str(video_id)
    existing = get_active_render_job(video_id)
    if existing:
        return existing

    now = _utc_now()
    job = {
        "job_id": str(uuid.uuid4()),
        "video_id": video_id,
        "preset_id": preset_id,
        "status": "queued",
        "phase": "queued",
        "phase_label": "Queued for rendering",
        "message": "Waiting for render worker",
        "progress_percent": 0.0,
        "started_at": now,
        "updated_at": now,
        "completed_at": None,
        "elapsed_seconds": 0.0,
        "cancel_requested": False,
        "cancelled_at": None,
        "error": None,
        "result": None,
        "details": {},
    }
    _render_jobs_by_id[job["job_id"]] = job
    _active_job_id_by_video_id[video_id] = job["job_id"]
    _save_render_jobs_to_store()
    logger.info("Render job %s queued for video %s", job["job_id"], video_id)
    return snapshot_render_job(job)


def get_render_job(job_id: str | None) -> dict[str, Any] | None:
    if not job_id:
        return None
    job = _render_jobs_by_id.get(str(job_id))
    return snapshot_render_job(job) if job else None


def get_active_render_job(video_id: str) -> dict[str, Any] | None:
    job_id = _active_job_id_by_video_id.get(str(video_id))
    if not job_id:
        return None
    job = _render_jobs_by_id.get(job_id)
    if not job:
        _active_job_id_by_video_id.pop(str(video_id), None)
        return None
    if job.get("status") not in ACTIVE_RENDER_JOB_STATUSES:
        _active_job_id_by_video_id.pop(str(video_id), None)
        _save_render_jobs_to_store()
        return None
    return snapshot_render_job(job)


def get_latest_render_job(video_id: str) -> dict[str, Any] | None:
    """Return the active job, or the most recent terminal job for a video."""
    active = get_active_render_job(video_id)
    if active:
        return active

    candidates = [
        job
        for job in _render_jobs_by_id.values()
        if str(job.get("video_id")) == str(video_id)
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    return snapshot_render_job(candidates[0])


def start_render_job(job_id: str | None, video_id: str) -> dict[str, Any]:
    job = _resolve_or_create_job(job_id, video_id)
    _update_job(
        job,
        status="running",
        phase="preparing",
        phase_label="Preparing render inputs",
        message="Loading approved edit plan and timeline",
        progress_percent=max(float(job.get("progress_percent") or 0.0), 1.0),
    )
    logger.info("Render job %s started for video %s", job["job_id"], video_id)
    return snapshot_render_job(job)


def update_render_job(
    job_id: str | None,
    video_id: str,
    *,
    progress_percent: float | None = None,
    phase: str | None = None,
    phase_label: str | None = None,
    message: str | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    job = _resolve_or_create_job(job_id, video_id)
    if job.get("status") == "queued":
        job["status"] = "running"
    updates: dict[str, Any] = {}
    if progress_percent is not None:
        updates["progress_percent"] = _clamp_progress(progress_percent)
    if phase is not None:
        updates["phase"] = phase
    if phase_label is not None:
        updates["phase_label"] = phase_label
    if message is not None:
        updates["message"] = message
    if details:
        merged = dict(job.get("details") or {})
        merged.update(details)
        updates["details"] = merged
    _update_job(job, **updates)
    return snapshot_render_job(job)


def request_render_cancel(video_id: str) -> dict[str, Any] | None:
    job_id = _active_job_id_by_video_id.get(str(video_id))
    if not job_id:
        return None
    job = _render_jobs_by_id.get(job_id)
    if not job or job.get("status") not in ACTIVE_RENDER_JOB_STATUSES:
        return None
    _update_job(
        job,
        status="cancel_requested",
        cancel_requested=True,
        phase_label="Cancelling render",
        message="Cancellation requested. The active FFmpeg operation is being stopped.",
    )
    logger.info("Render cancellation requested for job %s", job_id)
    return snapshot_render_job(job)


def ensure_not_cancelled(job_id: str | None, video_id: str) -> None:
    job = _resolve_or_create_job(job_id, video_id)
    if job.get("cancel_requested"):
        raise RenderCancelled("Render cancelled by user")


def complete_render_job(job_id: str | None, video_id: str, result: dict[str, Any] | None = None) -> dict[str, Any]:
    job = _resolve_or_create_job(job_id, video_id)
    _update_job(
        job,
        status="completed",
        phase="completed",
        phase_label="Render complete",
        message="Export files are ready",
        progress_percent=100.0,
        result=result or {},
        completed_at=_utc_now(),
    )
    _active_job_id_by_video_id.pop(str(video_id), None)
    _save_render_jobs_to_store()
    return snapshot_render_job(job)


def fail_render_job(job_id: str | None, video_id: str, error: str) -> dict[str, Any]:
    job = _resolve_or_create_job(job_id, video_id)
    _update_job(
        job,
        status="failed",
        phase="failed",
        phase_label="Render failed",
        message="Rendering stopped because an error occurred",
        error=error,
        completed_at=_utc_now(),
    )
    _active_job_id_by_video_id.pop(str(video_id), None)
    _save_render_jobs_to_store()
    return snapshot_render_job(job)


def cancel_render_job(job_id: str | None, video_id: str, message: str | None = None) -> dict[str, Any]:
    job = _resolve_or_create_job(job_id, video_id)
    _update_job(
        job,
        status="cancelled",
        phase="cancelled",
        phase_label="Render cancelled",
        message=message or "Render cancelled by user",
        cancel_requested=True,
        cancelled_at=_utc_now(),
        completed_at=_utc_now(),
    )
    _active_job_id_by_video_id.pop(str(video_id), None)
    _save_render_jobs_to_store()
    return snapshot_render_job(job)


def snapshot_render_job(job: dict[str, Any] | None) -> dict[str, Any] | None:
    if not job:
        return None
    snapshot = {
        key: value
        for key, value in job.items()
        if key not in {"_started_monotonic"}
    }
    snapshot["elapsed_seconds"] = _elapsed_seconds(job)
    snapshot["cancellable"] = snapshot.get("status") in ACTIVE_RENDER_JOB_STATUSES
    return snapshot


def _resolve_or_create_job(job_id: str | None, video_id: str) -> dict[str, Any]:
    if job_id and str(job_id) in _render_jobs_by_id:
        return _render_jobs_by_id[str(job_id)]
    active_id = _active_job_id_by_video_id.get(str(video_id))
    if active_id and active_id in _render_jobs_by_id:
        return _render_jobs_by_id[active_id]
    created = create_render_job(video_id)
    return _render_jobs_by_id[created["job_id"]]


def _update_job(job: dict[str, Any], **updates: Any) -> None:
    job.update(updates)
    job["updated_at"] = _utc_now()
    job["elapsed_seconds"] = _elapsed_seconds(job)
    _save_render_jobs_to_store()


def _elapsed_seconds(job: dict[str, Any]) -> float:
    started = job.setdefault("_started_monotonic", time.monotonic())
    completed_at = job.get("completed_at")
    if completed_at:
        return round(float(job.get("elapsed_seconds") or 0.0), 2)
    return round(time.monotonic() - started, 2)


def _clamp_progress(value: float) -> float:
    return round(max(0.0, min(100.0, float(value))), 1)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mark_interrupted_after_restart(job: dict[str, Any]) -> None:
    now = _utc_now()
    job.update(
        {
            "status": "failed",
            "phase": "interrupted",
            "phase_label": "Render interrupted",
            "message": "Rendering stopped because the backend restarted before the job finished.",
            "cancel_requested": False,
            "error": "Render interrupted by backend restart",
            "completed_at": now,
            "updated_at": now,
        }
    )


def _save_render_jobs_to_store() -> None:
    try:
        _render_job_store_path.parent.mkdir(parents=True, exist_ok=True)
        serializable_jobs = {
            job_id: {
                key: value
                for key, value in job.items()
                if key != "_started_monotonic"
            }
            for job_id, job in _render_jobs_by_id.items()
        }
        payload = {
            "schema_version": "phase9.render-jobs.v1",
            "jobs": serializable_jobs,
            "active_job_id_by_video_id": dict(_active_job_id_by_video_id),
            "updated_at": _utc_now(),
        }
        temp_path = _render_job_store_path.with_suffix(_render_job_store_path.suffix + ".tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
        os.replace(temp_path, _render_job_store_path)
    except OSError as exc:
        logger.warning("Could not save render job store %s: %s", _render_job_store_path, exc)


load_render_jobs_from_store()
