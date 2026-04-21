/**
 * API Client — communicates with the FastAPI backend.
 *
 * All backend calls go through this module.
 * The desktop app (Tauri) calls these functions from React components.
 */

import type {
  Video, VideoUploadResponse, Segment, EditPlan,
  ProcessingStatus, QualityReport, Chapter,
  RevalidationResult, SegmentAction,
} from "../types/api";

let BASE_URL = "http://localhost:8000/api/v1";

export function setBaseUrl(url: string) {
  BASE_URL = url.replace(/\/+$/, "") + "/api/v1";
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const url = `${BASE_URL}${path}`;
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", ...options?.headers },
    ...options,
  });

  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body.slice(0, 300)}`);
  }

  return res.json();
}

// ═══════════════════════════════════════════
//  VIDEO
// ═══════════════════════════════════════════

export async function uploadVideo(file: File): Promise<VideoUploadResponse> {
  const form = new FormData();
  form.append("file", file);

  const res = await fetch(`${BASE_URL}/videos/upload`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`Upload failed: ${res.status}`);
  return res.json();
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

  const res = await fetch(`${BASE_URL}/materials/upload`, { method: "POST", body: form });
  if (!res.ok) throw new Error(`Material upload failed: ${res.status}`);
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

export async function getSettings(): Promise<Record<string, unknown>> {
  return request("/settings");
}

export async function updateDomainTerms(terms: string[]): Promise<void> {
  await request("/settings/domain-terms", {
    method: "PUT",
    body: JSON.stringify({ terms }),
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
