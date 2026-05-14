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

class Video(Base):
    __tablename__ = "videos"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
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
