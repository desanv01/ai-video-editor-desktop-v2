import { useEffect, useMemo, useRef, useState } from "react";
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
import { provisioningClient } from "../provisioning";
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

const RUNNING_MODEL_STATES = new Set(["queued", "downloading", "verifying", "probing"]);

function formatModelState(model: LocalTranscriptionModel): string {
  if (model.status === "queued") return "Queued";
  if (model.status === "downloading") return `Downloading ${Math.round(model.download_progress_percent ?? 0)}%`;
  if (model.status === "verifying") return "Verifying SHA256";
  if (model.status === "probing") return "Testing local runtime";
  if (model.verification_required) return "Verification required";
  if (model.status === "paused") return "Paused";
  if (model.status === "interrupted") return "Interrupted";
  if (model.status === "failed") return "Failed";
  return model.downloaded ? "Ready" : "Not downloaded";
}

function exactBytes(bytes: number): string {
  return `${bytes.toLocaleString()} bytes`;
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
  const [qualificationModelId, setQualificationModelId] = useState<string | null>(null);
  const [cancellingModelId, setCancellingModelId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const selectedModel = useMemo(
    () => catalog?.models.find(model => model.model_id === selectedModelId) ?? null,
    [catalog, selectedModelId],
  );

  const native = api.isElectronDesktopRuntime() || catalog?.native === true;
  const sessionRef = useRef(0);
  const openRef = useRef(false);
  const actionRef = useRef<number | null>(null);
  const refreshRef = useRef<{ session: number; promise: Promise<void> } | null>(null);
  const dialogRef = useRef<HTMLElement | null>(null);
  const autoSelectRef = useRef<{ session: number; modelId: string } | null>(null);
  const hasRunningDownload = catalog?.models.some(model => RUNNING_MODEL_STATES.has(model.status)) ?? false;
  const currentSession = (session: number) => openRef.current && sessionRef.current === session;

  const loadPanel = async (session = sessionRef.current) => {
    setLoading(true);
    setError(null);
    try {
      const [nextSettings, nextCatalog] = await Promise.all([api.getAISettings(), api.getLocalTranscriptionModels()]);
      if (!currentSession(session)) return;
      const transcriptionSettings = nextSettings.capabilities.transcription;
      setSettings(nextSettings);
      setCatalog(nextCatalog);
      setSelectedMode(transcriptionSettings?.mode ?? nextSettings.preferred_processing_mode);
      setFallbackEnabled(transcriptionSettings?.fallback_enabled ?? nextSettings.fallback_enabled);
      setSelectedModelId(selectedModelIdFrom(nextSettings, nextCatalog));
    } catch (err) {
      if (currentSession(session)) setError(api.friendlyErrorMessage(err));
    } finally {
      if (currentSession(session)) setLoading(false);
    }
  };

  const refreshCatalog = (syncSelection = false, session = sessionRef.current): Promise<void> => {
    const flight = refreshRef.current;
    if (flight?.session === session) return flight.promise.then(() => {
      if (syncSelection && currentSession(session)) return refreshCatalog(true, session);
    });
    const promise = (async () => {
      try {
        const [nextCatalog, nextSettings] = await Promise.all([api.getLocalTranscriptionModels(), api.getAISettings()]);
        if (!currentSession(session)) return;
        setCatalog(nextCatalog);
        setSettings(nextSettings);
        const requested = autoSelectRef.current;
        if (requested?.session === session && nextCatalog.models.some(model => model.model_id === requested.modelId && model.downloaded && model.active)) {
          setSelectedModelId(requested.modelId);
          autoSelectRef.current = null;
        }
        if (syncSelection) setSelectedModelId(selectedModelIdFrom(nextSettings, nextCatalog));
        if (!api.isElectronDesktopRuntime() && !nextCatalog.native) {
          const operation = await provisioningClient.status().catch(() => null);
          if (!currentSession(session)) return;
          if (operation?.operationKind === "local-transcription-model"
            && (operation.state === "running" || operation.state === "cancelling")
            && nextCatalog.models.some(model => model.model_id === operation.targetId && model.downloaded)) {
            await provisioningClient.complete();
          }
        }
      } catch (err) {
        if (currentSession(session)) setError(api.friendlyErrorMessage(err));
      } finally {
        if (refreshRef.current?.session === session) refreshRef.current = null;
      }
    })();
    refreshRef.current = { session, promise };
    return promise;
  };

  useEffect(() => {
    const session = ++sessionRef.current;
    openRef.current = isOpen;
    if (isOpen) {
      setBusyModelId(null);
      setQualificationModelId(null);
      setCancellingModelId(null);
      setSaving(false);
      setNotice(null);
      setCatalog(null);
      autoSelectRef.current = null;
      void loadPanel(session);
    }
    return () => {
      openRef.current = false;
      ++sessionRef.current;
    };
  }, [isOpen]);

  useEffect(() => {
    if (!isOpen || (!hasRunningDownload && !qualificationModelId)) return;
    const session = sessionRef.current;
    let stopped = false;
    let timer: number | undefined;
    const poll = async () => {
      await refreshCatalog(false, session);
      if (!stopped && currentSession(session)) timer = window.setTimeout(() => void poll(), 1500);
    };
    timer = window.setTimeout(() => void poll(), 1500);
    return () => { stopped = true; window.clearTimeout(timer); };
  }, [hasRunningDownload, qualificationModelId, isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    const previous = document.activeElement as HTMLElement | null;
    dialogRef.current?.focus();
    const keydown = (event: KeyboardEvent) => {
      if (event.key === "Escape") { event.preventDefault(); onClose(); }
      if (event.key !== "Tab") return;
      const controls = dialogRef.current?.querySelectorAll<HTMLElement>("button:not(:disabled), input:not(:disabled), [tabindex='0']");
      if (!controls?.length) return;
      const first = controls[0], last = controls[controls.length - 1];
      if (event.shiftKey && (document.activeElement === first || document.activeElement === dialogRef.current)) {
        event.preventDefault(); last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault(); first.focus();
      }
    };
    document.addEventListener("keydown", keydown);
    return () => { document.removeEventListener("keydown", keydown); previous?.focus(); };
  }, [isOpen, onClose]);

  const runModelAction = async (model: LocalTranscriptionModel, action: () => Promise<void>) => {
    const session = sessionRef.current;
    if (actionRef.current !== null) return;
    actionRef.current = session;
    setBusyModelId(model.model_id);
    setError(null);
    setNotice(null);
    try { await action(); }
    catch (err) {
      await refreshCatalog(false, session);
      if (currentSession(session)) setError(api.friendlyErrorMessage(err));
    } finally {
      if (actionRef.current === session) actionRef.current = null;
      if (currentSession(session)) setBusyModelId(null);
    }
  };

  const handleDownload = async (model: LocalTranscriptionModel) => {
    const session = sessionRef.current;
    const verb = model.can_resume ? "Resume" : "Download";
    const storage = model.storage_required_bytes ? ` Allow ${exactBytes(model.storage_required_bytes)} of free storage including the safety margin.` : "";
    if (!window.confirm(`${verb} ${model.label} (${model.size_bytes ? exactBytes(model.size_bytes) : model.size})? This uses your internet connection and stores the model on this device.${storage}`)) return;
    await runModelAction(model, async () => {
      let coordinationStarted = false;
      try {
        if (!native) {
          await provisioningClient.begin("local-transcription-model", model.model_id);
          coordinationStarted = true;
        }
        const job = await api.downloadLocalTranscriptionModel(model.model_id, true);
        if (!currentSession(session)) return;
        if (native) autoSelectRef.current = { session, modelId: model.model_id };
        setNotice(job.status === "completed" ? `${model.label} is ready.` : `${verb} requested for ${model.label}; it will become active after verification and the local runtime test.`);
        if (!native) {
          setSelectedModelId(model.model_id);
          if (job.status === "completed") await provisioningClient.complete();
        }
        await refreshCatalog(job.status === "completed", session);
      } catch (err) {
        if (coordinationStarted) {
          try { await provisioningClient.cancel(); } catch { /* already terminal */ }
        }
        throw err;
      }
    });
  };

  const handleCancel = async (model: LocalTranscriptionModel) => {
    const session = sessionRef.current;
    if (cancellingModelId) return;
    setCancellingModelId(model.model_id);
    try {
      const job = await api.cancelLocalTranscriptionModel(model.model_id);
      if (!currentSession(session)) return;
      setNotice(job.status === "paused" ? `${model.label} paused; retained bytes can be resumed or verified.` : `Pause requested for ${model.label}; waiting for its transfer or verification to stop.`);
      await refreshCatalog(false, session);
    } catch (err) {
      if (currentSession(session)) setError(api.friendlyErrorMessage(err));
    } finally {
      if (currentSession(session)) setCancellingModelId(null);
    }
  };

  const handleVerify = async (model: LocalTranscriptionModel) => {
    const session = sessionRef.current;
    if (!window.confirm(`Verify the retained ${model.label} file and test it with the local runtime? This reads the local file and public test audio; it does not download a model. It becomes active only if both checks pass.`)) return;
    await runModelAction(model, async () => {
      setNotice(`Verifying ${model.label} and testing the local runtime…`);
      setQualificationModelId(model.model_id);
      try {
        await api.activateLocalTranscriptionModel(model.model_id);
      } finally {
        if (currentSession(session)) setQualificationModelId(null);
      }
      if (!currentSession(session)) return;
      setNotice(`${model.label} verified and active.`);
      await refreshCatalog(true, session);
    });
  };

  const handleRemove = async (model: LocalTranscriptionModel) => {
    const session = sessionRef.current;
    if (!window.confirm(`Remove ${model.label} and its retained partial from local storage? Protected Whisper small remains available.`)) return;
    await runModelAction(model, async () => {
      const result = await api.removeLocalTranscriptionModel(model.model_id);
      if (!currentSession(session)) return;
      setNotice(result.message);
      await refreshCatalog(true, session);
    });
  };

  const handleSave = async () => {
    if (!settings || !catalog || actionRef.current !== null) return;
    const session = sessionRef.current;
    actionRef.current = session;
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const selected = catalog.models.find(model => model.model_id === selectedModelId);
      let modelId = selectedModelId;
      let modelPath = selected?.file_path;
      if (native && modelId !== catalog.active_model_id) {
        if (!selected?.downloaded && !selected?.verification_required) {
          throw new Error("Download or resume this model explicitly before saving; model selection does not start a download.");
        }
        setNotice(`Verifying and activating ${selected.label} before saving…`);
        setQualificationModelId(modelId);
        const binding = await api.activateLocalTranscriptionModel(modelId);
        if (!currentSession(session)) return;
        modelId = binding.model_id;
        modelPath = binding.file_path;
      }
      const apiProviderId = settings.capabilities.transcription?.api_provider_id ?? settings.asr_provider ?? "voxtral";
      const nextSettings = await api.updateAISettings({
        preferred_processing_mode: selectedMode,
        fallback_enabled: fallbackEnabled,
        capabilities: { transcription: {
          mode: selectedMode, api_provider_id: apiProviderId, local_provider_id: "whisper-cpp",
          fallback_enabled: fallbackEnabled, hybrid_fallback_order: ["local", "api"],
        } },
        local_model_paths: modelPath ? { transcription: modelPath } : undefined,
        local_model_ids: { transcription: modelId },
      });
      if (!currentSession(session)) return;
      setSettings(nextSettings);
      setNotice("Transcription settings saved.");
      await refreshCatalog(false, session);
    } catch (err) {
      await refreshCatalog(true, session);
      if (currentSession(session)) setError(api.friendlyErrorMessage(err));
    } finally {
      if (actionRef.current === session) actionRef.current = null;
      if (currentSession(session)) {
        setSaving(false);
        setQualificationModelId(null);
      }
    }
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/50">
      <aside ref={dialogRef} role="dialog" aria-modal="true" aria-labelledby="transcription-settings-title" tabIndex={-1} className="h-full w-full max-w-[520px] overflow-y-auto border-l border-surface-border bg-surface-raised shadow-2xl">
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-surface-border bg-surface-raised px-5 py-4">
          <div>
            <p className="text-xs uppercase tracking-wide text-gray-500">Settings</p>
            <h2 id="transcription-settings-title" className="text-base font-semibold text-gray-100">Transcription</h2>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-2 text-gray-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent transition-colors hover:bg-surface-overlay hover:text-gray-100"
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
              <div role="alert" className="flex gap-3 rounded-lg border border-red-500/40 bg-red-500/10 p-3 text-sm text-red-200">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{error}</span>
              </div>
            )}

            {notice && (
              <div role="status" aria-live="polite" aria-atomic="true" className="flex gap-3 rounded-lg border border-emerald-500/40 bg-emerald-500/10 p-3 text-sm text-emerald-100">
                <Check className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{notice}</span>
              </div>
            )}

            <section className="space-y-3">
              <div className="flex items-center justify-between gap-3">
                <h3 className="text-sm font-semibold text-gray-100">Transcription Mode</h3>
                <button
                  type="button"
                  onClick={() => void loadPanel()}
                  disabled={saving || busyModelId !== null}
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
                      aria-pressed={selected}
                      disabled={saving}
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

              <p className="text-xs text-gray-300">{catalog?.runtime_message}</p>
              <div className="space-y-2">
                {catalog?.models.map(model => {
                  const selected = model.model_id === selectedModelId;
                  const busy = busyModelId === model.model_id;
                  const anyBusy = busyModelId !== null || saving;
                  const running = RUNNING_MODEL_STATES.has(model.status);
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
                          onClick={() => { autoSelectRef.current = null; setSelectedModelId(model.model_id); }}
                          aria-pressed={selected}
                          disabled={anyBusy}
                          aria-label={`Select ${model.label}`}
                          className="flex min-w-0 flex-1 items-start gap-3 rounded text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
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
                              {model.size} / {model.speed} / {model.quality}{model.bundled ? " / Protected bundle" : ""}
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
                          <div className="flex flex-wrap justify-end gap-2">
                            {(model.can_download || model.can_resume) && (
                              <button
                                type="button"
                                onClick={() => void handleDownload(model)}
                                disabled={anyBusy || running}
                                aria-label={`${model.can_resume ? "Resume" : "Download"} ${model.label}`}
                                className="inline-flex items-center gap-1 rounded-lg bg-accent px-2 py-1 text-xs font-medium text-white transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-60"
                              >
                                {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
                                {model.can_resume ? "Resume" : "Download"}
                              </button>
                            )}
                            {native && model.can_cancel && (
                              <button type="button" onClick={() => void handleCancel(model)} disabled={cancellingModelId !== null || (anyBusy && qualificationModelId !== model.model_id)}
                                aria-label={`Cancel ${model.label} download or verification`}
                                className="rounded-lg px-2 py-1 text-xs text-gray-200 hover:bg-surface-overlay disabled:opacity-60">{cancellingModelId === model.model_id ? "Pausing…" : "Cancel"}</button>
                            )}
                            {native && model.can_verify && (
                              <button type="button" onClick={() => void handleVerify(model)} disabled={anyBusy}
                                aria-label={`Verify ${model.label}`}
                                className="rounded-lg px-2 py-1 text-xs text-gray-200 hover:bg-surface-overlay disabled:opacity-60">Verify</button>
                            )}
                            {model.can_remove && !model.bundled && (
                              <button
                                type="button"
                                onClick={() => void handleRemove(model)}
                                disabled={anyBusy}
                                className="rounded-lg p-1.5 text-gray-500 transition-colors hover:bg-surface-overlay hover:text-red-300 disabled:cursor-not-allowed disabled:opacity-60"
                                aria-label={`Remove ${model.label}`}
                              >
                                {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                              </button>
                            )}
                          </div>
                        </div>
                      </div>

                      {native && model.size_bytes != null && (
                        <p className="mt-2 text-xs text-gray-400">
                          {exactBytes(model.download_bytes_downloaded)} retained / {exactBytes(model.size_bytes)} total
                        </p>
                      )}
                      {model.download_message && <p className="mt-2 text-xs text-gray-300">{model.download_message}</p>}
                      {model.download_error && <p className="mt-2 text-xs text-red-200">{model.download_error}</p>}
                      {model.file_path && <p className="mt-2 break-all text-xs text-gray-400">{model.file_path}</p>}
                      {running && model.download_progress_percent !== null && (
                        <div role="progressbar" aria-label={`${model.label}: ${formatModelState(model)}`} aria-valuemin={0} aria-valuemax={100} aria-valuenow={model.download_progress_percent ?? 0} className="mt-3 h-1.5 overflow-hidden rounded-full bg-surface-overlay">
                          <div
                            className="h-full rounded-full bg-accent"
                            style={{ width: `${Math.min(100, Math.max(2, model.download_progress_percent))}%` }}
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
                  disabled={saving || busyModelId !== null || !settings || !catalog || (native && hasRunningDownload)}
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
