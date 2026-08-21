"""Compatibility adapter for native SQLite jobs and Docker render jobs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services.error_normalization import normalize_error
from services.product_workflow import WorkflowState, map_legacy_status


ACTIVE_JOB_STATES = frozenset({"queued", "running", "cancel_requested"})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _job_state(status: str | None) -> str:
    normalized = str(status or "unknown")
    if normalized == "interrupted":
        return "failed"
    return normalized


def normalize_job(
    job: dict[str, Any] | None,
    *,
    job_type: str | None = None,
    video_id: str | None = None,
) -> dict[str, Any] | None:
    """Return the stable Phase 8 job shape while preserving legacy fields."""

    if not job:
        return None
    status = _job_state(str(job.get("state") or job.get("status") or "unknown"))
    error = job.get("error") or job.get("message") if status == "failed" else job.get("error")
    normalized_error = normalize_error(error) if error else None
    state = status
    payload = job.get("payload") if isinstance(job.get("payload"), dict) else {}
    progress = job.get("progress_percent")
    if progress is None:
        progress = payload.get("progress_percent", payload.get("progress", 0.0))
    stage = job.get("phase") or job.get("stage") or payload.get("stage") or status
    message = job.get("message") or payload.get("message") or stage.replace("_", " ").title()
    created_at = job.get("created_at") or job.get("started_at") or _now()
    updated_at = job.get("updated_at") or created_at
    completed_at = job.get("completed_at") or job.get("finished_at")
    result = {
        **job,
        "job_id": str(job.get("job_id") or job.get("id") or ""),
        "type": str(job.get("type") or job.get("kind") or job_type or "workflow"),
        "state": state,
        "status": str(job.get("status") or state),
        "progress_percent": max(0.0, min(100.0, float(progress or 0.0))),
        "stage": str(stage),
        "message": str(message),
        "created_at": created_at,
        "updated_at": updated_at,
        "started_at": job.get("started_at") or created_at,
        "completed_at": completed_at,
        "cancellable": bool(job.get("cancellable", status in ACTIVE_JOB_STATES)),
        "retryable": bool(job.get("retryable", status in {"failed", "cancelled", "interrupted"})),
        "error_code": normalized_error.code if normalized_error else job.get("error_code"),
        "error": normalized_error.message if normalized_error else error,
        "remediation": normalized_error.remediation if normalized_error else job.get("remediation"),
        "video_id": str(job.get("video_id") or video_id) if (job.get("video_id") or video_id) else None,
    }
    return result


def pipeline_job(
    video_id: str,
    *,
    legacy_status: str,
    progress: dict[str, Any] | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    progress = progress or {}
    workflow_state = map_legacy_status(video_status=legacy_status, has_source=True).value
    status = "failed" if legacy_status == "failed" else (
        "completed" if legacy_status in {"awaiting_review", "completed"} else "running"
    )
    if legacy_status == "uploaded":
        status = "queued"
    if legacy_status == "awaiting_review":
        status = "completed"
    job = {
        "job_id": f"analysis:{video_id}",
        "type": "analysis",
        "status": status,
        "state": status,
        "video_id": str(video_id),
        "progress_percent": progress.get("progress_percent", 0.0),
        "stage": progress.get("current_step", legacy_status),
        "message": progress.get("current_step_label") or "Analysis is ready for the next step.",
        "started_at": progress.get("started_at"),
        "updated_at": _now(),
        "completed_at": None,
        "cancellable": False,
        "retryable": legacy_status in {"failed", "uploaded"},
        "error_code": None,
        "error": error or progress.get("error"),
        "remediation": None,
        "workflow_state": workflow_state,
    }
    return normalize_job(job, job_type="analysis", video_id=video_id) or job


def native_job(job: dict[str, Any] | None) -> dict[str, Any] | None:
    return normalize_job(job, job_type=(job or {}).get("kind"))


def render_job(job: dict[str, Any] | None) -> dict[str, Any] | None:
    return normalize_job(job, job_type="export")
