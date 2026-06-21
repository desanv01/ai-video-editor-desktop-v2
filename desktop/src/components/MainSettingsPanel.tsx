import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import {
  AlertTriangle,
  Check,
  ChevronRight,
  Cloud,
  Cpu,
  Download,
  Eye,
  FolderOpen,
  Gauge,
  KeyRound,
  Layers3,
  Loader2,
  Map,
  Monitor,
  Palette,
  RefreshCw,
  RotateCcw,
  Save,
  Settings2,
  Sparkles,
  Trash2,
  X,
} from "lucide-react";
import * as api from "../lib/api";
import type {
  AICapabilitySettings,
  AIProcessingMode,
  AIProviderKind,
  APIKeyStatus,
  AppSettings,
  BackendAISettings,
  BackendAISettingsUpdate,
  ExportPreset,
  ExportPresetCatalog,
  LocalTranscriptionModel,
  LocalTranscriptionModelCatalog,
} from "../types/api";

interface Props {
  isOpen: boolean;
  onClose: () => void;
}

type SettingsTabId = "ai" | "providers" | "export" | "appearance" | "models" | "tours";
type CapabilityDrafts = Record<AIProviderKind, AICapabilitySettings>;
type LocalPathDrafts = Record<AIProviderKind, string>;

const CAPABILITY_ORDER: AIProviderKind[] = [
  "transcription",
  "chat",
  "embedding",
  "vision",
  "local_runtime",
];

const CAPABILITY_LABELS: Record<AIProviderKind, string> = {
  transcription: "Transcription",
  chat: "Planning",
  embedding: "Embeddings",
  vision: "Vision",
  local_runtime: "Local runtime",
};

const API_PROVIDER_OPTIONS: Partial<Record<AIProviderKind, { value: string; label: string }[]>> = {
  transcription: [
    { value: "voxtral", label: "Mistral Voxtral" },
    { value: "whisper", label: "OpenAI Whisper" },
  ],
  chat: [
    { value: "deepseek-v4-flash", label: "DeepSeek V4 Flash" },
    { value: "deepseek-v4-pro", label: "DeepSeek V4 Pro" },
  ],
  embedding: [
    { value: "openai-embeddings", label: "OpenAI Embeddings" },
  ],
  vision: [
    { value: "vision-unconfigured", label: "Not configured" },
    { value: "qwen-3.7-plus", label: "Qwen 3.7 Plus (Alibaba)" },
    { value: "deepseek-v4-flash", label: "DeepSeek V4 Flash" },
  ],
};

const LOCAL_PROVIDER_OPTIONS: Partial<Record<AIProviderKind, { value: string; label: string }[]>> = {
  transcription: [
    { value: "whisper-cpp", label: "whisper.cpp" },
  ],
  chat: [
    { value: "ollama-chat", label: "Ollama" },
    { value: "llama-cpp-chat", label: "llama.cpp" },
  ],
  embedding: [
    { value: "local-embeddings", label: "Local embeddings" },
  ],
  vision: [
    { value: "local-vision", label: "Local vision" },
  ],
  local_runtime: [
    { value: "local-runtime-unconfigured", label: "Not configured" },
    { value: "ollama", label: "Ollama" },
    { value: "llama-cpp", label: "llama.cpp" },
  ],
};

const MODE_OPTIONS: {
  value: AIProcessingMode;
  label: string;
  icon: LucideIcon;
}[] = [
  { value: "hybrid", label: "Hybrid", icon: Layers3 },
  { value: "local", label: "Local", icon: Cpu },
  { value: "api", label: "API", icon: Cloud },
];

const SETTINGS_TABS: {
  id: SettingsTabId;
  label: string;
  icon: LucideIcon;
}[] = [
  { id: "ai", label: "AI Mode", icon: Settings2 },
  { id: "providers", label: "Providers", icon: KeyRound },
  { id: "models", label: "Local Models", icon: Cpu },
  { id: "export", label: "Export", icon: FolderOpen },
  { id: "appearance", label: "Appearance", icon: Palette },
  { id: "tours", label: "Tours", icon: Map },
];

const LOCAL_ONLY_TABS: SettingsTabId[] = ["export", "appearance", "tours"];

const DEFAULT_CAPABILITY: AICapabilitySettings = {
  mode: "hybrid",
  api_provider_id: null,
  local_provider_id: null,
  fallback_enabled: true,
  hybrid_fallback_order: ["local", "api"],
};

function defaultCapability(kind: AIProviderKind): AICapabilitySettings {
  if (kind === "local_runtime") {
    return {
      ...DEFAULT_CAPABILITY,
      mode: "local",
      hybrid_fallback_order: ["local"],
      local_provider_id: "local-runtime-unconfigured",
    };
  }
  return { ...DEFAULT_CAPABILITY };
}

function normalizeCapabilities(settings: BackendAISettings): CapabilityDrafts {
  return CAPABILITY_ORDER.reduce((drafts, kind) => {
    drafts[kind] = {
      ...defaultCapability(kind),
      ...(settings.capabilities[kind] ?? {}),
    };
    return drafts;
  }, {} as CapabilityDrafts);
}

function normalizeLocalPaths(settings: BackendAISettings): LocalPathDrafts {
  return CAPABILITY_ORDER.reduce((drafts, kind) => {
    drafts[kind] = settings.local_model_paths[kind] ?? "";
    return drafts;
  }, {} as LocalPathDrafts);
}

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
  if (model.active && model.downloaded) return "Active";
  return model.downloaded ? "Ready" : "Not downloaded";
}

function localStorageSettings(): AppSettings {
  const raw = window.localStorage.getItem("ai-video-editor.settings");
  if (raw) {
    try {
      return { ...defaultAppSettings(), ...JSON.parse(raw) };
    } catch {
      return defaultAppSettings();
    }
  }
  return defaultAppSettings();
}

function defaultAppSettings(): AppSettings {
  return {
    backend_url: "http://localhost:8000",
    asr_provider: "voxtral",
    domain_terms: [],
    auto_accept_threshold: 0.85,
    export_folder: null,
    appearance_theme: "dark",
    interface_density: "comfortable",
    guided_tours_enabled: true,
    guided_hints_enabled: true,
  };
}

async function loadDesktopSettings(): Promise<AppSettings> {
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    return { ...defaultAppSettings(), ...(await invoke<AppSettings>("load_settings")) };
  } catch {
    return localStorageSettings();
  }
}

async function saveDesktopSettings(settings: AppSettings): Promise<void> {
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    await invoke("save_settings", { settings });
  } catch {
    window.localStorage.setItem("ai-video-editor.settings", JSON.stringify(settings));
  }
}

async function chooseDirectory(currentValue: string): Promise<string | null> {
  try {
    const { open } = await import("@tauri-apps/plugin-dialog");
    const selected = await open({
      directory: true,
      multiple: false,
      defaultPath: currentValue || undefined,
      title: "Select export folder",
    });
    return typeof selected === "string" ? selected : null;
  } catch {
    return window.prompt("Export folder", currentValue) ?? null;
  }
}

export function MainSettingsPanel({ isOpen, onClose }: Props) {
  const [activeTab, setActiveTab] = useState<SettingsTabId>("ai");
  const [backendSettings, setBackendSettings] = useState<BackendAISettings | null>(null);
  const [desktopSettings, setDesktopSettings] = useState<AppSettings>(defaultAppSettings());
  const [catalog, setCatalog] = useState<LocalTranscriptionModelCatalog | null>(null);
  const [exportCatalog, setExportCatalog] = useState<ExportPresetCatalog | null>(null);
  const [preferredMode, setPreferredMode] = useState<AIProcessingMode>("hybrid");
  const [fallbackEnabled, setFallbackEnabled] = useState(true);
  const [capabilities, setCapabilities] = useState<CapabilityDrafts | null>(null);
  const [localPaths, setLocalPaths] = useState<LocalPathDrafts | null>(null);
  const [selectedModelId, setSelectedModelId] = useState("small");
  const [apiKeyDrafts, setApiKeyDrafts] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [busyModelId, setBusyModelId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

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
      const nextDesktopSettings = await loadDesktopSettings();
      setDesktopSettings(nextDesktopSettings);

      const [nextBackendSettings, nextCatalog, nextExportCatalog] = await Promise.all([
        api.getAISettings(),
        api.getLocalTranscriptionModels(),
        api.getExportPresets(),
      ]);

      setBackendSettings(nextBackendSettings);
      setCatalog(nextCatalog);
      setExportCatalog(nextExportCatalog);
      setPreferredMode(nextBackendSettings.preferred_processing_mode);
      setFallbackEnabled(nextBackendSettings.fallback_enabled);
      setCapabilities(normalizeCapabilities(nextBackendSettings));
      setLocalPaths(normalizeLocalPaths(nextBackendSettings));
      setSelectedModelId(selectedModelIdFrom(nextBackendSettings, nextCatalog));
      setApiKeyDrafts({});
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  const refreshCatalog = async (): Promise<LocalTranscriptionModelCatalog | null> => {
    try {
      const nextCatalog = await api.getLocalTranscriptionModels();
      setCatalog(nextCatalog);
      return nextCatalog;
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      return null;
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

  const updateCapability = (
    kind: AIProviderKind,
    patch: Partial<AICapabilitySettings>,
  ) => {
    setCapabilities(prev => {
      if (!prev) return prev;
      return {
        ...prev,
        [kind]: {
          ...prev[kind],
          ...patch,
        },
      };
    });
  };

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
      const nextCatalog = await refreshCatalog();
      if (nextCatalog) {
        setSelectedModelId(
          nextCatalog.models.find(candidate => candidate.active)?.model_id
            ?? nextCatalog.active_model_id
            ?? nextCatalog.models[0]?.model_id
            ?? "small",
        );
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusyModelId(null);
    }
  };

  const handleChooseExportFolder = async () => {
    const selected = await chooseDirectory(desktopSettings.export_folder ?? "");
    if (selected !== null) {
      setDesktopSettings(prev => ({ ...prev, export_folder: selected.trim() || null }));
    }
  };

  const handleResetTours = () => {
    setDesktopSettings(prev => ({
      ...prev,
      guided_tours_enabled: true,
      guided_hints_enabled: true,
    }));
    setNotice("Tour preferences reset.");
  };

  const handleUseEnvKey = async (provider: string, status: APIKeyStatus) => {
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const next = await api.updateAISettings({
        api_keys: {
          [provider]: { use_env: true, env_var: status.env_var },
        },
      });
      setBackendSettings(next);
      setNotice(`${providerLabel(provider)} now uses environment configuration.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const handleClearKey = async (provider: string, status: APIKeyStatus) => {
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const next = await api.updateAISettings({
        api_keys: {
          [provider]: { clear: true, env_var: status.env_var },
        },
      });
      setBackendSettings(next);
      setApiKeyDrafts(prev => ({ ...prev, [provider]: "" }));
      setNotice(`${providerLabel(provider)} key cleared.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const handleSave = async () => {
    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      let nextBackendSettings: BackendAISettings | null = null;
      let nextDesktopSettings: AppSettings = desktopSettings;

      if (backendSettings && capabilities && localPaths && catalog) {
        const selected = catalog.models.find(model => model.model_id === selectedModelId);
        const localModelPaths = {
          ...localPaths,
          transcription: selected?.file_path ?? localPaths.transcription,
        };
        const apiKeys = Object.fromEntries(
          Object.entries(apiKeyDrafts)
            .map(([provider, value]) => [provider, value.trim()] as const)
            .filter(([, value]) => value.length > 0)
            .map(([provider, value]) => [provider, { api_key: value }]),
        );
        const payload: BackendAISettingsUpdate = {
          preferred_processing_mode: preferredMode,
          fallback_enabled: fallbackEnabled,
          capabilities,
          local_model_paths: localModelPaths,
          local_model_ids: {
            transcription: selectedModelId,
          },
          domain_terms: desktopSettings.domain_terms,
        };
        if (Object.keys(apiKeys).length > 0) {
          payload.api_keys = apiKeys;
        }

        nextBackendSettings = await api.updateAISettings(payload);
        nextDesktopSettings = {
          ...desktopSettings,
          asr_provider: capabilities.transcription.api_provider_id ?? desktopSettings.asr_provider,
        };
      }

      await saveDesktopSettings(nextDesktopSettings);

      if (nextBackendSettings) {
        setBackendSettings(nextBackendSettings);
      }
      setDesktopSettings(nextDesktopSettings);
      setApiKeyDrafts({});
      setNotice("Settings saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const ready = backendSettings && capabilities && localPaths;
  const localOnlyTab = LOCAL_ONLY_TABS.includes(activeTab);
  const canSave = Boolean(ready || localOnlyTab);

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/50">
      <aside className="flex h-full w-full max-w-[980px] flex-col border-l border-surface-border bg-surface-raised shadow-2xl">
        <div className="flex items-center justify-between border-b border-surface-border px-5 py-4">
          <div>
            <p className="text-xs uppercase tracking-wide text-gray-500">Workspace Settings</p>
            <h2 className="text-base font-semibold text-gray-100">AI Video Editor</h2>
          </div>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={loadPanel}
              className="inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-xs text-gray-400 transition-colors hover:bg-surface-overlay hover:text-gray-100"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              Refresh
            </button>
            <button
              type="button"
              onClick={onClose}
              className="rounded-md p-2 text-gray-400 transition-colors hover:bg-surface-overlay hover:text-gray-100"
              aria-label="Close settings"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {loading ? (
          <div className="flex flex-1 items-center justify-center gap-3 text-sm text-gray-300">
            <Loader2 className="h-5 w-5 animate-spin text-accent" />
            Loading settings...
          </div>
        ) : (
          <div className="flex min-h-0 flex-1">
            <nav className="w-56 shrink-0 border-r border-surface-border bg-surface px-3 py-4">
              <div className="space-y-1">
                {SETTINGS_TABS.map(tab => {
                  const Icon = tab.icon;
                  const active = activeTab === tab.id;
                  return (
                    <button
                      key={tab.id}
                      type="button"
                      onClick={() => setActiveTab(tab.id)}
                      className={`flex w-full items-center justify-between gap-3 rounded-md px-3 py-2 text-left text-sm transition-colors ${
                        active ? "bg-accent/15 text-white" : "text-gray-400 hover:bg-surface-overlay hover:text-gray-100"
                      }`}
                    >
                      <span className="flex min-w-0 items-center gap-2">
                        <Icon className="h-4 w-4 shrink-0" />
                        <span className="truncate">{tab.label}</span>
                      </span>
                      {active && <ChevronRight className="h-4 w-4 shrink-0" />}
                    </button>
                  );
                })}
              </div>

              <div className="mt-5 rounded-md border border-surface-border bg-surface-overlay p-3">
                <div className="flex items-center gap-2 text-xs font-semibold text-gray-200">
                  <Gauge className="h-3.5 w-3.5 text-accent" />
                  Global mode: {modeLabel(preferredMode)}
                </div>
                <p className="mt-2 text-xs leading-5 text-gray-500">
                  {fallbackEnabled ? "Fallback enabled" : "Fallback disabled"}
                </p>
              </div>
            </nav>

            <div className="min-w-0 flex-1 overflow-y-auto p-5">
              {(error || notice) && (
                <div className="mb-5 space-y-2">
                  {error && (
                    <StatusBox tone="danger" icon={AlertTriangle}>
                      {error}
                    </StatusBox>
                  )}
                  {notice && (
                    <StatusBox tone="success" icon={Check}>
                      {notice}
                    </StatusBox>
                  )}
                </div>
              )}

              {!ready && !localOnlyTab ? (
                <EmptyPanel />
              ) : (
                <>
                  {activeTab === "ai" && ready && (
                    <AISettingsTab
                      preferredMode={preferredMode}
                      fallbackEnabled={fallbackEnabled}
                      capabilities={capabilities}
                      onPreferredModeChange={setPreferredMode}
                      onFallbackEnabledChange={setFallbackEnabled}
                      onCapabilityChange={updateCapability}
                    />
                  )}

                  {activeTab === "providers" && ready && (
                    <ProvidersTab
                      settings={backendSettings}
                      apiKeyDrafts={apiKeyDrafts}
                      onApiKeyDraftChange={(provider, value) => setApiKeyDrafts(prev => ({ ...prev, [provider]: value }))}
                      onUseEnvKey={handleUseEnvKey}
                      onClearKey={handleClearKey}
                    />
                  )}

                  {activeTab === "models" && ready && (
                    <LocalModelsTab
                      catalog={catalog}
                      selectedModelId={selectedModelId}
                      busyModelId={busyModelId}
                      localPaths={localPaths}
                      onSelectedModelChange={setSelectedModelId}
                      onDownload={handleDownload}
                      onRemove={handleRemove}
                      onPathChange={(kind, value) => setLocalPaths(prev => prev ? { ...prev, [kind]: value } : prev)}
                    />
                  )}

                  {activeTab === "export" && (
                    <ExportTab
                      desktopSettings={desktopSettings}
                      exportCatalog={exportCatalog}
                      onDesktopSettingsChange={setDesktopSettings}
                      onChooseFolder={handleChooseExportFolder}
                    />
                  )}

                  {activeTab === "appearance" && (
                    <AppearanceTab
                      desktopSettings={desktopSettings}
                      onDesktopSettingsChange={setDesktopSettings}
                    />
                  )}

                  {activeTab === "tours" && (
                    <ToursTab
                      desktopSettings={desktopSettings}
                      onDesktopSettingsChange={setDesktopSettings}
                      onResetTours={handleResetTours}
                    />
                  )}
                </>
              )}
            </div>
          </div>
        )}

        <div className="flex items-center justify-between gap-4 border-t border-surface-border px-5 py-4">
          <div className="text-xs text-gray-500">
            {selectedModel ? `${selectedModel.label} selected` : "No local transcription model selected"}
          </div>
          <button
            type="button"
            onClick={handleSave}
            disabled={saving || !canSave}
            className="inline-flex items-center gap-2 rounded-md bg-accent px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-60"
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            Save Settings
          </button>
        </div>
      </aside>
    </div>
  );
}

function AISettingsTab({
  preferredMode,
  fallbackEnabled,
  capabilities,
  onPreferredModeChange,
  onFallbackEnabledChange,
  onCapabilityChange,
}: {
  preferredMode: AIProcessingMode;
  fallbackEnabled: boolean;
  capabilities: CapabilityDrafts;
  onPreferredModeChange: (mode: AIProcessingMode) => void;
  onFallbackEnabledChange: (enabled: boolean) => void;
  onCapabilityChange: (kind: AIProviderKind, patch: Partial<AICapabilitySettings>) => void;
}) {
  return (
    <PanelStack>
      <SectionHeader title="AI Mode" icon={Settings2} />
      <ModePicker value={preferredMode} onChange={onPreferredModeChange} />
      <ToggleRow
        label="Provider fallback"
        detail="Allow another configured route when the first provider fails."
        checked={fallbackEnabled}
        icon={<Layers3 className="h-4 w-4 text-accent" />}
        onChange={onFallbackEnabledChange}
      />

      <SectionHeader title="Capability Routing" icon={Gauge} />
      <div className="space-y-3">
        {CAPABILITY_ORDER.map(kind => (
          <CapabilityRow
            key={kind}
            kind={kind}
            value={capabilities[kind]}
            onChange={(patch) => onCapabilityChange(kind, patch)}
          />
        ))}
      </div>
    </PanelStack>
  );
}

function ProvidersTab({
  settings,
  apiKeyDrafts,
  onApiKeyDraftChange,
  onUseEnvKey,
  onClearKey,
}: {
  settings: BackendAISettings;
  apiKeyDrafts: Record<string, string>;
  onApiKeyDraftChange: (provider: string, value: string) => void;
  onUseEnvKey: (provider: string, status: APIKeyStatus) => void;
  onClearKey: (provider: string, status: APIKeyStatus) => void;
}) {
  // Always show these API providers even if no key is configured yet
  const knownProviders = ["mistral", "openai", "deepseek", "alibaba"];
  const apiKeys: [string, APIKeyStatus][] = knownProviders.map(provider => {
    const existing = settings.api_keys[provider];
    return [
      provider,
      existing ?? {
        has_key: false,
        source: "encrypted_db" as const,
        display_value: null,
        env_var: `${provider.toUpperCase()}_API_KEY`,
        provider,
        updated_at: null,
      },
    ];
  });

  return (
    <PanelStack>
      <SectionHeader title="API Providers" icon={Cloud} />
      <div className="grid gap-3">
        {apiKeys.map(([provider, status]) => (
          <div key={provider} className="rounded-md border border-surface-border bg-surface p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <h3 className="text-sm font-semibold text-gray-100">{providerLabel(provider)}</h3>
                <p className="mt-1 text-xs text-gray-500">
                  {status.source === "env" ? status.env_var : "Encrypted desktop setting"}
                </p>
              </div>
              <span className={`rounded px-2 py-1 text-xs font-semibold ${
                status.has_key ? "bg-emerald-500/15 text-emerald-300" : "bg-surface-overlay text-gray-500"
              }`}>
                {status.has_key ? status.display_value ?? "Configured" : "Missing"}
              </span>
            </div>
            <div className="mt-4 grid gap-2 sm:grid-cols-[1fr_auto_auto]">
              <input
                type="password"
                value={apiKeyDrafts[provider] ?? ""}
                onChange={event => onApiKeyDraftChange(provider, event.target.value)}
                placeholder="New API key"
                className="min-w-0 rounded-md border border-surface-border bg-surface-overlay px-3 py-2 text-sm text-gray-100 outline-none focus:border-accent"
              />
              <button
                type="button"
                onClick={() => onUseEnvKey(provider, status)}
                className="inline-flex items-center justify-center gap-2 rounded-md bg-surface-overlay px-3 py-2 text-sm text-gray-200 transition-colors hover:bg-surface-border"
              >
                <Monitor className="h-4 w-4" />
                Env
              </button>
              <button
                type="button"
                onClick={() => onClearKey(provider, status)}
                className="inline-flex items-center justify-center gap-2 rounded-md bg-surface-overlay px-3 py-2 text-sm text-gray-200 transition-colors hover:bg-surface-border hover:text-red-300"
              >
                <Trash2 className="h-4 w-4" />
                Clear
              </button>
            </div>
          </div>
        ))}
      </div>
    </PanelStack>
  );
}

function LocalModelsTab({
  catalog,
  selectedModelId,
  busyModelId,
  localPaths,
  onSelectedModelChange,
  onDownload,
  onRemove,
  onPathChange,
}: {
  catalog: LocalTranscriptionModelCatalog | null;
  selectedModelId: string;
  busyModelId: string | null;
  localPaths: LocalPathDrafts;
  onSelectedModelChange: (modelId: string) => void;
  onDownload: (model: LocalTranscriptionModel) => void;
  onRemove: (model: LocalTranscriptionModel) => void;
  onPathChange: (kind: AIProviderKind, value: string) => void;
}) {
  return (
    <PanelStack>
      <SectionHeader title="Local Whisper" icon={Cpu} />
      {catalog && (
        <div className={`rounded-md border px-3 py-2 text-xs ${
          catalog.runtime_configured
            ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-200"
            : "border-yellow-500/30 bg-yellow-500/10 text-yellow-100"
        }`}>
          <div className="font-semibold">
            Runtime {catalog.runtime_configured ? "ready" : "missing"}
          </div>
          <div className="mt-1 leading-5 text-gray-300">
            {catalog.runtime_configured
              ? `Using ${catalog.runtime_binary_path ?? "configured whisper.cpp binary"}`
              : catalog.runtime_message || "Set WHISPER_CPP_BINARY_PATH to whisper-cli.exe or put whisper-cli on PATH."}
          </div>
        </div>
      )}
      <div className="space-y-2">
        {catalog?.models.map(model => {
          const selected = model.model_id === selectedModelId;
          const busy = busyModelId === model.model_id;
          const running = model.status === "queued" || model.status === "downloading";
          return (
            <div
              key={model.model_id}
              className={`rounded-md border p-3 transition-colors ${
                selected ? "border-accent bg-accent/10" : "border-surface-border bg-surface"
              }`}
            >
              <div className="flex items-start justify-between gap-3">
                <button
                  type="button"
                  onClick={() => onSelectedModelChange(model.model_id)}
                  className="flex min-w-0 flex-1 items-start gap-3 text-left"
                >
                  <span className={`mt-1 h-3 w-3 rounded-full border ${
                    selected ? "border-accent bg-accent" : "border-gray-500"
                  }`} />
                  <span className="min-w-0">
                    <span className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium text-gray-100">{model.label}</span>
                      {model.active && model.downloaded && (
                        <span className="rounded bg-emerald-500/15 px-1.5 py-0.5 text-[11px] font-semibold uppercase text-emerald-300">
                          Active
                        </span>
                      )}
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
                        onClick={() => onDownload(model)}
                        disabled={busy || running}
                        className="inline-flex items-center gap-1 rounded-md bg-accent px-2 py-1 text-xs font-medium text-white transition-colors hover:bg-accent-hover disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Download className="h-3.5 w-3.5" />}
                        Download
                      </button>
                    )}
                    {model.can_remove && (
                      <button
                        type="button"
                        onClick={() => onRemove(model)}
                        disabled={busy}
                        className="inline-flex items-center gap-1 rounded-md bg-red-500 px-2 py-1 text-xs font-medium text-white transition-colors hover:bg-red-400 disabled:cursor-not-allowed disabled:opacity-60"
                        aria-label={`Remove ${model.label}`}
                      >
                        {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Trash2 className="h-3.5 w-3.5" />}
                        Remove
                      </button>
                    )}
                  </div>
                </div>
              </div>

              {running && model.download_progress_percent !== null && (
                <div className="mt-3">
                  <div className="h-1.5 overflow-hidden rounded-full bg-surface-overlay">
                    <div
                      className="h-full rounded-full bg-accent"
                      style={{ width: `${Math.max(2, model.download_progress_percent)}%` }}
                    />
                  </div>
                  <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-xs text-gray-500">
                    <span>
                      {formatBytes(model.download_bytes_downloaded)}
                      {` / ${formatBytes(model.download_total_bytes) ?? model.size}`}
                    </span>
                    <span>
                      {formatDownloadSpeed(model.download_speed_bytes_per_second)}
                      {model.download_eta_seconds !== null ? ` - ${formatEta(model.download_eta_seconds)} left` : ""}
                    </span>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>

      <SectionHeader title="Local Paths" icon={FolderOpen} />
      <div className="grid gap-3">
        {CAPABILITY_ORDER.filter(kind => kind !== "transcription").map(kind => (
          <label key={kind} className="grid gap-1.5">
            <span className="text-xs font-semibold text-gray-300">{CAPABILITY_LABELS[kind]}</span>
            <input
              value={localPaths[kind]}
              onChange={event => onPathChange(kind, event.target.value)}
              placeholder={kind === "local_runtime" ? "Path to whisper-cli.exe or local runtime" : "Model or runtime path"}
              className="rounded-md border border-surface-border bg-surface px-3 py-2 text-sm text-gray-100 outline-none focus:border-accent"
            />
          </label>
        ))}
      </div>
    </PanelStack>
  );
}

function ExportTab({
  desktopSettings,
  exportCatalog,
  onDesktopSettingsChange,
  onChooseFolder,
}: {
  desktopSettings: AppSettings;
  exportCatalog: ExportPresetCatalog | null;
  onDesktopSettingsChange: (settings: AppSettings) => void;
  onChooseFolder: () => void;
}) {
  const defaultPresets = exportCatalog
    ? prioritizedExportPresets(exportCatalog)
    : [];

  return (
    <PanelStack>
      <SectionHeader title="Export Folder" icon={FolderOpen} />
      <div className="rounded-md border border-surface-border bg-surface p-4">
        <label className="grid gap-2">
          <span className="text-xs font-semibold text-gray-300">Default folder</span>
          <div className="grid gap-2 sm:grid-cols-[1fr_auto]">
            <input
              value={desktopSettings.export_folder ?? ""}
              onChange={event => onDesktopSettingsChange({ ...desktopSettings, export_folder: event.target.value || null })}
              placeholder="Choose an export folder"
              className="min-w-0 rounded-md border border-surface-border bg-surface-overlay px-3 py-2 text-sm text-gray-100 outline-none focus:border-accent"
            />
            <button
              type="button"
              onClick={onChooseFolder}
              className="inline-flex items-center justify-center gap-2 rounded-md bg-surface-overlay px-3 py-2 text-sm text-gray-200 transition-colors hover:bg-surface-border"
            >
              <FolderOpen className="h-4 w-4" />
              Browse
            </button>
          </div>
        </label>
      </div>
      <SectionHeader title="Export Defaults" icon={Download} />
      {defaultPresets.length > 0 ? (
        <div className="grid gap-2 sm:grid-cols-3">
          {defaultPresets.map(preset => (
            <div key={preset.id} className="rounded-md border border-surface-border bg-surface px-3 py-3">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="truncate text-sm font-semibold text-gray-100">{preset.label}</div>
                  <div className="mt-1 text-xs text-gray-500">{exportPresetSummary(preset)}</div>
                </div>
                {preset.id === exportCatalog?.default_preset_id && (
                  <span className="shrink-0 rounded bg-accent/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-accent">
                    Default
                  </span>
                )}
              </div>
              <p className="mt-2 line-clamp-2 text-xs leading-5 text-gray-500">{preset.description}</p>
            </div>
          ))}
        </div>
      ) : (
        <div className="rounded-md border border-surface-border bg-surface px-3 py-3 text-sm text-gray-500">
          Export presets will appear when the backend catalog is available.
        </div>
      )}
    </PanelStack>
  );
}

function AppearanceTab({
  desktopSettings,
  onDesktopSettingsChange,
}: {
  desktopSettings: AppSettings;
  onDesktopSettingsChange: (settings: AppSettings) => void;
}) {
  return (
    <PanelStack>
      <SectionHeader title="Theme" icon={Palette} />
      <SegmentedControl
        value={desktopSettings.appearance_theme ?? "dark"}
        options={[
          { value: "dark", label: "Dark", icon: Monitor },
          { value: "system", label: "System", icon: Eye },
          { value: "light", label: "Light", icon: Sparkles },
        ]}
        onChange={(value) => onDesktopSettingsChange({ ...desktopSettings, appearance_theme: value })}
      />
      <SectionHeader title="Density" icon={Gauge} />
      <SegmentedControl
        value={desktopSettings.interface_density ?? "comfortable"}
        options={[
          { value: "comfortable", label: "Comfortable", icon: Layers3 },
          { value: "compact", label: "Compact", icon: Gauge },
        ]}
        onChange={(value) => onDesktopSettingsChange({ ...desktopSettings, interface_density: value })}
      />
    </PanelStack>
  );
}

function ToursTab({
  desktopSettings,
  onDesktopSettingsChange,
  onResetTours,
}: {
  desktopSettings: AppSettings;
  onDesktopSettingsChange: (settings: AppSettings) => void;
  onResetTours: () => void;
}) {
  return (
    <PanelStack>
      <SectionHeader title="Guided Tours" icon={Map} />
      <ToggleRow
        label="Editor tours"
        detail="Show guided workflow tours when new editing areas arrive."
        checked={desktopSettings.guided_tours_enabled ?? true}
        icon={<Map className="h-4 w-4 text-sky-300" />}
        onChange={(checked) => onDesktopSettingsChange({ ...desktopSettings, guided_tours_enabled: checked })}
      />
      <ToggleRow
        label="Context hints"
        detail="Show small guided hints in future workflow panels."
        checked={desktopSettings.guided_hints_enabled ?? true}
        icon={<Sparkles className="h-4 w-4 text-yellow-300" />}
        onChange={(checked) => onDesktopSettingsChange({ ...desktopSettings, guided_hints_enabled: checked })}
      />
      <button
        type="button"
        onClick={onResetTours}
        className="inline-flex items-center gap-2 rounded-md bg-surface-overlay px-3 py-2 text-sm text-gray-200 transition-colors hover:bg-surface-border"
      >
        <RotateCcw className="h-4 w-4" />
        Reset Tours
      </button>
    </PanelStack>
  );
}

function CapabilityRow({
  kind,
  value,
  onChange,
}: {
  kind: AIProviderKind;
  value: AICapabilitySettings;
  onChange: (patch: Partial<AICapabilitySettings>) => void;
}) {
  const apiOptions = API_PROVIDER_OPTIONS[kind] ?? [];
  const localOptions = LOCAL_PROVIDER_OPTIONS[kind] ?? [];

  return (
    <div className="rounded-md border border-surface-border bg-surface p-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h3 className="text-sm font-semibold text-gray-100">{CAPABILITY_LABELS[kind]}</h3>
        <label className="flex items-center gap-2 text-xs text-gray-400">
          <input
            type="checkbox"
            checked={value.fallback_enabled}
            onChange={event => onChange({ fallback_enabled: event.target.checked })}
            className="h-4 w-4 accent-accent"
          />
          Fallback
        </label>
      </div>
      <div className="grid gap-3 lg:grid-cols-[1fr_1fr_1fr]">
        <label className="grid gap-1.5">
          <span className="text-xs font-semibold text-gray-400">Mode</span>
          <select
            value={value.mode}
            onChange={event => onChange({ mode: event.target.value as AIProcessingMode })}
            className="rounded-md border border-surface-border bg-surface-overlay px-3 py-2 text-sm text-gray-100 outline-none focus:border-accent"
          >
            {MODE_OPTIONS.map(option => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </label>
        <ProviderSelect
          label="API provider"
          value={value.api_provider_id ?? ""}
          options={apiOptions}
          onChange={(nextValue) => onChange({ api_provider_id: nextValue || null })}
        />
        <ProviderSelect
          label="Local provider"
          value={value.local_provider_id ?? ""}
          options={localOptions}
          onChange={(nextValue) => onChange({ local_provider_id: nextValue || null })}
        />
      </div>
    </div>
  );
}

function ProviderSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: { value: string; label: string }[];
  onChange: (value: string) => void;
}) {
  const hasValue = value && !options.some(option => option.value === value);
  return (
    <label className="grid gap-1.5">
      <span className="text-xs font-semibold text-gray-400">{label}</span>
      <select
        value={value}
        onChange={event => onChange(event.target.value)}
        className="rounded-md border border-surface-border bg-surface-overlay px-3 py-2 text-sm text-gray-100 outline-none focus:border-accent"
      >
        <option value="">None</option>
        {hasValue && <option value={value}>{value}</option>}
        {options.map(option => (
          <option key={option.value} value={option.value}>{option.label}</option>
        ))}
      </select>
    </label>
  );
}

function ModePicker({ value, onChange }: { value: AIProcessingMode; onChange: (value: AIProcessingMode) => void }) {
  return (
    <div className="grid gap-2 sm:grid-cols-3">
      {MODE_OPTIONS.map(option => {
        const Icon = option.icon;
        const selected = value === option.value;
        return (
          <button
            key={option.value}
            type="button"
            onClick={() => onChange(option.value)}
            className={`flex items-center gap-3 rounded-md border px-3 py-3 text-left transition-colors ${
              selected ? "border-accent bg-accent/15 text-white" : "border-surface-border bg-surface text-gray-400 hover:border-gray-500"
            }`}
          >
            <Icon className="h-4 w-4 shrink-0" />
            <span className="text-sm font-semibold">{option.label}</span>
          </button>
        );
      })}
    </div>
  );
}

function SegmentedControl({
  value,
  options,
  onChange,
}: {
  value: string;
  options: { value: string; label: string; icon: LucideIcon }[];
  onChange: (value: string) => void;
}) {
  return (
    <div className="grid gap-2 sm:grid-cols-3">
      {options.map(option => {
        const Icon = option.icon;
        const selected = value === option.value;
        return (
          <button
            key={option.value}
            type="button"
            onClick={() => onChange(option.value)}
            className={`flex items-center justify-center gap-2 rounded-md border px-3 py-2 text-sm font-semibold transition-colors ${
              selected ? "border-accent bg-accent/15 text-white" : "border-surface-border bg-surface text-gray-400 hover:border-gray-500"
            }`}
          >
            <Icon className="h-4 w-4" />
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

function ToggleRow({
  label,
  detail,
  checked,
  icon,
  onChange,
}: {
  label: string;
  detail: string;
  checked: boolean;
  icon: ReactNode;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex cursor-pointer items-start gap-3 rounded-md border border-surface-border bg-surface p-3">
      <span className="mt-0.5">{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm font-semibold text-gray-100">{label}</span>
        <span className="mt-1 block text-xs leading-5 text-gray-500">{detail}</span>
      </span>
      <input
        type="checkbox"
        checked={checked}
        onChange={event => onChange(event.target.checked)}
        className="mt-1 h-4 w-4 accent-accent"
      />
    </label>
  );
}

function SectionHeader({ title, icon: Icon }: { title: string; icon: LucideIcon }) {
  return (
    <div className="flex items-center gap-2">
      <Icon className="h-4 w-4 text-accent" />
      <h3 className="text-sm font-semibold text-gray-100">{title}</h3>
    </div>
  );
}

function StatusBox({
  tone,
  icon: Icon,
  children,
}: {
  tone: "danger" | "success";
  icon: LucideIcon;
  children: ReactNode;
}) {
  const classes = tone === "danger"
    ? "border-red-500/40 bg-red-500/10 text-red-200"
    : "border-emerald-500/40 bg-emerald-500/10 text-emerald-100";

  return (
    <div className={`flex gap-3 rounded-md border p-3 text-sm ${classes}`}>
      <Icon className="mt-0.5 h-4 w-4 shrink-0" />
      <span>{children}</span>
    </div>
  );
}

function PanelStack({ children }: { children: ReactNode }) {
  return <div className="space-y-5">{children}</div>;
}

function EmptyPanel() {
  return (
    <div className="rounded-md border border-dashed border-surface-border bg-surface p-8 text-center text-sm text-gray-500">
      Settings are unavailable.
    </div>
  );
}

function providerLabel(provider: string): string {
  return {
    mistral: "Mistral",
    openai: "OpenAI",
    deepseek: "DeepSeek",
    alibaba: "Alibaba (Qwen)",
  }[provider] ?? provider;
}

function modeLabel(mode: AIProcessingMode): string {
  return MODE_OPTIONS.find(option => option.value === mode)?.label ?? mode;
}

function prioritizedExportPresets(catalog: ExportPresetCatalog): ExportPreset[] {
  const presets = catalog.groups.flatMap(group => group.presets);
  const preferredIds = [catalog.default_preset_id, "lms_mp4", "podcast_audio"];
  const preferred = preferredIds
    .map(id => presets.find(preset => preset.id === id))
    .filter((preset): preset is ExportPreset => Boolean(preset));
  const fallback = presets.filter(preset => !preferredIds.includes(preset.id));
  return [...preferred, ...fallback].slice(0, 3);
}

function exportPresetSummary(preset: ExportPreset): string {
  if (preset.audio_only) {
    return `${preset.container.toUpperCase()} ${preset.audio_codec.toUpperCase()} ${preset.audio_bitrate}`;
  }
  const size = preset.width && preset.height ? `${preset.width}x${preset.height}` : preset.aspect_ratio ?? "video";
  return `${size} ${preset.video_codec?.toUpperCase() ?? "VIDEO"} / ${preset.audio_codec.toUpperCase()}`;
}

function formatBytes(value: number | null | undefined): string | null {
  if (value === null || value === undefined) return null;
  if (value <= 0) return "0 MB";
  const units = ["B", "KB", "MB", "GB"];
  let nextValue = value;
  let unitIndex = 0;
  while (nextValue >= 1024 && unitIndex < units.length - 1) {
    nextValue /= 1024;
    unitIndex += 1;
  }
  const precision = nextValue >= 10 || unitIndex === 0 ? 0 : 1;
  return `${nextValue.toFixed(precision)} ${units[unitIndex]}`;
}

function formatDownloadSpeed(value: number | null | undefined): string {
  const formatted = formatBytes(value);
  return formatted ? `${formatted}/s` : "Calculating speed";
}

function formatEta(value: number): string {
  if (!Number.isFinite(value) || value < 0) return "unknown";
  if (value < 60) return `${Math.max(1, Math.round(value))}s`;
  const minutes = Math.floor(value / 60);
  const seconds = Math.round(value % 60);
  if (minutes < 60) return `${minutes}m ${seconds}s`;
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  return `${hours}h ${remainingMinutes}m`;
}
