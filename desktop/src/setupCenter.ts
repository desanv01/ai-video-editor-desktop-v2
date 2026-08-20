import { invoke } from "@tauri-apps/api/core";
import type {
  ComponentProgress,
  ComponentStatusResult,
} from "./componentManager.ts";
import type { SupervisorStatus } from "./desktopV2.ts";

export const REQUIRED_COMPONENT_IDS = ["aive-engine", "ffmpeg"] as const;
export const OPTIONAL_COMPONENT_IDS = ["local-transcription", "model-pack", "render-pack"] as const;

export type SetupStage =
  | "welcome"
  | "system-check"
  | "choose-components"
  | "review"
  | "download"
  | "verify"
  | "activate"
  | "readiness"
  | "complete"
  | "management"
  | "diagnostics";

export type CatalogAvailability = "available" | "catalog-only" | "unavailable";

export interface SetupCatalogEntry {
  componentId: string;
  displayName: string;
  required: boolean;
  availability: CatalogAvailability;
  description: string;
  artifactBytes: number;
  licenseVersion: string;
  licenseName: string;
  sourceUrl: string | null;
  unavailableReason: string | null;
  manifest: Record<string, unknown> | null;
}

export interface SetupCatalog {
  schemaVersion: "desktop.setup-catalog.v1";
  catalogId: string;
  channel: "stable" | "beta" | "nightly";
  generatedAt: string;
  expiresAt: string;
  entries: SetupCatalogEntry[];
  signature: { algorithm: string; keyId: string; value: string };
}

export interface SetupCatalogInfo {
  catalog: SetupCatalog;
  source: "production" | "offline-import";
  verifiedAtEpochMs: number;
  path: string;
}

export interface SetupState {
  schemaVersion: "desktop.setup-state.v1";
  selectedOptionalPacks: string[];
  acceptedLicenseVersions: Record<string, string>;
  catalogChannel: "stable" | "beta" | "nightly";
  lastSuccessfulSetup: string | null;
  incompleteOperationIds: Record<string, string>;
  onboardingCompleted: boolean;
  updatedAtEpochMs: number;
}

export interface SetupImportResult {
  catalog: SetupCatalogInfo;
  importedManifestIds: string[];
  catalogOnlyIds: string[];
}

export interface SetupSystemCheck {
  id: string;
  label: string;
  severity: "pass" | "info" | "warning" | "error";
  explanation: string;
  remediation: string;
  technicalDetail: string | null;
}

export interface SetupSystemChecksResult {
  schemaVersion: "desktop.setup-system-checks.v1";
  generatedAtEpochMs: number;
  supported: boolean;
  processElevated: boolean;
  architecture: string;
  freeSpaceBytes: number | null;
  componentRoot: string;
  userStateRoot: string;
  checks: SetupSystemCheck[];
}

export interface SetupCatalogConfiguration {
  channel: "stable" | "beta" | "nightly";
  productionUrlConfigured: boolean;
  productionUrl: string | null;
  offlineImportSupported: boolean;
  trustPolicy: string;
}

export interface SetupError {
  code: string;
  message: string;
  retryable: boolean;
  remediationCodes: string[];
  technicalDetail?: string;
}

export const DEFAULT_COMPONENT_CARDS: ReadonlyArray<Pick<SetupCatalogEntry, "componentId" | "displayName" | "required" | "description">> = [
  {
    componentId: "aive-engine",
    displayName: "Core engine",
    required: true,
    description: "The local authenticated engine that powers projects, imports, processing, and rendering.",
  },
  {
    componentId: "ffmpeg",
    displayName: "FFmpeg",
    required: true,
    description: "The pinned media toolchain used by the engine for safe encode, decode, and probe operations.",
  },
  {
    componentId: "local-transcription",
    displayName: "Local transcription pack",
    required: false,
    description: "Optional local speech models. This remains catalog-only until a signed artifact and supported runtime are released.",
  },
  {
    componentId: "model-pack",
    displayName: "Local AI model pack",
    required: false,
    description: "Optional models for local workflows. No model is claimed as installed without a verified catalog manifest.",
  },
  {
    componentId: "render-pack",
    displayName: "Additional render pack",
    required: false,
    description: "Optional rendering capabilities, shown only when a signed release artifact is available.",
  },
];

export function defaultSetupState(now = Date.now()): SetupState {
  return {
    schemaVersion: "desktop.setup-state.v1",
    selectedOptionalPacks: [],
    acceptedLicenseVersions: {},
    catalogChannel: "stable",
    lastSuccessfulSetup: null,
    incompleteOperationIds: {},
    onboardingCompleted: false,
    updatedAtEpochMs: now,
  };
}

export function catalogEntryFor(
  catalog: SetupCatalog | null,
  componentId: string,
): SetupCatalogEntry | null {
  return catalog?.entries.find(entry => entry.componentId === componentId) ?? null;
}

export function catalogEntryIsInstallable(entry: SetupCatalogEntry | null): boolean {
  return entry?.availability === "available" && entry.manifest !== null;
}

export function requiredComponentsReady(statuses: ComponentStatusResult[]): boolean {
  return REQUIRED_COMPONENT_IDS.every(id => statuses.some(status => status.id === id && status.state === "active"));
}

export function optionalComponentIsSelected(state: SetupState, componentId: string): boolean {
  return state.selectedOptionalPacks.includes(componentId);
}

export function setupStepLabel(stage: SetupStage): string {
  switch (stage) {
    case "welcome": return "Welcome";
    case "system-check": return "System check";
    case "choose-components": return "Choose components";
    case "review": return "Review";
    case "download": return "Download";
    case "verify": return "Verify";
    case "activate": return "Install and activate";
    case "readiness": return "Engine readiness";
    case "complete": return "Complete";
    case "management": return "Component management";
    case "diagnostics": return "Diagnostics";
  }
}

export function setupStepIndex(stage: SetupStage): number {
  const stages: SetupStage[] = ["welcome", "system-check", "choose-components", "review", "download", "verify", "activate", "readiness", "complete"];
  return Math.max(0, stages.indexOf(stage));
}

export function aggregateProgress(
  selectedIds: string[],
  progressByOperation: Record<string, ComponentProgress>,
): { percent: number; bytesDownloaded: number; totalBytes: number; activeCount: number; message: string } {
  const latest = selectedIds
    .map(id => {
      const matching = Object.values(progressByOperation).filter(progress => progress.componentId === id);
      return matching[matching.length - 1];
    })
    .filter((progress): progress is ComponentProgress => Boolean(progress));
  if (latest.length === 0) {
    return { percent: 0, bytesDownloaded: 0, totalBytes: 0, activeCount: 0, message: "Waiting to begin" };
  }
  const totalBytes = latest.reduce((sum, progress) => sum + Math.max(progress.totalBytes, 0), 0);
  const bytesDownloaded = latest.reduce((sum, progress) => sum + Math.min(progress.bytesDownloaded, Math.max(progress.totalBytes, progress.bytesDownloaded)), 0);
  const percent = totalBytes > 0
    ? Math.min(100, Math.round((bytesDownloaded / totalBytes) * 1000) / 10)
    : Math.round(latest.reduce((sum, progress) => sum + progress.percent, 0) / latest.length);
  const current = latest.find(progress => !["active", "cancelled", "failed", "rolled-back"].includes(progress.state)) ?? latest[latest.length - 1];
  return {
    percent,
    bytesDownloaded,
    totalBytes,
    activeCount: latest.filter(progress => !["active", "cancelled", "failed", "rolled-back"].includes(progress.state)).length,
    message: current?.message ?? "Component operation complete",
  };
}

export function canLaunchEditor(supervisor: Pick<SupervisorStatus, "state" | "engineReady"> | null): boolean {
  return Boolean(supervisor?.engineReady && (supervisor.state === "ready" || supervisor.state === "degraded"));
}

export function normalizeSetupError(error: unknown): SetupError {
  if (typeof error === "object" && error !== null && "code" in error) {
    const candidate = error as Partial<SetupError>;
    const code = typeof candidate.code === "string" ? candidate.code : "SETUP_OPERATION_FAILED";
    return {
      code,
      message: friendlySetupMessage(code),
      retryable: candidate.retryable === true,
      remediationCodes: Array.isArray(candidate.remediationCodes)
        ? candidate.remediationCodes.filter((item): item is string => typeof item === "string")
        : [],
      technicalDetail: typeof candidate.message === "string" ? redactTechnicalDetail(candidate.message) : undefined,
    };
  }
  return {
    code: "SETUP_OPERATION_FAILED",
    message: "Setup could not finish this step.",
    retryable: true,
    remediationCodes: ["RETRY_OPERATION"],
    technicalDetail: error instanceof Error ? redactTechnicalDetail(error.message) : undefined,
  };
}

export function friendlySetupMessage(code: string): string {
  switch (code) {
    case "CATALOG_NETWORK_ERROR": return "The component catalog could not be reached. Check network, proxy, or TLS settings, or use Offline import.";
    case "HTTPS_REQUIRED": return "This source is not trusted for production. Production catalogs and artifacts must use HTTPS.";
    case "SIGNATURE_INVALID": return "The catalog or component signature could not be verified. Nothing was installed.";
    case "UNKNOWN_TRUST_KEY": return "This catalog was signed by an unknown publisher. Import a catalog from the approved release channel.";
    case "CATALOG_SCHEMA_INVALID": return "This catalog is not compatible with the installed shell.";
    case "CATALOG_EXPIRED": return "This setup catalog has expired. Refresh the production catalog or import a current signed offline catalog.";
    case "CATALOG_MANIFEST_MISMATCH": return "A catalog entry did not match its signed component manifest.";
    case "DISK_SPACE_LOW": return "There is not enough space to stage this component and retain rollback data.";
    case "ELEVATION_REQUIRED":
    case "STORAGE_NOT_WRITABLE": return "The component store is not writable. Approve the scoped UAC action or repair the per-machine component-store permissions.";
    case "DOWNLOAD_PAUSED": return "The download is paused and can be resumed from its saved staging cursor.";
    case "DOWNLOAD_CANCELLED": return "The operation was cancelled. Any resumable download state was retained for a later retry.";
    case "DOWNLOAD_HASH_MISMATCH":
    case "ARTIFACT_HASH_MISMATCH": return "The downloaded bytes do not match the signed artifact hash. The artifact was discarded.";
    case "OS_INCOMPATIBLE":
    case "ARCHITECTURE_INCOMPATIBLE":
    case "SHELL_VERSION_INCOMPATIBLE": return "This component is not compatible with this Windows installation.";
    case "SELF_TEST_FAILED": return "The component installed into staging but did not pass its signed self-test.";
    case "COMPONENT_VERSION_INCOMPATIBLE": return "The component failed integrity or readiness checks and needs repair or rollback.";
    case "ENGINE_CRASHED":
    case "ENGINE_CRASH_BUDGET_EXHAUSTED": return "The native engine stopped during startup. Retry, repair, or roll back the active component.";
    case "UAC_CANCELLED": return "The permission request was cancelled. No component was moved into the active slot.";
    case "OPERATION_RETRY_EXHAUSTED": return "Setup has exhausted its safe retries. Review Diagnostics before trying again.";
    default: return "Setup could not finish this step. Review the remediation guidance or open Diagnostics.";
  }
}

export function redactTechnicalDetail(value: string): string {
  return value
    .slice(0, 1200)
    .replace(/((?:password|passwd|secret|token|api[_-]?key|authorization)\s*[:=]\s*)[^\s,;&]+/gi, "$1[REDACTED]")
    .replace(/\bBearer\s+[^\s,;&]+/gi, "Bearer [REDACTED]")
    .replace(/\b(?:sk|pk)-[A-Za-z0-9_-]{12,}\b/g, "[REDACTED_TOKEN]")
    .replace(/\bghp_[A-Za-z0-9_-]{12,}\b/g, "[REDACTED_TOKEN]");
}

export function validateCatalogEnvelope(value: unknown): { valid: boolean; reason?: string } {
  if (typeof value !== "object" || value === null) return { valid: false, reason: "Catalog must be a JSON object." };
  const candidate = value as Partial<SetupCatalog>;
  if (candidate.schemaVersion !== "desktop.setup-catalog.v1") return { valid: false, reason: "Unsupported catalog version." };
  if (!Array.isArray(candidate.entries) || candidate.entries.length === 0) return { valid: false, reason: "Catalog has no component entries." };
  if (!candidate.signature || candidate.signature.algorithm !== "ed25519" || typeof candidate.signature.keyId !== "string") {
    return { valid: false, reason: "Catalog is missing its detached signature." };
  }
  const ids = candidate.entries.map(entry => entry.componentId);
  if (new Set(ids).size !== ids.length) return { valid: false, reason: "Catalog contains duplicate component ids." };
  for (const requiredId of REQUIRED_COMPONENT_IDS) {
    const entry = candidate.entries.find(item => item.componentId === requiredId);
    if (!entry || entry.required !== true) return { valid: false, reason: `Catalog is missing required ${requiredId}.` };
  }
  return { valid: true };
}

export interface SetupBridgeTransport {
  invoke<T>(command: string, args?: Record<string, unknown>): Promise<T>;
}

export interface SetupClient {
  getState: () => Promise<SetupState>;
  saveState: (state: SetupState) => Promise<SetupState>;
  getCatalog: () => Promise<SetupCatalogInfo | null>;
  importCatalog: (catalogJson: string, source: "production" | "offline-import") => Promise<SetupImportResult>;
  catalogConfiguration: (channel?: SetupState["catalogChannel"]) => Promise<SetupCatalogConfiguration>;
  refreshCatalog: () => Promise<SetupImportResult>;
  runSystemChecks: (probeNetwork?: boolean) => Promise<SetupSystemChecksResult>;
}

export function createSetupClient(transport: SetupBridgeTransport): SetupClient {
  return {
    getState: () => transport.invoke<SetupState>("setup_get_state"),
    saveState: (state: SetupState) => transport.invoke<SetupState>("setup_save_state", { state }),
    getCatalog: () => transport.invoke<SetupCatalogInfo | null>("setup_get_catalog"),
    importCatalog: (catalogJson: string, source: "production" | "offline-import") =>
      transport.invoke<SetupImportResult>("setup_import_catalog", { catalogJson, source }),
    catalogConfiguration: (channel?: SetupState["catalogChannel"]) =>
      transport.invoke<SetupCatalogConfiguration>("setup_catalog_configuration", { channel }),
    refreshCatalog: () => transport.invoke<SetupImportResult>("setup_refresh_catalog"),
    runSystemChecks: (probeNetwork = true) =>
      transport.invoke<SetupSystemChecksResult>("setup_run_system_checks", { probeNetwork }),
  };
}

export const setupClient: SetupClient = createSetupClient({ invoke });
