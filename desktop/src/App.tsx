import { useEffect, useState } from "react";
import { UploadPanel } from "./components/UploadPanel";
import { ProcessingView } from "./components/ProcessingView";
import { ReviewEditor } from "./components/ReviewEditor";
import { MainSettingsPanel } from "./components/MainSettingsPanel";
import { ProjectDashboard } from "./components/ProjectDashboard";
import { Clapperboard, FolderOpen, Settings } from "lucide-react";
import type { AppSettings, Project, Video } from "./types/api";
import { setBaseUrl } from "./lib/api";

type View = "dashboard" | "upload" | "processing" | "review";

type DashboardContinueTarget = {
  project: Project;
  video: Video | null;
  nextView: "upload" | "processing" | "review";
};

export default function App() {
  const [view, setView] = useState<View>("dashboard");
  const [videoId, setVideoId] = useState<string | null>(null);
  const [videoFilename, setVideoFilename] = useState<string>("");
  const [selectedProject, setSelectedProject] = useState<Project | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);

  useEffect(() => {
    (async () => {
      try {
        const { invoke } = await import("@tauri-apps/api/core");
        const settings = await invoke<AppSettings>("load_settings");
        if (settings?.backend_url) setBaseUrl(settings.backend_url);
      } catch {
        // Browser dev mode uses the default localhost backend.
      }
    })();
  }, []);

  const handleUpload = (id: string, filename: string) => {
    setVideoId(id);
    setVideoFilename(filename);
    setView("processing");
  };

  const handleProcessingComplete = () => {
    setView("review");
  };

  const handleBackToDashboard = () => {
    setVideoId(null);
    setVideoFilename("");
    setSelectedProject(null);
    setView("dashboard");
  };

  const handleDashboardContinue = ({ project, video, nextView }: DashboardContinueTarget) => {
    setSelectedProject(project);
    setVideoId(video?.id ?? null);
    setVideoFilename(video?.original_filename ?? project.title);
    setView(nextView);
  };

  return (
    <div className="h-screen flex flex-col bg-surface overflow-hidden">
      <header className="flex items-center justify-between px-4 py-2 bg-surface-raised border-b border-surface-border shrink-0">
        <div className="flex items-center gap-2">
          <Clapperboard className="w-5 h-5 text-accent" />
          <h1 className="text-sm font-semibold tracking-wide">AI Video Editor</h1>
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

      <main className="flex-1 overflow-hidden">
        {view === "dashboard" && (
          <ProjectDashboard onContinue={handleDashboardContinue} />
        )}
        {view === "upload" && (
          <UploadPanel project={selectedProject} onUpload={handleUpload} />
        )}
        {view === "processing" && videoId && (
          <ProcessingView
            videoId={videoId}
            onComplete={handleProcessingComplete}
          />
        )}
        {view === "review" && videoId && (
          <ReviewEditor videoId={videoId} videoFilename={videoFilename} />
        )}
      </main>

      <MainSettingsPanel
        isOpen={settingsOpen}
        onClose={() => setSettingsOpen(false)}
      />
    </div>
  );
}
