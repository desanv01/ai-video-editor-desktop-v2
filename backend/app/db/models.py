"""
Database ORM models — represents the core data entities.
"""

import uuid
from datetime import datetime
from sqlalchemy import (
    Column, String, Text, Float, Integer, Boolean,
    DateTime, ForeignKey, Enum, JSON
)
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from db.database import Base
import enum


# ── Enums ──

def enum_values(enum_class):
    return [item.value for item in enum_class]


class VideoStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    TRANSCRIBING = "transcribing"
    ANALYZING = "analyzing"
    PLANNING = "planning"
    AWAITING_REVIEW = "awaiting_review"
    RENDERING = "rendering"
    COMPLETED = "completed"
    FAILED = "failed"


class ProjectStatus(str, enum.Enum):
    DRAFT = "draft"
    IMPORTING = "importing"
    READY = "ready"
    PROCESSING = "processing"
    AWAITING_REVIEW = "awaiting_review"
    COMPLETED = "completed"
    ARCHIVED = "archived"
    FAILED = "failed"


class ProjectSourceMode(str, enum.Enum):
    SINGLE_VIDEO = "single_video"
    MULTI_SOURCE = "multi_source"


class ProjectAssetKind(str, enum.Enum):
    MIXED_VIDEO = "mixed_video"
    SCREEN_VIDEO = "screen_video"
    CAMERA_VIDEO = "camera_video"
    AUDIO = "audio"
    SLIDE_DECK = "slide_deck"
    PDF_NOTES = "pdf_notes"
    TEXT_NOTES = "text_notes"
    IMAGE = "image"
    B_ROLL = "b_roll"
    TRANSCRIPT = "transcript"
    COURSE_MATERIAL = "course_material"
    OTHER = "other"


class ProjectAssetRole(str, enum.Enum):
    PRIMARY = "primary"
    SCREEN = "screen"
    CAMERA = "camera"
    AUDIO = "audio"
    SLIDES = "slides"
    NOTES = "notes"
    SUPPORTING_MATERIAL = "supporting_material"
    B_ROLL = "b_roll"
    TRANSCRIPT = "transcript"
    OTHER = "other"


class ProjectMediaSourceType(str, enum.Enum):
    MIXED_VIDEO = "mixed_video"
    SCREEN_RECORDING = "screen_recording"
    CAMERA_RECORDING = "camera_recording"
    WEBCAM_RECORDING = "webcam_recording"
    PHONE_CAMERA_RECORDING = "phone_camera_recording"
    SEPARATE_AUDIO = "separate_audio"
    SLIDE_DECK = "slide_deck"
    PDF_NOTES = "pdf_notes"
    TEXT_NOTES = "text_notes"
    COURSE_MATERIAL = "course_material"
    IMAGE = "image"
    B_ROLL = "b_roll"
    TRANSCRIPT = "transcript"
    OTHER = "other"


class ProjectAssetSyncRole(str, enum.Enum):
    PRIMARY_TIMELINE = "primary_timeline"
    SCREEN_REFERENCE = "screen_reference"
    CAMERA_OVERLAY = "camera_overlay"
    AUDIO_MASTER = "audio_master"
    AUDIO_REFERENCE = "audio_reference"
    STRUCTURE_REFERENCE = "structure_reference"
    NONE = "none"


class ProjectAssetStatus(str, enum.Enum):
    UPLOADED = "uploaded"
    READY = "ready"
    PROCESSING = "processing"
    FAILED = "failed"
    ARCHIVED = "archived"


class SegmentAction(str, enum.Enum):
    KEEP = "keep"
    CUT = "cut"
    SHORTEN = "shorten"
    HIGHLIGHT = "highlight"


class SegmentType(str, enum.Enum):
    CORE_CONTENT = "core_content"
    EXAMPLE = "example"
    FILLER = "filler"
    PAUSE = "pause"
    REPETITION = "repetition"
    INTRO_OUTRO = "intro_outro"
    QA = "qa"
    TRANSITION = "transition"


# ── Models ──

class Project(Base):
    """Top-level editing workspace for single-video and future multi-source flows."""
    __tablename__ = "projects"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title = Column(String(255), nullable=False)
    description = Column(Text)
    status = Column(Enum(ProjectStatus, values_callable=enum_values, native_enum=False), default=ProjectStatus.DRAFT, nullable=False)
    source_mode = Column(Enum(ProjectSourceMode, values_callable=enum_values, native_enum=False), default=ProjectSourceMode.SINGLE_VIDEO, nullable=False)
    project_type = Column(String(50), default="lecture")
    metadata_json = Column(JSON, default=dict)
    error_message = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    assets = relationship("ProjectAsset", back_populates="project", cascade="all, delete-orphan", order_by="ProjectAsset.created_at")
    videos = relationship("Video", back_populates="project")


class ProjectAsset(Base):
    """A project-owned source file or material that can feed editing and analysis."""
    __tablename__ = "project_assets"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)

    kind = Column(Enum(ProjectAssetKind, values_callable=enum_values, native_enum=False), nullable=False)
    role = Column(Enum(ProjectAssetRole, values_callable=enum_values, native_enum=False), default=ProjectAssetRole.OTHER, nullable=False)
    source_type = Column(Enum(ProjectMediaSourceType, values_callable=enum_values, native_enum=False), default=ProjectMediaSourceType.OTHER, nullable=False)
    sync_role = Column(Enum(ProjectAssetSyncRole, values_callable=enum_values, native_enum=False), default=ProjectAssetSyncRole.NONE, nullable=False)
    status = Column(Enum(ProjectAssetStatus, values_callable=enum_values, native_enum=False), default=ProjectAssetStatus.UPLOADED, nullable=False)
    is_primary = Column(Boolean, default=False, nullable=False)

    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_size_bytes = Column(Integer)
    mime_type = Column(String(100))
    duration_seconds = Column(Float)

    sync_offset_seconds = Column(Float, default=0.0, nullable=False)
    metadata_json = Column(JSON, default=dict)
    error_message = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    project = relationship("Project", back_populates="assets")
    legacy_video = relationship("Video", back_populates="project_asset", foreign_keys="Video.project_asset_id", uselist=False)


class Video(Base):
    __tablename__ = "videos"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(UUID(as_uuid=True), ForeignKey("projects.id", ondelete="SET NULL"))
    project_asset_id = Column(UUID(as_uuid=True), ForeignKey("project_assets.id", ondelete="SET NULL"), unique=True)
    filename = Column(String(255), nullable=False)
    original_filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_size_bytes = Column(Integer)
    duration_seconds = Column(Float)
    resolution = Column(String(20))       # e.g. "1920x1080"
    fps = Column(Float)
    status = Column(Enum(VideoStatus), default=VideoStatus.UPLOADED, nullable=False)
    error_message = Column(Text)

    # Processing metadata
    audio_path = Column(String(500))
    processed_video_path = Column(String(500))   # final rendered output

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    project = relationship("Project", back_populates="videos")
    project_asset = relationship("ProjectAsset", back_populates="legacy_video", foreign_keys=[project_asset_id], uselist=False)
    transcript = relationship("Transcript", back_populates="video", uselist=False, cascade="all, delete-orphan")
    segments = relationship("Segment", back_populates="video", cascade="all, delete-orphan", order_by="Segment.start_time")
    edit_plan = relationship("EditPlan", back_populates="video", uselist=False, cascade="all, delete-orphan")
    scenes = relationship("Scene", back_populates="video", cascade="all, delete-orphan", order_by="Scene.timestamp")


class Transcript(Base):
    __tablename__ = "transcripts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    video_id = Column(UUID(as_uuid=True), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False, unique=True)
    full_text = Column(Text)
    language = Column(String(10))
    word_count = Column(Integer)

    # Word-level timestamps
    # Format: [{"word": "Hello", "start": 0.0, "end": 0.5, "speaker": "Speaker 1"}, ...]
    words_json = Column(JSON)

    # Segment-level transcript with speaker labels (diarization)
    # Format: [{"text": "...", "start": 0.0, "end": 30.0, "speaker": "Speaker 1"}, ...]
    segments_json = Column(JSON)

    # Speaker diarization summary (from Voxtral)
    # Format: [{"label": "Speaker 1", "segments_count": 15}, ...]
    speakers_json = Column(JSON)

    # Which ASR provider was used
    asr_provider = Column(String(30))  # "voxtral", "whisper", "whisper_fallback"

    created_at = Column(DateTime, default=datetime.utcnow)

    video = relationship("Video", back_populates="transcript")


class Segment(Base):
    """
    A time-based segment of the video with analysis results.
    Created by Agents 2, 3, 4 and used by Agent 5 to build the edit plan.
    """
    __tablename__ = "segments"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    video_id = Column(UUID(as_uuid=True), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False)
    segment_index = Column(Integer, nullable=False)

    start_time = Column(Float, nullable=False)
    end_time = Column(Float, nullable=False)
    duration = Column(Float)
    text = Column(Text)
    speaker = Column(String(50))                # Speaker label from diarization (e.g. "Speaker 1")

    # Agent 2 — Content Understanding
    topic_label = Column(String(255))
    summary = Column(Text)
    importance_score = Column(Float)          # 0.0 to 1.0
    segment_type = Column(Enum(SegmentType))

    # Agent 3 — Fluency Analysis
    filler_count = Column(Integer, default=0)
    filler_words = Column(JSON)               # ["um", "uh", "like"]
    pause_duration_total = Column(Float, default=0.0)
    has_repetition = Column(Boolean, default=False)
    fluency_score = Column(Float)             # 0.0 to 1.0

    # Agent 4 — Visual Structure
    scene_id = Column(String(50))
    slide_index = Column(Integer)
    has_slide_change = Column(Boolean, default=False)

    # Agent 5 — Edit Decision
    action = Column(Enum(SegmentAction), default=SegmentAction.KEEP)
    action_confidence = Column(Float)         # 0.0 to 1.0
    action_reason = Column(Text)

    # Teacher override
    teacher_action = Column(Enum(SegmentAction))
    teacher_note = Column(Text)
    is_teacher_modified = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    video = relationship("Video", back_populates="segments")


class Scene(Base):
    """Scene/slide change boundaries detected by Agent 4 (Visual Structure)."""
    __tablename__ = "scenes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    video_id = Column(UUID(as_uuid=True), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False)

    timestamp = Column(Float, nullable=False)
    scene_index = Column(Integer, nullable=False)
    scene_type = Column(String(50))           # "slide", "face", "whiteboard", "demo"
    thumbnail_path = Column(String(500))
    confidence = Column(Float)

    created_at = Column(DateTime, default=datetime.utcnow)

    video = relationship("Video", back_populates="scenes")


class EditPlan(Base):
    """The complete edit plan generated by Agent 5, reviewed by teacher."""
    __tablename__ = "edit_plans"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    video_id = Column(UUID(as_uuid=True), ForeignKey("videos.id", ondelete="CASCADE"), nullable=False, unique=True)

    # The full plan as JSON array
    # [{"segment_id": "...", "start": 0, "end": 30, "action": "keep", ...}, ...]
    plan_json = Column(JSON)

    # Stats
    original_duration = Column(Float)
    estimated_duration = Column(Float)
    segments_total = Column(Integer)
    segments_keep = Column(Integer)
    segments_cut = Column(Integer)
    segments_highlight = Column(Integer)
    filler_words_removed = Column(Integer)
    silence_removed_seconds = Column(Float)

    # Review status
    is_approved = Column(Boolean, default=False)
    approved_at = Column(DateTime)
    teacher_notes = Column(Text)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    video = relationship("Video", back_populates="edit_plan")


class CourseMaterial(Base):
    """Course materials uploaded for RAG knowledge base."""
    __tablename__ = "course_materials"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_type = Column(String(20))            # "pdf", "pptx", "txt", "md"
    content_text = Column(Text)               # extracted text
    chunk_count = Column(Integer, default=0)
    is_embedded = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)


class AppAISettings(Base):
    """Singleton app settings for AI provider routing and local model choices."""
    __tablename__ = "app_ai_settings"

    id = Column(String(50), primary_key=True, default="default")
    preferred_processing_mode = Column(String(20), nullable=False, default="hybrid")
    fallback_enabled = Column(Boolean, nullable=False, default=True)

    # Per-capability settings keyed by ProviderKind.value.
    # Example:
    # {"chat": {"mode": "api", "api_provider_id": "deepseek-chat", ...}}
    capabilities_json = Column(JSON, nullable=False, default=dict)

    # API keys are never returned through API responses. Values stored here are
    # encrypted payloads plus redaction metadata or environment variable refs.
    api_keys_json = Column(JSON, nullable=False, default=dict)

    # Local model/runtime paths keyed by capability or runtime role.
    local_model_paths_json = Column(JSON, nullable=False, default=dict)

    # Domain terms are persisted here instead of mutating process memory only.
    domain_terms_json = Column(JSON, nullable=False, default=list)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
