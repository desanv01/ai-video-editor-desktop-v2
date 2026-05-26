"""
In-memory render job tracker.

Rendering is still driven by FastAPI background tasks and durable Video.status,
but this module keeps the live progress/error/cancel state that the desktop UI
can poll while FFmpeg work is active.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)


TERMINAL_RENDER_JOB_STATUSES = {"completed", "failed", "cancelled"}
ACTIVE_RENDER_JOB_STATUSES = {"queued", "running", "cancel_requested"}

_render_jobs_by_id: dict[str, dict[str, Any]] = {}
_active_job_id_by_video_id: dict[str, str] = {}


class RenderCancelled(RuntimeError):
    """Raised when a user-requested cancellation is observed between render phases."""


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
        message="Cancellation requested. The current FFmpeg operation will finish before the render stops.",
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


def _elapsed_seconds(job: dict[str, Any]) -> float:
    started = job.setdefault("_started_monotonic", time.monotonic())
    completed_at = job.get("completed_at")
    if completed_at:
        return round(float(job.get("elapsed_seconds") or 0.0), 2)
    return round(time.monotonic() - started, 2)


def _clamp_progress(value: float) -> float:
    return round(max(0.0, min(100.0, float(value))), 1)


def _utc_now() -> str:
    return datetime.utcnow().isoformat()
