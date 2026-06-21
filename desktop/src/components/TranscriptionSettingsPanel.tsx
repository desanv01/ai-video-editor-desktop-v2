import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Check,
  Cloud,
  Cpu,
  Download,
  Layers3,
  Loader2,
  RefreshCw,
  Trash2,
  X,
} from "lucide-react";
import * as api from "../lib/api";
import type {
  AIProcessingMode,
  BackendAISettings,
  LocalTranscriptionModel,
  LocalTranscriptionModelCatalog,
} from "../types/api";

interface Props {
  isOpen: boolean;
  onClose: () => void;
}

const MODE_OPTIONS: {
  value: AIProcessingMode;
  label: string;
  description: string;
  icon: typeof Cloud;
}[] = [
  {
    value: "hybrid",
    label: "Hybrid",
    description: "Use API Voxtral first, then local Whisper fallback when needed.",
    icon: Layers3,
  },
  {
    value: "local",
    label: "Local",
    description: "Use whisper.cpp only for private offline transcription.",
    icon: Cpu,
  },
  {
    value: "api",
    label: "API",
    description: "Use Voxtral (Mistral) or Whisper (OpenAI) API.",
    icon: Cloud,
  },
];

function modelMatchesPath(model: LocalTranscriptionModel, path: string | null | undefined): boolean {
  if (!path) return false;
  const normalizedPath = path.replace(/\\/g, "/").toLowerCase();
  const normalizedFilePath = model.file_path?.replace(/\\/g, "/").toLowerCase();
  return normalizedFilePath === normalizedPath || normalizedPath.endsWith(model.expected_filename.toLowerCase());
}

function selectedModelIdFrom(
  settings: BackendAISettings,
  catalog: LocalTranscriptionModelCatalog,
): string {
  const persistedId = settings.local_model_ids?.transcription;
  if (persistedId && catalog.models.some(model => model.model_id === persistedId)) {
    return persistedId;
  }
  const persistedPath = settings.local_model_paths.transcription;
  const pathMatch = catalog.models.find(model => modelMatchesPath(model, persistedPath));
  return pathMatch?.model_id
    ?? catalog.models.find(model => model.active)?.model_id
    ?? catalog.active_model_id
    ?? catalog.models[0]?.model_id
    ?? "small";
}

function formatModelState(model: LocalTranscriptionModel): string {
  if (model.status === "downloading" && model.download_progress_percent !== null) {
    return `${Math.round(model.download_progress_percent)}%`;
  }
  if (model.status === "queued") return "Queued";
  if (model.status === "failed") return "Failed";
  return model.downloaded ? "Ready" : "Not downloaded";
}

export function TranscriptionSettingsPanel({ isOpen, onClose }: Props) {
  const [settings, setSettings] = useState<BackendAISettings | null>(null);
  const [catalog, setCatalog] = useState<LocalTranscriptionModelCatalog | null>(null);
  const [selectedMode, setSelectedMode] = useState<AIProcessingMode>("hybrid");
  const [selectedModelId, setSelectedModelId] = useState("small");
  const [fallbackEnabled, setFallbackEnabled] = useState(true);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [busyModelId, setBusyModelId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const selectedModel = useMemo(
    () => catalog?.models.find(model => model.model_id === selectedModelId) ?? null,
    [catalog, selectedModelId],
  );

  const hasRunningDownload = useMemo(
    () => catalog?.models.some(model => model.status === "queued" || model.status === "downloading") ?? false,
    [catalog],
  );

  const loadPanel = async () => {
    setLoading(true);
    setError(null);
    try {
      const [nextSettings, nextCatalog] = await Promise.all([
        api.getAISettings(),
        api.getLocalTranscriptionModels(),
      ]);
      const transcriptionSettings = nextSettings.capabilities.transcription;
      setSettings(nextSettings);
      setCatalog(nextCatalog);
      setSelectedMode(transcriptionSettings?.mode ?? nextSettings.preferred_processing_mode);
      setFallbackEnabled(transcriptionSettings?.fallback_enabled ?? nextSettings.fallback_enabled);
      setSelectedModelId(selectedModelIdFrom(nextSettings, nextCatalog));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  const refreshCatalog = async () => {
    try {
      const nextCatalog = await api.getLocalTranscriptionModels();
      setCatalog(nextCatalog);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  useEffect(() => {
    if (isOpen) void loadPanel();
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen || !hasRunningDownload) return;
    const intervalId = window.setInterval(() => {
      void refreshCatalog();
    }, 1500);
    return () => window.clearInterval(intervalId);
  }, [hasRunningDownload, isOpen]);

  if (!isOpen) return null;

  const handleDownload = async (model: LocalTranscriptionModel) => {
    setBusyModelId(model.model_id);
    setError(null);
    setNotice(null);
    try {
      const job = await api.downloadLocalTranscriptionModel(model.model_id, true);
      setSelectedModelId(model.model_id);
      setNotice(job.status === "completed" ? `${model.label} is ready.` : `Downloading ${model.label}.`);
      await refreshCatalog();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyModelId(null);
    }
  };

  const handleRemove = async (model: LocalTranscriptionModel) => {
    if (!window.confirm(`Remove ${model.label} from local storage?`)) return;

    setBusyModelId(model.model_id);
    setError(null);
    setNotice(null);
    try {
      const result = await api.removeLocalTranscriptionModel(model.model_id);
      setNotice(result.message);
      await refreshCatalog();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyModelId(null);
    }
  };

  const handleSave = async () => {
    if (!settings || !catalog) return;

    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const selected = catalog.models.find(model => model.model_id === selectedModelId);
      const apiProviderId = settings.capabilities.transcription?.api_provider_id
        ?? settings.asr_provider
        ?? "voxtral";
      const nextSettings = await api.updateAISettings({
        preferred_processing_mode: selectedMode,
        fallback_enabled: fallbackEnabled,
        capabilities: {
          transcription: {
            mode: selectedMode,
            api_provider_id: apiProviderId,
            local_provider_id: "whisper-cpp",
            fallback_enabled: fallbackEnabled,
            hybrid_fallback_order: ["local", "api"],
          },
        },
        local_model_paths: selected?.file_path ? { transcription: selected.file_path } : undefined,
        local_model_ids: { transcription: selectedModelId },
      });
      setSettings(nextSettings);
      setNotice("Transcription settings saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/50">
      <aside className="h-full w-full max-w-[520px] overflow-y-auto border-l border-surface-border bg-surface-raised shadow-2xl">
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-surface-border bg-surface-raised px-5 py-4">
          <div>
            <p className="text-xs uppercase tracking-wide text-gray-500">Settings</p>
            <h2 className="text-base font-semibold text-gray-100">Transcription</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-2 text-gray-400 transition-colors hover:bg-surface-overlay hover:text-gray-100"
            aria-label="Close transcription settings"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {loading ? (
          <div className="flex h-64 items-center justify-center gap-3 text-sm text-gray-300">
            <Loader2 className="h-5 w-5 animate-spin text-accent" />
            Loading transcription settings...
          </div>
        ) : (
          <div className="space-y-6 p-5">
            {error && (
              <div className="flex gap-3 rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-200">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{error}</span>
              </div>
            )}

            {notice && (
              <div className="flex gap-3 rounded-lg border border-emerald-500/40 bg-emerald-500/10 p-3 text-sm text-emerald-100">
                <Check className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{notice}</span>
              </div>
            )}

            <section className="space-y-3">
              <div className="flex items-center justify-between gap-3">
                <h3 className="text-sm font-semibold text-gray-100">Transcription Mode</h3>
                <button
                  type="button"
                  onClick={loadPanel}
                  className="inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-xs text-gray-400 transition-colors hover:bg-surface-overlay hover:text-gray-100"
                >
                  <RefreshCw className="h-3.5 w-3.5" />
                  Refresh
                </button>
              </div>
              <div className="grid gap-2 sm:grid-cols-3">
                {MODE_OPTIONS.map(option => {
                  const Icon = option.icon;
                  const selected = selectedMode === option.value;
                  return (
                    <button
                      key={option.value}
                      type="button"
                      onClick={() => setSelectedMode(option.value)}
                      className={`rounded-lg border p-3 text-left transition-colors ${
                        selected
                          ? "border-accent bg-accent/15 text-white"
                          : "border-surface-border bg-surface hover:border-gray-500"
                      }`}
                    >
                      <div className="mb-2 flex items-center gap-2 text-sm font-medium">
                        <Icon className="h-4 w-4" />
                        {option.label}
                      </div>
                      <p className="text-xs leading-5 text-gray-400">{option.description}</p>
                    </button>
                  );
                })}
              </div>
              <label className="flex items-center justify-between gap-4 rounded-lg border border-surface-border bg-surface px-3 py-2 text-sm text-gray-200">
                <span>Allow fallback when the selected transcription route fails</span>
                <input
                  type="checkbox"
                  checked={fallbackEnabled}
                  onChange={event => setFallbackEnabled(event.target.checked)}
                  className="h-4 w-4 accent-accent"
                />
              </label>
            </section>

            <section className="space-y-3">
              <div>
                <h3 className="text-sm font-semibold text-gray-100">Local Whisper Model</h3>
                <p className="mt-1 text-xs text-gray-500">Used by Local and Hybrid transcription modes.</p>
              </div>

              <div className="space-y-2">
                {catalog?.models.map(model => {
                  const selected = model.model_id === selectedModelId;
                  const busy = busyModelId === model.model_id;
                  const running = model.status === "queued" || model.status === "downloading";
                  return (
                    <div
                      key={model.model_id}
                      className={`rounded-lg border p-3 transition-colors ${
                        selected ? "border-accent bg-accent/10" : "border-surface-border bg-surface"
                      }`}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <button
                          type="button"
                          onClick={() => setSelectedModelId(model.model_id)}
                          className="flex min-w-0 flex-1 items-start gap-3 text-left"
                        >
                          <span className={`mt-1 h-3 w-3 rounded-full border ${
                            selected ? "border-accent bg-accent" : "border-gray-500"
                          }`} />
                          <span className="min-w-0">
                            <span className="flex flex-wrap items-center gap-2">
                              <span className="text-sm font-medium text-gray-100">{model.label}</span>
                              <span className="rounded bg-surface-overlay px-1.5 py-0.5 text-[11px] uppercase text-gray-400">
                                {model.tier}
                              </span>
                            </span>
                            <span className="mt-1 block text-xs leading-5 text-gray-400">
                              {model.size} / {model.speed} / {model.quality}
                            </span>
                            <span className="mt-1 block text-xs leading-5 text-gray-500">
                              {model.description}
                            </span>
                          </span>
                        </button>

                        <div className="flex shrink-0 flex-col items-end gap-2">
                          <span className={`text-xs ${
                            model.downloaded ? "text-emerald-300" : model.status === "failed" ? "text-red-300" : "text-gray-500"
                          }`}>
                            {formatModelState(model)}
                          </span>
                          <div className="flex items-center gap-1">
                            {model.can_download && (
                              <button
                                type="button"
                                onClick={() => void handleDownload(model)}
                                disabled={busy || running}
                                className="inline-flex items-center gap-1 rounded-lg bg-accent px-2 py-1 text-xs font-medium text-white transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-60"
                              >
                                {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
                                Download
                              </button>
                            )}
                            {model.can_remove && (
                              <button
                                type="button"
                                onClick={() => void handleRemove(model)}
                                disabled={busy}
                                className="rounded-lg p-1.5 text-gray-500 transition-colors hover:bg-surface-overlay hover:text-red-300 disabled:cursor-not-allowed disabled:opacity-60"
                                aria-label={`Remove ${model.label}`}
                              >
                                {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                              </button>
                            )}
                          </div>
                        </div>
                      </div>

                      {running && model.download_progress_percent !== null && (
                        <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-surface-overlay">
                          <div
                            className="h-full rounded-full bg-accent"
                            style={{ width: `${Math.max(2, model.download_progress_percent)}%` }}
                          />
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            </section>

            <div className="sticky bottom-0 -mx-5 border-t border-surface-border bg-surface-raised px-5 py-4">
              <div className="flex items-center justify-between gap-4">
                <p className="text-xs text-gray-500">
                  {selectedModel
                    ? `${selectedModel.label} selected for local transcription.`
                    : "Choose a local model before using Local or Hybrid mode."}
                </p>
                <button
                  type="button"
                  onClick={handleSave}
                  disabled={saving || !settings || !catalog}
                  className="inline-flex items-center gap-2 rounded-lg bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                  Save Settings
                </button>
              </div>
            </div>
          </div>
        )}
      </aside>
    </div>
  );
}
