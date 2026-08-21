import type { Project, ProjectStatus, Video } from "../types/api";
import { legacyToWorkflowState } from "./workflow.ts";

export type DashboardSort = "updated" | "created" | "title";

export function filterAndSortProjects(
  projects: Project[],
  videosByProject: Map<string, Video[]>,
  query: string,
  status: "all" | ProjectStatus,
  sort: DashboardSort,
): Project[] {
  const needle = query.trim().toLowerCase();
  return [...projects]
    .filter(project => {
      const video = videosByProject.get(project.id)?.[0] ?? null;
      const state = legacyToWorkflowState(project, video);
      const matchesQuery = !needle || `${project.title} ${project.description ?? ""} ${project.project_type ?? ""} ${state}`.toLowerCase().includes(needle);
      const effectiveStatus = video?.status === "awaiting_review"
        ? "awaiting_review"
        : video?.status === "completed"
          ? "completed"
          : video?.status === "failed"
            ? "failed"
            : video?.status === "rendering" || ["processing", "transcribing", "analyzing", "planning"].includes(video?.status ?? "")
              ? "processing"
              : project.status;
      const matchesStatus = status === "all" || effectiveStatus === status;
      return matchesQuery && matchesStatus;
    })
    .sort((left, right) => {
      if (sort === "title") return left.title.localeCompare(right.title);
      const leftValue = sort === "created" ? left.created_at : left.updated_at;
      const rightValue = sort === "created" ? right.created_at : right.updated_at;
      return rightValue.localeCompare(leftValue);
    });
}
