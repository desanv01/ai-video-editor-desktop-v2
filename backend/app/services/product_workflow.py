"""Shared product workflow and job vocabulary for Docker and native modes.

The database keeps the original Phase 0-7 status values because those values
are part of the persisted compatibility contract.  This module is the small
translation layer used by API responses and the desktop client so new UI work
does not need to know which legacy status produced a state.
"""

from __future__ import annotations

from enum import Enum
from typing import Any


class WorkflowState(str, Enum):
    SOURCE_REQUIRED = "source_required"
    VALIDATING = "validating"
    READY_FOR_ANALYSIS = "ready_for_analysis"
    ANALYZING = "analyzing"
    REVIEW_SUGGESTIONS = "review_suggestions"
    EDITING = "editing"
    EXPORT_READY = "export_ready"
    EXPORTING = "exporting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


WORKFLOW_LABELS: dict[WorkflowState, str] = {
    WorkflowState.SOURCE_REQUIRED: "Add a source",
    WorkflowState.VALIDATING: "Checking source",
    WorkflowState.READY_FOR_ANALYSIS: "Ready for analysis",
    WorkflowState.ANALYZING: "Analyzing",
    WorkflowState.REVIEW_SUGGESTIONS: "Review suggestions",
    WorkflowState.EDITING: "Editing",
    WorkflowState.EXPORT_READY: "Ready to export",
    WorkflowState.EXPORTING: "Exporting",
    WorkflowState.COMPLETED: "Completed",
    WorkflowState.FAILED: "Needs attention",
    WorkflowState.CANCELLED: "Cancelled",
}


LEGACY_VIDEO_STATE_MAP: dict[str, WorkflowState] = {
    "uploaded": WorkflowState.READY_FOR_ANALYSIS,
    "processing": WorkflowState.ANALYZING,
    "transcribing": WorkflowState.ANALYZING,
    "analyzing": WorkflowState.ANALYZING,
    "planning": WorkflowState.ANALYZING,
    "awaiting_review": WorkflowState.REVIEW_SUGGESTIONS,
    "rendering": WorkflowState.EXPORTING,
    "completed": WorkflowState.COMPLETED,
    "failed": WorkflowState.FAILED,
}

LEGACY_PROJECT_STATE_MAP: dict[str, WorkflowState] = {
    "draft": WorkflowState.SOURCE_REQUIRED,
    "importing": WorkflowState.VALIDATING,
    "ready": WorkflowState.READY_FOR_ANALYSIS,
    "processing": WorkflowState.ANALYZING,
    "awaiting_review": WorkflowState.REVIEW_SUGGESTIONS,
    "completed": WorkflowState.COMPLETED,
    "archived": WorkflowState.COMPLETED,
    "failed": WorkflowState.FAILED,
}


ACTIVE_WORKFLOW_STATES = frozenset(
    {
        WorkflowState.VALIDATING,
        WorkflowState.ANALYZING,
        WorkflowState.EXPORTING,
    }
)

TERMINAL_WORKFLOW_STATES = frozenset(
    {
        WorkflowState.COMPLETED,
        WorkflowState.FAILED,
        WorkflowState.CANCELLED,
    }
)


_ALLOWED_TRANSITIONS: dict[WorkflowState, frozenset[WorkflowState]] = {
    WorkflowState.SOURCE_REQUIRED: frozenset(
        {WorkflowState.VALIDATING, WorkflowState.READY_FOR_ANALYSIS}
    ),
    WorkflowState.VALIDATING: frozenset(
        {WorkflowState.READY_FOR_ANALYSIS, WorkflowState.FAILED, WorkflowState.CANCELLED}
    ),
    WorkflowState.READY_FOR_ANALYSIS: frozenset(
        {WorkflowState.ANALYZING, WorkflowState.EDITING, WorkflowState.FAILED}
    ),
    WorkflowState.ANALYZING: frozenset(
        {
            WorkflowState.REVIEW_SUGGESTIONS,
            WorkflowState.FAILED,
            WorkflowState.CANCELLED,
        }
    ),
    WorkflowState.REVIEW_SUGGESTIONS: frozenset(
        {WorkflowState.EDITING, WorkflowState.EXPORT_READY, WorkflowState.FAILED}
    ),
    WorkflowState.EDITING: frozenset(
        {WorkflowState.EDITING, WorkflowState.EXPORT_READY, WorkflowState.FAILED}
    ),
    WorkflowState.EXPORT_READY: frozenset(
        {WorkflowState.EXPORTING, WorkflowState.EDITING, WorkflowState.FAILED}
    ),
    WorkflowState.EXPORTING: frozenset(
        {WorkflowState.COMPLETED, WorkflowState.FAILED, WorkflowState.CANCELLED}
    ),
    WorkflowState.COMPLETED: frozenset(
        {WorkflowState.EDITING, WorkflowState.EXPORTING}
    ),
    WorkflowState.FAILED: frozenset(
        {
            WorkflowState.SOURCE_REQUIRED,
            WorkflowState.READY_FOR_ANALYSIS,
            WorkflowState.ANALYZING,
            WorkflowState.EDITING,
            WorkflowState.EXPORT_READY,
            WorkflowState.EXPORTING,
        }
    ),
    WorkflowState.CANCELLED: frozenset(
        {WorkflowState.SOURCE_REQUIRED, WorkflowState.READY_FOR_ANALYSIS, WorkflowState.ANALYZING, WorkflowState.EXPORT_READY}
    ),
}


def workflow_label(state: WorkflowState | str) -> str:
    normalized = coerce_workflow_state(state)
    return WORKFLOW_LABELS[normalized]


def coerce_workflow_state(value: WorkflowState | str) -> WorkflowState:
    if isinstance(value, WorkflowState):
        return value
    try:
        return WorkflowState(str(value))
    except ValueError:
        return WorkflowState.FAILED


def map_legacy_status(
    *,
    video_status: str | None = None,
    project_status: str | None = None,
    has_source: bool = True,
    has_edit_plan: bool = False,
    has_render_output: bool = False,
) -> WorkflowState:
    """Map persisted statuses to one product state.

    A source-less draft always wins over a stale project ``ready`` value.  A
    completed render with an existing output is still ``completed`` even when
    the parent project has not yet caught up.
    """

    if not has_source:
        return WorkflowState.SOURCE_REQUIRED

    normalized_video = str(getattr(video_status, "value", video_status or ""))
    if normalized_video:
        state = LEGACY_VIDEO_STATE_MAP.get(normalized_video)
        if state is not None:
            if state == WorkflowState.READY_FOR_ANALYSIS and has_edit_plan:
                return WorkflowState.EDITING
            if state == WorkflowState.COMPLETED and not has_render_output and has_edit_plan:
                return WorkflowState.EXPORT_READY
            return state

    normalized_project = str(getattr(project_status, "value", project_status or ""))
    return LEGACY_PROJECT_STATE_MAP.get(
        normalized_project,
        WorkflowState.READY_FOR_ANALYSIS,
    )


def transition_allowed(current: WorkflowState | str, target: WorkflowState | str) -> bool:
    current_state = coerce_workflow_state(current)
    target_state = coerce_workflow_state(target)
    if current_state == target_state:
        return True
    return target_state in _ALLOWED_TRANSITIONS.get(current_state, frozenset())


def validate_transition(current: WorkflowState | str, target: WorkflowState | str) -> None:
    if not transition_allowed(current, target):
        raise ValueError(
            f"Invalid workflow transition: {coerce_workflow_state(current).value} "
            f"-> {coerce_workflow_state(target).value}"
        )


def workflow_descriptor(
    state: WorkflowState | str,
    *,
    progress_percent: float = 0.0,
    stage: str | None = None,
    message: str | None = None,
    required_actions: list[str] | None = None,
) -> dict[str, Any]:
    normalized = coerce_workflow_state(state)
    return {
        "state": normalized.value,
        "label": workflow_label(normalized),
        "progress_percent": max(0.0, min(100.0, float(progress_percent))),
        "stage": stage or normalized.value,
        "message": message or workflow_label(normalized),
        "required_actions": list(required_actions or []),
    }
