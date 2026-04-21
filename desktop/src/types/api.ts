/** Mirrors backend db/models.py and models/schemas.py */

export type VideoStatus =
  | "uploaded" | "processing" | "transcribing" | "analyzing"
  | "planning" | "awaiting_review" | "rendering" | "completed" | "failed";

export type SegmentAction = "keep" | "cut" | "shorten" | "highlight";

export type SegmentType =
  | "core_content" | "example" | "filler" | "pause"
  | "repetition" | "intro_outro" | "qa" | "transition";

// ── Video ──

export interface Video {
  id: string;
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

export interface AppSettings {
  backend_url: string;
  asr_provider: string;
  domain_terms: string[];
  auto_accept_threshold: number;
}
