/** Mirrors backend db/models.py and models/schemas.py */

export type VideoStatus =
  | "uploaded" | "processing" | "transcribing" | "analyzing"
  | "planning" | "awaiting_review" | "rendering" | "completed" | "failed";

export type SegmentAction = "keep" | "cut" | "shorten" | "highlight";

export type SegmentType =
  | "core_content" | "example" | "filler" | "pause"
  | "repetition" | "intro_outro" | "qa" | "transition";

export type ProjectStatus =
  | "draft" | "importing" | "ready" | "processing"
  | "awaiting_review" | "completed" | "archived" | "failed";

export type ProjectSourceMode = "single_video" | "multi_source";

export type ProjectAssetKind =
  | "mixed_video" | "screen_video" | "camera_video" | "audio"
  | "slide_deck" | "pdf_notes" | "text_notes" | "image"
  | "b_roll" | "transcript" | "course_material" | "other";

export type ProjectAssetRole =
  | "primary" | "screen" | "camera" | "audio" | "slides"
  | "notes" | "supporting_material" | "b_roll" | "transcript" | "other";

export type ProjectMediaSourceType =
  | "mixed_video" | "screen_recording" | "camera_recording" | "webcam_recording" | "phone_camera_recording"
  | "separate_audio" | "slide_deck" | "pdf_notes" | "text_notes"
  | "course_material" | "image" | "b_roll" | "transcript" | "other";

export type ProjectAssetSyncRole =
  | "primary_timeline" | "screen_reference" | "camera_overlay" | "audio_master"
  | "audio_reference" | "structure_reference" | "none";

export type ProjectAssetStatus = "uploaded" | "ready" | "processing" | "failed" | "archived";

export type ProjectAssetUploadType =
  | "video" | "screen" | "camera" | "webcam" | "phone_camera" | "audio" | "slides" | "notes" | "materials";

export interface Project {
  id: string;
  title: string;
  description: string | null;
  status: ProjectStatus;
  source_mode: ProjectSourceMode;
  project_type: string | null;
  metadata_json: Record<string, unknown>;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectAsset {
  id: string;
  project_id: string;
  kind: ProjectAssetKind;
  role: ProjectAssetRole;
  source_type: ProjectMediaSourceType;
  sync_role: ProjectAssetSyncRole;
  status: ProjectAssetStatus;
  is_primary: boolean;
  filename: string;
  original_filename: string;
  file_path: string;
  file_size_bytes: number | null;
  mime_type: string | null;
  duration_seconds: number | null;
  sync_offset_seconds: number;
  metadata_json: Record<string, unknown>;
  error_message: string | null;
  created_at: string;
  updated_at: string;
  structure_reference_role?: string | null;
  document_format?: string | null;
  structure_inference_ready?: boolean;
}

export interface ProjectDetail extends Project {
  assets: ProjectAsset[];
}

export interface ProjectCreateRequest {
  title: string;
  description?: string | null;
  source_mode?: ProjectSourceMode;
  project_type?: string;
  metadata?: Record<string, unknown>;
}

export interface ProjectAssetUploadResponse extends ProjectAsset {
  file_size_mb: number | null;
  message: string;
}

// ── Video ──

export interface Video {
  id: string;
  project_id: string | null;
  project_asset_id: string | null;
  original_filename: string;
  duration_seconds: number | null;
  resolution: string | null;
  status: VideoStatus;
  error_message: string | null;
  created_at: string;
  updated_at: string;
}

export interface VideoUploadResponse {
  id: string;
  project_id: string | null;
  project_asset_id: string | null;
  filename: string;
  status: VideoStatus;
  duration_seconds: number | null;
  resolution: string | null;
  file_size_mb: number | null;
  message: string;
}

// ── Transcript ──

export interface SpeakerInfo {
  label: string;
  segments_count: number;
}

export interface Transcript {
  id: string;
  full_text: string | null;
  language: string | null;
  word_count: number | null;
  asr_provider: string | null;
  speakers: SpeakerInfo[] | null;
}

// ── Segment ──

export interface Segment {
  id: string;
  segment_index: number;
  start_time: number;
  end_time: number;
  duration: number | null;
  text: string | null;
  speaker: string | null;

  // Agent 2
  topic_label: string | null;
  summary: string | null;
  importance_score: number | null;
  segment_type: SegmentType | null;

  // Agent 3
  filler_count: number;
  filler_words: string[] | null;
  fluency_score: number | null;
  pause_duration_total: number;
  has_repetition: boolean;

  // Agent 4
  has_slide_change: boolean;
  slide_index: number | null;

  // Agent 5
  action: SegmentAction;
  action_confidence: number | null;
  action_reason: string | null;

  // Teacher
  teacher_action: SegmentAction | null;
  teacher_note: string | null;
  is_teacher_modified: boolean;
}

// ── Edit Plan ──

export interface EditPlan {
  id: string;
  original_duration: number | null;
  estimated_duration: number | null;
  segments_total: number | null;
  segments_keep: number | null;
  segments_cut: number | null;
  segments_highlight: number | null;
  filler_words_removed: number | null;
  silence_removed_seconds: number | null;
  is_approved: boolean;
  teacher_notes: string | null;
}

// ── Processing Status ──

export interface ProcessingStatus {
  video_id: string;
  status: VideoStatus;
  current_step: string;
  current_step_label: string;
  progress_percent: number;
  steps_completed: string[];
  steps_timing: Record<string, { elapsed_seconds: number; summary?: Record<string, unknown> }>;
  total_elapsed_seconds: number;
  error_message: string | null;
}

// ── Quality Report ──

export interface QualityReport {
  video_id: string;
  original_duration_seconds: number;
  estimated_duration_seconds: number;
  time_saved_seconds: number;
  reduction_percent: number;
  total_segments: number;
  segments_keep: number;
  segments_cut: number;
  segments_highlight: number;
  total_filler_words: number;
  total_pause_seconds: number;
  average_importance_score: number;
  average_fluency_score: number;
  topic_distribution: Record<string, { count: number; total_duration: number }>;
  segment_type_distribution: Record<string, number>;
}

// ── Chapters ──

export interface Chapter {
  timestamp: number;
  formatted: string;
  label: string;
  segment_index: number;
}

// ── Revalidation ──

export interface RevalidationResult {
  warnings: string[];
  consequence_alerts: { segment_index: number; type: string; message: string }[];
}

// ── App Settings ──

export type AIProcessingMode = "api" | "local" | "hybrid";
export type AIProviderKind = "transcription" | "chat" | "embedding" | "vision" | "local_runtime";

export interface AICapabilitySettings {
  mode: AIProcessingMode;
  api_provider_id: string | null;
  local_provider_id: string | null;
  fallback_enabled: boolean;
  hybrid_fallback_order: AIProcessingMode[];
}

export interface APIKeyStatus {
  provider: string;
  source: "env" | "encrypted_db";
  env_var: string | null;
  has_key: boolean;
  display_value: string | null;
  updated_at: string | null;
}

export interface BackendAISettings {
  asr_provider: string;
  agent2_model: string;
  agent3_model: string;
  agent5_model: string;
  embedding_model: string;
  domain_terms: string[];
  preferred_processing_mode: AIProcessingMode;
  fallback_enabled: boolean;
  capabilities: Record<AIProviderKind, AICapabilitySettings>;
  api_keys: Record<string, APIKeyStatus>;
  local_model_paths: Record<AIProviderKind, string | null>;
}

export type AICapabilitySettingsUpdate = Partial<AICapabilitySettings>;

export interface BackendAISettingsUpdate {
  preferred_processing_mode?: AIProcessingMode;
  fallback_enabled?: boolean;
  capabilities?: Partial<Record<AIProviderKind, AICapabilitySettingsUpdate>>;
  local_model_paths?: Partial<Record<AIProviderKind, string | null>>;
  domain_terms?: string[];
}

export type LocalTranscriptionModelStatus =
  | "not_downloaded" | "queued" | "downloading" | "downloaded" | "completed" | "failed";

export interface LocalTranscriptionModel {
  model_id: string;
  provider_id: "whisper-cpp";
  tier: "fast" | "balanced" | "accurate" | string;
  label: string;
  expected_filename: string;
  download_url: string;
  description: string;
  size: string;
  size_mb: number;
  speed: string;
  quality: string;
  active: boolean;
  downloaded: boolean;
  managed: boolean;
  status: LocalTranscriptionModelStatus;
  can_download: boolean;
  can_remove: boolean;
  download_progress_percent: number | null;
  file_path: string | null;
}

export interface LocalTranscriptionModelCatalog {
  provider_id: "whisper-cpp";
  active_model_id: string;
  models: LocalTranscriptionModel[];
}

export interface LocalTranscriptionModelDownload {
  job_id: string;
  provider_id: "whisper-cpp";
  model_id: string;
  status: "queued" | "downloading" | "completed" | "failed" | string;
  file_path: string;
  download_url: string;
  total_bytes: number | null;
  bytes_downloaded: number;
  progress_percent: number;
  message: string;
  error: string | null;
  active: boolean;
}

export interface LocalTranscriptionModelRemoveResult {
  provider_id: "whisper-cpp";
  model_id: string;
  removed: boolean;
  file_path: string | null;
  message: string;
}

export interface AppSettings {
  backend_url: string;
  asr_provider: string;
  domain_terms: string[];
  auto_accept_threshold: number;
}
