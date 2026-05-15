import { useState, useEffect } from "react";
import { UploadPanel } from "./components/UploadPanel";
import { ProcessingView } from "./components/ProcessingView";
import { ReviewEditor } from "./components/ReviewEditor";
import { TranscriptionSettingsPanel } from "./components/TranscriptionSettingsPanel";
import { Clapperboard, Settings } from "lucide-react";
import type { AppSettings } from "./types/api";
import { setBaseUrl } from "./lib/api";

type View = "upload" | "processing" | "review";

export default function App() {
  const [view, setView] = useState<View>("upload");
  const [videoId, setVideoId] = useState<string | null>(null);
  const [videoFilename, setVideoFilename] = useState<string>("");
  const [settingsOpen, setSettingsOpen] = useState(false);

  // Load backend URL from Tauri settings on mount
  useEffect(() => {
    (async () => {
      try {
        const { invoke } = await import("@tauri-apps/api/core");
        const settings = await invoke<AppSettings>("load_settings");
        if (settings?.backend_url) setBaseUrl(settings.backend_url);
      } catch {
        // Not running in Tauri (browser dev mode) — use default localhost
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

  const handleBackToUpload = () => {
    setVideoId(null);
    setVideoFilename("");
    setView("upload");
  };

  return (
    <div className="h-screen flex flex-col bg-surface overflow-hidden">
      {/* ── Title Bar ── */}
      <header className="flex items-center justify-between px-4 py-2 bg-surface-raised border-b border-surface-border shrink-0">
        <div className="flex items-center gap-2">
          <Clapperboard className="w-5 h-5 text-accent" />
          <h1 className="text-sm font-semibold tracking-wide">AI Video Editor</h1>
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
            Transcription
          </button>
          {videoId && (
            <button
              onClick={handleBackToUpload}
              className="hover:text-gray-200 transition-colors"
            >
              ← New Video
            </button>
          )}
        </div>
      </header>

      {/* ── Main Content ── */}
      <main className="flex-1 overflow-hidden">
        {view === "upload" && (
          <UploadPanel onUpload={handleUpload} />
        )}
        {view === "processing" && videoId && (
          <ProcessingView
            videoId={videoId}
            onComplete={handleProcessingComplete}
          />
        )}
        {view === "review" && videoId && (
          <ReviewEditor videoId={videoId} />
        )}
      </main>

      <TranscriptionSettingsPanel
        isOpen={settingsOpen}
        onClose={() => setSettingsOpen(false)}
      />
    </div>
  );
}
