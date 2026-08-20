import { useEffect, useState } from "react";
import { UploadPanel } from "./components/UploadPanel";
import { ProcessingView } from "./components/ProcessingView";
import { ReviewEditor } from "./components/ReviewEditor";
import { MainSettingsPanel } from "./components/MainSettingsPanel";
import { ProjectDashboard } from "./components/ProjectDashboard";
import { DesktopV2ErrorBoundary, DesktopV2Shell } from "./components/DesktopV2Shell";
import { resolveAppRoute } from "./desktopV2";
import { Clapperboard, FolderOpen, Settings } from "lucide-react";
import type { Project, Video } from "./types/api";
import * as api from "./lib/api";

type View = "dashboard" | "upload" | "processing" | "review";

type DashboardContinueTarget = {
  project: Project;
  video: Video | null;
  nextView: "upload" | "processing" | "review";
};

type AppRoute = {
  view: View;
  projectId: string | null;
  videoId: string | null;
};

export default function App() {
  const [isTauriRuntime, setIsTauriRuntime] = useState<boolean | null>(null);

  useEffect(() => {
    let cancelled = false;
    void api.isTauriDesktopRuntime().then(isTauri => {
      if (!cancelled) setIsTauriRuntime(isTauri);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  if (isTauriRuntime === null) return <RuntimeDetectionScreen />;
  return resolveAppRoute(isTauriRuntime) === "desktop-v2-shell"
    ? <DesktopV2ErrorBoundary><DesktopV2Shell /></DesktopV2ErrorBoundary>
    : <BrowserEditorApp />;
}
function RuntimeDetectionScreen() {
  return (
    <div className="flex h-screen items-center justify-center bg-surface text-gray-300">
      <div className="rounded-xl border border-surface-border bg-surface-raised px-5 py-4 text-sm">Preparing AI Video Editor…</div>
    </div>
  );
}
function BrowserEditorApp() {
  const [view, setView] = useState<View>("dashboard");
  const [videoId, setVideoId] = useState<string | null>(null);
  const [videoFilename, setVideoFilename] = useState<string>("");
  const [selectedVideo, setSelectedVideo] = useState<Video | null>(null);
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  useEffect(() => {
    (async () => {
      try {
        const { invoke } = await import("@tauri-apps/api/core");
        const settings = await invoke<{ backend_url?: string }>("load_settings");
        if (settings?.backend_url) api.setBaseUrl(settings.backend_url);
      } catch {
        // Browser dev mode uses the default localhost backend.
      }

      await restoreRouteFromHash();
    })();
  }, []);

  const restoreRouteFromHash = async () => {
    const route = parseRouteHash();
    if (!route || route.view === "dashboard") return;

    try {
      const video = route.videoId ? await api.getVideo(route.videoId) : null;
      const projectId = route.projectId ?? video?.project_id ?? null;
      const project = projectId ? await api.getProject(projectId) : null;

      if (route.view !== "upload" && !video) return;
      if (route.view === "upload" && !project) return;

      setSelectedProject(project);
      setSelectedVideo(video);
      setVideoId(video?.id ?? null);
      setVideoFilename(video?.original_filename ?? project?.title ?? "");
      setView(route.view);
    } catch {
      replaceRouteHash("dashboard", null, null);
    }
  };

  const handleUpload = (id: string, filename: string) => {
    setVideoId(id);
    setVideoFilename(filename);
    setSelectedVideo(null);
    setView("processing");
    replaceRouteHash("processing", selectedProject?.id ?? null, id);
  };

  const handleProcessingComplete = () => {
    setView("review");
    replaceRouteHash("review", selectedProject?.id ?? selectedVideo?.project_id ?? null, videoId);
  };

  const handleBackToDashboard = () => {
    setVideoId(null);
    setVideoFilename("");
    setSelectedVideo(null);
    setSelectedProject(null);
    setView("dashboard");
    replaceRouteHash("dashboard", null, null);
  };

  const handleDashboardContinue = ({ project, video, nextView }: DashboardContinueTarget) => {
    setSelectedProject(project);
    setSelectedVideo(video);
    setVideoId(video?.id ?? null);
    setVideoFilename(video?.original_filename ?? project.title);
    setView(nextView);
    replaceRouteHash(nextView, project.id, video?.id ?? null);
  };

  const handleProjectResolved = (project: Project) => {
    setSelectedProject(project);
    replaceRouteHash(view, project.id, videoId);
  };

  return (
    <div className="h-screen flex flex-col bg-surface overflow-hidden">
      <header className="flex items-center justify-between px-4 py-2 bg-surface-raised border-b border-surface-border shrink-0">
        <button
          type="button"
          onClick={handleBackToDashboard}
          className="group inline-flex items-center gap-2 rounded-md px-1.5 py-1 text-left transition-colors hover:bg-surface-overlay focus:outline-none focus:ring-1 focus:ring-accent"
          aria-label="Go to project dashboard"
        >
          <span className="flex h-7 w-7 items-center justify-center rounded-md bg-accent/15 text-accent ring-1 ring-accent/30 transition-colors group-hover:bg-accent/20">
            <Clapperboard className="h-4 w-4" />
          </span>
          <span className="text-sm font-semibold tracking-wide text-white">AI Video Editor</span>
        </button>
        <div className="flex items-center gap-2">
          {selectedProject && (
            <span className="ml-2 hidden items-center gap-1.5 rounded bg-surface-overlay px-2 py-1 text-xs text-gray-400 sm:inline-flex">
              <FolderOpen className="h-3.5 w-3.5" />
              {selectedProject.title}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3 text-xs text-gray-400">
          {videoFilename && (
            <span className="bg-surface-overlay px-2 py-1 rounded">{videoFilename}</span>
          )}
          <button
            type="button"
            onClick={() => setSettingsOpen(true)}
            className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 transition-colors hover:bg-surface-overlay hover:text-gray-200"
          >
            <Settings className="w-3.5 h-3.5" />
            Settings
          </button>
          {view !== "dashboard" && (
            <button
              onClick={handleBackToDashboard}
              className="hover:text-gray-200 transition-colors"
            >
              Projects
            </button>
          )}
        </div>
      </header>

      <main className="min-h-0 flex-1 overflow-hidden">
        {view === "dashboard" && (
          <ProjectDashboard onContinue={handleDashboardContinue} />
        )}
        {view === "upload" && (
          <UploadPanel
            project={selectedProject}
            existingVideo={selectedVideo}
            onUpload={handleUpload}
            onProjectResolved={handleProjectResolved}
          />
        )}
        {view === "processing" && videoId && (
          <ProcessingView
            videoId={videoId}
            onComplete={handleProcessingComplete}
          />
        )}
        {view === "review" && videoId && (
          <ReviewEditor
            videoId={videoId}
            videoFilename={videoFilename}
            onOpenSettings={() => setSettingsOpen(true)}
          />
        )}
      </main>

      <MainSettingsPanel
        isOpen={settingsOpen}
        onClose={() => setSettingsOpen(false)}
      />
    </div>
  );
}

function parseRouteHash(): AppRoute | null {
  const hash = window.location.hash.replace(/^#\/?/, "");
  if (!hash) return null;

  const [path, query = ""] = hash.split("?");
  const parts = path.split("/").filter(Boolean);
  const params = new URLSearchParams(query);
  const view = parts[0] as View | undefined;

  if (view === "dashboard") {
    return { view, projectId: null, videoId: null };
  }

  if (view === "upload" || view === "processing" || view === "review") {
    return {
      view,
      projectId: params.get("projectId"),
      videoId: params.get("videoId"),
    };
  }

  return null;
}

function replaceRouteHash(view: View, projectId: string | null, videoId: string | null) {
  if (view === "dashboard") {
    window.history.replaceState(null, "", window.location.pathname + window.location.search);
    return;
  }

  const params = new URLSearchParams();
  if (projectId) params.set("projectId", projectId);
  if (videoId) params.set("videoId", videoId);
  const query = params.toString();
  window.history.replaceState(null, "", `#/${view}${query ? `?${query}` : ""}`);
}
