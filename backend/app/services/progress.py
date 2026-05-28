"""
Pipeline Progress Tracker — tracks per-step processing status.

The desktop app polls GET /api/v1/videos/{id}/status to see
which step is currently executing, timing for each completed step,
and any errors encountered along the way.

Uses a combination of:
  - In-memory dict (fast reads during active processing)
  - Video.status DB field (durable state that survives restarts)
"""

import time
import logging
from typing import Optional, Dict
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# In-memory progress store (keyed by video_id)
_progress: Dict[str, dict] = {}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class PipelineStep:
    """Constants for pipeline step names."""
    QUEUED = "queued"
    EXTRACTING_AUDIO = "extracting_audio"
    TRANSCRIBING = "transcribing"
    EMBEDDING_TRANSCRIPT = "embedding_transcript"
    ANALYZING_CONTENT = "analyzing_content"
    ANALYZING_FLUENCY = "analyzing_fluency"
    ANALYZING_VISUAL = "analyzing_visual"
    PLANNING_EDITS = "planning_edits"
    AWAITING_REVIEW = "awaiting_review"
    RENDERING = "rendering"
    COMPLETED = "completed"
    FAILED = "failed"

    # Ordered list for progress percentage calculation
    ALL_STEPS = [
        QUEUED,
        EXTRACTING_AUDIO,
        TRANSCRIBING,
        EMBEDDING_TRANSCRIPT,
        ANALYZING_CONTENT,
        ANALYZING_FLUENCY,   # runs parallel with visual
        ANALYZING_VISUAL,    # runs parallel with fluency
        PLANNING_EDITS,
        AWAITING_REVIEW,
    ]

    # Human-readable labels for the desktop app
    LABELS = {
        QUEUED: "Queued for processing",
        EXTRACTING_AUDIO: "Extracting audio from video...",
        TRANSCRIBING: "Transcribing speech to text (Voxtral)...",
        EMBEDDING_TRANSCRIPT: "Building knowledge base from transcript...",
        ANALYZING_CONTENT: "Analyzing educational content (Agent 2)...",
        ANALYZING_FLUENCY: "Detecting filler words and pauses (Agent 3)...",
        ANALYZING_VISUAL: "Detecting slide changes (Agent 4)...",
        PLANNING_EDITS: "Generating edit plan (Agent 5)...",
        AWAITING_REVIEW: "Ready for teacher review",
        RENDERING: "Rendering final video...",
        COMPLETED: "Complete!",
        FAILED: "Processing failed",
    }


def init_progress(video_id: str):
    """Initialize progress tracking for a new pipeline run."""
    _progress[video_id] = {
        "video_id": video_id,
        "current_step": PipelineStep.QUEUED,
        "steps_completed": [],
        "steps_timing": {},
        "started_at": _utc_now_iso(),
        "error": None,
        "_step_start_time": None,
    }
    logger.info(f"Pipeline progress initialized for {video_id}")


def start_step(video_id: str, step: str):
    """Mark a step as started."""
    prog = _progress.get(video_id)
    if not prog:
        init_progress(video_id)
        prog = _progress[video_id]

    prog["current_step"] = step
    prog["_step_start_time"] = time.time()
    logger.info(f"Pipeline [{video_id[:8]}...] → {PipelineStep.LABELS.get(step, step)}")


def complete_step(video_id: str, step: str, result: Optional[dict] = None):
    """Mark a step as completed with timing."""
    prog = _progress.get(video_id)
    if not prog:
        return

    elapsed = 0.0
    if prog.get("_step_start_time"):
        elapsed = round(time.time() - prog["_step_start_time"], 2)

    prog["steps_completed"].append(step)
    prog["steps_timing"][step] = {
        "elapsed_seconds": elapsed,
        "completed_at": _utc_now_iso(),
    }

    # Attach key metrics from result if available
    if result and isinstance(result, dict):
        summary = {}
        for key in ["word_count", "segment_count", "segments_analyzed",
                     "total_fillers", "scenes_detected", "segments_keep",
                     "segments_cut", "time_saved_seconds", "provider"]:
            if key in result:
                summary[key] = result[key]
        if summary:
            prog["steps_timing"][step]["summary"] = summary

    logger.info(f"Pipeline [{video_id[:8]}...] ✓ {step} ({elapsed:.1f}s)")


def fail_step(video_id: str, step: str, error: str):
    """Mark a step as failed."""
    prog = _progress.get(video_id)
    if not prog:
        return

    prog["current_step"] = PipelineStep.FAILED
    prog["error"] = f"[{step}] {error}"
    logger.error(f"Pipeline [{video_id[:8]}...] ✗ {step}: {error}")


def get_progress(video_id: str) -> dict:
    """
    Get current progress for a video.

    Returns a clean dict suitable for the desktop app:
    {
        "video_id": "...",
        "current_step": "analyzing_content",
        "current_step_label": "Analyzing educational content (Agent 2)...",
        "progress_percent": 55.0,
        "steps_completed": ["queued", "extracting_audio", "transcribing", ...],
        "steps_timing": { "transcribing": {"elapsed_seconds": 12.5}, ... },
        "total_elapsed_seconds": 45.2,
        "error": null
    }
    """
    prog = _progress.get(video_id)
    if not prog:
        return {
            "video_id": video_id,
            "current_step": "unknown",
            "current_step_label": "No active processing",
            "progress_percent": 0.0,
            "steps_completed": [],
            "steps_timing": {},
            "total_elapsed_seconds": 0,
            "error": None,
        }

    # Calculate progress percentage
    completed_count = len(prog.get("steps_completed", []))
    total_steps = len(PipelineStep.ALL_STEPS)
    progress_pct = round(min(completed_count / max(total_steps, 1) * 100, 100), 1)

    # Calculate total elapsed
    total_elapsed = sum(
        t.get("elapsed_seconds", 0) for t in prog.get("steps_timing", {}).values()
    )

    current = prog.get("current_step", "unknown")

    return {
        "video_id": video_id,
        "current_step": current,
        "current_step_label": PipelineStep.LABELS.get(current, current),
        "progress_percent": progress_pct,
        "steps_completed": prog.get("steps_completed", []),
        "steps_timing": {
            k: {sk: sv for sk, sv in v.items() if not sk.startswith("_")}
            for k, v in prog.get("steps_timing", {}).items()
        },
        "total_elapsed_seconds": round(total_elapsed, 2),
        "started_at": prog.get("started_at"),
        "error": prog.get("error"),
    }


def cleanup_progress(video_id: str):
    """Remove progress data after pipeline completes (free memory)."""
    _progress.pop(video_id, None)
