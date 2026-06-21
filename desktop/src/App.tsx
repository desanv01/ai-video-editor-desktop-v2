import { useEffect, useState } from "react";
import { UploadPanel } from "./components/UploadPanel";
import { ProcessingView } from "./components/ProcessingView";
import { ReviewEditor } from "./components/ReviewEditor";
import { MainSettingsPanel } from "./components/MainSettingsPanel";
import { ProjectDashboard } from "./components/ProjectDashboard";
import { Clapperboard, FolderOpen, Settings } from "lucide-react";
import type { AppSettings, DesktopBootstrapResult, Project, Video } from "./types/api";
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
  const [view, setView] = useState<View>("dashboard");
  const [videoId, setVideoId] = useState<string | null>(null);
  const [videoFilename, setVideoFilename] = useState<string>("");
  const [selectedVideo, setSelectedVideo] = useState<Video | null>(null);
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [desktopBootstrap, setDesktopBootstrap] = useState<{
    loading: boolean;
    result: DesktopBootstrapResult | null;
    error: string | null;
  }>({
    loading: false,
    result: null,
    error: null,
  });

  useEffect(() => {
    (async () => {
      const nativeDesktop = await api.isNativeDesktop().catch(() => false);
      if (nativeDesktop) {
        setDesktopBootstrap({ loading: true, result: null, error: null });
        try {
          const result = await api.bootstrapDesktopBackend();
          api.setBaseUrl(result.backendUrl);
          setDesktopBootstrap({ loading: false, result, error: null });
        } catch (error) {
          setDesktopBootstrap({ loading: false, result: null, error: String(error) });
        }
      } else {
        try {
          const { invoke } = await import("@tauri-apps/api/core");
          const settings = await invoke<AppSettings>("load_settings");
          if (settings?.backend_url) api.setBaseUrl(settings.backend_url);
        } catch {
          // Browser dev mode uses the default localhost backend.
        }
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
        {(desktopBootstrap.loading || desktopBootstrap.error) && (
          <SystemReadinessPanel
            bootstrap={desktopBootstrap}
            onRetry={async () => {
              setDesktopBootstrap({ loading: true, result: null, error: null });
              try {
                const result = await api.bootstrapDesktopBackend();
                api.setBaseUrl(result.backendUrl);
                setDesktopBootstrap({ loading: false, result, error: null });
              } catch (error) {
                setDesktopBootstrap({ loading: false, result: null, error: String(error) });
              }
            }}
          />
        )}
        {!desktopBootstrap.loading && !desktopBootstrap.error && view === "dashboard" && (
          <ProjectDashboard onContinue={handleDashboardContinue} />
        )}
        {!desktopBootstrap.loading && !desktopBootstrap.error && view === "upload" && (
          <UploadPanel
            project={selectedProject}
            existingVideo={selectedVideo}
            onUpload={handleUpload}
            onProjectResolved={handleProjectResolved}
          />
        )}
        {!desktopBootstrap.loading && !desktopBootstrap.error && view === "processing" && videoId && (
          <ProcessingView
            videoId={videoId}
            onComplete={handleProcessingComplete}
          />
        )}
        {!desktopBootstrap.loading && !desktopBootstrap.error && view === "review" && videoId && (
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

function SystemReadinessPanel({
  bootstrap,
  onRetry,
}: {
  bootstrap: {
    loading: boolean;
    result: DesktopBootstrapResult | null;
    error: string | null;
  };
  onRetry: () => Promise<void>;
}) {
  const items = bootstrap.result?.items ?? [];
  const showPanel = bootstrap.loading || bootstrap.error || items.length > 0;
  if (!showPanel) return null;

  return (
    <div className="h-full overflow-auto bg-surface px-6 py-8 text-gray-100">
      <div className="mx-auto max-w-4xl rounded-2xl border border-surface-border bg-surface-raised p-6">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h2 className="text-2xl font-semibold text-white">System Readiness</h2>
            <p className="mt-2 text-sm text-gray-400">
              The desktop app is preparing its local Docker backend and storage before opening the editor.
            </p>
          </div>
          {bootstrap.loading ? (
            <span className="rounded-full border border-accent/40 bg-accent/10 px-3 py-1 text-xs text-accent">
              Starting services...
            </span>
          ) : bootstrap.result?.ready ? (
            <span className="rounded-full border border-emerald-500/40 bg-emerald-500/10 px-3 py-1 text-xs text-emerald-300">
              Ready
            </span>
          ) : null}
        </div>

        {bootstrap.error ? (
          <div className="mt-6 rounded-xl border border-red-400/40 bg-red-500/10 p-4 text-sm text-red-100">
            <p className="font-semibold">Bootstrap failed</p>
            <p className="mt-2 whitespace-pre-wrap text-red-100/80">{bootstrap.error}</p>
            <button
              type="button"
              onClick={() => void onRetry()}
              className="mt-4 rounded-md border border-surface-border px-3 py-1.5 text-xs font-medium text-gray-100 transition-colors hover:border-accent"
            >
              Retry services
            </button>
          </div>
        ) : null}

        {items.length > 0 ? (
          <div className="mt-6 grid gap-3 md:grid-cols-2">
            {items.map(item => (
              <div key={item.key} className="rounded-xl border border-surface-border bg-surface-overlay p-4">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-sm font-semibold text-white">{item.label}</p>
                  <span className="rounded-full bg-surface px-2 py-0.5 text-[11px] uppercase tracking-wide text-gray-300">
                    {item.status}
                  </span>
                </div>
                <p className="mt-2 text-xs leading-5 text-gray-400">{item.detail}</p>
              </div>
            ))}
          </div>
        ) : null}

        {bootstrap.result?.ready ? (
          <p className="mt-6 text-xs text-gray-500">
            Backend URL: {bootstrap.result.backendUrl}
          </p>
        ) : null}
      </div>
    </div>
  );
}
