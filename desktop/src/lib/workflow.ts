import type { Project, ProjectReadiness, ProjectStatus, Video, VideoStatus, WorkflowState } from "../types/api";

export const WORKFLOW_LABELS: Record<WorkflowState, string> = {
  source_required: "Add a source",
  validating: "Checking source",
  ready_for_analysis: "Ready for analysis",
  analyzing: "Analyzing",
  review_suggestions: "Review suggestions",
  editing: "Editing",
  export_ready: "Ready to export",
  exporting: "Exporting",
  completed: "Completed",
  failed: "Needs attention",
  cancelled: "Cancelled",
};

const VIDEO_STATE_MAP: Record<VideoStatus, WorkflowState> = {
  uploaded: "ready_for_analysis",
  processing: "analyzing",
  transcribing: "analyzing",
  analyzing: "analyzing",
  planning: "analyzing",
  awaiting_review: "review_suggestions",
  rendering: "exporting",
  completed: "completed",
  failed: "failed",
};

const PROJECT_STATE_MAP: Record<ProjectStatus, WorkflowState> = {
  draft: "source_required",
  importing: "validating",
  ready: "ready_for_analysis",
  processing: "analyzing",
  awaiting_review: "review_suggestions",
  completed: "completed",
  archived: "completed",
  failed: "failed",
};

export function legacyToWorkflowState(
  project: Project | Pick<Project, "status">,
  video?: Pick<Video, "status"> | null,
  readiness?: Pick<ProjectReadiness, "workflow_state" | "source"> | null,
): WorkflowState {
  if (readiness?.workflow_state) return readiness.workflow_state;
  if (readiness && !readiness.source.path_available) return "source_required";
  if (video) return VIDEO_STATE_MAP[video.status] ?? "failed";
  return PROJECT_STATE_MAP[project.status] ?? "source_required";
}

export function workflowLabel(state: WorkflowState): string {
  return WORKFLOW_LABELS[state] ?? "Needs attention";
}

export function workflowNextAction(state: WorkflowState): string {
  switch (state) {
    case "source_required": return "Import a primary video";
    case "ready_for_analysis": return "Start analysis";
    case "analyzing": return "View processing";
    case "review_suggestions": return "Review suggestions";
    case "editing":
    case "export_ready": return "Open export";
    case "exporting": return "View export progress";
    case "completed": return "Continue editing";
    case "failed": return "Repair or retry";
    case "cancelled": return "Resume when ready";
    default: return "Open project";
  }
}

export function isWorkflowActive(state: WorkflowState): boolean {
  return state === "validating" || state === "analyzing" || state === "exporting";
}

export function workflowProgress(video: Pick<Video, "status"> | null, progress?: number): number | null {
  if (typeof progress === "number" && Number.isFinite(progress)) return Math.max(0, Math.min(100, progress));
  if (!video) return null;
  if (video.status === "completed" || video.status === "awaiting_review") return 100;
  if (video.status === "uploaded") return 0;
  return null;
}
