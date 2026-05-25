"""
Pydantic schemas for API requests and responses.
Updated for v2: speaker diarization, ASR provider tracking, domain terms.
"""

from pydantic import BaseModel, Field, computed_field
from typing import Any, Dict, Optional, List
from datetime import datetime
from uuid import UUID
from db.models import (
    ProjectAssetSyncRole,
    ProjectAssetKind,
    ProjectMediaSourceType,
    ProjectAssetRole,
    ProjectAssetStatus,
    ProjectSourceMode,
    ProjectStatus,
    VideoStatus,
    SegmentAction,
    SegmentType,
)


# ═══════════════════════════════════════════
#  PROJECT / VIDEO COMPATIBILITY
# ═══════════════════════════════════════════

class ProjectAssetResponse(BaseModel):
    id: UUID
    project_id: UUID
    kind: ProjectAssetKind
    role: ProjectAssetRole
    source_type: ProjectMediaSourceType = ProjectMediaSourceType.OTHER
    sync_role: ProjectAssetSyncRole = ProjectAssetSyncRole.NONE
    status: ProjectAssetStatus
    is_primary: bool = False
    filename: str
    original_filename: str
    file_path: str
    file_size_bytes: Optional[int] = None
    mime_type: Optional[str] = None
    duration_seconds: Optional[float] = None
    sync_offset_seconds: float = 0.0
    metadata_json: Dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    @computed_field
    @property
    def structure_reference_role(self) -> Optional[str]:
        value = (self.metadata_json or {}).get("structure_reference_role")
        return str(value) if value is not None else None

    @computed_field
    @property
    def document_format(self) -> Optional[str]:
        value = (self.metadata_json or {}).get("document_format")
        return str(value) if value is not None else None

    @computed_field
    @property
    def structure_inference_ready(self) -> bool:
        return bool((self.metadata_json or {}).get("structure_inference_ready", False))

    class Config:
        from_attributes = True


class ProjectAssetSyncUpdateRequest(BaseModel):
    sync_offset_seconds: float = Field(ge=-3600, le=3600)
    note: Optional[str] = Field(default=None, max_length=500)


class ProjectSourceSyncAsset(BaseModel):
    asset: ProjectAssetResponse
    reference_asset_id: UUID
    recommended_offset_seconds: float
    current_offset_seconds: float
    manual_adjustment_seconds: float
    confidence: float
    method: str
    reason: str
    needs_user_review: bool = True
    waveform_sync_ready: bool = True
    metadata_anchor: Optional[Dict[str, Any]] = None


class ProjectSourceSyncPlanResponse(BaseModel):
    project_id: UUID
    reference_asset_id: Optional[UUID] = None
    sync_basis: str = "metadata"
    assets: List[ProjectSourceSyncAsset] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)


class ProjectSourceSyncApplyRequest(BaseModel):
    force: bool = False
    note: Optional[str] = Field(default=None, max_length=500)


class ProjectResponse(BaseModel):
    id: UUID
    title: str
    description: Optional[str] = None
    status: ProjectStatus
    source_mode: ProjectSourceMode
    project_type: Optional[str] = "lecture"
    metadata_json: Dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ProjectDetailResponse(ProjectResponse):
    assets: List[ProjectAssetResponse] = Field(default_factory=list)


class ProjectCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    source_mode: ProjectSourceMode = ProjectSourceMode.SINGLE_VIDEO
    project_type: str = Field(default="lecture", max_length=50)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ProjectAssetUploadResponse(ProjectAssetResponse):
    file_size_mb: Optional[float] = None
    message: str = "Asset uploaded successfully."


class VideoUploadResponse(BaseModel):
    id: UUID
    project_id: Optional[UUID] = None
    project_asset_id: Optional[UUID] = None
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
    project_id: Optional[UUID] = None
    project_asset_id: Optional[UUID] = None
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
    project: Optional[ProjectResponse] = None
    project_asset: Optional[ProjectAssetResponse] = None
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


class TranscriptTimelineWord(BaseModel):
    word_index: int
    text: str
    start_time: float
    end_time: float
    duration: float
    speaker: Optional[str] = None
    confidence: Optional[float] = None
    is_estimated: bool = False
    source: str = "asr_word"
    transcript_segment_index: Optional[int] = None
    segment_id: Optional[UUID] = None
    segment_index: Optional[int] = None


class TranscriptTimelineSegment(BaseModel):
    segment_id: UUID
    segment_index: int
    start_time: float
    end_time: float
    duration: Optional[float] = None
    text: Optional[str] = None
    speaker: Optional[str] = None
    word_start_index: Optional[int] = None
    word_end_index: Optional[int] = None
    word_count: int = 0


class TranscriptTimelineResponse(BaseModel):
    video_id: UUID
    transcript_id: UUID
    full_text: Optional[str] = None
    language: Optional[str] = None
    asr_provider: Optional[str] = None
    duration_seconds: Optional[float] = None
    word_count: int = 0
    words: List[TranscriptTimelineWord] = Field(default_factory=list)
    segments: List[TranscriptTimelineSegment] = Field(default_factory=list)


class TranscriptCutDecisionRequest(BaseModel):
    word_start_index: int = Field(ge=0)
    word_end_index: int = Field(ge=0)
    teacher_note: Optional[str] = Field(default=None, max_length=500)


class TranscriptCutTrimUpdateRequest(BaseModel):
    start_time: Optional[float] = Field(default=None, ge=0)
    end_time: Optional[float] = Field(default=None, ge=0)
    pre_roll_seconds: Optional[float] = Field(default=None, ge=0, le=5)
    post_roll_seconds: Optional[float] = Field(default=None, ge=0, le=5)
    teacher_note: Optional[str] = Field(default=None, max_length=500)


class TranscriptCutDecisionResponse(BaseModel):
    id: str
    kind: str = "transcript_cut"
    action: str = "cut"
    source: str = "manual_text_selection"
    status: str = "active"
    text: str
    word_start_time: Optional[float] = None
    word_end_time: Optional[float] = None
    start_time: float
    end_time: float
    duration: float
    pre_roll_seconds: float = 0.0
    post_roll_seconds: float = 0.0
    trim_source: str = "word_bounds"
    word_start_index: int
    word_end_index: int
    segment_ids: List[str] = Field(default_factory=list)
    segment_indexes: List[int] = Field(default_factory=list)
    teacher_note: Optional[str] = None
    created_at: str
    updated_at: Optional[str] = None


class TranscriptCutIntervalResponse(BaseModel):
    start_time: float
    end_time: float
    duration: float
    decision_ids: List[str] = Field(default_factory=list)
    texts: List[str] = Field(default_factory=list)
    word_start_index: Optional[int] = None
    word_end_index: Optional[int] = None
    source: str = "transcript_cut"


class EditDecisionPlayableRangeResponse(BaseModel):
    segment_id: UUID
    segment_index: int
    source_start_time: float
    source_end_time: float
    duration: float
    output_start_time: float
    output_end_time: float
    action: str


class EditDecisionSegmentOverlayResponse(BaseModel):
    segment_id: UUID
    segment_index: int
    cut_intervals: List[TranscriptCutIntervalResponse] = Field(default_factory=list)
    covered_duration: float = 0.0


class EditDecisionExportPlanResponse(BaseModel):
    source_duration_seconds: Optional[float] = None
    estimated_output_duration_seconds: float = 0.0
    transcript_cut_count: int = 0
    merged_cut_interval_count: int = 0
    transcript_cut_duration_seconds: float = 0.0
    playable_range_count: int = 0


class EditDecisionSyncResponse(BaseModel):
    schema_version: str
    cut_intervals: List[TranscriptCutIntervalResponse] = Field(default_factory=list)
    playable_ranges: List[EditDecisionPlayableRangeResponse] = Field(default_factory=list)
    segment_overlays: List[EditDecisionSegmentOverlayResponse] = Field(default_factory=list)
    export_plan: EditDecisionExportPlanResponse


class CleanProfileResponse(BaseModel):
    id: str
    label: str
    description: str


class CleanSuggestionResponse(BaseModel):
    id: str
    type: str
    title: str
    text: str = ""
    reason: str
    confidence: float
    start_time: float
    end_time: float
    duration: float
    word_start_index: Optional[int] = None
    word_end_index: Optional[int] = None
    segment_id: Optional[str] = None
    segment_index: Optional[int] = None
    target_action: str
    apply_kind: str
    padding_seconds: Optional[float] = None
    matched_text: Optional[str] = None
    duplicate_of_segment_id: Optional[str] = None
    duplicate_of_segment_index: Optional[int] = None


class CleanSummaryResponse(BaseModel):
    suggestions_total: int = 0
    filler_word_count: int = 0
    dead_air_count: int = 0
    bad_take_count: int = 0
    false_start_count: int = 0
    repeated_phrase_count: int = 0
    restarted_sentence_count: int = 0
    repeated_explanation_count: int = 0
    repetition_suggestion_count: int = 0
    estimated_time_saved_seconds: float = 0.0


class CleanAnalyzeResponse(BaseModel):
    schema_version: str
    profile: str
    profiles: List[CleanProfileResponse] = Field(default_factory=list)
    summary: CleanSummaryResponse
    suggestions: List[CleanSuggestionResponse] = Field(default_factory=list)


class CleanApplyRequest(BaseModel):
    profile: str = "conservative"
    suggestion_ids: Optional[List[str]] = None


class CleanSegmentUpdateResponse(BaseModel):
    segment_id: str
    segment_index: int
    teacher_action: str
    teacher_note: Optional[str] = None


class CleanApplyResponse(BaseModel):
    schema_version: str
    profile: str
    summary: CleanSummaryResponse
    created_transcript_cuts: List[TranscriptCutDecisionResponse] = Field(default_factory=list)
    updated_segments: List[CleanSegmentUpdateResponse] = Field(default_factory=list)
    suggestions: List[CleanSuggestionResponse] = Field(default_factory=list)


class TopicSectionSignalResponse(BaseModel):
    topic_change: bool = False
    long_pause: bool = False
    content_shift: bool = False
    transition_cue: bool = False
    slide_change: bool = False
    structure_title_change: bool = False
    pause_seconds: float = 0.0
    content_shift_score: float = 0.0
    structure_match_confidence: float = 0.0
    structure_title: Optional[str] = None
    structure_reference_role: Optional[str] = None


class LectureSectionResponse(BaseModel):
    id: str
    chapter_index: int
    timestamp: float
    formatted: str
    label: str
    title: str
    summary: str = ""
    start_time: float
    end_time: float
    duration: float
    segment_start_index: int
    segment_end_index: int
    segment_index: int
    segment_indexes: List[int] = Field(default_factory=list)
    segment_count: int
    keywords: List[str] = Field(default_factory=list)
    confidence: float
    boundary_reason: str
    source_signals: TopicSectionSignalResponse
    label_source: str = "transcript"
    structure_reference: Optional[Dict[str, Any]] = None


class ChapterResponse(BaseModel):
    timestamp: float
    formatted: str
    label: str
    segment_index: int
    duration: Optional[float] = None
    confidence: Optional[float] = None
    boundary_reason: Optional[str] = None
    keywords: List[str] = Field(default_factory=list)
    segment_count: Optional[int] = None
    structure_reference: Optional[Dict[str, Any]] = None


class TopicSegmentationSummaryResponse(BaseModel):
    sections_total: int = 0
    chapters_total: int = 0
    average_confidence: float = 0.0
    estimated_total_duration_seconds: float = 0.0
    structure_reference_count: int = 0
    slide_aware_sections: int = 0


class TopicSegmentationResponse(BaseModel):
    video_id: UUID
    schema_version: str
    summary: TopicSegmentationSummaryResponse
    sections: List[LectureSectionResponse] = Field(default_factory=list)
    chapters: List[ChapterResponse] = Field(default_factory=list)
    chapters_count: int = 0
    youtube_format: str = ""


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
    teacher_action: Optional[SegmentAction] = None
    teacher_note: Optional[str] = None
    is_teacher_modified: Optional[bool] = None


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
    plan_json: Optional[Any] = Field(default=None, exclude=True)
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

    @computed_field
    @property
    def schema_version(self) -> str:
        return self._payload().get("schema_version", "phase6.edit-plan.v2")

    @computed_field
    @property
    def metadata(self) -> Dict[str, Any]:
        return self._payload().get("metadata", {})

    @computed_field
    @property
    def segments(self) -> List[Dict[str, Any]]:
        return self._payload().get("segments", [])

    @computed_field
    @property
    def edit_decisions(self) -> List[Dict[str, Any]]:
        return self._payload().get("edit_decisions", [])

    @computed_field
    @property
    def transcript_edit_summary(self) -> Dict[str, Any]:
        return self._payload().get("transcript_edit_summary", {})

    @computed_field
    @property
    def cleaning_suggestions(self) -> List[Dict[str, Any]]:
        return self._payload().get("cleaning_suggestions", [])

    @computed_field
    @property
    def clean_summary(self) -> Dict[str, Any]:
        return self._payload().get("clean_summary", {})

    @computed_field
    @property
    def sections(self) -> List[Dict[str, Any]]:
        return self._payload().get("sections", [])

    @computed_field
    @property
    def chapters(self) -> List[Dict[str, Any]]:
        return self._payload().get("chapters", [])

    @computed_field
    @property
    def section_summary(self) -> Dict[str, Any]:
        return self._payload().get("section_summary", {})

    @computed_field
    @property
    def layout_cues(self) -> List[Dict[str, Any]]:
        return self._payload().get("layout_cues", [])

    @computed_field
    @property
    def polish_actions(self) -> List[Dict[str, Any]]:
        return self._payload().get("polish_actions", [])

    @computed_field
    @property
    def export_metadata(self) -> Dict[str, Any]:
        return self._payload().get("export_metadata", {})

    def _payload(self) -> Dict[str, Any]:
        from services.edit_plan_payload import normalize_plan_payload

        return normalize_plan_payload(getattr(self, "plan_json", None))

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
    preferred_processing_mode: str = "hybrid"
    fallback_enabled: bool = True
    capabilities: Dict[str, "AICapabilitySettings"] = Field(default_factory=dict)
    api_keys: Dict[str, "APIKeyStatus"] = Field(default_factory=dict)
    local_model_paths: Dict[str, Optional[str]] = Field(default_factory=dict)


class AICapabilitySettings(BaseModel):
    mode: str
    api_provider_id: Optional[str] = None
    local_provider_id: Optional[str] = None
    fallback_enabled: bool = True
    hybrid_fallback_order: List[str] = Field(default_factory=list)


class APIKeyStatus(BaseModel):
    provider: str
    source: str = "env"
    env_var: Optional[str] = None
    has_key: bool = False
    display_value: Optional[str] = None
    updated_at: Optional[str] = None


class LocalTranscriptionModelCatalogItem(BaseModel):
    model_id: str
    provider_id: str = "whisper-cpp"
    tier: str
    label: str
    expected_filename: str
    download_url: str
    description: str
    size: str
    size_mb: int
    speed: str
    quality: str
    active: bool = False
    downloaded: bool = False
    managed: bool = True
    status: str = "not_downloaded"
    can_download: bool = True
    can_remove: bool = False
    download_progress_percent: Optional[float] = None
    file_path: Optional[str] = None


class LocalTranscriptionModelCatalogResponse(BaseModel):
    provider_id: str = "whisper-cpp"
    active_model_id: str
    models: List[LocalTranscriptionModelCatalogItem]


class LocalTranscriptionModelDownloadRequest(BaseModel):
    make_active: bool = True


class LocalTranscriptionModelDownloadResponse(BaseModel):
    job_id: str
    provider_id: str = "whisper-cpp"
    model_id: str
    status: str
    file_path: str
    download_url: str
    total_bytes: Optional[int] = None
    bytes_downloaded: int = 0
    progress_percent: float = 0.0
    message: str
    error: Optional[str] = None
    active: bool = False


class LocalTranscriptionModelRemoveResponse(BaseModel):
    provider_id: str = "whisper-cpp"
    model_id: str
    removed: bool
    file_path: Optional[str] = None
    message: str


class APIKeyUpdate(BaseModel):
    api_key: Optional[str] = Field(default=None, max_length=4096)
    clear: bool = False
    use_env: bool = False
    env_var: Optional[str] = Field(default=None, max_length=100)


class AICapabilitySettingsUpdate(BaseModel):
    mode: Optional[str] = None
    api_provider_id: Optional[str] = Field(default=None, max_length=100)
    local_provider_id: Optional[str] = Field(default=None, max_length=100)
    fallback_enabled: Optional[bool] = None
    hybrid_fallback_order: Optional[List[str]] = None


class AppSettingsUpdateRequest(BaseModel):
    preferred_processing_mode: Optional[str] = None
    fallback_enabled: Optional[bool] = None
    capabilities: Optional[Dict[str, AICapabilitySettingsUpdate]] = None
    api_keys: Optional[Dict[str, APIKeyUpdate]] = None
    local_model_paths: Optional[Dict[str, Optional[str]]] = None
    domain_terms: Optional[List[str]] = Field(default=None, max_length=100)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DomainTermsUpdateRequest(BaseModel):
    """Teacher updates domain-specific terms for ASR context biasing."""
    terms: List[str] = Field(max_length=100)   # max 100 terms per Voxtral spec


# Resolve forward references
VideoDetailResponse.model_rebuild()
AppSettingsResponse.model_rebuild()
