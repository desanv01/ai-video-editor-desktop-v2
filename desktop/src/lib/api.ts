/**
 * API Client — communicates with the FastAPI backend.
 *
 * All backend calls go through this module.
 * The desktop app (Tauri) calls these functions from React components.
 */

import type {
  Video, VideoUploadResponse, Segment, EditPlan,
  ProcessingStatus, QualityReport, Chapter,
  RevalidationResult, SegmentAction, BackendAISettings,
  BackendAISettingsUpdate,
  LocalTranscriptionModelCatalog, LocalTranscriptionModelDownload,
  LocalTranscriptionModelRemoveResult,
  Project, ProjectAsset, ProjectAssetUploadResponse,
  ProjectAssetSyncUpdateRequest, ProjectAssetUploadType,
  ProjectCreateRequest, ProjectDetail, ProjectSourceSyncPlan,
} from "../types/api";

let BASE_URL = "http://localhost:8000/api/v1";
const DEFAULT_TIMEOUT_MS = 30_000;
const VIDEO_UPLOAD_TIMEOUT_MS = 10 * 60_000;
const MATERIAL_UPLOAD_TIMEOUT_MS = 90_000;

export function setBaseUrl(url: string) {
  BASE_URL = url.replace(/\/+$/, "") + "/api/v1";
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${BASE_URL}${path}`;
  const res = await fetchWithTimeout(url, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  }, DEFAULT_TIMEOUT_MS);

  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body.slice(0, 300)}`);
  }

  return res.json();
}

async function fetchWithTimeout(url: string, options: RequestInit, timeoutMs: number): Promise<Response> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);

  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error(`Request timed out after ${Math.round(timeoutMs / 1000)} seconds`);
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

async function errorFromResponse(prefix: string, res: Response): Promise<Error> {
  const body = await res.text();
  return new Error(`${prefix}: ${res.status}${body ? ` - ${body.slice(0, 300)}` : ""}`);
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
): Promise<VideoUploadResponse> {
  const form = new FormData();
  form.append("file", file);

  const res = await fetchWithTimeout(
    `${BASE_URL}/projects/${projectId}/videos/upload`,
    { method: "POST", body: form },
    VIDEO_UPLOAD_TIMEOUT_MS,
  );
  if (!res.ok) throw await errorFromResponse("Project video upload failed", res);
  return res.json();
}

export async function deleteProjectAsset(projectId: string, assetId: string): Promise<void> {
  await request(`/projects/${projectId}/assets/${assetId}`, { method: "DELETE" });
}

export function getProjectAssetDownloadUrl(projectId: string, assetId: string): string {
  return `${BASE_URL}/projects/${projectId}/assets/${assetId}/download`;
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

export async function listVideos(): Promise<Video[]> {
  return request("/videos");
}

export async function getVideo(id: string): Promise<Video> {
  return request(`/videos/${id}`);
}

export async function getProcessingStatus(id: string): Promise<ProcessingStatus> {
  return request(`/videos/${id}/status`);
}

// ═══════════════════════════════════════════
//  SEGMENTS
// ═══════════════════════════════════════════

export async function getSegments(videoId: string): Promise<Segment[]> {
  return request(`/videos/${videoId}/segments`);
}

export async function updateSegment(
  videoId: string,
  segmentId: string,
  action: SegmentAction,
  note?: string,
): Promise<void> {
  await request(`/videos/${videoId}/segments/${segmentId}`, {
    method: "PUT",
    body: JSON.stringify({ teacher_action: action, teacher_note: note || null }),
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

export async function approvePlan(videoId: string, notes?: string): Promise<void> {
  await request(`/videos/${videoId}/plan/approve`, {
    method: "POST",
    body: JSON.stringify({ teacher_notes: notes || null }),
  });
}

export async function revalidatePlan(videoId: string): Promise<RevalidationResult> {
  return request(`/videos/${videoId}/plan/revalidate`, { method: "POST" });
}

export async function getChapters(videoId: string): Promise<{ chapters: Chapter[]; youtube_format: string }> {
  return request(`/videos/${videoId}/chapters`);
}

// ═══════════════════════════════════════════
//  QUALITY REPORT
// ═══════════════════════════════════════════

export async function getQualityReport(videoId: string): Promise<QualityReport> {
  return request(`/videos/${videoId}/report`);
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
  return `${BASE_URL}/videos/${videoId}/download`;
}

export function getSubtitleDownloadUrl(videoId: string): string {
  return `${BASE_URL}/videos/${videoId}/subtitles`;
}

export function getSubtitleVttUrl(videoId: string): string {
  return `${BASE_URL}/videos/${videoId}/subtitles/vtt`;
}

export function getChaptersDownloadUrl(videoId: string): string {
  return `${BASE_URL}/videos/${videoId}/chapters/download`;
}

export function getPlanExportUrl(videoId: string): string {
  return `${BASE_URL}/videos/${videoId}/plan/export`;
}

export function getVideoStreamUrl(videoId: string): string {
  return `${BASE_URL}/videos/${videoId}/stream`;
}
