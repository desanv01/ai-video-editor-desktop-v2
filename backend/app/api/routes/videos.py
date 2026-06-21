"""
API Routes — Video upload, processing, teacher review, rendering.
"""

import os
import uuid
import shutil
import logging
import json
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from db.database import get_db
from db.models import (
    Video, VideoStatus, Transcript, Segment, EditPlan, Scene,
    CourseMaterial, SegmentAction, Project, ProjectAsset,
    ProjectAssetKind, ProjectAssetRole, ProjectAssetStatus,
    ProjectAssetSyncRole, ProjectMediaSourceType,
    ProjectSourceMode, ProjectStatus,
)
from models.schemas import (
    VideoUploadResponse, VideoResponse, VideoDetailResponse,
    SegmentResponse, SegmentUpdateRequest, BulkSegmentUpdateRequest,
    EditDecisionSyncResponse,
    CleanAnalyzeResponse, CleanApplyRequest, CleanApplyResponse,
    TopicSegmentationResponse,
    TranscriptCutDecisionRequest, TranscriptCutDecisionResponse, TranscriptCutTrimUpdateRequest,
    TranscriptCutWordRestoreRequest,
    TranscriptTimelineResponse,
    EditPlanResponse, EditPlanApproveRequest, CaptionPolicyUpdateRequest,
    LayoutCuesUpdateRequest, LayoutCuesAutoGenerateRequest, SlideCuesUpdateRequest,
    EditorialBlocksUpdateRequest,
    AnnotationActionsUpdateRequest, EducationalOverlayActionsUpdateRequest,
    EndCardActionsUpdateRequest,
    ExportPresetCatalogResponse,
    CourseMaterialUploadResponse, CourseMaterialResponse,
    ProcessingStatus, AppSettingsResponse, AppSettingsUpdateRequest,
    DomainTermsUpdateRequest,
)
from agents.orchestrator import run_processing_pipeline, run_render_pipeline
from agents.edit_planner import revalidate_edit_plan
from services.ffmpeg import ffmpeg_service
from services.lecture_structure import build_structure_references_from_assets
from services.mode_comparison import (
    build_mode_comparison_markdown,
    build_mode_comparison_report,
)
from services.renderer import generate_quality_report
from services.text_extraction import text_extractor
from services.transcript_timeline import build_transcript_timeline
from services.transcript_edit_decisions import (
    build_synced_timeline_plan,
    create_transcript_cut_decision,
    list_transcript_cut_decisions,
    remove_transcript_cut_decision,
    restore_word_from_transcript_cut,
    update_transcript_cut_trim,
)
from services.clean_tools import analyze_clean_suggestions, apply_clean_suggestions
from services.edit_plan_payload import (
    normalize_plan_payload,
    update_annotations,
    update_caption_policy,
    update_educational_overlays,
    update_end_cards,
    update_export_metadata,
    update_layout_cues,
    update_slide_cues,
    update_editorial_blocks,
    update_sections_payload,
)
from services.semantic_render_plan import (
    build_semantic_render_plan,
    with_semantic_render_plan,
)
from services.export_artifacts import (
    artifact_records,
    build_academic_evidence_artifact,
    build_before_after_comparison,
    build_evidence_markdown,
    build_generated_evidence_index,
    build_metrics_summary_artifact,
    build_provider_mode_trace,
    build_timeline_decision_rows,
    build_timeline_decisions_artifact,
    create_artifact_bundle,
    TIMELINE_DECISION_CSV_FIELDS,
    write_csv_artifact,
    write_json_artifact,
    write_text_artifact,
)
from services.export_presets import get_export_preset, list_grouped_export_presets
from services.topic_segmentation import analyze_topic_sections
from services.progress import get_progress as get_pipeline_progress
from services.render_jobs import (
    create_render_job_with_status,
    get_active_render_job,
    get_latest_render_job,
    request_render_cancel,
)
from services.upload_limits import max_upload_size_bytes, upload_limit_label
from services.app_settings import (
    get_or_create_ai_settings,
    load_and_apply_persisted_ai_settings,
    settings_response,
    update_ai_settings,
)
from providers.whisper_cpp import resolve_whisper_cpp_runtime_status
from rag.vector_store import rag_service
from config import settings


router = APIRouter()
logger = logging.getLogger(__name__)
UPLOAD_COPY_BUFFER_BYTES = 8 * 1024 * 1024


# ═══════════════════════════════════════════
#  VIDEO ENDPOINTS
# ═══════════════════════════════════════════

@router.post("/videos/upload", response_model=VideoUploadResponse, tags=["Videos"])
async def upload_video(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload a video file and wait for the user to start processing."""
    # Validate file type
    allowed_types = {"video/mp4", "video/mpeg", "video/quicktime", "video/x-msvideo", "video/webm"}
    if file.content_type not in allowed_types:
        raise HTTPException(400, f"Invalid file type: {file.content_type}. Allowed: {allowed_types}")

    # Save file
    video_id = uuid.uuid4()
    ext = os.path.splitext(file.filename)[1] or ".mp4"
    filename = f"{video_id}{ext}"
    file_path = os.path.join(settings.UPLOAD_PATH, filename)

    os.makedirs(settings.UPLOAD_PATH, exist_ok=True)
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f, length=UPLOAD_COPY_BUFFER_BYTES)

    file_size = os.path.getsize(file_path)
    if file_size > max_upload_size_bytes(settings):
        os.remove(file_path)
        raise HTTPException(413, f"File too large. Maximum: {upload_limit_label(settings)}")

    # Get video metadata
    try:
        metadata = await ffmpeg_service.get_video_metadata(file_path)
    except Exception:
        metadata = {}

    # ── P1: Preprocess iPhone 4K .MOV / HEVC for compatibility ──
    # Detect files that need conversion: .MOV extension or HEVC/H.265 codec.
    # Convert to 1080p H.264 MP4 to avoid slowdown in the render pipeline.
    ext_lower = ext.lower()
    video_codec = str(metadata.get("video_codec", "")).lower() if metadata else ""
    needs_preprocessing = (
        ext_lower == ".mov"
        or video_codec in {"hevc", "h265", "hvc1"}
        or metadata.get("width", 0) > 1920
        or metadata.get("height", 0) > 1080
    )
    was_preprocessed = False
    if needs_preprocessing:
        logger.info(
            "Preprocessing upload %s (ext=%s, codec=%s, %dx%d) for compatibility",
            file.filename, ext_lower, video_codec,
            metadata.get("width", 0), metadata.get("height", 0),
        )
        preprocessed_filename = f"{video_id}_preprocessed.mp4"
        preprocessed_path = os.path.join(settings.UPLOAD_PATH, preprocessed_filename)
        try:
            await ffmpeg_service.preprocess_for_compatibility(
                input_path=file_path,
                output_path=preprocessed_path,
            )
            # Swap to the preprocessed file
            old_path = file_path
            file_path = preprocessed_path
            filename = preprocessed_filename
            ext = ".mp4"
            file_size = os.path.getsize(file_path)
            # Re-read metadata from the converted file
            try:
                metadata = await ffmpeg_service.get_video_metadata(file_path)
            except Exception:
                pass
            was_preprocessed = True
            # Remove the original large file to free space
            try:
                os.remove(old_path)
            except OSError:
                logger.warning("Could not remove original file after preprocessing: %s", old_path)
        except Exception as exc:
            logger.error("Preprocessing failed for %s, falling back to original: %s", file.filename, exc)
            # Continue with the original file — preprocessing is a best-effort optimisation

    # Create database record
    project = Project(
        title=os.path.splitext(file.filename)[0] or file.filename,
        status=ProjectStatus.READY,
        source_mode=ProjectSourceMode.SINGLE_VIDEO,
        project_type="lecture",
        metadata_json={"created_from": "legacy_video_upload"},
    )
    db.add(project)
    await db.flush()

    asset = ProjectAsset(
        project_id=project.id,
        kind=ProjectAssetKind.MIXED_VIDEO,
        role=ProjectAssetRole.PRIMARY,
        source_type=ProjectMediaSourceType.MIXED_VIDEO,
        sync_role=ProjectAssetSyncRole.PRIMARY_TIMELINE,
        status=ProjectAssetStatus.READY,
        is_primary=True,
        filename=filename,
        original_filename=file.filename,
        file_path=file_path,
        file_size_bytes=file_size,
        mime_type="video/mp4" if was_preprocessed else file.content_type,
        duration_seconds=metadata.get("duration"),
        metadata_json={
            "legacy_video_id": str(video_id),
            "source_type": ProjectMediaSourceType.MIXED_VIDEO.value,
            "sync_role": ProjectAssetSyncRole.PRIMARY_TIMELINE.value,
            "resolution": f"{metadata.get('width', 0)}x{metadata.get('height', 0)}" if metadata else None,
            "fps": metadata.get("fps"),
            **({"preprocessed": True, "preprocessed_from_original_filename": file.filename} if was_preprocessed else {}),
        },
    )
    db.add(asset)
    await db.flush()

    video = Video(
        id=video_id,
        project_id=project.id,
        project_asset_id=asset.id,
        filename=filename,
        original_filename=file.filename,
        file_path=file_path,
        file_size_bytes=file_size,
        duration_seconds=metadata.get("duration"),
        resolution=f"{metadata.get('width', 0)}x{metadata.get('height', 0)}",
        fps=metadata.get("fps"),
        status=VideoStatus.UPLOADED,
    )
    db.add(video)
    await db.commit()

    return VideoUploadResponse(
        id=video_id,
        project_id=project.id,
        project_asset_id=asset.id,
        filename=file.filename,
        status=VideoStatus.UPLOADED,
        duration_seconds=metadata.get("duration"),
        resolution=f"{metadata.get('width', 0)}x{metadata.get('height', 0)}" if metadata else None,
        file_size_mb=round(file_size / 1024 / 1024, 1),
        message=f"Video uploaded ({file_size / 1024 / 1024:.1f}MB). Add course materials, then start processing.",
    )


@router.post("/videos/{video_id}/process", tags=["Videos"])
async def start_video_processing(
    video_id: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Start the processing pipeline after video/material uploads are complete."""
    video = await db.get(Video, video_id)
    if not video:
        raise HTTPException(404, "Video not found")

    in_progress = {
        VideoStatus.PROCESSING,
        VideoStatus.TRANSCRIBING,
        VideoStatus.ANALYZING,
        VideoStatus.PLANNING,
        VideoStatus.RENDERING,
    }
    if video.status in in_progress:
        return {
            "status": video.status.value,
            "video_id": video_id,
            "message": "Processing is already running.",
        }

    if video.status in {VideoStatus.AWAITING_REVIEW, VideoStatus.COMPLETED}:
        return {
            "status": video.status.value,
            "video_id": video_id,
            "message": "This video has already been processed.",
        }

    await load_and_apply_persisted_ai_settings(db)
    preflight_error = _local_transcription_preflight_error()
    if preflight_error:
        raise HTTPException(409, preflight_error)

    video.status = VideoStatus.PROCESSING
    video.error_message = None
    await db.commit()

    background_tasks.add_task(_process_video_bg, str(video_id))

    return {
        "status": VideoStatus.PROCESSING.value,
        "video_id": video_id,
        "message": "Processing started.",
    }


@router.get("/videos", response_model=List[VideoResponse], tags=["Videos"])
async def list_videos(db: AsyncSession = Depends(get_db)):
    """List all uploaded videos."""
    result = await db.execute(
        select(Video).order_by(Video.created_at.desc())
    )
    return result.scalars().all()


@router.get("/videos/{video_id}", response_model=VideoDetailResponse, tags=["Videos"])
async def get_video(video_id: str, db: AsyncSession = Depends(get_db)):
    """Get full video details including transcript, segments, and edit plan."""
    result = await db.execute(
        select(Video)
        .options(
            selectinload(Video.transcript),
            selectinload(Video.project),
            selectinload(Video.project_asset),
            selectinload(Video.segments),
            selectinload(Video.edit_plan),
            selectinload(Video.scenes),
        )
        .where(Video.id == video_id)
    )
    video = result.scalar_one_or_none()
    if not video:
        raise HTTPException(404, "Video not found")
    return video


@router.get("/videos/{video_id}/status", tags=["Videos"])
async def get_processing_status(video_id: str, db: AsyncSession = Depends(get_db)):
    """
    Get processing status — used by the desktop app for polling.

    Returns both the durable DB status and the live pipeline progress
    (which step is currently running, timing per step, percentage).

    The desktop app should poll this every 2-3 seconds during processing.
    """
    video = await db.get(Video, video_id)
    if not video:
        raise HTTPException(404, "Video not found")

    # Get live pipeline/render progress (in-memory, detailed)
    progress = get_pipeline_progress(str(video_id))
    render_job = get_latest_render_job(str(video_id))
    render_active = bool(render_job and render_job.get("status") in {"queued", "running", "cancel_requested"})
    if video.status == VideoStatus.RENDERING and not render_active:
        terminal_status = str((render_job or {}).get("status") or "")
        if terminal_status == "completed":
            video.status = VideoStatus.COMPLETED
            video.error_message = None
        else:
            video.status = VideoStatus.FAILED
            video.error_message = str(
                (render_job or {}).get("error")
                or "Render interrupted because the backend stopped before completion. Start Export again."
            )
        await db.commit()
        await db.refresh(video)
    current_step = progress.get("current_step", video.status.value)
    current_step_label = progress.get("current_step_label", video.status.value)
    progress_percent = progress.get("progress_percent", 0)
    total_elapsed_seconds = progress.get("total_elapsed_seconds", 0)
    if render_active or video.status == VideoStatus.RENDERING:
        current_step = "rendering"
        current_step_label = (render_job or {}).get("phase_label") or "Rendering final video..."
        progress_percent = (render_job or {}).get("progress_percent", progress_percent)
        total_elapsed_seconds = (render_job or {}).get("elapsed_seconds", total_elapsed_seconds)

    return {
        "video_id": str(video.id),
        "status": video.status.value,
        "error_message": video.error_message,
        # Live pipeline progress
        "current_step": current_step,
        "current_step_label": current_step_label,
        "progress_percent": progress_percent,
        "steps_completed": progress.get("steps_completed", []),
        "steps_failed": progress.get("steps_failed", {}),
        "steps_timing": progress.get("steps_timing", {}),
        "total_elapsed_seconds": total_elapsed_seconds,
        "render_job": render_job,
    }


# ═══════════════════════════════════════════
#  TRANSCRIPT TIMELINE ENDPOINTS
# ═══════════════════════════════════════════

@router.get("/videos/{video_id}/transcript/timeline", response_model=TranscriptTimelineResponse, tags=["Transcript"])
async def get_transcript_timeline(video_id: str, db: AsyncSession = Depends(get_db)):
    """Get word-level transcript timing mapped to the existing review segments."""
    result = await db.execute(
        select(Video)
        .options(selectinload(Video.transcript), selectinload(Video.segments))
        .where(Video.id == video_id)
    )
    video = result.scalar_one_or_none()
    if not video:
        raise HTTPException(404, "Video not found")
    if not video.transcript:
        raise HTTPException(404, "Transcript not found")

    return build_transcript_timeline(
        video_id=video.id,
        transcript=video.transcript,
        review_segments=video.segments,
        duration_seconds=video.duration_seconds,
    )


@router.get(
    "/videos/{video_id}/transcript/cuts",
    response_model=List[TranscriptCutDecisionResponse],
    tags=["Transcript"],
)
async def get_transcript_cut_decisions(video_id: str, db: AsyncSession = Depends(get_db)):
    """List manual word-level cut decisions for a video's transcript."""
    result = await db.execute(
        select(EditPlan).where(EditPlan.video_id == video_id)
    )
    plan = result.scalar_one_or_none()
    return list_transcript_cut_decisions(plan)


@router.post(
    "/videos/{video_id}/transcript/cuts",
    response_model=TranscriptCutDecisionResponse,
    tags=["Transcript"],
)
async def create_transcript_cut(
    video_id: str,
    request: TranscriptCutDecisionRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create a cut decision from selected transcript words."""
    result = await db.execute(
        select(Video)
        .options(selectinload(Video.transcript), selectinload(Video.segments), selectinload(Video.edit_plan))
        .where(Video.id == video_id)
    )
    video = result.scalar_one_or_none()
    if not video:
        raise HTTPException(404, "Video not found")
    if not video.transcript:
        raise HTTPException(404, "Transcript not found")

    timeline = build_transcript_timeline(
        video_id=video.id,
        transcript=video.transcript,
        review_segments=video.segments,
        duration_seconds=video.duration_seconds,
    )

    plan = video.edit_plan
    if not plan:
        plan = EditPlan(
            id=uuid.uuid4(),
            video_id=video.id,
            plan_json=[],
            original_duration=video.duration_seconds,
            estimated_duration=video.duration_seconds,
            segments_total=len(video.segments),
            segments_keep=len(video.segments),
            segments_cut=0,
            segments_highlight=0,
        )
        db.add(plan)
        await db.flush()

    try:
        decision = create_transcript_cut_decision(
            plan=plan,
            timeline_words=timeline["words"],
            word_start_index=request.word_start_index,
            word_end_index=request.word_end_index,
            teacher_note=request.teacher_note,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    await db.commit()
    return decision


@router.delete(
    "/videos/{video_id}/transcript/cuts/{decision_id}",
    tags=["Transcript"],
)
async def delete_transcript_cut(
    video_id: str,
    decision_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Remove a manual transcript cut decision."""
    result = await db.execute(
        select(EditPlan).where(EditPlan.video_id == video_id)
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(404, "Edit plan not found")

    if not remove_transcript_cut_decision(plan=plan, decision_id=decision_id):
        raise HTTPException(404, "Transcript cut decision not found")

    await db.commit()
    return {"status": "removed", "decision_id": decision_id}


@router.put(
    "/videos/{video_id}/transcript/cuts/{decision_id}/trim",
    response_model=TranscriptCutDecisionResponse,
    tags=["Transcript"],
)
async def update_transcript_cut_trim_settings(
    video_id: str,
    decision_id: str,
    request: TranscriptCutTrimUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Adjust exact trim timing and pre/post-roll tolerance for a transcript cut."""
    result = await db.execute(
        select(EditPlan).where(EditPlan.video_id == video_id)
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(404, "Edit plan not found")

    try:
        decision = update_transcript_cut_trim(
            plan=plan,
            decision_id=decision_id,
            start_time=request.start_time,
            end_time=request.end_time,
            pre_roll_seconds=request.pre_roll_seconds,
            post_roll_seconds=request.post_roll_seconds,
            teacher_note=request.teacher_note,
        )
    except ValueError as exc:
        message = str(exc)
        if "not found" in message:
            raise HTTPException(404, message) from exc
        raise HTTPException(400, message) from exc

    await db.commit()
    return decision


@router.post(
    "/videos/{video_id}/transcript/cuts/{decision_id}/restore-word",
    response_model=List[TranscriptCutDecisionResponse],
    tags=["Transcript"],
)
async def restore_transcript_cut_word(
    video_id: str,
    decision_id: str,
    request: TranscriptCutWordRestoreRequest,
    db: AsyncSession = Depends(get_db),
):
    """Restore a single word from a cut decision and split the remaining cut range."""
    result = await db.execute(
        select(Video)
        .options(selectinload(Video.transcript), selectinload(Video.segments), selectinload(Video.edit_plan))
        .where(Video.id == video_id)
    )
    video = result.scalar_one_or_none()
    if not video:
        raise HTTPException(404, "Video not found")
    if not video.transcript:
        raise HTTPException(404, "Transcript not found")
    if not video.edit_plan:
        raise HTTPException(404, "Edit plan not found")

    timeline = build_transcript_timeline(
        video_id=video.id,
        transcript=video.transcript,
        review_segments=video.segments,
        duration_seconds=video.duration_seconds,
    )

    try:
        decisions = restore_word_from_transcript_cut(
            plan=video.edit_plan,
            timeline_words=timeline["words"],
            decision_id=decision_id,
            word_index=request.word_index,
            teacher_note=request.teacher_note,
        )
    except ValueError as exc:
        message = str(exc)
        if "not found" in message:
            raise HTTPException(404, message) from exc
        raise HTTPException(400, message) from exc

    await db.commit()
    return decisions


@router.get(
    "/videos/{video_id}/edit-decision-sync",
    response_model=EditDecisionSyncResponse,
    tags=["Edit Plan"],
)
async def get_edit_decision_sync(video_id: str, db: AsyncSession = Depends(get_db)):
    """Return synchronized transcript cuts, playable ranges, timeline overlays, and export planning."""
    result = await db.execute(
        select(Video)
        .options(selectinload(Video.segments), selectinload(Video.edit_plan))
        .where(Video.id == video_id)
    )
    video = result.scalar_one_or_none()
    if not video:
        raise HTTPException(404, "Video not found")

    return build_synced_timeline_plan(
        plan=video.edit_plan,
        segments=video.segments,
        duration_seconds=video.duration_seconds,
    )


# ═══════════════════════════════════════════
#  SEGMENT / REVIEW ENDPOINTS
# ═══════════════════════════════════════════

@router.get(
    "/videos/{video_id}/clean/analyze",
    response_model=CleanAnalyzeResponse,
    tags=["Clean"],
)
async def analyze_clean_tools(
    video_id: str,
    profile: str = "conservative",
    db: AsyncSession = Depends(get_db),
):
    """Preview Clean step suggestions for filler removal, repetition, dead air, and bad takes."""
    result = await db.execute(
        select(Video)
        .options(selectinload(Video.transcript), selectinload(Video.segments), selectinload(Video.edit_plan))
        .where(Video.id == video_id)
    )
    video = result.scalar_one_or_none()
    if not video:
        raise HTTPException(404, "Video not found")

    timeline_words = []
    if video.transcript:
        timeline = build_transcript_timeline(
            video_id=video.id,
            transcript=video.transcript,
            review_segments=video.segments,
            duration_seconds=video.duration_seconds,
        )
        timeline_words = timeline["words"]

    try:
        return analyze_clean_suggestions(
            segments=video.segments,
            timeline_words=timeline_words,
            plan=video.edit_plan,
            profile_id=profile,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post(
    "/videos/{video_id}/clean/apply",
    response_model=CleanApplyResponse,
    tags=["Clean"],
)
async def apply_clean_tools(
    video_id: str,
    request: CleanApplyRequest,
    db: AsyncSession = Depends(get_db),
):
    """Apply auto-clean suggestions as reviewable edit decisions."""
    result = await db.execute(
        select(Video)
        .options(selectinload(Video.transcript), selectinload(Video.segments), selectinload(Video.edit_plan))
        .where(Video.id == video_id)
    )
    video = result.scalar_one_or_none()
    if not video:
        raise HTTPException(404, "Video not found")

    timeline_words = []
    if video.transcript:
        timeline = build_transcript_timeline(
            video_id=video.id,
            transcript=video.transcript,
            review_segments=video.segments,
            duration_seconds=video.duration_seconds,
        )
        timeline_words = timeline["words"]

    plan = video.edit_plan
    if not plan:
        plan = EditPlan(
            id=uuid.uuid4(),
            video_id=video.id,
            plan_json=[],
            original_duration=video.duration_seconds,
            estimated_duration=video.duration_seconds,
            segments_total=len(video.segments),
            segments_keep=len(video.segments),
            segments_cut=0,
            segments_highlight=0,
        )
        db.add(plan)
        await db.flush()

    try:
        applied = apply_clean_suggestions(
            plan=plan,
            segments=video.segments,
            timeline_words=timeline_words,
            profile_id=request.profile,
            suggestion_ids=set(request.suggestion_ids) if request.suggestion_ids else None,
            suggestion_types=set(request.suggestion_types) if request.suggestion_types else None,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    await db.commit()
    return applied


@router.get("/videos/{video_id}/segments", response_model=List[SegmentResponse], tags=["Review"])
async def get_segments(video_id: str, db: AsyncSession = Depends(get_db)):
    """Get all segments with their analysis and edit decisions."""
    result = await db.execute(
        select(Segment)
        .where(Segment.video_id == video_id)
        .order_by(Segment.segment_index)
    )
    return result.scalars().all()


@router.put("/videos/{video_id}/segments/{segment_id}", tags=["Review"])
async def update_segment(
    video_id: str,
    segment_id: str,
    update: SegmentUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Teacher overrides a segment's action."""
    segment = await db.get(Segment, segment_id)
    if not segment or str(segment.video_id) != video_id:
        raise HTTPException(404, "Segment not found")

    segment.teacher_action = update.teacher_action
    segment.teacher_note = update.teacher_note
    if update.is_teacher_modified is not None:
        segment.is_teacher_modified = update.is_teacher_modified
    else:
        segment.is_teacher_modified = update.teacher_action is not None
    await db.commit()

    return {"status": "updated", "segment_id": segment_id}


@router.put("/videos/{video_id}/segments/bulk", tags=["Review"])
async def bulk_update_segments(
    video_id: str,
    request: BulkSegmentUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Teacher bulk-updates multiple segments at once."""
    updated = 0
    for upd in request.updates:
        segment = await db.get(Segment, upd["segment_id"])
        if segment and str(segment.video_id) == video_id:
            segment.teacher_action = SegmentAction(upd["teacher_action"])
            segment.teacher_note = upd.get("teacher_note")
            segment.is_teacher_modified = True
            updated += 1

    await db.commit()
    return {"status": "updated", "segments_updated": updated}


# ═══════════════════════════════════════════
#  EDIT PLAN / APPROVAL ENDPOINTS
# ═══════════════════════════════════════════

@router.get("/videos/{video_id}/plan", response_model=EditPlanResponse, tags=["Edit Plan"])
async def get_edit_plan(video_id: str, db: AsyncSession = Depends(get_db)):
    """Get the current edit plan."""
    result = await db.execute(
        select(EditPlan).where(EditPlan.video_id == video_id)
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(404, "Edit plan not found")
    return plan


@router.get("/videos/{video_id}/render-plan", tags=["Edit Plan"])
async def get_semantic_render_plan(video_id: str, db: AsyncSession = Depends(get_db)):
    """Return the shared preview/export render plan for a reviewed lecture."""
    video, plan, segments, transcript, assets = await _load_render_plan_context(video_id, db)
    render_plan = build_semantic_render_plan(
        video=video,
        plan=plan,
        segments=segments,
        transcript=transcript,
        assets=assets,
    )
    plan.plan_json = with_semantic_render_plan(plan.plan_json, render_plan)
    await db.commit()
    return render_plan


@router.post("/videos/{video_id}/render-plan/regenerate", tags=["Edit Plan"])
async def regenerate_semantic_render_plan(video_id: str, db: AsyncSession = Depends(get_db)):
    """Regenerate and persist the semantic render plan after teacher changes."""
    video, plan, segments, transcript, assets = await _load_render_plan_context(video_id, db)
    render_plan = build_semantic_render_plan(
        video=video,
        plan=plan,
        segments=segments,
        transcript=transcript,
        assets=assets,
    )
    plan.plan_json = with_semantic_render_plan(plan.plan_json, render_plan)
    await db.commit()
    return render_plan


@router.get("/videos/{video_id}/render-plan/slides/{slide_id}", tags=["Edit Plan"])
async def get_semantic_render_slide(video_id: str, slide_id: str, db: AsyncSession = Depends(get_db)):
    """Serve the exact extracted PDF/PPTX page used by preview and export."""
    _video, plan, _segments, _transcript, _assets = await _load_render_plan_context(video_id, db)
    payload = normalize_plan_payload(plan.plan_json)
    render_plan = payload.get("render_plan") if isinstance(payload.get("render_plan"), dict) else {}
    slide = next(
        (item for item in render_plan.get("slides", []) if isinstance(item, dict) and str(item.get("id")) == slide_id),
        None,
    )
    path = os.path.realpath(str((slide or {}).get("image_path") or ""))
    storage_root = os.path.realpath(settings.VIDEO_STORAGE_PATH)
    if not path or not path.startswith(storage_root + os.sep) or not os.path.isfile(path):
        raise HTTPException(404, "Rendered slide page not found")
    return FileResponse(path, media_type="image/png", filename=os.path.basename(path))


@router.put("/videos/{video_id}/plan/captions", response_model=EditPlanResponse, tags=["Edit Plan"])
async def update_plan_captions(
    video_id: str,
    request: CaptionPolicyUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Persist selective caption appearance, placement, style, and export behavior."""
    result = await db.execute(
        select(EditPlan).where(EditPlan.video_id == video_id)
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(404, "Edit plan not found")

    plan.plan_json = update_caption_policy(
        plan.plan_json,
        request.model_dump(exclude_none=True),
    )
    await db.commit()
    await db.refresh(plan)
    return plan


@router.put("/videos/{video_id}/plan/layout-cues", response_model=EditPlanResponse, tags=["Edit Plan"])
async def update_plan_layout_cues(
    video_id: str,
    request: LayoutCuesUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Persist studio layout cues for preview, timeline composition, and export."""
    result = await db.execute(
        select(EditPlan).where(EditPlan.video_id == video_id)
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(404, "Edit plan not found")

    plan.plan_json = update_layout_cues(
        plan.plan_json,
        request.layout_cues,
        source=request.source or "teacher_layout_override",
    )
    await db.flush()
    video, plan, segments, transcript, assets = await _load_render_plan_context(video_id, db)
    render_plan = build_semantic_render_plan(
        video=video,
        plan=plan,
        segments=segments,
        transcript=transcript,
        assets=assets,
    )
    plan.plan_json = with_semantic_render_plan(plan.plan_json, render_plan)
    await db.commit()
    await db.refresh(plan)
    return plan


@router.put("/videos/{video_id}/plan/slide-cues", response_model=EditPlanResponse, tags=["Edit Plan"])
async def update_plan_slide_cues(
    video_id: str,
    request: SlideCuesUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Persist teacher-corrected slide timing without changing layout or export settings."""
    result = await db.execute(select(EditPlan).where(EditPlan.video_id == video_id))
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(404, "Edit plan not found")

    plan.plan_json = update_slide_cues(
        plan.plan_json,
        request.slide_cues,
        source=request.source or "teacher_slide_override",
    )
    await db.flush()
    video, plan, segments, transcript, assets = await _load_render_plan_context(video_id, db)
    render_plan = build_semantic_render_plan(
        video=video,
        plan=plan,
        segments=segments,
        transcript=transcript,
        assets=assets,
    )
    plan.plan_json = with_semantic_render_plan(plan.plan_json, render_plan)
    await db.commit()
    await db.refresh(plan)
    return plan


@router.put("/videos/{video_id}/plan/editorial-blocks", response_model=EditPlanResponse, tags=["Edit Plan"])
async def update_plan_editorial_blocks(
    video_id: str,
    request: EditorialBlocksUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Persist combined slide and layout decisions, then refresh preview/export parity."""
    result = await db.execute(select(EditPlan).where(EditPlan.video_id == video_id))
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(404, "Edit plan not found")

    plan.plan_json = update_editorial_blocks(
        plan.plan_json,
        request.editorial_blocks,
        source=request.source or "teacher_editorial_override",
    )
    await db.flush()
    video, plan, segments, transcript, assets = await _load_render_plan_context(video_id, db)
    render_plan = build_semantic_render_plan(
        video=video,
        plan=plan,
        segments=segments,
        transcript=transcript,
        assets=assets,
    )
    plan.plan_json = with_semantic_render_plan(plan.plan_json, render_plan)
    await db.commit()
    await db.refresh(plan)
    return plan


@router.post("/videos/{video_id}/plan/layout-cues/auto", response_model=EditPlanResponse, tags=["Edit Plan"])
async def auto_generate_plan_layout_cues(
    video_id: str,
    request: LayoutCuesAutoGenerateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Regenerate the combined semantic slide/layout plan and refresh preview/export."""
    plan_result = await db.execute(
        select(EditPlan).where(EditPlan.video_id == video_id)
    )
    plan = plan_result.scalar_one_or_none()
    if not plan:
        raise HTTPException(404, "Edit plan not found")

    video_result = await db.execute(select(Video).where(Video.id == video_id))
    video = video_result.scalar_one_or_none()
    if not video:
        raise HTTPException(404, "Video not found")

    from agents.visual_structure import run_visual_structure_agent

    visual_result = await run_visual_structure_agent(video_id, db)
    blocks = list(visual_result.get("editorial_blocks") or [])
    if not blocks:
        raise HTTPException(422, "The AI could not produce a semantic editorial plan for this video")
    plan.plan_json = update_editorial_blocks(
        plan.plan_json,
        blocks,
        source="agent4_editorial_plan",
    )
    payload = normalize_plan_payload(plan.plan_json)
    metadata = dict(payload.get("metadata") or {})
    metadata["editorial_planning"] = {
        "status": visual_result.get("planning_status") or "verified",
        "warnings": list(visual_result.get("planning_warnings") or []),
        "degraded_reason": visual_result.get("degraded_reason"),
    }
    payload["metadata"] = metadata
    payload["visual_analysis"] = {
        **dict(payload.get("visual_analysis") or {}),
        "analysis_source": visual_result.get("analysis_source"),
        "vision_provider": visual_result.get("vision_provider"),
        "slide_scope": visual_result.get("slide_scope"),
        "slide_timeline": list(visual_result.get("slide_timeline") or []),
        "editorial_blocks": blocks,
        "slide_assets": list(visual_result.get("slide_assets") or []),
        "planning_status": visual_result.get("planning_status") or "verified",
        "planning_warnings": list(visual_result.get("planning_warnings") or []),
        "degraded_reason": visual_result.get("degraded_reason"),
        "document_preflight": visual_result.get("document_preflight"),
    }
    plan.plan_json = payload
    await db.flush()
    video, plan, segments, transcript, assets = await _load_render_plan_context(video_id, db)
    render_plan = build_semantic_render_plan(
        video=video,
        plan=plan,
        segments=segments,
        transcript=transcript,
        assets=assets,
    )
    plan.plan_json = with_semantic_render_plan(plan.plan_json, render_plan)
    await db.commit()
    await db.refresh(plan)
    return plan


@router.put("/videos/{video_id}/plan/annotations", response_model=EditPlanResponse, tags=["Edit Plan"])
async def update_plan_annotations(
    video_id: str,
    request: AnnotationActionsUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Persist timed annotations and callouts for preview, timeline, and export."""
    result = await db.execute(
        select(EditPlan).where(EditPlan.video_id == video_id)
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(404, "Edit plan not found")

    plan.plan_json = update_annotations(
        plan.plan_json,
        [item.model_dump(exclude_none=True) for item in request.annotations],
    )
    await db.commit()
    await db.refresh(plan)
    return plan


@router.put("/videos/{video_id}/plan/educational-overlays", response_model=EditPlanResponse, tags=["Edit Plan"])
async def update_plan_educational_overlays(
    video_id: str,
    request: EducationalOverlayActionsUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Persist educational step labels, intro cards, section title cards, and chapter labels."""
    result = await db.execute(
        select(EditPlan).where(EditPlan.video_id == video_id)
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(404, "Edit plan not found")

    plan.plan_json = update_educational_overlays(
        plan.plan_json,
        [item.model_dump(exclude_none=True) for item in request.overlays],
    )
    await db.commit()
    await db.refresh(plan)
    return plan


@router.put("/videos/{video_id}/plan/end-cards", response_model=EditPlanResponse, tags=["Edit Plan"])
async def update_plan_end_cards(
    video_id: str,
    request: EndCardActionsUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Persist appended end cards and CTAs for lecture summary, next topic, course link, or custom close."""
    result = await db.execute(
        select(EditPlan).where(EditPlan.video_id == video_id)
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(404, "Edit plan not found")

    plan.plan_json = update_end_cards(
        plan.plan_json,
        [item.model_dump(exclude_none=True) for item in request.end_cards],
    )
    await db.commit()
    await db.refresh(plan)
    return plan


@router.get("/export/presets", response_model=ExportPresetCatalogResponse, tags=["Export"])
async def get_export_presets():
    """Return grouped export presets for social, professional, and education targets."""
    return list_grouped_export_presets()


@router.post("/videos/{video_id}/plan/approve", tags=["Edit Plan"])
async def approve_edit_plan(
    video_id: str,
    request: EditPlanApproveRequest,
    db: AsyncSession = Depends(get_db),
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    """Teacher approves the edit plan → triggers rendering."""
    result = await db.execute(
        select(EditPlan).where(EditPlan.video_id == video_id)
    )
    plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(404, "Edit plan not found")

    try:
        selected_preset = get_export_preset(request.export_preset_id)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    active_render_job = get_active_render_job(video_id)
    if active_render_job:
        return {
            "status": "already_rendering",
            "message": "Rendering is already in progress for this video.",
            "video_id": video_id,
            "export_preset_id": active_render_job.get("preset_id") or selected_preset["id"],
            "render_job": active_render_job,
        }

    video, plan, segments, transcript, assets = await _load_render_plan_context(video_id, db, existing_plan=plan)
    render_plan = build_semantic_render_plan(
        video=video,
        plan=plan,
        segments=segments,
        transcript=transcript,
        assets=assets,
    )

    plan.is_approved = True
    plan.approved_at = datetime.now(timezone.utc).replace(tzinfo=None)
    plan.teacher_notes = request.teacher_notes
    plan.plan_json = with_semantic_render_plan(plan.plan_json, render_plan)
    plan.plan_json = update_export_metadata(
        plan.plan_json,
        target_presets=[selected_preset["id"]],
    )
    plan.plan_json["export_metadata"]["selected_preset"] = selected_preset
    video = await db.get(Video, video_id)
    if video:
        video.status = VideoStatus.RENDERING
        video.error_message = None
    render_job, render_job_created = create_render_job_with_status(video_id, selected_preset["id"])
    await db.commit()

    if render_job_created:
        background_tasks.add_task(_render_video_bg, video_id, render_job["job_id"])

    return {
        "status": "approved" if render_job_created else "already_rendering",
        "message": (
            "Edit plan approved. Rendering started."
            if render_job_created
            else "Rendering is already in progress for this video."
        ),
        "video_id": video_id,
        "export_preset_id": selected_preset["id"],
        "render_job": render_job,
    }


@router.post("/videos/{video_id}/render/cancel", tags=["Export"])
async def cancel_render(video_id: str, db: AsyncSession = Depends(get_db)):
    """Request cancellation for an active render job."""
    video = await db.get(Video, video_id)
    if not video:
        raise HTTPException(404, "Video not found")

    render_job = request_render_cancel(video_id)
    if not render_job:
        raise HTTPException(409, "No active render job to cancel")

    return {
        "status": "cancel_requested",
        "message": "Render cancellation requested.",
        "video_id": video_id,
        "render_job": render_job,
    }


async def _load_render_plan_context(
    video_id: str,
    db: AsyncSession,
    *,
    existing_plan: EditPlan | None = None,
) -> tuple[Video, EditPlan, list[Segment], Transcript | None, list[ProjectAsset]]:
    video = await db.get(Video, video_id)
    if not video:
        raise HTTPException(404, "Video not found")

    plan = existing_plan
    if plan is None:
        result = await db.execute(select(EditPlan).where(EditPlan.video_id == video_id))
        plan = result.scalar_one_or_none()
    if not plan:
        raise HTTPException(404, "Edit plan not found")

    segment_result = await db.execute(
        select(Segment).where(Segment.video_id == video_id).order_by(Segment.start_time)
    )
    segments = list(segment_result.scalars().all())
    if not segments:
        raise HTTPException(404, "No transcript segments found for render plan")

    transcript_result = await db.execute(select(Transcript).where(Transcript.video_id == video_id))
    transcript = transcript_result.scalar_one_or_none()

    assets: list[ProjectAsset] = []
    if video.project_id:
        asset_result = await db.execute(
            select(ProjectAsset).where(ProjectAsset.project_id == video.project_id)
        )
        assets = list(asset_result.scalars().all())

    return video, plan, segments, transcript, assets


@router.post("/videos/{video_id}/plan/revalidate", tags=["Edit Plan"])
async def revalidate_plan(
    video_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Re-validate the edit plan after teacher modifications.

    Call this after the teacher changes segment actions to get:
    - Coherence warnings (e.g., "cutting this breaks the logical flow")
    - Consequence alerts (e.g., "this removes the only quicksort example")

    The desktop app should call this after every teacher modification
    and display the warnings/alerts in the UI.
    """
    result = await revalidate_edit_plan(video_id, db)
    return result


@router.get("/videos/{video_id}/chapters", response_model=TopicSegmentationResponse, tags=["Edit Plan"])
async def get_chapters(video_id: str, db: AsyncSession = Depends(get_db)):
    """
    Get auto-generated chapter and section markers for the video.

    Chapters are generated from transcript content shifts, topic transitions,
    pauses, slide changes, and uploaded slide/PDF title cues.
    Format compatible with YouTube chapter markers.
    """
    result = await db.execute(
        select(Video)
        .options(
            selectinload(Video.transcript),
            selectinload(Video.segments),
            selectinload(Video.edit_plan),
            selectinload(Video.project).selectinload(Project.assets),
        )
        .where(Video.id == video_id)
    )
    video = result.scalar_one_or_none()

    if not video:
        raise HTTPException(404, "Video not found")
    if not video.segments:
        raise HTTPException(404, "No segments found")

    timeline_words = []
    if video.transcript:
        timeline = build_transcript_timeline(
            video_id=video.id,
            transcript=video.transcript,
            review_segments=video.segments,
            duration_seconds=video.duration_seconds,
        )
        timeline_words = timeline["words"]

    analysis = analyze_topic_sections(
        segments=video.segments,
        timeline_words=timeline_words,
        duration_seconds=video.duration_seconds,
        structure_references=build_structure_references_from_assets(
            video.project.assets if video.project else []
        ),
        project_type=video.project.project_type if video.project else None,
    )
    if video.edit_plan:
        video.edit_plan.plan_json = update_sections_payload(video.edit_plan.plan_json, analysis)
        await db.commit()

    return {
        "video_id": video_id,
        "chapters_count": len(analysis["chapters"]),
        **analysis,
    }


@router.post("/videos/{video_id}/section-clips/export", tags=["Export"])
async def export_section_clips(video_id: str, db: AsyncSession = Depends(get_db)):
    """Export one MP4 clip per generated lecture section or subtopic."""
    video = await _load_video_for_chapter_analysis(video_id, db)
    analysis = await _chapter_analysis_for_video(video)
    chapters = analysis.get("chapters") or []
    if not chapters:
        raise HTTPException(400, "No chapter markers are available for section clip export")

    source_path = video.file_path if video.file_path and os.path.exists(video.file_path) else video.processed_video_path
    source_kind = "source_video" if source_path == video.file_path else "rendered_fallback"
    if not source_path or not os.path.exists(source_path):
        raise HTTPException(404, "Source video for section clip export was not found")

    try:
        metadata = await ffmpeg_service.get_video_metadata(source_path)
        base_duration = float(metadata.get("duration") or video.duration_seconds or 0.0)
    except Exception:
        base_duration = float(video.duration_seconds or 0.0)

    clip_dir = os.path.join(settings.VIDEO_STORAGE_PATH, f"{video_id}_section_clips")
    os.makedirs(clip_dir, exist_ok=True)
    clips = _section_clip_specs(chapters, base_duration)
    if not clips:
        raise HTTPException(400, "Chapter markers did not produce valid section clip ranges")
    exported_clips = []

    for index, clip in enumerate(clips, start=1):
        output_path = os.path.join(
            clip_dir,
            f"{index:02d}_{_safe_filename(clip['label'])}.mp4",
        )
        await ffmpeg_service.trim_video(
            source_path,
            output_path,
            clip["start_time"],
            clip["end_time"],
        )
        exported_clips.append({
            **clip,
            "clip_index": index,
            "filename": os.path.basename(output_path),
            "path": output_path,
            "download_url": f"/api/v1/videos/{video_id}/section-clips/{index}/download",
        })

    manifest = {
        "schema_version": "section-clips.v1",
        "video_id": video_id,
        "source_path": source_path,
        "source_kind": source_kind,
        "project_type": video.project.project_type if video.project else "lecture",
        "clip_count": len(exported_clips),
        "clips": exported_clips,
        "chapter_summary": analysis.get("summary") or {},
    }
    manifest_path = os.path.join(settings.VIDEO_STORAGE_PATH, f"{video_id}_section_clips_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)

    return manifest


@router.get("/videos/{video_id}/section-clips/manifest", tags=["Export"])
async def download_section_clip_manifest(video_id: str):
    """Download the section/subtopic clip export manifest."""
    path = os.path.join(settings.VIDEO_STORAGE_PATH, f"{video_id}_section_clips_manifest.json")
    if not os.path.exists(path):
        raise HTTPException(404, "Section clip manifest is not available yet")
    from fastapi.responses import FileResponse

    return FileResponse(path=path, media_type="application/json", filename=f"{video_id}_section_clips_manifest.json")


@router.get("/videos/{video_id}/section-clips/{clip_index}/download", tags=["Export"])
async def download_section_clip(video_id: str, clip_index: int):
    """Download one exported section/subtopic clip."""
    manifest_path = os.path.join(settings.VIDEO_STORAGE_PATH, f"{video_id}_section_clips_manifest.json")
    if not os.path.exists(manifest_path):
        raise HTTPException(404, "Section clip manifest is not available yet")
    with open(manifest_path, "r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    clip = next((item for item in manifest.get("clips", []) if item.get("clip_index") == clip_index), None)
    if not clip or not os.path.exists(clip.get("path", "")):
        raise HTTPException(404, "Section clip file is not available")
    from fastapi.responses import FileResponse

    return FileResponse(path=clip["path"], media_type="video/mp4", filename=clip["filename"])


async def _load_video_for_chapter_analysis(video_id: str, db: AsyncSession) -> Video:
    result = await db.execute(
        select(Video)
        .options(
            selectinload(Video.transcript),
            selectinload(Video.segments),
            selectinload(Video.edit_plan),
            selectinload(Video.project).selectinload(Project.assets),
        )
        .where(Video.id == video_id)
    )
    video = result.scalar_one_or_none()
    if not video:
        raise HTTPException(404, "Video not found")
    return video


async def _chapter_analysis_for_video(video: Video) -> dict:
    timeline_words = []
    if video.transcript:
        timeline = build_transcript_timeline(
            video_id=video.id,
            transcript=video.transcript,
            review_segments=video.segments,
            duration_seconds=video.duration_seconds,
        )
        timeline_words = timeline["words"]

    analysis = analyze_topic_sections(
        segments=video.segments,
        timeline_words=timeline_words,
        duration_seconds=video.duration_seconds,
        structure_references=build_structure_references_from_assets(
            video.project.assets if video.project else []
        ),
        project_type=video.project.project_type if video.project else None,
    )
    return analysis


def _section_clip_specs(chapters: list[dict], duration_seconds: float) -> list[dict]:
    specs: list[dict] = []
    for index, chapter in enumerate(chapters):
        start_time = float(chapter.get("timestamp") or 0.0)
        next_start = (
            float(chapters[index + 1].get("timestamp") or duration_seconds)
            if index + 1 < len(chapters)
            else duration_seconds
        )
        end_time = max(start_time, next_start)
        if end_time <= start_time:
            continue
        specs.append({
            "label": chapter.get("label") or f"Section {index + 1}",
            "start_time": round(start_time, 3),
            "end_time": round(end_time, 3),
            "duration_seconds": round(end_time - start_time, 3),
            "chapter_timestamp": chapter.get("formatted"),
            "segment_index": chapter.get("segment_index"),
        })
    return specs


def _safe_filename(value: object) -> str:
    text = str(value or "section").strip().lower()
    text = "".join(character if character.isalnum() else "_" for character in text)
    text = "_".join(part for part in text.split("_") if part)
    return (text or "section")[:80]


# ═══════════════════════════════════════════
#  QUALITY REPORT
# ═══════════════════════════════════════════

@router.get("/videos/{video_id}/report", tags=["Reports"])
async def get_quality_report(video_id: str, db: AsyncSession = Depends(get_db)):
    """Get quality metrics report for a processed video."""
    report = await generate_quality_report(video_id, db)
    if "error" in report:
        raise HTTPException(404, report["error"])
    return report


@router.get("/videos/{video_id}/mode-comparison", tags=["Reports"])
async def get_mode_comparison_report(video_id: str, db: AsyncSession = Depends(get_db)):
    """Compare API, local, and hybrid mode tradeoffs for the processed video."""
    return await _build_mode_comparison_for_video(video_id, db)


# ═══════════════════════════════════════════
#  COURSE MATERIALS
# ═══════════════════════════════════════════

@router.post("/materials/upload", response_model=CourseMaterialUploadResponse, tags=["Course Materials"])
async def upload_course_material(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    background_tasks: BackgroundTasks = BackgroundTasks(),
):
    """
    Upload course material (PDF, PPTX, DOCX, TXT, MD) for the RAG knowledge base.

    The file is:
      1. Saved to disk
      2. Text extracted (PDF/PPTX/DOCX/TXT/MD)
      3. Chunked into overlapping segments (page-aware)
      4. Embedded and stored in Qdrant for semantic search

    Agent 2 uses this knowledge base during content analysis to determine
    which parts of a lecture are covering important curriculum topics.
    """
    # Validate extension
    allowed_extensions = {".pdf", ".pptx", ".docx", ".txt", ".md", ".csv"}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed_extensions:
        raise HTTPException(400, f"Unsupported file type: {ext}. Allowed: {allowed_extensions}")

    # Save file
    material_id = uuid.uuid4()
    save_path = os.path.join(settings.UPLOAD_PATH, f"material_{material_id}{ext}")
    os.makedirs(settings.UPLOAD_PATH, exist_ok=True)

    with open(save_path, "wb") as f:
        shutil.copyfileobj(file.file, f, length=UPLOAD_COPY_BUFFER_BYTES)

    # Extract text
    try:
        extraction = await text_extractor.extract(save_path)
        content = extraction["text"]
        pages = extraction.get("pages", [])
        meta = extraction.get("metadata", {})
    except Exception as e:
        raise HTTPException(422, f"Failed to extract text from {file.filename}: {str(e)}")

    if not content.strip():
        raise HTTPException(422, f"No text content found in {file.filename}. Is the file empty or image-only?")

    # Create DB record
    material = CourseMaterial(
        id=material_id,
        filename=file.filename,
        file_path=save_path,
        file_type=ext.lstrip("."),
        content_text=content[:50000],  # Store first 50K chars in DB for quick access
    )
    db.add(material)
    await db.commit()

    # Embedding can take a while or fail if the vector/LLM services are still warming up.
    # Keep the upload responsive and surface embedding issues in backend logs.
    background_tasks.add_task(
        _embed_material_bg,
        str(material_id),
        file.filename,
        pages,
    )

    return CourseMaterialUploadResponse(
        id=material_id,
        filename=file.filename,
        file_type=ext.lstrip("."),
        chunk_count=0,
        message=f"Extracted {meta.get('word_count', 0)} words from {meta.get('page_count', '?')} pages. Embedding queued.",
    )


@router.get("/materials", response_model=List[CourseMaterialResponse], tags=["Course Materials"])
async def list_course_materials(db: AsyncSession = Depends(get_db)):
    """List all uploaded course materials."""
    result = await db.execute(
        select(CourseMaterial).order_by(CourseMaterial.created_at.desc())
    )
    return result.scalars().all()


@router.delete("/materials/{material_id}", tags=["Course Materials"])
async def delete_course_material(material_id: str, db: AsyncSession = Depends(get_db)):
    """Delete a course material and its embeddings."""
    material = await db.get(CourseMaterial, material_id)
    if not material:
        raise HTTPException(404, "Material not found")

    # Remove embeddings from Qdrant
    await rag_service.delete_by_source(str(material_id))

    # Remove file
    if material.file_path and os.path.exists(material.file_path):
        os.remove(material.file_path)

    await db.delete(material)
    await db.commit()
    return {"status": "deleted", "material_id": material_id}


# ═══════════════════════════════════════════
#  SETTINGS (for desktop app)
# ═══════════════════════════════════════════

@router.get("/settings", response_model=AppSettingsResponse, tags=["Settings"])
async def get_settings(db: AsyncSession = Depends(get_db)):
    """Get current application settings with API keys redacted."""
    record = await get_or_create_ai_settings(db)
    return settings_response(record)


@router.get("/settings/ai", response_model=AppSettingsResponse, tags=["Settings"])
async def get_ai_settings(db: AsyncSession = Depends(get_db)):
    """Get AI provider settings for the desktop settings UI."""
    record = await get_or_create_ai_settings(db)
    return settings_response(record)


@router.put("/settings/ai", response_model=AppSettingsResponse, tags=["Settings"])
async def update_settings(
    request: AppSettingsUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Persist AI provider settings, local paths, fallback behavior, and API keys."""
    return await update_ai_settings(db, request)


@router.put("/settings/domain-terms", tags=["Settings"])
async def update_domain_terms(
    request: DomainTermsUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Update domain-specific terms for ASR context biasing.
    These terms improve Voxtral's accuracy on specialized vocabulary.
    Note: In production, this would persist to a config store.
    For the FYP, we update the in-memory settings.
    """
    response = await update_ai_settings(
        db,
        AppSettingsUpdateRequest(domain_terms=request.terms),
    )
    return {
        "status": "updated",
        "terms_count": len(request.terms),
        "terms": response.domain_terms,
    }


# ═══════════════════════════════════════════
#  FILE DOWNLOAD (for desktop app)
# ═══════════════════════════════════════════

@router.get("/videos/{video_id}/stream", tags=["Videos"])
async def stream_original_video(video_id: str, db: AsyncSession = Depends(get_db)):
    """Stream the original uploaded video (for the review editor's video player)."""
    from fastapi.responses import FileResponse

    video = await db.get(Video, video_id)
    if not video:
        raise HTTPException(404, "Video not found")
    if not video.file_path or not os.path.exists(video.file_path):
        raise HTTPException(404, "Original video file not found")

    return FileResponse(
        path=video.file_path,
        media_type="video/mp4",
        filename=video.original_filename,
    )


@router.get("/videos/{video_id}/download", tags=["Videos"])
async def download_rendered_video(video_id: str, db: AsyncSession = Depends(get_db)):
    """Get download path for the rendered video or audio-only export."""
    from fastapi.responses import FileResponse

    video = await db.get(Video, video_id)
    if not video:
        raise HTTPException(404, "Video not found")
    if video.status == VideoStatus.RENDERING:
        raise HTTPException(409, "Rendered output is still being finalized")
    if not video.processed_video_path or not os.path.exists(video.processed_video_path):
        raise HTTPException(404, "Rendered output not available yet")
    if os.path.getsize(video.processed_video_path) <= 0:
        raise HTTPException(409, "Rendered output is not ready for download")

    extension = os.path.splitext(video.processed_video_path)[1].lower() or ".mp4"
    media_type = {
        ".m4a": "audio/mp4",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
    }.get(extension, "video/mp4")
    suffix = "_audio" if media_type.startswith("audio/") else "_edited"
    base_name = video.original_filename.rsplit(".", 1)[0]

    return FileResponse(
        path=video.processed_video_path,
        media_type=media_type,
        filename=f"{base_name}{suffix}{extension}",
        headers={
            "Accept-Ranges": "bytes",
            "Cache-Control": "private, no-transform",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/videos/{video_id}/subtitles", tags=["Videos"])
async def download_subtitles(video_id: str, db: AsyncSession = Depends(get_db)):
    """Download SRT subtitle file for the rendered video."""
    from fastapi.responses import FileResponse

    srt_path = os.path.join(settings.VIDEO_STORAGE_PATH, f"{video_id}_subtitles.srt")
    if not os.path.exists(srt_path):
        raise HTTPException(404, "Subtitle file not available yet")

    return FileResponse(
        path=srt_path,
        media_type="application/x-subrip",
        filename=f"{video_id}_subtitles.srt",
    )


@router.get("/videos/{video_id}/subtitles/vtt", tags=["Export"])
async def download_subtitles_vtt(video_id: str):
    """Download WebVTT subtitle file (for web/HTML5 playback)."""
    from fastapi.responses import FileResponse

    vtt_path = os.path.join(settings.VIDEO_STORAGE_PATH, f"{video_id}_subtitles.vtt")
    if not os.path.exists(vtt_path):
        raise HTTPException(404, "VTT file not available yet")

    return FileResponse(
        path=vtt_path,
        media_type="text/vtt",
        filename=f"{video_id}_subtitles.vtt",
    )


@router.get("/videos/{video_id}/chapters/download", tags=["Export"])
async def download_chapters(video_id: str):
    """Download YouTube-compatible chapter markers file."""
    from fastapi.responses import FileResponse

    path = os.path.join(settings.VIDEO_STORAGE_PATH, f"{video_id}_chapters.txt")
    if not os.path.exists(path):
        raise HTTPException(404, "Chapters file not available yet")

    return FileResponse(
        path=path,
        media_type="text/plain",
        filename=f"{video_id}_chapters.txt",
    )


@router.get("/videos/{video_id}/plan/export", tags=["Export"])
async def download_plan_export(video_id: str):
    """Download the full edit plan as JSON (for thesis documentation / reproducibility)."""
    from fastapi.responses import FileResponse

    path = os.path.join(settings.VIDEO_STORAGE_PATH, f"{video_id}_edit_plan.json")
    if not os.path.exists(path):
        raise HTTPException(404, "Plan export not available yet — render the video first")

    return FileResponse(
        path=path,
        media_type="application/json",
        filename=f"{video_id}_edit_plan.json",
    )


@router.get("/videos/{video_id}/report/export", tags=["Export"])
async def download_quality_report_export(video_id: str, db: AsyncSession = Depends(get_db)):
    """Download the persisted quality report JSON used for evaluation."""
    from fastapi.responses import FileResponse

    paths = await _ensure_evaluation_exports(video_id, db)
    path = paths["quality_report"]
    if not os.path.exists(path):
        raise HTTPException(404, "Quality report export not available yet")

    return FileResponse(
        path=path,
        media_type="application/json",
        filename=f"{video_id}_quality_report.json",
    )


@router.get("/videos/{video_id}/mode-comparison/export", tags=["Export"])
async def download_mode_comparison_export(video_id: str, db: AsyncSession = Depends(get_db)):
    """Download the API/local/hybrid comparison report JSON."""
    from fastapi.responses import FileResponse

    paths = await _ensure_evaluation_exports(video_id, db)
    path = paths["mode_comparison_json"]
    if not path or not os.path.exists(path):
        raise HTTPException(404, "Mode comparison export not available yet")

    return FileResponse(
        path=path,
        media_type="application/json",
        filename=f"{video_id}_mode_comparison.json",
    )


@router.get("/videos/{video_id}/mode-comparison/summary", tags=["Export"])
async def download_mode_comparison_summary(video_id: str, db: AsyncSession = Depends(get_db)):
    """Download a Markdown API/local/hybrid comparison summary."""
    from fastapi.responses import FileResponse

    paths = await _ensure_evaluation_exports(video_id, db)
    path = paths["mode_comparison_markdown"]
    if not path or not os.path.exists(path):
        raise HTTPException(404, "Mode comparison summary not available yet")

    return FileResponse(
        path=path,
        media_type="text/markdown",
        filename=f"{video_id}_mode_comparison.md",
    )


@router.get("/videos/{video_id}/evidence/export", tags=["Export"])
async def download_academic_evidence_export(video_id: str, db: AsyncSession = Depends(get_db)):
    """Download academic evidence JSON for thesis evaluation and demos."""
    from fastapi.responses import FileResponse

    paths = await _ensure_evaluation_exports(video_id, db)
    path = paths["academic_evidence_json"]
    if not os.path.exists(path):
        raise HTTPException(404, "Academic evidence export not available yet")

    return FileResponse(
        path=path,
        media_type="application/json",
        filename=f"{video_id}_academic_evidence.json",
    )


@router.get("/videos/{video_id}/evidence/summary", tags=["Export"])
async def download_academic_evidence_summary(video_id: str, db: AsyncSession = Depends(get_db)):
    """Download a human-readable academic evidence summary."""
    from fastapi.responses import FileResponse

    paths = await _ensure_evaluation_exports(video_id, db)
    path = paths["academic_evidence_markdown"]
    if not os.path.exists(path):
        raise HTTPException(404, "Academic evidence summary not available yet")

    return FileResponse(
        path=path,
        media_type="text/markdown",
        filename=f"{video_id}_academic_evidence.md",
    )


@router.get("/videos/{video_id}/evidence/before-after", tags=["Export"])
async def download_before_after_comparison(video_id: str, db: AsyncSession = Depends(get_db)):
    """Download a before/after duration and editing outcome comparison."""
    from fastapi.responses import FileResponse

    paths = await _ensure_evaluation_exports(video_id, db)
    path = paths["before_after_comparison_json"]
    if not path or not os.path.exists(path):
        raise HTTPException(404, "Before/after comparison export not available yet")

    return FileResponse(
        path=path,
        media_type="application/json",
        filename=f"{video_id}_before_after_comparison.json",
    )


@router.get("/videos/{video_id}/evidence/timeline-decisions", tags=["Export"])
async def download_timeline_decisions(video_id: str, db: AsyncSession = Depends(get_db)):
    """Download timeline decisions as a CSV table for thesis appendices."""
    from fastapi.responses import FileResponse

    paths = await _ensure_evaluation_exports(video_id, db)
    path = paths["timeline_decisions_csv"]
    if not path or not os.path.exists(path):
        raise HTTPException(404, "Timeline decisions export not available yet")

    return FileResponse(
        path=path,
        media_type="text/csv",
        filename=f"{video_id}_timeline_decisions.csv",
    )


@router.get("/videos/{video_id}/evidence/provider-mode", tags=["Export"])
async def download_provider_mode_trace(video_id: str, db: AsyncSession = Depends(get_db)):
    """Download the AI provider mode trace used for this processed video."""
    from fastapi.responses import FileResponse

    paths = await _ensure_evaluation_exports(video_id, db)
    path = paths["provider_mode_trace_json"]
    if not path or not os.path.exists(path):
        raise HTTPException(404, "Provider mode trace export not available yet")

    return FileResponse(
        path=path,
        media_type="application/json",
        filename=f"{video_id}_provider_mode_trace.json",
    )


@router.get("/videos/{video_id}/evidence/metrics-summary", tags=["Export"])
async def download_metrics_summary(video_id: str, db: AsyncSession = Depends(get_db)):
    """Download a compact thesis metrics summary JSON."""
    from fastapi.responses import FileResponse

    paths = await _ensure_evaluation_exports(video_id, db)
    path = paths["metrics_summary_json"]
    if not path or not os.path.exists(path):
        raise HTTPException(404, "Metrics summary export not available yet")

    return FileResponse(
        path=path,
        media_type="application/json",
        filename=f"{video_id}_metrics_summary.json",
    )


@router.get("/videos/{video_id}/evidence/bundle", tags=["Export"])
async def download_academic_evidence_bundle(video_id: str, db: AsyncSession = Depends(get_db)):
    """Download a ZIP bundle of edit-plan, caption, chapter, quality, and evidence artifacts."""
    from fastapi.responses import FileResponse

    paths = await _ensure_evaluation_exports(video_id, db)
    bundle_path = os.path.join(settings.VIDEO_STORAGE_PATH, f"{video_id}_academic_evidence_bundle.zip")
    records = artifact_records(paths)
    bundle = create_artifact_bundle(bundle_path, records)
    if not bundle["available"]:
        raise HTTPException(404, "Academic evidence bundle could not be created")

    return FileResponse(
        path=bundle_path,
        media_type="application/zip",
        filename=f"{video_id}_academic_evidence_bundle.zip",
    )


@router.get("/videos/{video_id}/exports", tags=["Export"])
async def list_exports(video_id: str, db: AsyncSession = Depends(get_db)):
    """List all available export files for a video."""
    video = await db.get(Video, video_id)
    if not video:
        raise HTTPException(404, "Video not found")

    base = settings.VIDEO_STORAGE_PATH
    rendered_output = {
        "path": f"/api/v1/videos/{video_id}/download",
        "available": bool(video.processed_video_path and os.path.exists(video.processed_video_path)),
        "kind": "audio_only" if str(video.processed_video_path or "").lower().endswith((".m4a", ".mp3", ".wav")) else "video",
    }
    files = {
        "edited_video": rendered_output,
        "rendered_output": rendered_output,
        "subtitles_srt": {
            "path": f"/api/v1/videos/{video_id}/subtitles",
            "available": os.path.exists(os.path.join(base, f"{video_id}_subtitles.srt")),
        },
        "subtitles_vtt": {
            "path": f"/api/v1/videos/{video_id}/subtitles/vtt",
            "available": os.path.exists(os.path.join(base, f"{video_id}_subtitles.vtt")),
        },
        "chapters": {
            "path": f"/api/v1/videos/{video_id}/chapters/download",
            "available": os.path.exists(os.path.join(base, f"{video_id}_chapters.txt")),
        },
        "edit_plan_json": {
            "path": f"/api/v1/videos/{video_id}/plan/export",
            "available": os.path.exists(os.path.join(base, f"{video_id}_edit_plan.json")),
        },
        "quality_report_json": {
            "path": f"/api/v1/videos/{video_id}/report/export",
            "available": os.path.exists(os.path.join(base, f"{video_id}_quality_report.json")),
        },
        "mode_comparison_json": {
            "path": f"/api/v1/videos/{video_id}/mode-comparison/export",
            "available": os.path.exists(os.path.join(base, f"{video_id}_mode_comparison.json")),
        },
        "mode_comparison_markdown": {
            "path": f"/api/v1/videos/{video_id}/mode-comparison/summary",
            "available": os.path.exists(os.path.join(base, f"{video_id}_mode_comparison.md")),
        },
        "academic_evidence_json": {
            "path": f"/api/v1/videos/{video_id}/evidence/export",
            "available": os.path.exists(os.path.join(base, f"{video_id}_academic_evidence.json")),
        },
        "academic_evidence_markdown": {
            "path": f"/api/v1/videos/{video_id}/evidence/summary",
            "available": os.path.exists(os.path.join(base, f"{video_id}_academic_evidence.md")),
        },
        "before_after_comparison_json": {
            "path": f"/api/v1/videos/{video_id}/evidence/before-after",
            "available": os.path.exists(os.path.join(base, f"{video_id}_before_after_comparison.json")),
        },
        "timeline_decisions_csv": {
            "path": f"/api/v1/videos/{video_id}/evidence/timeline-decisions",
            "available": os.path.exists(os.path.join(base, f"{video_id}_timeline_decisions.csv")),
        },
        "provider_mode_trace_json": {
            "path": f"/api/v1/videos/{video_id}/evidence/provider-mode",
            "available": os.path.exists(os.path.join(base, f"{video_id}_provider_mode_trace.json")),
        },
        "metrics_summary_json": {
            "path": f"/api/v1/videos/{video_id}/evidence/metrics-summary",
            "available": os.path.exists(os.path.join(base, f"{video_id}_metrics_summary.json")),
        },
        "academic_evidence_bundle": {
            "path": f"/api/v1/videos/{video_id}/evidence/bundle",
            "available": any(
                os.path.exists(os.path.join(base, f"{video_id}_{suffix}"))
                for suffix in [
                    "edit_plan.json",
                    "subtitles.srt",
                    "subtitles.vtt",
                    "chapters.txt",
                    "quality_report.json",
                    "mode_comparison.json",
                    "mode_comparison.md",
                    "academic_evidence.json",
                    "academic_evidence.md",
                    "before_after_comparison.json",
                    "timeline_decisions.csv",
                    "provider_mode_trace.json",
                    "metrics_summary.json",
                    "generated_evidence_index.json",
                ]
            ),
        },
    }

    return {
        "video_id": video_id,
        "status": video.status.value,
        "exports": files,
    }


# ═══════════════════════════════════════════
#  BACKGROUND TASK HELPERS
# ═══════════════════════════════════════════

async def _build_mode_comparison_for_video(video_id: str, db: AsyncSession) -> dict:
    result = await db.execute(
        select(Video)
        .options(selectinload(Video.transcript), selectinload(Video.segments), selectinload(Video.edit_plan))
        .where(Video.id == video_id)
    )
    video = result.scalar_one_or_none()
    if not video:
        raise HTTPException(404, "Video not found")
    if not video.edit_plan or not video.segments:
        raise HTTPException(404, "Edit plan and segment data are required before comparing provider modes")

    quality_report = await generate_quality_report(video_id, db)
    if "error" in quality_report:
        raise HTTPException(404, quality_report["error"])

    settings_record = await get_or_create_ai_settings(db)
    return build_mode_comparison_report(
        video=video,
        plan=video.edit_plan,
        segments=video.segments,
        transcript=video.transcript,
        plan_payload=normalize_plan_payload(video.edit_plan.plan_json),
        quality_report=quality_report,
        settings_record=settings_record,
        render_job=get_latest_render_job(video_id),
    )


async def _ensure_evaluation_exports(video_id: str, db: AsyncSession) -> dict[str, str | None]:
    result = await db.execute(
        select(Video)
        .options(selectinload(Video.transcript), selectinload(Video.segments), selectinload(Video.edit_plan))
        .where(Video.id == video_id)
    )
    video = result.scalar_one_or_none()
    if not video:
        raise HTTPException(404, "Video not found")
    if not video.edit_plan or not video.segments:
        raise HTTPException(404, "Edit plan and segment data are required before exporting evidence")

    paths = _evaluation_artifact_paths(video)
    quality_report = await generate_quality_report(video_id, db)
    if "error" in quality_report:
        raise HTTPException(404, quality_report["error"])
    write_json_artifact(paths["quality_report"], quality_report)
    settings_record = await get_or_create_ai_settings(db)
    plan_payload = normalize_plan_payload(video.edit_plan.plan_json)
    mode_comparison = build_mode_comparison_report(
        video=video,
        plan=video.edit_plan,
        segments=video.segments,
        transcript=video.transcript,
        plan_payload=plan_payload,
        quality_report=quality_report,
        settings_record=settings_record,
        render_job=get_latest_render_job(video_id),
    )
    write_json_artifact(paths["mode_comparison_json"], mode_comparison)
    write_text_artifact(paths["mode_comparison_markdown"], build_mode_comparison_markdown(mode_comparison))
    before_after = build_before_after_comparison(
        video=video,
        plan=video.edit_plan,
        segments=video.segments,
        plan_payload=plan_payload,
        quality_report=quality_report,
    )
    timeline_decisions = build_timeline_decisions_artifact(
        segments=video.segments,
        plan_payload=plan_payload,
        quality_report=quality_report,
    )
    provider_trace = build_provider_mode_trace(
        transcript=video.transcript,
        plan_payload=plan_payload,
        quality_report=quality_report,
        mode_comparison=mode_comparison,
    )
    metrics_summary = build_metrics_summary_artifact(quality_report)
    write_json_artifact(paths["before_after_comparison_json"], before_after)
    write_json_artifact(paths["timeline_decisions_json"], timeline_decisions)
    write_csv_artifact(
        paths["timeline_decisions_csv"],
        build_timeline_decision_rows(
            segments=video.segments,
            plan_payload=plan_payload,
            quality_report=quality_report,
        ),
        TIMELINE_DECISION_CSV_FIELDS,
    )
    write_json_artifact(paths["provider_mode_trace_json"], provider_trace)
    write_json_artifact(paths["metrics_summary_json"], metrics_summary)

    manifest = artifact_records(paths)
    write_json_artifact(paths["generated_evidence_index_json"], build_generated_evidence_index(manifest))
    manifest = artifact_records(paths)
    evidence = build_academic_evidence_artifact(
        video=video,
        plan=video.edit_plan,
        segments=video.segments,
        transcript=video.transcript,
        plan_payload=plan_payload,
        quality_report=quality_report,
        artifact_manifest=manifest,
        mode_comparison=mode_comparison,
    )
    write_json_artifact(paths["academic_evidence_json"], evidence)
    write_text_artifact(paths["academic_evidence_markdown"], build_evidence_markdown(evidence))

    manifest = artifact_records(paths)
    write_json_artifact(paths["generated_evidence_index_json"], build_generated_evidence_index(manifest))
    manifest = artifact_records(paths)
    evidence["artifact_manifest"] = manifest
    evidence["generated_evidence_files"] = build_generated_evidence_index(manifest)
    write_json_artifact(paths["academic_evidence_json"], evidence)
    write_text_artifact(paths["academic_evidence_markdown"], build_evidence_markdown(evidence))

    video.edit_plan.plan_json = update_export_metadata(
        plan_payload,
        artifacts=manifest,
        render=plan_payload.get("export_metadata", {}).get("render"),
    )
    plan_path = paths["plan_json"]
    if plan_path and os.path.exists(plan_path):
        try:
            import json as json_module

            with open(plan_path, "r", encoding="utf-8") as handle:
                plan_export = json_module.load(handle)
            if isinstance(plan_export, dict):
                plan_export["edit_plan_payload"] = video.edit_plan.plan_json
                plan_export["export_metadata"] = video.edit_plan.plan_json.get("export_metadata", {})
                write_json_artifact(plan_path, plan_export)
        except Exception:
            logger.warning("Could not refresh plan export artifact metadata for %s", video_id)
    await db.commit()
    return paths


def _local_transcription_preflight_error() -> str | None:
    """Return a user-facing error when local transcription cannot run."""
    mode = (settings.AI_TRANSCRIPTION_MODE or settings.AI_PROCESSING_MODE or "api").strip().lower()
    fallback_enabled = (
        settings.AI_TRANSCRIPTION_FALLBACK_ENABLED
        if settings.AI_TRANSCRIPTION_FALLBACK_ENABLED is not None
        else settings.AI_PROVIDER_FALLBACK_ENABLED
    )
    fallback_order = [
        item.strip().lower()
        for item in (settings.AI_TRANSCRIPTION_HYBRID_FALLBACK_ORDER or "").split(",")
        if item.strip()
    ]
    local_is_required = (mode == "local" and not bool(fallback_enabled)) or (
        mode == "hybrid"
        and not bool(fallback_enabled)
        and (not fallback_order or fallback_order[0] == "local")
    )
    if not local_is_required:
        return None

    runtime = resolve_whisper_cpp_runtime_status(settings)
    if runtime.configured:
        return None

    return (
        "Local transcription is selected but whisper.cpp is not ready. "
        f"{runtime.message}. Set the Local runtime path to whisper-cli.exe, configure "
        "WHISPER_CPP_BINARY_PATH, or switch transcription to API/Hybrid fallback."
    )


def _evaluation_artifact_paths(video: Video) -> dict[str, str | None]:
    video_id = str(video.id)
    output_kind = (
        "audio_only"
        if str(video.processed_video_path or "").lower().endswith((".m4a", ".mp3", ".wav"))
        else "edited_video"
    )
    return {
        output_kind: video.processed_video_path,
        "subtitles_srt": os.path.join(settings.VIDEO_STORAGE_PATH, f"{video_id}_subtitles.srt"),
        "subtitles_vtt": os.path.join(settings.VIDEO_STORAGE_PATH, f"{video_id}_subtitles.vtt"),
        "chapters": os.path.join(settings.VIDEO_STORAGE_PATH, f"{video_id}_chapters.txt"),
        "plan_json": os.path.join(settings.VIDEO_STORAGE_PATH, f"{video_id}_edit_plan.json"),
        "quality_report": os.path.join(settings.VIDEO_STORAGE_PATH, f"{video_id}_quality_report.json"),
        "mode_comparison_json": os.path.join(settings.VIDEO_STORAGE_PATH, f"{video_id}_mode_comparison.json"),
        "mode_comparison_markdown": os.path.join(settings.VIDEO_STORAGE_PATH, f"{video_id}_mode_comparison.md"),
        "academic_evidence_json": os.path.join(settings.VIDEO_STORAGE_PATH, f"{video_id}_academic_evidence.json"),
        "academic_evidence_markdown": os.path.join(settings.VIDEO_STORAGE_PATH, f"{video_id}_academic_evidence.md"),
        "before_after_comparison_json": os.path.join(settings.VIDEO_STORAGE_PATH, f"{video_id}_before_after_comparison.json"),
        "timeline_decisions_json": os.path.join(settings.VIDEO_STORAGE_PATH, f"{video_id}_timeline_decisions.json"),
        "timeline_decisions_csv": os.path.join(settings.VIDEO_STORAGE_PATH, f"{video_id}_timeline_decisions.csv"),
        "provider_mode_trace_json": os.path.join(settings.VIDEO_STORAGE_PATH, f"{video_id}_provider_mode_trace.json"),
        "metrics_summary_json": os.path.join(settings.VIDEO_STORAGE_PATH, f"{video_id}_metrics_summary.json"),
        "generated_evidence_index_json": os.path.join(settings.VIDEO_STORAGE_PATH, f"{video_id}_generated_evidence_index.json"),
    }


async def _embed_material_bg(material_id: str, filename: str, pages: list[dict]):
    """Embed an uploaded material after the HTTP upload response returns."""
    from db.database import async_session

    logger.info(f"Embedding queued material {material_id} ({filename})")

    async with async_session() as db:
        try:
            material = await db.get(CourseMaterial, material_id)
            if not material:
                logger.warning(f"Material {material_id} missing before embedding")
                return

            await rag_service.ensure_collection()
            chunk_count = await rag_service.ingest_course_material(
                source_id=material_id,
                filename=filename,
                pages=pages,
            )

            material.chunk_count = chunk_count
            material.is_embedded = chunk_count > 0
            await db.commit()

            logger.info(
                f"Embedded material {material_id} ({filename}): {chunk_count} chunks"
            )

        except Exception as e:
            logger.error(f"Material embedding failed for {material_id} ({filename}): {e}", exc_info=True)
            try:
                material = await db.get(CourseMaterial, material_id)
                if material:
                    material.is_embedded = False
                    await db.commit()
            except Exception:
                logger.error(f"Failed to mark material {material_id} embedding failure", exc_info=True)


async def _process_video_bg(video_id: str):
    """
    Background task: run the full processing pipeline.

    This is triggered by the upload endpoint and runs the entire
    LangGraph pipeline (Phases 1-5) asynchronously.
    The desktop app polls /status to track progress.
    """
    import traceback as tb
    import logging
    logger = logging.getLogger("pipeline")

    from db.database import async_session
    from services.progress import init_progress, fail_step

    logger.info(f"🎬 Starting pipeline for video {video_id}")

    async with async_session() as db:
        try:
            # Mark as processing
            video = await db.get(Video, video_id)
            if not video:
                logger.error(f"Video {video_id} not found in DB")
                return

            video.status = VideoStatus.PROCESSING
            await db.commit()

            await load_and_apply_persisted_ai_settings(db)

            # Ensure Qdrant collection exists
            await rag_service.ensure_collection()

            # Run the full pipeline
            result = await run_processing_pipeline(video_id, db)
            await db.commit()

            status = result.get("status", "unknown")
            if status == "awaiting_review":
                logger.info(f"✅ Pipeline complete for {video_id} — awaiting teacher review")
            elif status == "failed":
                logger.error(f"❌ Pipeline failed for {video_id}: {result.get('error', 'unknown')}")
            else:
                logger.info(f"Pipeline ended with status: {status}")

        except Exception as e:
            error_msg = f"Pipeline crashed: {str(e)}"
            logger.error(f"❌ {error_msg}\n{tb.format_exc()}")
            fail_step(video_id, "pipeline", str(e))

            try:
                video = await db.get(Video, video_id)
                if video:
                    video.status = VideoStatus.FAILED
                    video.error_message = error_msg
                    await db.commit()
            except Exception:
                logger.error("Failed to update video status after crash")


async def _render_video_bg(video_id: str, render_job_id: str | None = None):
    """
    Background task: render final video after teacher approval.

    Triggered by the plan approval endpoint.
    """
    import traceback as tb
    import logging
    logger = logging.getLogger("pipeline")

    from db.database import async_session
    from services.render_jobs import fail_render_job

    logger.info(f"🎬 Starting render for video {video_id}")

    async with async_session() as db:
        try:
            result = await run_render_pipeline(video_id, db, render_job_id=render_job_id)
            await db.commit()

            if result.get("status") == "completed":
                logger.info(f"✅ Render complete for {video_id}")
            elif result.get("status") == "cancelled":
                logger.info(f"Render cancelled for {video_id}")
            else:
                logger.warning(f"Render ended with status: {result.get('status')}")

        except Exception as e:
            error_msg = f"Render crashed: {str(e)}"
            fail_render_job(render_job_id, video_id, error_msg)
            logger.error(f"❌ {error_msg}\n{tb.format_exc()}")

            try:
                video = await db.get(Video, video_id)
                if video:
                    video.status = VideoStatus.FAILED
                    video.error_message = error_msg
                    await db.commit()
            except Exception:
                logger.error("Failed to update video status after render crash")
