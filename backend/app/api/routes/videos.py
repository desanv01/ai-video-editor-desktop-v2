"""
API Routes — Video upload, processing, teacher review, rendering.
"""

import os
import uuid
import shutil
import logging
from datetime import datetime
from typing import List

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, BackgroundTasks
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
    TranscriptTimelineResponse,
    EditPlanResponse, EditPlanApproveRequest, CaptionPolicyUpdateRequest,
    AnnotationActionsUpdateRequest,
    CourseMaterialUploadResponse, CourseMaterialResponse,
    ProcessingStatus, AppSettingsResponse, AppSettingsUpdateRequest,
    DomainTermsUpdateRequest,
)
from agents.orchestrator import run_processing_pipeline, run_render_pipeline
from agents.edit_planner import revalidate_edit_plan
from services.ffmpeg import ffmpeg_service
from services.lecture_structure import build_structure_references_from_assets
from services.renderer import generate_quality_report
from services.text_extraction import text_extractor
from services.transcript_timeline import build_transcript_timeline
from services.transcript_edit_decisions import (
    build_synced_timeline_plan,
    create_transcript_cut_decision,
    list_transcript_cut_decisions,
    remove_transcript_cut_decision,
    update_transcript_cut_trim,
)
from services.clean_tools import analyze_clean_suggestions, apply_clean_suggestions
from services.edit_plan_payload import update_annotations, update_caption_policy, update_sections_payload
from services.topic_segmentation import analyze_topic_sections
from services.progress import get_progress as get_pipeline_progress
from services.app_settings import (
    get_or_create_ai_settings,
    settings_response,
    update_ai_settings,
)
from rag.vector_store import rag_service
from config import settings


router = APIRouter()
logger = logging.getLogger(__name__)


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
        shutil.copyfileobj(file.file, f)

    file_size = os.path.getsize(file_path)
    if file_size > settings.MAX_VIDEO_SIZE_MB * 1024 * 1024:
        os.remove(file_path)
        raise HTTPException(413, f"File too large. Maximum: {settings.MAX_VIDEO_SIZE_MB}MB")

    # Get video metadata
    try:
        metadata = await ffmpeg_service.get_video_metadata(file_path)
    except Exception:
        metadata = {}

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
        mime_type=file.content_type,
        duration_seconds=metadata.get("duration"),
        metadata_json={
            "legacy_video_id": str(video_id),
            "source_type": ProjectMediaSourceType.MIXED_VIDEO.value,
            "sync_role": ProjectAssetSyncRole.PRIMARY_TIMELINE.value,
            "resolution": f"{metadata.get('width', 0)}x{metadata.get('height', 0)}" if metadata else None,
            "fps": metadata.get("fps"),
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

    # Get live pipeline progress (in-memory, detailed)
    progress = get_pipeline_progress(str(video_id))

    return {
        "video_id": str(video.id),
        "status": video.status.value,
        "error_message": video.error_message,
        # Live pipeline progress
        "current_step": progress.get("current_step", video.status.value),
        "current_step_label": progress.get("current_step_label", video.status.value),
        "progress_percent": progress.get("progress_percent", 0),
        "steps_completed": progress.get("steps_completed", []),
        "steps_timing": progress.get("steps_timing", {}),
        "total_elapsed_seconds": progress.get("total_elapsed_seconds", 0),
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

    plan.is_approved = True
    plan.approved_at = datetime.utcnow()
    plan.teacher_notes = request.teacher_notes
    await db.commit()

    # Start rendering in background
    background_tasks.add_task(_render_video_bg, video_id)

    return {
        "status": "approved",
        "message": "Edit plan approved. Rendering started.",
        "video_id": video_id,
    }


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
    )
    if video.edit_plan:
        video.edit_plan.plan_json = update_sections_payload(video.edit_plan.plan_json, analysis)
        await db.commit()

    return {
        "video_id": video_id,
        "chapters_count": len(analysis["chapters"]),
        **analysis,
    }


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
        shutil.copyfileobj(file.file, f)

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
    """Get download path for the rendered video."""
    from fastapi.responses import FileResponse

    video = await db.get(Video, video_id)
    if not video:
        raise HTTPException(404, "Video not found")
    if not video.processed_video_path or not os.path.exists(video.processed_video_path):
        raise HTTPException(404, "Rendered video not available yet")

    return FileResponse(
        path=video.processed_video_path,
        media_type="video/mp4",
        filename=f"{video.original_filename.rsplit('.', 1)[0]}_edited.mp4",
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


@router.get("/videos/{video_id}/exports", tags=["Export"])
async def list_exports(video_id: str, db: AsyncSession = Depends(get_db)):
    """List all available export files for a video."""
    video = await db.get(Video, video_id)
    if not video:
        raise HTTPException(404, "Video not found")

    base = settings.VIDEO_STORAGE_PATH
    files = {
        "edited_video": {
            "path": f"/api/v1/videos/{video_id}/download",
            "available": bool(video.processed_video_path and os.path.exists(video.processed_video_path)),
        },
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
    }

    return {
        "video_id": video_id,
        "status": video.status.value,
        "exports": files,
    }


# ═══════════════════════════════════════════
#  BACKGROUND TASK HELPERS
# ═══════════════════════════════════════════

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


async def _render_video_bg(video_id: str):
    """
    Background task: render final video after teacher approval.

    Triggered by the plan approval endpoint.
    """
    import traceback as tb
    import logging
    logger = logging.getLogger("pipeline")

    from db.database import async_session

    logger.info(f"🎬 Starting render for video {video_id}")

    async with async_session() as db:
        try:
            result = await run_render_pipeline(video_id, db)
            await db.commit()

            if result.get("status") == "completed":
                logger.info(f"✅ Render complete for {video_id}")
            else:
                logger.warning(f"Render ended with status: {result.get('status')}")

        except Exception as e:
            error_msg = f"Render crashed: {str(e)}"
            logger.error(f"❌ {error_msg}\n{tb.format_exc()}")

            try:
                video = await db.get(Video, video_id)
                if video:
                    video.status = VideoStatus.FAILED
                    video.error_message = error_msg
                    await db.commit()
            except Exception:
                logger.error("Failed to update video status after render crash")
