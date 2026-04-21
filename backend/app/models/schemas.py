"""
Pydantic schemas for API requests and responses.
Updated for v2: speaker diarization, ASR provider tracking, domain terms.
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from uuid import UUID
from db.models import VideoStatus, SegmentAction, SegmentType


# ═══════════════════════════════════════════
#  VIDEO
# ═══════════════════════════════════════════

class VideoUploadResponse(BaseModel):
    id: UUID
    filename: str
    status: VideoStatus
    duration_seconds: Optional[float] = None
    resolution: Optional[str] = None
    file_size_mb: Optional[float] = None
    message: str = "Video uploaded successfully. Processing will begin shortly."

    class Config:
        from_attributes = True


class VideoResponse(BaseModel):
    id: UUID
    original_filename: str
    duration_seconds: Optional[float] = None
    resolution: Optional[str] = None
    status: VideoStatus
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class VideoDetailResponse(VideoResponse):
    transcript: Optional["TranscriptResponse"] = None
    segments: Optional[List["SegmentResponse"]] = None
    edit_plan: Optional["EditPlanResponse"] = None
    scenes: Optional[List["SceneResponse"]] = None


# ═══════════════════════════════════════════
#  TRANSCRIPT (with diarization support)
# ═══════════════════════════════════════════

class TranscriptWord(BaseModel):
    word: str
    start: float
    end: float
    speaker: Optional[str] = None              # e.g. "Speaker 1" (from Voxtral diarization)


class TranscriptSegment(BaseModel):
    text: str
    start: float
    end: float
    speaker: Optional[str] = None              # e.g. "Speaker 1" (from Voxtral diarization)


class SpeakerInfo(BaseModel):
    label: str                                 # e.g. "Speaker 1"
    segments_count: int


class TranscriptResponse(BaseModel):
    id: UUID
    full_text: Optional[str] = None
    language: Optional[str] = None
    word_count: Optional[int] = None
    asr_provider: Optional[str] = None         # "voxtral", "whisper", "whisper_fallback"
    speakers: Optional[List[SpeakerInfo]] = None
    segments: Optional[List[TranscriptSegment]] = None

    class Config:
        from_attributes = True


# ═══════════════════════════════════════════
#  SEGMENT
# ═══════════════════════════════════════════

class SegmentResponse(BaseModel):
    id: UUID
    segment_index: int
    start_time: float
    end_time: float
    duration: Optional[float] = None
    text: Optional[str] = None
    speaker: Optional[str] = None              # Speaker label from diarization

    # Agent 2 — Content Understanding
    topic_label: Optional[str] = None
    summary: Optional[str] = None
    importance_score: Optional[float] = None
    segment_type: Optional[SegmentType] = None

    # Agent 3 — Fluency
    filler_count: Optional[int] = 0
    filler_words: Optional[List[str]] = None
    fluency_score: Optional[float] = None
    pause_duration_total: Optional[float] = 0.0
    has_repetition: Optional[bool] = False

    # Agent 4 — Visual
    has_slide_change: Optional[bool] = False
    slide_index: Optional[int] = None
    scene_id: Optional[str] = None

    # Agent 5 — Edit Decision
    action: Optional[SegmentAction] = SegmentAction.KEEP
    action_confidence: Optional[float] = None
    action_reason: Optional[str] = None

    # Teacher override
    teacher_action: Optional[SegmentAction] = None
    teacher_note: Optional[str] = None
    is_teacher_modified: bool = False

    class Config:
        from_attributes = True


class SegmentUpdateRequest(BaseModel):
    """Teacher updates a single segment's action."""
    teacher_action: SegmentAction
    teacher_note: Optional[str] = None


class BulkSegmentUpdateRequest(BaseModel):
    """Teacher bulk-updates multiple segments."""
    updates: List[dict]  # [{"segment_id": "...", "teacher_action": "keep", "teacher_note": "..."}]


# ═══════════════════════════════════════════
#  SCENE
# ═══════════════════════════════════════════

class SceneResponse(BaseModel):
    id: UUID
    timestamp: float
    scene_index: int
    scene_type: Optional[str] = None
    thumbnail_path: Optional[str] = None
    confidence: Optional[float] = None

    class Config:
        from_attributes = True


# ═══════════════════════════════════════════
#  EDIT PLAN
# ═══════════════════════════════════════════

class EditPlanResponse(BaseModel):
    id: UUID
    original_duration: Optional[float] = None
    estimated_duration: Optional[float] = None
    segments_total: Optional[int] = None
    segments_keep: Optional[int] = None
    segments_cut: Optional[int] = None
    segments_highlight: Optional[int] = None
    filler_words_removed: Optional[int] = None
    silence_removed_seconds: Optional[float] = None
    is_approved: bool = False
    approved_at: Optional[datetime] = None
    teacher_notes: Optional[str] = None

    class Config:
        from_attributes = True


class EditPlanApproveRequest(BaseModel):
    teacher_notes: Optional[str] = None


# ═══════════════════════════════════════════
#  COURSE MATERIAL
# ═══════════════════════════════════════════

class CourseMaterialUploadResponse(BaseModel):
    id: UUID
    filename: str
    file_type: Optional[str] = None
    chunk_count: int = 0
    message: str = "Material uploaded and will be embedded into the knowledge base."


class CourseMaterialResponse(BaseModel):
    id: UUID
    filename: str
    file_type: Optional[str] = None
    chunk_count: int = 0
    is_embedded: bool = False
    created_at: datetime

    class Config:
        from_attributes = True


# ═══════════════════════════════════════════
#  PROCESSING STATUS
# ═══════════════════════════════════════════

class ProcessingStatus(BaseModel):
    video_id: UUID
    status: VideoStatus
    current_step: str
    progress_percent: Optional[float] = None
    message: Optional[str] = None


# ═══════════════════════════════════════════
#  SETTINGS (for desktop app to read/write)
# ═══════════════════════════════════════════

class AppSettingsResponse(BaseModel):
    asr_provider: str
    agent2_model: str
    agent3_model: str
    agent5_model: str
    embedding_model: str
    domain_terms: List[str]


class DomainTermsUpdateRequest(BaseModel):
    """Teacher updates domain-specific terms for ASR context biasing."""
    terms: List[str] = Field(max_length=100)   # max 100 terms per Voxtral spec


# Resolve forward references
VideoDetailResponse.model_rebuild()
