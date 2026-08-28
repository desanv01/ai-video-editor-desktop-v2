/**
 * API Client — communicates with the FastAPI backend.
 *
 * All backend calls go through this module.
 * The desktop app (Tauri) calls these functions from React components.
 */

import type {
  Video, VideoUploadResponse, Segment, EditPlan,
  ProcessingStatus, QualityReport,
  ModeComparisonReport,
  RevalidationResult, SegmentAction, BackendAISettings,
  BackendAISettingsUpdate,
  TranscriptTimeline,
  TranscriptCutDecision, TranscriptCutDecisionRequest, TranscriptCutTrimUpdateRequest,
  TranscriptCutWordRestoreRequest,
  EditDecisionSync,
  CleanAnalyzeResult, CleanApplyResult, CleanProfileId,
  LocalTranscriptionModelCatalog, LocalTranscriptionModelDownload,
  LocalTranscriptionModelRemoveResult,
  Project, ProjectAsset, ProjectAssetUploadResponse,
  ProjectAssetSyncUpdateRequest, ProjectAssetMetadataUpdateRequest, ProjectAssetUploadType,
  ProjectCreateRequest, ProjectDetail, ProjectSourceSyncPlan,
  ProjectUpdateRequest,
  TopicSegmentationResult,
  AnnotationActionUpdate,
  CaptionPolicyUpdate,
  EndCardActionUpdate,
  EducationalOverlayActionUpdate,
  LayoutCueUpdate,
  ExportPresetCatalog,
  AppStorageLayout,
  NativeImportProgress,
  NativeImportResult,
  PrimaryImportChunkResponse,
  PrimaryImportInitSession,
  PrimaryImportStatus,
  ApprovePlanResponse,
  RenderCancelResponse,
  SemanticRenderPlan,
  SectionClipExportManifest,
  SlideCue,
  EditorialBlock,
  ProductReadiness,
  ProjectReadiness,
  UnifiedJob,
  ProviderConnectionTestResult,
} from "../types/api";
import type {
  ActivationMetadataInspection,
  DesktopV2BootstrapResult,
  DiagnosticSnapshotResult,
  ResolvedDesktopPaths,
  SafeLogDirectoryResult,
  ShellInfo,
  SupervisorDiagnostics,
  SupervisorStatus,
} from "../desktopV2";

let BASE_URL = "http://localhost:8000/api/v1";
let NATIVE_BRIDGE_ENABLED = false;
const DEFAULT_TIMEOUT_MS = 30_000;
const APPROVAL_TIMEOUT_MS = 10 * 60_000;
const VIDEO_UPLOAD_TIMEOUT_MS = 60 * 60_000;
const MATERIAL_UPLOAD_TIMEOUT_MS = 90_000;
const PRIMARY_BROWSER_UPLOAD_CHUNK_BYTES = 8 * 1024 * 1024;

export class ApiClientError extends Error {
  readonly status: number | null;
  readonly code: string;
  readonly remediation: string | null;
  readonly retryable: boolean;

  constructor(
    message: string,
    options: { status?: number | null; code?: string; remediation?: string | null; retryable?: boolean } = {},
  ) {
    super(message);
    this.name = "ApiClientError";
    this.status = options.status ?? null;
    this.code = options.code ?? "API_ERROR";
    this.remediation = options.remediation ?? null;
    this.retryable = options.retryable ?? true;
  }
}

export function friendlyErrorMessage(error: unknown): string {
  if (error instanceof ApiClientError) {
    return error.remediation ? `${error.message} ${error.remediation}` : error.message;
  }
  const message = error instanceof Error ? error.message : String(error ?? "");
  const lower = message.toLowerCase();
  if (lower.includes("failed to fetch") || lower.includes("networkerror") || lower.includes("load failed")) {
    return "The local backend is offline or not ready. Start the backend/desktop engine, then try again. Your project data is kept.";
  }
  if (lower.includes("abort") || lower.includes("cancel")) return "The operation was cancelled. You can resume it when ready.";
  return message.replace(/^Error:\s*/i, "") || "The operation could not be completed. Try again or open diagnostics.";
}

export function setBaseUrl(url: string) {
  BASE_URL = url.replace(/\/+$/, "") + "/api/v1";
}

export function getBackendBaseUrl(): string {
  return NATIVE_BRIDGE_ENABLED ? "bridge://engine" : BASE_URL.replace(/\/api\/v1$/, "");
}

export function setNativeBridgeEnabled(enabled: boolean): void {
  NATIVE_BRIDGE_ENABLED = enabled;
}

export function isNativeBridgeEnabled(): boolean {
  return NATIVE_BRIDGE_ENABLED;
}

function resourceUrl(path: string): string {
  return NATIVE_BRIDGE_ENABLED ? `bridge://engine-resource${path}` : `${BASE_URL}${path}`;
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${BASE_URL}${path}`;
  const headers = new Headers(options?.headers);
  if (options?.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  let res: Response;
  try {
    res = await fetchWithTimeout(url, {
      ...options,
      headers,
    }, DEFAULT_TIMEOUT_MS);
  } catch (error) {
    throw new ApiClientError(friendlyErrorMessage(error), { code: "BACKEND_UNAVAILABLE" });
  }

  if (!res.ok) {
    const body = await res.text();
    throw parseApiError(res.status, body, res.headers);
  }

  return res.json();
}

function parseApiError(status: number, body: string, headers?: Headers): ApiClientError {
  let parsed: Record<string, unknown> | null = null;
  try {
    const candidate = JSON.parse(body);
    if (candidate && typeof candidate === "object") parsed = candidate as Record<string, unknown>;
  } catch {
    // FastAPI/proxy errors may be plain text.
  }
  const detail = parsed?.detail;
  const detailObject = detail && typeof detail === "object" ? detail as Record<string, unknown> : null;
  const rawMessage = detailObject?.message ?? (typeof detail === "string" ? detail : parsed?.message ?? body);
  const message = String(rawMessage || "Request failed");
  const code = String(detailObject?.code ?? parsed?.code ?? headers?.get("X-AIVE-Error-Code") ?? `HTTP_${status}`);
  const remediation = detailObject?.remediation ?? parsed?.remediation ?? null;
  return new ApiClientError(message.slice(0, 500), {
    status,
    code,
    remediation: typeof remediation === "string" ? remediation : null,
    retryable: detailObject?.retryable !== false && parsed?.retryable !== false,
  });
}

async function fetchWithTimeout(url: string, options: RequestInit, timeoutMs: number): Promise<Response> {
  if (NATIVE_BRIDGE_ENABLED) {
    return nativeBridgeFetch(url, options, timeoutMs);
  }
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  const upstreamSignal = options.signal;
  const abortFromUpstream = () => controller.abort();

  if (upstreamSignal) {
    if (upstreamSignal.aborted) {
      controller.abort();
    } else {
      upstreamSignal.addEventListener("abort", abortFromUpstream, { once: true });
    }
  }

  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      if (upstreamSignal?.aborted) {
        throw new Error("Request cancelled");
      }
      throw new Error(`Request timed out after ${Math.round(timeoutMs / 1000)} seconds`);
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
    upstreamSignal?.removeEventListener("abort", abortFromUpstream);
  }
}

type NativeBridgeResponse = {
  status: number;
  headers: Record<string, string>;
  bodyBase64: string;
};

async function nativeBridgeFetch(url: string, options: RequestInit, timeoutMs: number): Promise<Response> {
  const { invoke } = await import("@tauri-apps/api/core");
  const parsed = new URL(url, window.location.href);
  const headers = new Headers(options.headers);
  let bodyBase64: string | undefined;
  let contentType = headers.get("Content-Type");

  if (options.body !== undefined && options.body !== null) {
    let bodyBytes: ArrayBuffer;
    if (typeof options.body === "string") {
      bodyBytes = new TextEncoder().encode(options.body).buffer;
    } else {
      const encodedRequest = new Request("http://desktop-v2-bridge.invalid", {
        method: options.method ?? "GET",
        headers,
        body: options.body as BodyInit,
      });
      bodyBytes = await encodedRequest.arrayBuffer();
      contentType = contentType ?? encodedRequest.headers.get("Content-Type");
    }
    const bodyView = new Uint8Array(bodyBytes);
    let binary = "";
    for (const byte of bodyView) binary += String.fromCharCode(byte);
    bodyBase64 = btoa(binary);
  }

  const invokePromise = invoke<NativeBridgeResponse>("engine_api_request", {
    request: {
      method: options.method ?? "GET",
      path: parsed.pathname + parsed.search,
      bodyBase64,
      contentType: contentType ?? undefined,
      timeoutMs,
    },
  });
  let timer: number | undefined;
  const timeoutPromise = new Promise<never>((_, reject) => {
    timer = window.setTimeout(() => reject(new Error(`Engine request timed out after ${Math.round(timeoutMs / 1000)} seconds`)), timeoutMs);
  });
  let result: NativeBridgeResponse;
  try {
    result = await Promise.race([invokePromise, timeoutPromise]);
  } finally {
    if (timer !== undefined) window.clearTimeout(timer);
  }

  const raw = atob(result.bodyBase64);
  const body = new Uint8Array(raw.length);
  for (let index = 0; index < raw.length; index += 1) body[index] = raw.charCodeAt(index);
  return new Response(body, { status: result.status, headers: result.headers });
}

async function errorFromResponse(prefix: string, res: Response): Promise<Error> {
  const body = await res.text();
  const error = parseApiError(res.status, body, res.headers);
  return new ApiClientError(`${prefix}: ${error.message}`, {
    status: error.status,
    code: error.code,
    remediation: error.remediation,
    retryable: error.retryable,
  });
}

type BrowserPrimaryUploadCallbacks = {
  onProgress?: (payload: NativeImportProgress) => void;
  onSession?: (token: string) => void;
  signal?: AbortSignal;
};

type StoredBrowserUploadSession = {
  token: string;
  projectId: string;
  filename: string;
  fileSize: number;
  fileLastModified: number;
};

function browserUploadStorageKey(projectId: string, file: File): string {
  return `aive:browser-primary-upload:${projectId}:${file.name}:${file.size}:${file.lastModified}`;
}

function loadBrowserUploadSession(projectId: string, file: File): StoredBrowserUploadSession | null {
  try {
    const raw = window.localStorage.getItem(browserUploadStorageKey(projectId, file));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StoredBrowserUploadSession;
    if (parsed.projectId !== projectId || parsed.filename !== file.name || parsed.fileSize !== file.size) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

function saveBrowserUploadSession(projectId: string, file: File, token: string): void {
  const payload: StoredBrowserUploadSession = {
    token,
    projectId,
    filename: file.name,
    fileSize: file.size,
    fileLastModified: file.lastModified,
  };
  window.localStorage.setItem(browserUploadStorageKey(projectId, file), JSON.stringify(payload));
}

function clearBrowserUploadSession(projectId: string, file: File): void {
  window.localStorage.removeItem(browserUploadStorageKey(projectId, file));
}

function toImportProgress(
  projectId: string,
  filename: string,
  status: string,
  bytesCopied: number,
  totalBytes: number,
  bytesPerSecond: number,
  etaSeconds: number | null,
  message: string,
  token: string,
): NativeImportProgress {
  return {
    token,
    projectId,
    filename,
    status,
    bytesCopied,
    totalBytes,
    percent: totalBytes > 0 ? (bytesCopied / totalBytes) * 100 : 0,
    bytesPerSecond,
    etaSeconds,
    message,
  };
}

async function initBrowserPrimaryImport(
  projectId: string,
  file: File,
): Promise<PrimaryImportInitSession> {
  return request(`/projects/${projectId}/imports/browser/primary/init`, {
    method: "POST",
    body: JSON.stringify({
      original_filename: file.name,
      file_size_bytes: file.size,
      mime_type: file.type || null,
    }),
  });
}

async function getBrowserPrimaryImportStatus(projectId: string, token: string): Promise<PrimaryImportStatus> {
  return request(`/projects/${projectId}/imports/browser/primary/${token}`);
}

async function appendBrowserPrimaryImportChunk(
  projectId: string,
  token: string,
  offset: number,
  chunk: Blob,
  signal?: AbortSignal,
): Promise<PrimaryImportChunkResponse> {
  const res = await fetchWithTimeout(
    `${BASE_URL}/projects/${projectId}/imports/browser/primary/${token}/chunk?offset=${offset}`,
    {
      method: "PUT",
      body: chunk,
      headers: {
        "Content-Type": "application/octet-stream",
      },
      signal,
    },
    VIDEO_UPLOAD_TIMEOUT_MS,
  );
  if (!res.ok) throw await errorFromResponse("Browser upload chunk failed", res);
  return res.json();
}

async function finalizeBrowserPrimaryImport(
  projectId: string,
  token: string,
  copiedFileSizeBytes: number,
): Promise<VideoUploadResponse> {
  return request(`/projects/${projectId}/imports/browser/primary/${token}/finalize`, {
    method: "POST",
    body: JSON.stringify({ copied_file_size_bytes: copiedFileSizeBytes }),
  });
}

async function cancelBrowserPrimaryImport(projectId: string, token: string): Promise<void> {
  await request(`/projects/${projectId}/imports/browser/primary/${token}/cancel`, {
    method: "POST",
  });
}

export async function isNativeDesktop(): Promise<boolean> {
  return isTauriDesktopRuntime();
}

export async function isTauriDesktopRuntime(): Promise<boolean> {
  try {
    const { invoke } = await import("@tauri-apps/api/core");
    await invoke<ShellInfo>("get_shell_info");
    setNativeBridgeEnabled(true);
    return true;
  } catch {
    return false;
  }
}

export async function fetchEngineResource(path: string, timeoutMs = VIDEO_UPLOAD_TIMEOUT_MS): Promise<Blob> {
  const res = await fetchWithTimeout(`${BASE_URL}${path}`, {}, timeoutMs);
  if (!res.ok) throw await errorFromResponse("Engine resource request failed", res);
  return res.blob();
}

export async function downloadEngineResource(resource: string, filename: string): Promise<void> {
  const parsed = new URL(resource, window.location.href);
  const path = parsed.protocol === "bridge:" ? parsed.pathname + parsed.search : parsed.pathname + parsed.search;
  const blob = await fetchEngineResource(path);
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = objectUrl;
  anchor.download = filename.replace(/[^A-Za-z0-9._ -]/g, "_");
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
}

export async function getShellInfo(): Promise<ShellInfo> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<ShellInfo>("get_shell_info");
}

export async function getCanonicalDesktopPaths(): Promise<ResolvedDesktopPaths> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<ResolvedDesktopPaths>("get_canonical_paths");
}

export async function inspectDesktopActivationMetadata(): Promise<ActivationMetadataInspection> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<ActivationMetadataInspection>("inspect_activation_metadata");
}

export async function getSafeLogDirectory(): Promise<SafeLogDirectoryResult> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<SafeLogDirectoryResult>("get_safe_log_directory");
}

export async function bootstrapDesktopV2Shell(): Promise<DesktopV2BootstrapResult> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<DesktopV2BootstrapResult>("desktop_v2_bootstrap");
}

export async function generateDesktopDiagnosticSnapshot(): Promise<DiagnosticSnapshotResult> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<DiagnosticSnapshotResult>("generate_diagnostic_snapshot");
}

export async function getSupervisorStatus(): Promise<SupervisorStatus> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<SupervisorStatus>("supervisor_status");
}

export async function startSupervisor(): Promise<SupervisorStatus> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<SupervisorStatus>("supervisor_start");
}

export async function stopSupervisor(): Promise<SupervisorStatus> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<SupervisorStatus>("supervisor_stop");
}

export async function restartSupervisor(): Promise<SupervisorStatus> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<SupervisorStatus>("supervisor_restart");
}

export async function retrySupervisor(): Promise<SupervisorStatus> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<SupervisorStatus>("supervisor_retry");
}

export async function getSupervisorDiagnostics(): Promise<SupervisorDiagnostics> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<SupervisorDiagnostics>("supervisor_diagnostics");
}

export async function getAppStorageLayout(): Promise<AppStorageLayout> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<AppStorageLayout>("get_app_storage_layout");
}

export async function pickNativePrimaryVideoPath(): Promise<string | null> {
  const { open } = await import("@tauri-apps/plugin-dialog");
  const selected = await open({
    multiple: false,
    filters: [
      {
        name: "Video",
        extensions: ["mp4", "mov", "avi", "webm", "mkv", "mpeg", "mpg"],
      },
    ],
  });
  if (Array.isArray(selected)) return selected[0] ?? null;
  return selected;
}

export async function listenToNativeImportProgress(
  onProgress: (payload: NativeImportProgress) => void,
): Promise<() => void> {
  const { listen } = await import("@tauri-apps/api/event");
  return listen<NativeImportProgress>("native-import-progress", event => {
    onProgress(event.payload);
  });
}

export async function startNativePrimaryImport(
  projectId: string,
  sourcePath: string,
): Promise<NativeImportResult> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<NativeImportResult>("start_native_primary_import", {
    projectId,
    sourcePath,
    backendUrl: getBackendBaseUrl(),
  });
}

export async function cancelNativeImport(token: string): Promise<boolean> {
  const { invoke } = await import("@tauri-apps/api/core");
  return invoke<boolean>("cancel_native_import", { token });
}

export async function createProject(requestBody: ProjectCreateRequest): Promise<ProjectDetail> {
  return request("/projects", {
    method: "POST",
    body: JSON.stringify(requestBody),
  });
}

export async function listProjects(): Promise<Project[]> {
  return request("/projects");
}

export async function getProject(projectId: string): Promise<ProjectDetail> {
  return request(`/projects/${projectId}`);
}

export async function updateProject(projectId: string, requestBody: ProjectUpdateRequest): Promise<ProjectDetail> {
  return request(`/projects/${projectId}`, {
    method: "PATCH",
    body: JSON.stringify(requestBody),
  });
}

export async function deleteProject(projectId: string): Promise<void> {
  await request(`/projects/${projectId}`, { method: "DELETE" });
}

export async function getProductReadiness(): Promise<ProductReadiness> {
  return request("/product-readiness");
}

export async function getProjectReadiness(projectId: string): Promise<ProjectReadiness> {
  return request(`/projects/${projectId}/readiness`);
}

export async function getVideoReadiness(videoId: string): Promise<ProjectReadiness> {
  return request(`/videos/${videoId}/readiness`);
}

export async function listProjectAssets(projectId: string): Promise<ProjectAsset[]> {
  return request(`/projects/${projectId}/assets`);
}

export async function getProjectSourceSyncPlan(projectId: string): Promise<ProjectSourceSyncPlan> {
  return request(`/projects/${projectId}/source-sync`);
}

export async function applyProjectSourceSyncMetadata(projectId: string, force = false): Promise<ProjectSourceSyncPlan> {
  return request(`/projects/${projectId}/source-sync/apply-metadata`, {
    method: "POST",
    body: JSON.stringify({ force }),
  });
}

export async function updateProjectAssetSyncOffset(
  projectId: string,
  assetId: string,
  payload: ProjectAssetSyncUpdateRequest,
): Promise<ProjectAsset> {
  return request(`/projects/${projectId}/assets/${assetId}/sync`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function updateProjectAssetMetadata(
  projectId: string,
  assetId: string,
  payload: ProjectAssetMetadataUpdateRequest,
): Promise<ProjectAsset> {
  return request(`/projects/${projectId}/assets/${assetId}/metadata`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
}

export async function uploadProjectAsset(
  projectId: string,
  assetType: ProjectAssetUploadType,
  file: File,
  isPrimary = false,
  metadata?: Record<string, unknown>,
): Promise<ProjectAssetUploadResponse> {
  const form = new FormData();
  form.append("asset_type", assetType);
  form.append("is_primary", String(isPrimary));
  if (metadata) {
    form.append("metadata", JSON.stringify(metadata));
  }
  form.append("file", file);

  const res = await fetchWithTimeout(
    `${BASE_URL}/projects/${projectId}/assets/upload`,
    { method: "POST", body: form },
    VIDEO_UPLOAD_TIMEOUT_MS,
  );
  if (!res.ok) throw await errorFromResponse("Project asset upload failed", res);
  return res.json();
}

export async function uploadProjectPrimaryVideo(
  projectId: string,
  file: File,
  callbacks?: BrowserPrimaryUploadCallbacks,
): Promise<VideoUploadResponse> {
  const callbacksSafe = callbacks ?? {};
  let token = loadBrowserUploadSession(projectId, file)?.token ?? null;
  let status: PrimaryImportStatus | null = null;

  if (token) {
    try {
      status = await getBrowserPrimaryImportStatus(projectId, token);
      if (
        status.total_bytes !== file.size ||
        status.filename !== file.name ||
        ["cancelled", "finalized"].includes(status.status)
      ) {
        clearBrowserUploadSession(projectId, file);
        token = null;
        status = null;
      }
    } catch {
      clearBrowserUploadSession(projectId, file);
      token = null;
      status = null;
    }
  }

  if (!token) {
    const session = await initBrowserPrimaryImport(projectId, file);
    token = session.token;
    saveBrowserUploadSession(projectId, file, token);
    callbacksSafe.onSession?.(token);
    status = {
      token,
      project_id: session.project_id,
      filename: file.name,
      status: "initialized",
      bytes_received: 0,
      total_bytes: file.size,
      percent: 0,
      complete: false,
      updated_at: null,
      warnings: session.warnings,
    };
  } else {
    callbacksSafe.onSession?.(token);
  }

  let bytesUploaded = status?.bytes_received ?? 0;
  let lastTick = performance.now();
  let lastBytes = bytesUploaded;
  callbacksSafe.onProgress?.(
    toImportProgress(
      projectId,
      file.name,
      bytesUploaded >= file.size ? "finalizing" : "copying",
      bytesUploaded,
      file.size,
      0,
      null,
      bytesUploaded > 0 ? "Resuming browser upload" : "Uploading video in resumable chunks",
      token,
    ),
  );

  try {
    while (bytesUploaded < file.size) {
      const nextChunk = file.slice(bytesUploaded, bytesUploaded + PRIMARY_BROWSER_UPLOAD_CHUNK_BYTES);
      const chunkResult = await appendBrowserPrimaryImportChunk(
        projectId,
        token,
        bytesUploaded,
        nextChunk,
        callbacksSafe.signal,
      );

      const now = performance.now();
      const deltaBytes = chunkResult.bytes_received - lastBytes;
      const elapsedSeconds = Math.max((now - lastTick) / 1000, 0.001);
      const bytesPerSecond = deltaBytes > 0 ? deltaBytes / elapsedSeconds : 0;
      const remainingBytes = Math.max(file.size - chunkResult.bytes_received, 0);
      const etaSeconds = bytesPerSecond > 0 ? remainingBytes / bytesPerSecond : null;

      bytesUploaded = chunkResult.bytes_received;
      lastTick = now;
      lastBytes = bytesUploaded;

      callbacksSafe.onProgress?.(
        toImportProgress(
          projectId,
          file.name,
          chunkResult.complete ? "finalizing" : "copying",
          bytesUploaded,
          file.size,
          bytesPerSecond,
          etaSeconds,
          chunkResult.complete ? "Finalizing uploaded video" : "Uploading video in resumable chunks",
          token,
        ),
      );
    }

    const result = await finalizeBrowserPrimaryImport(projectId, token, file.size);
    clearBrowserUploadSession(projectId, file);
    callbacksSafe.onProgress?.(
      toImportProgress(
        projectId,
        file.name,
        "completed",
        file.size,
        file.size,
        0,
        0,
        "Browser upload completed",
        token,
      ),
    );
    return result;
  } catch (error) {
    if (callbacksSafe.signal?.aborted) {
      clearBrowserUploadSession(projectId, file);
      try {
        await cancelBrowserPrimaryImport(projectId, token);
      } catch {
        // Ignore cleanup failures after an explicit cancel.
      }
      callbacksSafe.onProgress?.(
        toImportProgress(
          projectId,
          file.name,
          "cancelled",
          bytesUploaded,
          file.size,
          0,
          null,
          "Browser upload cancelled",
          token,
        ),
      );
    }
    throw error;
  }
}

export async function deleteProjectAsset(projectId: string, assetId: string): Promise<void> {
  await request(`/projects/${projectId}/assets/${assetId}`, { method: "DELETE" });
}

export function getProjectAssetDownloadUrl(projectId: string, assetId: string): string {
  return resourceUrl(`/projects/${projectId}/assets/${assetId}/download`);
}

// ═══════════════════════════════════════════
//  VIDEO
// ═══════════════════════════════════════════

export async function uploadVideo(file: File): Promise<VideoUploadResponse> {
  const form = new FormData();
  form.append("file", file);

  const res = await fetchWithTimeout(
    `${BASE_URL}/videos/upload`,
    { method: "POST", body: form },
    VIDEO_UPLOAD_TIMEOUT_MS,
  );
  if (!res.ok) throw await errorFromResponse("Upload failed", res);
  return res.json();
}

export async function startVideoProcessing(id: string): Promise<{ status: string; message: string }> {
  return request(`/videos/${id}/process`, { method: "POST" });
}

export async function retryVideoProcessing(id: string): Promise<{ status: string; message: string; job?: UnifiedJob | null }> {
  return request(`/videos/${id}/process/retry`, { method: "POST" });
}

export async function listVideos(): Promise<Video[]> {
  return request("/videos");
}

export async function getVideo(id: string): Promise<Video> {
  return request(`/videos/${id}`);
}

export async function getProcessingStatus(id: string): Promise<ProcessingStatus> {
  return request(`/videos/${id}/status`);
}

export async function getTranscriptTimeline(videoId: string): Promise<TranscriptTimeline> {
  return request(`/videos/${videoId}/transcript/timeline`);
}

export async function getTranscriptCutDecisions(videoId: string): Promise<TranscriptCutDecision[]> {
  return request(`/videos/${videoId}/transcript/cuts`);
}

export async function createTranscriptCutDecision(
  videoId: string,
  payload: TranscriptCutDecisionRequest,
): Promise<TranscriptCutDecision> {
  return request(`/videos/${videoId}/transcript/cuts`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function deleteTranscriptCutDecision(videoId: string, decisionId: string): Promise<void> {
  await request(`/videos/${videoId}/transcript/cuts/${decisionId}`, {
    method: "DELETE",
  });
}

export async function updateTranscriptCutTrim(
  videoId: string,
  decisionId: string,
  payload: TranscriptCutTrimUpdateRequest,
): Promise<TranscriptCutDecision> {
  return request(`/videos/${videoId}/transcript/cuts/${decisionId}/trim`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function restoreTranscriptCutWord(
  videoId: string,
  decisionId: string,
  payload: TranscriptCutWordRestoreRequest,
): Promise<TranscriptCutDecision[]> {
  return request(`/videos/${videoId}/transcript/cuts/${decisionId}/restore-word`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getEditDecisionSync(videoId: string): Promise<EditDecisionSync> {
  return request(`/videos/${videoId}/edit-decision-sync`);
}

// ═══════════════════════════════════════════
//  SEGMENTS
// ═══════════════════════════════════════════

export async function analyzeCleanSuggestions(
  videoId: string,
  profile: CleanProfileId | string = "moderate",
): Promise<CleanAnalyzeResult> {
  return request(`/videos/${videoId}/clean/analyze?profile=${encodeURIComponent(profile)}`);
}

export async function applyCleanSuggestions(
  videoId: string,
  profile: CleanProfileId | string = "moderate",
  suggestionIds?: string[],
  suggestionTypes?: string[],
): Promise<CleanApplyResult> {
  return request(`/videos/${videoId}/clean/apply`, {
    method: "POST",
    body: JSON.stringify({
      profile,
      suggestion_ids: suggestionIds && suggestionIds.length > 0 ? suggestionIds : null,
      suggestion_types: suggestionTypes && suggestionTypes.length > 0 ? suggestionTypes : null,
    }),
  });
}

export async function getSegments(videoId: string): Promise<Segment[]> {
  return request(`/videos/${videoId}/segments`);
}

export async function updateSegment(
  videoId: string,
  segmentId: string,
  action: SegmentAction | null,
  note?: string | null,
  isTeacherModified?: boolean,
): Promise<void> {
  await request(`/videos/${videoId}/segments/${segmentId}`, {
    method: "PUT",
    body: JSON.stringify({
      teacher_action: action,
      teacher_note: note || null,
      is_teacher_modified: isTeacherModified,
    }),
  });
}

export async function bulkUpdateSegments(
  videoId: string,
  updates: { segment_id: string; teacher_action: SegmentAction; teacher_note?: string }[],
): Promise<void> {
  await request(`/videos/${videoId}/segments/bulk`, {
    method: "PUT",
    body: JSON.stringify({ updates }),
  });
}

// ═══════════════════════════════════════════
//  EDIT PLAN
// ═══════════════════════════════════════════

export async function getEditPlan(videoId: string): Promise<EditPlan> {
  return request(`/videos/${videoId}/plan`);
}

export async function getSemanticRenderPlan(videoId: string): Promise<SemanticRenderPlan> {
  return request(`/videos/${videoId}/render-plan`);
}

export async function regenerateSemanticRenderPlan(videoId: string): Promise<SemanticRenderPlan> {
  return request(`/videos/${videoId}/render-plan/regenerate`, { method: "POST" });
}

export async function updateCaptionPolicy(videoId: string, payload: CaptionPolicyUpdate): Promise<EditPlan> {
  return request(`/videos/${videoId}/plan/captions`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function updateLayoutCues(videoId: string, layoutCues: LayoutCueUpdate[]): Promise<EditPlan> {
  return request(`/videos/${videoId}/plan/layout-cues`, {
    method: "PUT",
    body: JSON.stringify({ layout_cues: layoutCues }),
  });
}

export async function updateSlideCues(videoId: string, slideCues: SlideCue[]): Promise<EditPlan> {
  return request(`/videos/${videoId}/plan/slide-cues`, {
    method: "PUT",
    body: JSON.stringify({ slide_cues: slideCues, source: "teacher_slide_override" }),
  });
}

export async function updateEditorialBlocks(videoId: string, editorialBlocks: EditorialBlock[]): Promise<EditPlan> {
  return request(`/videos/${videoId}/plan/editorial-blocks`, {
    method: "PUT",
    body: JSON.stringify({ editorial_blocks: editorialBlocks, source: "teacher_editorial_override" }),
  });
}

export async function autoGenerateLayoutCues(videoId: string, profile = "balanced"): Promise<EditPlan> {
  return request(`/videos/${videoId}/plan/layout-cues/auto`, {
    method: "POST",
    body: JSON.stringify({ profile }),
  });
}

export async function updateAnnotations(videoId: string, annotations: AnnotationActionUpdate[]): Promise<EditPlan> {
  return request(`/videos/${videoId}/plan/annotations`, {
    method: "PUT",
    body: JSON.stringify({ annotations }),
  });
}

export async function updateEducationalOverlays(
  videoId: string,
  overlays: EducationalOverlayActionUpdate[],
): Promise<EditPlan> {
  return request(`/videos/${videoId}/plan/educational-overlays`, {
    method: "PUT",
    body: JSON.stringify({ overlays }),
  });
}

export async function updateEndCards(
  videoId: string,
  endCards: EndCardActionUpdate[],
): Promise<EditPlan> {
  return request(`/videos/${videoId}/plan/end-cards`, {
    method: "PUT",
    body: JSON.stringify({ end_cards: endCards }),
  });
}

export async function getExportPresets(): Promise<ExportPresetCatalog> {
  return request("/export/presets");
}

export async function approvePlan(videoId: string, notes?: string, exportPresetId?: string): Promise<ApprovePlanResponse> {
  const url = `${BASE_URL}/videos/${videoId}/plan/approve`;
  const res = await fetchWithTimeout(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ teacher_notes: notes || null, export_preset_id: exportPresetId || null }),
  }, APPROVAL_TIMEOUT_MS);
  if (!res.ok) {
    throw await errorFromResponse("Export could not start", res);
  }
  return res.json();
}

export async function cancelRender(videoId: string): Promise<RenderCancelResponse> {
  return request(`/videos/${videoId}/render/cancel`, { method: "POST" });
}

export async function revalidatePlan(videoId: string): Promise<RevalidationResult> {
  return request(`/videos/${videoId}/plan/revalidate`, { method: "POST" });
}

export async function getChapters(videoId: string): Promise<TopicSegmentationResult> {
  return request(`/videos/${videoId}/chapters`);
}

// ═══════════════════════════════════════════
//  QUALITY REPORT
// ═══════════════════════════════════════════

export async function getQualityReport(videoId: string): Promise<QualityReport> {
  return request(`/videos/${videoId}/report`);
}

export async function getModeComparisonReport(videoId: string): Promise<ModeComparisonReport> {
  return request(`/videos/${videoId}/mode-comparison`);
}

// ═══════════════════════════════════════════
//  COURSE MATERIALS
// ═══════════════════════════════════════════

export async function uploadMaterial(file: File): Promise<{ id: string; chunk_count: number; message: string }> {
  const form = new FormData();
  form.append("file", file);

  const res = await fetchWithTimeout(
    `${BASE_URL}/materials/upload`,
    { method: "POST", body: form },
    MATERIAL_UPLOAD_TIMEOUT_MS,
  );
  if (!res.ok) throw await errorFromResponse("Material upload failed", res);
  return res.json();
}

export async function listMaterials(): Promise<{ id: string; filename: string; chunk_count: number }[]> {
  return request("/materials");
}

export async function deleteMaterial(id: string): Promise<void> {
  await request(`/materials/${id}`, { method: "DELETE" });
}

// ═══════════════════════════════════════════
//  SETTINGS
// ═══════════════════════════════════════════

export async function getSettings(): Promise<BackendAISettings> {
  return request("/settings");
}

export async function getAISettings(): Promise<BackendAISettings> {
  return request("/settings/ai");
}

export async function updateAISettings(settings: BackendAISettingsUpdate): Promise<BackendAISettings> {
  return request("/settings/ai", {
    method: "PUT",
    body: JSON.stringify(settings),
  });
}

export async function testProviderConnection(
  providerId: string,
  model?: string | null,
): Promise<ProviderConnectionTestResult> {
  return request("/settings/ai/test-provider", {
    method: "POST",
    body: JSON.stringify({ provider_id: providerId, model: model ?? null }),
  });
}

export async function updateDomainTerms(terms: string[]): Promise<void> {
  await request("/settings/domain-terms", {
    method: "PUT",
    body: JSON.stringify({ terms }),
  });
}
export async function getLocalTranscriptionModels(): Promise<LocalTranscriptionModelCatalog> {
  return request("/settings/models/local-transcription");
}

export async function downloadLocalTranscriptionModel(
  modelId: string,
  makeActive = true,
): Promise<LocalTranscriptionModelDownload> {
  return request(`/settings/models/local-transcription/${modelId}/download`, {
    method: "POST",
    body: JSON.stringify({ make_active: makeActive }),
  });
}

export async function getLocalTranscriptionModelDownload(
  modelId: string,
): Promise<LocalTranscriptionModelDownload> {
  return request(`/settings/models/local-transcription/${modelId}/download`);
}

export async function removeLocalTranscriptionModel(
  modelId: string,
): Promise<LocalTranscriptionModelRemoveResult> {
  return request(`/settings/models/local-transcription/${modelId}`, {
    method: "DELETE",
  });
}

// ═══════════════════════════════════════════
//  DOWNLOADS
// ═══════════════════════════════════════════

export function getVideoDownloadUrl(videoId: string): string {
  return resourceUrl(`/videos/${videoId}/download`);
}

export function getSubtitleDownloadUrl(videoId: string): string {
  return resourceUrl(`/videos/${videoId}/subtitles`);
}

export function getSubtitleVttUrl(videoId: string): string {
  return resourceUrl(`/videos/${videoId}/subtitles/vtt`);
}

export function getChaptersDownloadUrl(videoId: string): string {
  return resourceUrl(`/videos/${videoId}/chapters/download`);
}

export async function exportSectionClips(videoId: string): Promise<SectionClipExportManifest> {
  return request(`/videos/${videoId}/section-clips/export`, { method: "POST" });
}

export function getSectionClipsManifestUrl(videoId: string): string {
  return resourceUrl(`/videos/${videoId}/section-clips/manifest`);
}

export function getPlanExportUrl(videoId: string): string {
  return resourceUrl(`/videos/${videoId}/plan/export`);
}

export function getQualityReportExportUrl(videoId: string): string {
  return resourceUrl(`/videos/${videoId}/report/export`);
}

export function getModeComparisonExportUrl(videoId: string): string {
  return resourceUrl(`/videos/${videoId}/mode-comparison/export`);
}

export function getModeComparisonSummaryUrl(videoId: string): string {
  return resourceUrl(`/videos/${videoId}/mode-comparison/summary`);
}

export function getAcademicEvidenceExportUrl(videoId: string): string {
  return resourceUrl(`/videos/${videoId}/evidence/export`);
}

export function getAcademicEvidenceSummaryUrl(videoId: string): string {
  return resourceUrl(`/videos/${videoId}/evidence/summary`);
}

export function getAcademicEvidenceBundleUrl(videoId: string): string {
  return resourceUrl(`/videos/${videoId}/evidence/bundle`);
}

export function getBeforeAfterComparisonUrl(videoId: string): string {
  return resourceUrl(`/videos/${videoId}/evidence/before-after`);
}

export function getTimelineDecisionsUrl(videoId: string): string {
  return resourceUrl(`/videos/${videoId}/evidence/timeline-decisions`);
}

export function getProviderModeTraceUrl(videoId: string): string {
  return resourceUrl(`/videos/${videoId}/evidence/provider-mode`);
}

export function getMetricsSummaryUrl(videoId: string): string {
  return resourceUrl(`/videos/${videoId}/evidence/metrics-summary`);
}

export function getVideoStreamUrl(videoId: string): string {
  return resourceUrl(`/videos/${videoId}/stream`);
}
