import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertCircle,
  ArrowRight,
  CalendarClock,
  CheckCircle2,
  CircleDashed,
  Clock3,
  FileVideo,
  FolderOpen,
  LayoutDashboard,
  Loader2,
  MonitorPlay,
  Plus,
  RefreshCcw,
  Search,
  Settings2,
  Sparkles,
} from "lucide-react";
import * as api from "../lib/api";
import type { Project, ProjectCreateRequest, ProjectSourceMode, ProjectStatus, Video } from "../types/api";

type ContinueTarget = {
  project: Project;
  video: Video | null;
  nextView: "upload" | "processing" | "review";
};

interface Props {
  onContinue: (target: ContinueTarget) => void;
}

type ProjectTypeOption = {
  value: string;
  label: string;
  description: string;
};

const PROJECT_TYPES: ProjectTypeOption[] = [
  { value: "lecture", label: "Lecture", description: "Single class recording or seminar" },
  { value: "mooc", label: "MOOC", description: "Structured online course lesson" },
  { value: "tutorial", label: "Tutorial", description: "Screen-led walkthrough" },
  { value: "workshop", label: "Workshop", description: "Long-form practical session" },
];

const STATUS_META: Record<ProjectStatus, { label: string; className: string; icon: typeof CircleDashed }> = {
  draft: { label: "Draft", className: "border-gray-500/40 bg-gray-500/10 text-gray-300", icon: CircleDashed },
  importing: { label: "Importing", className: "border-sky-400/40 bg-sky-500/10 text-sky-200", icon: Loader2 },
  ready: { label: "Ready", className: "border-emerald-400/40 bg-emerald-500/10 text-emerald-200", icon: CheckCircle2 },
  processing: { label: "Processing", className: "border-sky-400/40 bg-sky-500/10 text-sky-200", icon: Loader2 },
  awaiting_review: { label: "Review", className: "border-amber-400/40 bg-amber-500/10 text-amber-200", icon: Sparkles },
  completed: { label: "Done", className: "border-emerald-400/40 bg-emerald-500/10 text-emerald-200", icon: CheckCircle2 },
  archived: { label: "Archived", className: "border-gray-500/40 bg-gray-500/10 text-gray-400", icon: FolderOpen },
  failed: { label: "Failed", className: "border-red-400/40 bg-red-500/10 text-red-200", icon: AlertCircle },
};

const BUSY_VIDEO_STATUSES = new Set(["processing", "transcribing", "analyzing", "planning", "rendering"]);

export function ProjectDashboard({ onContinue }: Props) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [videos, setVideos] = useState<Video[]>([]);
  const [loading, setLoading] = useState(true);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [newProject, setNewProject] = useState<ProjectCreateRequest>({
    title: "",
    description: "",
    source_mode: "single_video",
    project_type: "lecture",
    metadata: { dashboard_created: true },
  });

  const loadDashboard = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [projectList, videoList] = await Promise.all([
        api.listProjects(),
        api.listVideos(),
      ]);
      setProjects(projectList);
      setVideos(videoList);
    } catch (err) {
      setError(String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadDashboard();
  }, [loadDashboard]);

  const videosByProject = useMemo(() => {
    const grouped = new Map<string, Video[]>();
    videos.forEach((video) => {
      if (!video.project_id) return;
      const list = grouped.get(video.project_id) ?? [];
      list.push(video);
      grouped.set(video.project_id, list);
    });
    return grouped;
  }, [videos]);

  const filteredProjects = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (!needle) return projects;
    return projects.filter((project) => {
      const projectType = project.project_type ?? "";
      return `${project.title} ${project.description ?? ""} ${projectType}`.toLowerCase().includes(needle);
    });
  }, [projects, query]);

  const recentProjects = projects.slice(0, 4);
  const activeProjectCount = projects.filter((project) => {
    const status = effectiveProjectStatus(project, videosByProject.get(project.id)?.[0] ?? null);
    return status !== "archived" && status !== "completed";
  }).length;
  const reviewProjectCount = projects.filter((project) => {
    const status = effectiveProjectStatus(project, videosByProject.get(project.id)?.[0] ?? null);
    return status === "awaiting_review";
  }).length;
  const multiSourceCount = projects.filter(project => project.source_mode === "multi_source").length;

  const handleCreateProject = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const title = newProject.title.trim();
    if (!title) return;

    setCreating(true);
    setError(null);
    try {
      const created = await api.createProject({
        ...newProject,
        title,
        description: newProject.description?.trim() || null,
      });
      setProjects(prev => [created, ...prev]);
      setNewProject(prev => ({ ...prev, title: "", description: "" }));
      onContinue({ project: created, video: null, nextView: "upload" });
    } catch (err) {
      setError(String(err));
    } finally {
      setCreating(false);
    }
  };

  const continueProject = (project: Project) => {
    const linkedVideo = videosByProject.get(project.id)?.[0] ?? null;
    if (!linkedVideo) {
      onContinue({ project, video: null, nextView: "upload" });
      return;
    }

    if (linkedVideo.status === "awaiting_review" || linkedVideo.status === "completed") {
      onContinue({ project, video: linkedVideo, nextView: "review" });
      return;
    }

    if (BUSY_VIDEO_STATUSES.has(linkedVideo.status)) {
      onContinue({ project, video: linkedVideo, nextView: "processing" });
      return;
    }

    onContinue({ project, video: linkedVideo, nextView: "upload" });
  };

  return (
    <div className="h-full overflow-hidden bg-surface text-gray-100">
      <div className="grid h-full grid-cols-[minmax(0,1fr)_340px] overflow-hidden">
        <section className="flex min-w-0 flex-col overflow-hidden border-r border-surface-border">
          <div className="border-b border-surface-border px-6 py-5">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-2 text-xs font-medium uppercase tracking-wide text-gray-500">
                  <LayoutDashboard className="h-3.5 w-3.5" />
                  Project Dashboard
                </div>
                <h2 className="mt-2 text-2xl font-semibold tracking-normal text-white">Editing workspaces</h2>
              </div>
              <button
                type="button"
                onClick={() => void loadDashboard()}
                disabled={loading}
                className="inline-flex items-center gap-2 rounded-md border border-surface-border px-3 py-2 text-sm text-gray-300 transition-colors hover:border-gray-500 hover:text-white disabled:cursor-not-allowed disabled:opacity-60"
              >
                {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCcw className="h-4 w-4" />}
                Refresh
              </button>
            </div>

            <div className="mt-5 grid grid-cols-3 gap-3">
              <MetricTile label="Active" value={activeProjectCount} accent="text-sky-200" />
              <MetricTile label="Ready to review" value={reviewProjectCount} accent="text-amber-200" />
              <MetricTile label="Multi-source" value={multiSourceCount} accent="text-emerald-200" />
            </div>
          </div>

          <div className="flex items-center gap-3 border-b border-surface-border px-6 py-3">
            <div className="relative min-w-0 flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-500" />
              <input
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Search projects"
                className="h-10 w-full rounded-md border border-surface-border bg-surface-raised pl-9 pr-3 text-sm text-gray-100 outline-none transition-colors placeholder:text-gray-600 focus:border-accent"
              />
            </div>
          </div>

          {error ? (
            <div className="mx-6 mt-4 flex items-start gap-3 rounded-md border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-200">
              <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
              <span>{error}</span>
            </div>
          ) : null}

          <div className="min-h-0 flex-1 overflow-auto">
            {loading ? (
              <div className="flex h-full items-center justify-center text-sm text-gray-400">
                <Loader2 className="mr-2 h-4 w-4 animate-spin text-accent" />
                Loading projects
              </div>
            ) : filteredProjects.length === 0 ? (
              <EmptyProjectState hasQuery={Boolean(query.trim())} />
            ) : (
              <div className="divide-y divide-surface-border">
                {filteredProjects.map((project) => {
                  const linkedVideo = videosByProject.get(project.id)?.[0] ?? null;
                  return (
                    <ProjectRow
                      key={project.id}
                      project={project}
                      video={linkedVideo}
                      onContinue={() => continueProject(project)}
                    />
                  );
                })}
              </div>
            )}
          </div>
        </section>

        <aside className="flex min-h-0 flex-col overflow-hidden bg-surface-raised">
          <form onSubmit={handleCreateProject} className="border-b border-surface-border p-5">
            <div className="mb-4 flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold text-white">Create Project</h3>
                <p className="mt-1 text-xs text-gray-500">Set the workspace type before importing sources.</p>
              </div>
              <Plus className="h-4 w-4 text-accent" />
            </div>

            <div className="space-y-3">
              <label className="block">
                <span className="mb-1 block text-xs font-medium text-gray-400">Project title</span>
                <input
                  value={newProject.title}
                  onChange={(event) => setNewProject(prev => ({ ...prev, title: event.target.value }))}
                  placeholder="Week 4: Binary Trees"
                  className="h-10 w-full rounded-md border border-surface-border bg-surface px-3 text-sm text-gray-100 outline-none transition-colors placeholder:text-gray-600 focus:border-accent"
                />
              </label>

              <label className="block">
                <span className="mb-1 block text-xs font-medium text-gray-400">Description</span>
                <textarea
                  value={newProject.description ?? ""}
                  onChange={(event) => setNewProject(prev => ({ ...prev, description: event.target.value }))}
                  placeholder="Optional editing notes"
                  rows={3}
                  className="w-full resize-none rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-gray-100 outline-none transition-colors placeholder:text-gray-600 focus:border-accent"
                />
              </label>

              <div>
                <span className="mb-2 block text-xs font-medium text-gray-400">Project type</span>
                <div className="grid grid-cols-2 gap-2">
                  {PROJECT_TYPES.map((type) => (
                    <button
                      key={type.value}
                      type="button"
                      onClick={() => setNewProject(prev => ({ ...prev, project_type: type.value }))}
                      className={`rounded-md border p-3 text-left transition-colors ${
                        newProject.project_type === type.value
                          ? "border-accent bg-accent/10 text-white"
                          : "border-surface-border bg-surface text-gray-300 hover:border-gray-500"
                      }`}
                    >
                      <span className="block text-sm font-medium">{type.label}</span>
                      <span className="mt-1 block text-xs leading-4 text-gray-500">{type.description}</span>
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <span className="mb-2 block text-xs font-medium text-gray-400">Source setup</span>
                <div className="grid grid-cols-2 gap-2">
                  <SourceModeButton
                    active={newProject.source_mode === "single_video"}
                    icon={FileVideo}
                    label="Single video"
                    onClick={() => setNewProject(prev => ({ ...prev, source_mode: "single_video" }))}
                  />
                  <SourceModeButton
                    active={newProject.source_mode === "multi_source"}
                    icon={MonitorPlay}
                    label="Multi-source"
                    onClick={() => setNewProject(prev => ({ ...prev, source_mode: "multi_source" }))}
                  />
                </div>
              </div>

              <button
                type="submit"
                disabled={!newProject.title.trim() || creating}
                className="inline-flex h-10 w-full items-center justify-center gap-2 rounded-md bg-accent px-3 text-sm font-medium text-white transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-50"
              >
                {creating ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus className="h-4 w-4" />}
                Create and Open
              </button>
            </div>
          </form>

          <div className="min-h-0 flex-1 overflow-auto p-5">
            <div className="mb-3 flex items-center gap-2 text-sm font-semibold text-white">
              <Clock3 className="h-4 w-4 text-gray-400" />
              Recent Projects
            </div>
            <div className="space-y-2">
              {recentProjects.length === 0 ? (
                <p className="rounded-md border border-dashed border-surface-border p-4 text-sm text-gray-500">
                  Recent workspaces will appear here after a project is created or a legacy video is uploaded.
                </p>
              ) : (
                recentProjects.map((project) => (
                  <button
                    key={project.id}
                    type="button"
                    onClick={() => continueProject(project)}
                    className="w-full rounded-md border border-surface-border bg-surface p-3 text-left transition-colors hover:border-gray-500"
                  >
                    <div className="flex items-center justify-between gap-3">
                      <span className="min-w-0 truncate text-sm font-medium text-gray-100">{project.title}</span>
                      <ProjectStatusPill status={effectiveProjectStatus(project, videosByProject.get(project.id)?.[0] ?? null)} />
                    </div>
                    <div className="mt-2 flex items-center gap-2 text-xs text-gray-500">
                      <CalendarClock className="h-3.5 w-3.5" />
                      {formatRelativeDate(project.updated_at)}
                    </div>
                  </button>
                ))
              )}
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}

function MetricTile({ label, value, accent }: { label: string; value: number; accent: string }) {
  return (
    <div className="rounded-md border border-surface-border bg-surface-raised px-4 py-3">
      <div className={`text-2xl font-semibold ${accent}`}>{value}</div>
      <div className="mt-1 text-xs text-gray-500">{label}</div>
    </div>
  );
}

function ProjectRow({ project, video, onContinue }: { project: Project; video: Video | null; onContinue: () => void }) {
  const actionLabel = getContinueLabel(project, video);
  const detail = video ? `${video.original_filename} / ${formatVideoStatus(video.status)}` : "Workspace setup";
  const displayStatus = effectiveProjectStatus(project, video);

  return (
    <div className="grid grid-cols-[minmax(220px,1fr)_130px_140px_150px] items-center gap-4 px-6 py-4 transition-colors hover:bg-surface-raised/70">
      <div className="min-w-0">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-surface-raised text-gray-400">
            <FolderOpen className="h-4 w-4" />
          </div>
          <div className="min-w-0">
            <h3 className="truncate text-sm font-semibold text-white">{project.title}</h3>
            <p className="mt-1 truncate text-xs text-gray-500">{project.description || detail}</p>
          </div>
        </div>
      </div>

      <div>
        <ProjectStatusPill status={displayStatus} />
      </div>

      <div className="min-w-0 text-xs">
        <div className="capitalize text-gray-300">{formatProjectType(project.project_type)}</div>
        <div className="mt-1 text-gray-500">{formatSourceMode(project.source_mode)}</div>
      </div>

      <div className="flex items-center justify-end gap-3">
        <div className="hidden text-right text-xs text-gray-500 xl:block">
          <div>Updated</div>
          <div className="mt-1 text-gray-400">{formatRelativeDate(project.updated_at)}</div>
        </div>
        <button
          type="button"
          onClick={onContinue}
          className="inline-flex h-9 items-center gap-2 rounded-md border border-surface-border px-3 text-sm text-gray-200 transition-colors hover:border-accent hover:text-white"
        >
          {actionLabel}
          <ArrowRight className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}

function ProjectStatusPill({ status }: { status: ProjectStatus }) {
  const meta = STATUS_META[status];
  const Icon = meta.icon;
  const spin = status === "importing" || status === "processing";
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border px-2 py-1 text-xs font-medium ${meta.className}`}>
      <Icon className={`h-3.5 w-3.5 ${spin ? "animate-spin" : ""}`} />
      {meta.label}
    </span>
  );
}

function SourceModeButton({
  active,
  icon: Icon,
  label,
  onClick,
}: {
  active: boolean;
  icon: typeof FileVideo;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex h-10 items-center justify-center gap-2 rounded-md border px-2 text-sm transition-colors ${
        active
          ? "border-accent bg-accent/10 text-white"
          : "border-surface-border bg-surface text-gray-400 hover:border-gray-500 hover:text-gray-200"
      }`}
    >
      <Icon className="h-4 w-4" />
      {label}
    </button>
  );
}

function EmptyProjectState({ hasQuery }: { hasQuery: boolean }) {
  return (
    <div className="flex h-full items-center justify-center p-10">
      <div className="max-w-sm text-center">
        <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-md border border-surface-border bg-surface-raised text-gray-400">
          {hasQuery ? <Search className="h-5 w-5" /> : <Settings2 className="h-5 w-5" />}
        </div>
        <h3 className="mt-4 text-base font-semibold text-white">
          {hasQuery ? "No matching projects" : "No projects yet"}
        </h3>
        <p className="mt-2 text-sm leading-6 text-gray-500">
          {hasQuery
            ? "Adjust the search term to find a workspace."
            : "Create a project or upload a legacy video to start building the editor workspace list."}
        </p>
      </div>
    </div>
  );
}

function getContinueLabel(project: Project, video: Video | null) {
  if (!video) return project.status === "draft" ? "Open Project" : "Continue";
  if (video.status === "awaiting_review" || video.status === "completed") return "Continue Editing";
  if (BUSY_VIDEO_STATUSES.has(video.status)) return "View Progress";
  if (video.status === "failed") return "Inspect";
  return "Open Project";
}

function effectiveProjectStatus(project: Project, video: Video | null): ProjectStatus {
  if (!video) return project.status;
  if (video.status === "awaiting_review") return "awaiting_review";
  if (video.status === "completed") return "completed";
  if (video.status === "failed") return "failed";
  if (BUSY_VIDEO_STATUSES.has(video.status)) return "processing";
  return project.status === "draft" ? "ready" : project.status;
}

function formatProjectType(projectType: string | null) {
  return (projectType || "project").replace(/_/g, " ");
}

function formatSourceMode(sourceMode: ProjectSourceMode) {
  return sourceMode === "multi_source" ? "Multi-source" : "Single video";
}

function formatVideoStatus(status: Video["status"]) {
  return status.replace(/_/g, " ");
}

function formatRelativeDate(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Unknown";

  const diffMs = Date.now() - date.getTime();
  const minute = 60_000;
  const hour = minute * 60;
  const day = hour * 24;

  if (diffMs < minute) return "Just now";
  if (diffMs < hour) return `${Math.floor(diffMs / minute)}m ago`;
  if (diffMs < day) return `${Math.floor(diffMs / hour)}h ago`;
  if (diffMs < day * 7) return `${Math.floor(diffMs / day)}d ago`;

  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    year: date.getFullYear() === new Date().getFullYear() ? undefined : "numeric",
  }).format(date);
}
