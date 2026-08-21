"""
Project-first API routes for source assets and teaching materials.
"""

import logging
import json
import os
from pathlib import Path
import shutil
import uuid
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from config import settings
from db.database import get_db
from db.models import (
    Project,
    ProjectAsset,
    ProjectAssetSyncRole,
    ProjectAssetKind,
    ProjectAssetRole,
    ProjectAssetStatus,
    ProjectMediaSourceType,
    ProjectSourceMode,
    ProjectStatus,
    Video,
    VideoStatus,
)
from models.schemas import (
    NativeImportCancelResponse,
    NativeImportFinalizeRequest,
    NativeImportInitRequest,
    NativeImportInitResponse,
    NativeImportOrphanReport,
    PrimaryImportChunkResponse,
    PrimaryImportStatusResponse,
    ProjectAssetResponse,
    ProjectAssetMetadataUpdateRequest,
    ProjectAssetSyncUpdateRequest,
    ProjectAssetUploadResponse,
    ProjectCreateRequest,
    ProjectDetailResponse,
    ProjectResponse,
    ProjectSourceSyncApplyRequest,
    ProjectSourceSyncAsset,
    ProjectSourceSyncPlanResponse,
    ProjectUpdateRequest,
    ProjectReadinessResponse,
    VideoUploadResponse,
)
from services.native_semantic_compositor import prewarm_render_proxy
from services.native_imports import (
    append_native_import_chunk,
    cancel_native_import_session,
    create_native_import_session,
    get_native_import_received_bytes,
    list_native_import_orphans,
    load_native_import_session,
    mark_native_import_status,
    quarantine_native_import,
    resolve_staged_path,
)
from services.ffmpeg import ffmpeg_service
from services.lecture_structure import extract_structure_reference_metadata
from services.source_sync import (
    SYNC_METADATA_KEY,
    build_sync_metadata,
    extract_user_sync_offset,
    merge_sync_metadata,
    recommend_sync_offsets,
)
from services.upload_limits import max_upload_size_bytes, upload_limit_label
from services.readiness import build_project_readiness
from services.render_jobs import get_active_render_job


router = APIRouter(prefix="/projects")
logger = logging.getLogger(__name__)
UPLOAD_COPY_BUFFER_BYTES = 8 * 1024 * 1024

AssetUploadType = Literal[
    "video",
    "screen",
    "camera",
    "webcam",
    "phone_camera",
    "audio",
    "slides",
    "notes",
    "materials",
]

VIDEO_EXTENSIONS = {".mp4", ".mpeg", ".mpg", ".mov", ".avi", ".webm", ".mkv"}
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".webm"}
SLIDE_EXTENSIONS = {".ppt", ".pptx", ".pdf"}
NOTE_EXTENSIONS = {".pdf", ".docx", ".txt", ".md"}
MATERIAL_EXTENSIONS = {
    ".pdf",
    ".ppt",
    ".pptx",
    ".docx",
    ".txt",
    ".md",
    ".csv",
    ".tsv",
    ".xlsx",
    ".json",
    ".zip",
}

VIDEO_ARTIFACT_SUFFIXES = (
    "subtitles.srt",
    "subtitles.vtt",
    "chapters.txt",
    "edit_plan.json",
    "quality_report.json",
    "mode_comparison.json",
    "mode_comparison.md",
    "academic_evidence.json",
    "academic_evidence.md",
    "before_after_comparison.json",
    "timeline_decisions.csv",
    "evidence_bundle.zip",
)

ALLOWED_EXTENSIONS_BY_TYPE = {
    "video": VIDEO_EXTENSIONS,
    "screen": VIDEO_EXTENSIONS,
    "camera": VIDEO_EXTENSIONS,
    "webcam": VIDEO_EXTENSIONS,
    "phone_camera": VIDEO_EXTENSIONS,
    "audio": AUDIO_EXTENSIONS,
    "slides": SLIDE_EXTENSIONS,
    "notes": NOTE_EXTENSIONS,
    "materials": MATERIAL_EXTENSIONS,
}


def _extension(filename: str | None) -> str:
    return os.path.splitext(filename or "")[1].lower()


def _asset_kind_for_upload(asset_type: AssetUploadType, filename: str | None) -> ProjectAssetKind:
    ext = _extension(filename)
    if asset_type == "video":
        return ProjectAssetKind.MIXED_VIDEO
    if asset_type == "screen":
        return ProjectAssetKind.SCREEN_VIDEO
    if asset_type in {"camera", "webcam", "phone_camera"}:
        return ProjectAssetKind.CAMERA_VIDEO
    if asset_type == "audio":
        return ProjectAssetKind.AUDIO
    if asset_type == "slides":
        return ProjectAssetKind.SLIDE_DECK
    if asset_type == "notes":
        return ProjectAssetKind.PDF_NOTES if ext == ".pdf" else ProjectAssetKind.TEXT_NOTES
    return ProjectAssetKind.COURSE_MATERIAL


def _asset_role_for_upload(asset_type: AssetUploadType) -> ProjectAssetRole:
    return {
        "video": ProjectAssetRole.PRIMARY,
        "screen": ProjectAssetRole.SCREEN,
        "camera": ProjectAssetRole.CAMERA,
        "webcam": ProjectAssetRole.CAMERA,
        "phone_camera": ProjectAssetRole.CAMERA,
        "audio": ProjectAssetRole.AUDIO,
        "slides": ProjectAssetRole.SLIDES,
        "notes": ProjectAssetRole.NOTES,
        "materials": ProjectAssetRole.SUPPORTING_MATERIAL,
    }[asset_type]


def _source_type_for_upload(asset_type: AssetUploadType, filename: str | None) -> ProjectMediaSourceType:
    ext = _extension(filename)
    if asset_type == "video":
        return ProjectMediaSourceType.MIXED_VIDEO
    if asset_type == "screen":
        return ProjectMediaSourceType.SCREEN_RECORDING
    if asset_type == "camera":
        return ProjectMediaSourceType.CAMERA_RECORDING
    if asset_type == "webcam":
        return ProjectMediaSourceType.WEBCAM_RECORDING
    if asset_type == "phone_camera":
        return ProjectMediaSourceType.PHONE_CAMERA_RECORDING
    if asset_type == "audio":
        return ProjectMediaSourceType.SEPARATE_AUDIO
    if asset_type == "slides":
        return ProjectMediaSourceType.SLIDE_DECK
    if asset_type == "notes":
        return ProjectMediaSourceType.PDF_NOTES if ext == ".pdf" else ProjectMediaSourceType.TEXT_NOTES
    return ProjectMediaSourceType.COURSE_MATERIAL


def _sync_role_for_upload(asset_type: AssetUploadType) -> ProjectAssetSyncRole:
    return {
        "video": ProjectAssetSyncRole.PRIMARY_TIMELINE,
        "screen": ProjectAssetSyncRole.SCREEN_REFERENCE,
        "camera": ProjectAssetSyncRole.CAMERA_OVERLAY,
        "webcam": ProjectAssetSyncRole.CAMERA_OVERLAY,
        "phone_camera": ProjectAssetSyncRole.CAMERA_OVERLAY,
        "audio": ProjectAssetSyncRole.AUDIO_MASTER,
        "slides": ProjectAssetSyncRole.STRUCTURE_REFERENCE,
        "notes": ProjectAssetSyncRole.STRUCTURE_REFERENCE,
        "materials": ProjectAssetSyncRole.STRUCTURE_REFERENCE,
    }[asset_type]


def _structure_metadata_for_upload(
    asset_type: AssetUploadType,
    source_type: ProjectMediaSourceType,
    ext: str,
) -> dict[str, Any]:
    if asset_type == "slides":
        return {
            "teaching_material": True,
            "structure_reference_role": "slide_sequence",
            "document_format": ext.lstrip("."),
            "structure_inference_ready": True,
            "expected_structure_signals": ["slide_order", "slide_titles", "section_breaks"],
            "text_extraction_status": "pending",
        }
    if asset_type == "notes":
        role = "pdf_notes" if source_type == ProjectMediaSourceType.PDF_NOTES else "text_notes"
        return {
            "teaching_material": True,
            "structure_reference_role": role,
            "document_format": ext.lstrip("."),
            "structure_inference_ready": True,
            "expected_structure_signals": ["headings", "objectives", "topic_outlines"],
            "text_extraction_status": "pending",
        }
    if asset_type == "materials":
        return {
            "teaching_material": True,
            "structure_reference_role": "supporting_reference",
            "document_format": ext.lstrip("."),
            "structure_inference_ready": False,
            "expected_structure_signals": ["supporting_terms", "examples", "references"],
            "text_extraction_status": "pending",
        }
    return {}


def _parse_metadata_form(metadata: str | None) -> dict[str, Any]:
    if not metadata:
        return {}
    try:
        parsed = json.loads(metadata)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, f"Invalid metadata JSON: {exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise HTTPException(400, "metadata must be a JSON object")
    return parsed


def _asset_matches_structure(asset: ProjectAsset) -> bool:
    return asset.role in {
        ProjectAssetRole.SLIDES,
        ProjectAssetRole.NOTES,
        ProjectAssetRole.SUPPORTING_MATERIAL,
    } or asset.sync_role == ProjectAssetSyncRole.STRUCTURE_REFERENCE


def _validate_asset_upload(file: UploadFile, asset_type: AssetUploadType) -> str:
    ext = _extension(file.filename)
    allowed_extensions = ALLOWED_EXTENSIONS_BY_TYPE[asset_type]
    if ext not in allowed_extensions:
        allowed = ", ".join(sorted(allowed_extensions))
        raise HTTPException(
            400,
            f"Unsupported {asset_type} file type: {ext or 'missing extension'}. Allowed: {allowed}",
        )
    return ext


def _asset_storage_path(project_id: UUID, asset_id: UUID, ext: str) -> tuple[str, str]:
    filename = f"{asset_id}{ext}"
    directory = os.path.join(settings.UPLOAD_PATH, "projects", str(project_id), "assets")
    return filename, os.path.join(directory, filename)


def _remove_file_if_present(path: str | None, removed: set[str]) -> None:
    if not path:
        return
    normalized = os.path.abspath(path)
    if normalized in removed or not os.path.isfile(normalized):
        return
    try:
        os.remove(normalized)
        removed.add(normalized)
    except OSError as exc:
        logger.warning("Could not remove project file %s: %s", normalized, exc)


def _remove_video_artifacts(video_id: UUID, removed: set[str]) -> None:
    for suffix in VIDEO_ARTIFACT_SUFFIXES:
        _remove_file_if_present(
            os.path.join(settings.VIDEO_STORAGE_PATH, f"{video_id}_{suffix}"),
            removed,
        )


async def _media_metadata(file_path: str, asset_type: AssetUploadType) -> dict:
    if asset_type not in {"video", "screen", "camera", "webcam", "phone_camera", "audio"}:
        return {}
    try:
        return await ffmpeg_service.get_video_metadata(file_path)
    except Exception as exc:
        logger.warning("Could not read media metadata for %s: %s", file_path, exc)
        return {}


def _import_session_warnings(session) -> list[str]:
    warnings: list[str] = []
    if session.last_error:
        warnings.append(session.last_error)
    return warnings


def _import_session_status_response(session, *, project_id: UUID) -> PrimaryImportStatusResponse:
    bytes_received = get_native_import_received_bytes(settings, session)
    if bytes_received == 0 and session.status in {"finalizing", "finalized"}:
        bytes_received = session.file_size_bytes
    total_bytes = session.file_size_bytes
    percent = round((bytes_received / total_bytes) * 100, 3) if total_bytes else 0.0
    return PrimaryImportStatusResponse(
        token=session.token,
        project_id=project_id,
        filename=session.original_filename,
        status=session.status,
        bytes_received=bytes_received,
        total_bytes=total_bytes,
        percent=percent,
        complete=bytes_received >= total_bytes and total_bytes > 0,
        updated_at=session.updated_at,
        warnings=_import_session_warnings(session),
    )


async def _finalize_project_primary_import_session(
    *,
    project: Project,
    session,
    request: NativeImportFinalizeRequest,
    upload_type: str,
    success_message: str,
    background_tasks: BackgroundTasks,
    db: AsyncSession,
) -> VideoUploadResponse:
    part_path = resolve_staged_path(settings, session, part=True)
    staged_path = resolve_staged_path(settings, session, part=False)
    if part_path.exists():
        raise HTTPException(409, "Import copy is still in progress because the partial file remains present")
    if not staged_path.exists():
        raise HTTPException(409, "Staged import file is missing. Retry the import.")

    actual_size = os.path.getsize(staged_path)
    if actual_size != session.file_size_bytes or actual_size != request.copied_file_size_bytes:
        raise HTTPException(
            409,
            f"Staged file size mismatch. Expected {session.file_size_bytes} bytes but found {actual_size} bytes.",
        )

    session = mark_native_import_status(settings, session, "finalizing")

    try:
        media_metadata = await _media_metadata(str(staged_path), "video")
    except Exception:
        media_metadata = {}

    existing_primary_result = await db.execute(
        select(ProjectAsset).where(
            ProjectAsset.project_id == project.id,
            ProjectAsset.is_primary.is_(True),
        )
    )
    for existing_asset in existing_primary_result.scalars():
        existing_asset.is_primary = False

    asset_id = uuid.uuid4()
    video_id = uuid.uuid4()
    ext = _extension(session.original_filename)
    filename, file_path = _asset_storage_path(project.id, asset_id, ext)
    os.makedirs(os.path.dirname(file_path), exist_ok=True)

    try:
        os.replace(staged_path, file_path)
    except OSError as exc:
        mark_native_import_status(settings, session, "copy_failed")
        raise HTTPException(500, f"Could not move the staged import into project storage: {exc}") from exc

    asset = ProjectAsset(
        id=asset_id,
        project_id=project.id,
        kind=ProjectAssetKind.MIXED_VIDEO,
        role=ProjectAssetRole.PRIMARY,
        source_type=ProjectMediaSourceType.MIXED_VIDEO,
        sync_role=ProjectAssetSyncRole.PRIMARY_TIMELINE,
        status=ProjectAssetStatus.READY,
        is_primary=True,
        filename=filename,
        original_filename=session.original_filename,
        file_path=file_path,
        file_size_bytes=actual_size,
        mime_type=session.mime_type,
        duration_seconds=media_metadata.get("duration"),
        metadata_json={
            "legacy_video_id": str(video_id),
            "source_type": ProjectMediaSourceType.MIXED_VIDEO.value,
            "sync_role": ProjectAssetSyncRole.PRIMARY_TIMELINE.value,
            "upload_type": upload_type,
            "storage_scope": "native_primary_import",
            "extension": ext,
            "native_import_token": session.token,
            "resolution": (
                f"{media_metadata.get('width')}x{media_metadata.get('height')}"
                if media_metadata.get("width") and media_metadata.get("height")
                else None
            ),
            "fps": media_metadata.get("fps"),
        },
    )
    db.add(asset)

    video = Video(
        id=video_id,
        project_id=project.id,
        project_asset_id=asset_id,
        filename=filename,
        original_filename=session.original_filename,
        file_path=file_path,
        file_size_bytes=actual_size,
        duration_seconds=media_metadata.get("duration"),
        resolution=(
            f"{media_metadata.get('width')}x{media_metadata.get('height')}"
            if media_metadata.get("width") and media_metadata.get("height")
            else None
        ),
        fps=media_metadata.get("fps"),
        status=VideoStatus.UPLOADED,
    )
    db.add(video)

    if project.status == ProjectStatus.DRAFT:
        project.status = ProjectStatus.READY
    if project.source_mode != ProjectSourceMode.MULTI_SOURCE:
        project.source_mode = ProjectSourceMode.SINGLE_VIDEO

    try:
        await db.commit()
    except Exception as exc:
        await db.rollback()
        quarantined_path = quarantine_native_import(settings, session, Path(file_path), "database_finalize_failure")
        raise HTTPException(
            500,
            "Import finalization failed after file staging. "
            f"The staged copy was quarantined at {quarantined_path.name}. Error: {exc}",
        ) from exc

    mark_native_import_status(settings, session, "finalized")
    background_tasks.add_task(_prewarm_primary_video_proxy, file_path)

    return VideoUploadResponse(
        id=video_id,
        project_id=project.id,
        project_asset_id=asset.id,
        filename=session.original_filename,
        status=VideoStatus.UPLOADED,
        duration_seconds=media_metadata.get("duration"),
        resolution=video.resolution,
        file_size_mb=round(actual_size / 1024 / 1024, 1),
        message=success_message,
    )


async def _upload_project_asset(
    project_id: UUID,
    asset_type: AssetUploadType,
    file: UploadFile,
    is_primary: bool,
    db: AsyncSession,
    metadata: dict[str, Any] | None = None,
) -> ProjectAssetUploadResponse:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    ext = _validate_asset_upload(file, asset_type)
    asset_id = uuid.uuid4()
    filename, file_path = _asset_storage_path(project_id, asset_id, ext)

    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "wb") as saved_file:
        shutil.copyfileobj(file.file, saved_file, length=UPLOAD_COPY_BUFFER_BYTES)

    file_size = os.path.getsize(file_path)
    if file_size > max_upload_size_bytes(settings):
        os.remove(file_path)
        raise HTTPException(413, f"File too large. Maximum: {upload_limit_label(settings)}")

    media_metadata = await _media_metadata(file_path, asset_type)
    kind = _asset_kind_for_upload(asset_type, file.filename)
    role = _asset_role_for_upload(asset_type)
    source_type = _source_type_for_upload(asset_type, file.filename)
    sync_role = _sync_role_for_upload(asset_type)

    if is_primary:
        existing_primary_result = await db.execute(
            select(ProjectAsset).where(
                ProjectAsset.project_id == project_id,
                ProjectAsset.is_primary.is_(True),
            )
        )
        for existing_asset in existing_primary_result.scalars():
            existing_asset.is_primary = False

    user_metadata = metadata or {}
    metadata_json = {
        "upload_type": asset_type,
        "source_type": source_type.value,
        "sync_role": sync_role.value,
        "extension": ext,
        "storage_scope": "project_asset",
    }
    metadata_json.update(_structure_metadata_for_upload(asset_type, source_type, ext))
    if user_metadata:
        metadata_json["user_metadata"] = user_metadata
    if media_metadata:
        metadata_json.update(
            {
                "format": media_metadata.get("format"),
                "resolution": (
                    f"{media_metadata.get('width')}x{media_metadata.get('height')}"
                    if media_metadata.get("width") and media_metadata.get("height")
                    else None
                ),
                "fps": media_metadata.get("fps"),
                "video_codec": media_metadata.get("video_codec"),
                "audio_codec": media_metadata.get("audio_codec"),
                "audio_sample_rate": media_metadata.get("audio_sample_rate"),
                "ffprobe_tags": media_metadata.get("format_tags") or {},
                "video_stream_tags": media_metadata.get("video_tags") or {},
                "audio_stream_tags": media_metadata.get("audio_tags") or {},
            }
        )

    if metadata_json.get("structure_inference_ready"):
        try:
            metadata_json.update(
                await extract_structure_reference_metadata(
                    file_path=file_path,
                    original_filename=file.filename or filename,
                    structure_reference_role=str(metadata_json.get("structure_reference_role") or "teaching_material"),
                )
            )
        except Exception as exc:
            logger.warning("Could not extract structure metadata for %s: %s", file_path, exc)
            metadata_json.update({
                "text_extraction_status": "failed",
                "text_extraction_error": str(exc),
            })

    user_sync_offset = extract_user_sync_offset(user_metadata)
    if user_sync_offset is not None:
        metadata_json[SYNC_METADATA_KEY] = {
            "method": "user_provided_upload_metadata",
            "confidence": 1.0,
            "recommended_offset_seconds": user_sync_offset,
            "applied_offset_seconds": user_sync_offset,
            "needs_user_review": False,
            "user_adjusted": True,
            "applied_by": "upload_metadata",
            "waveform_sync_ready": True,
            "reason": "Offset supplied by the uploader metadata.",
        }

    asset = ProjectAsset(
        id=asset_id,
        project_id=project_id,
        kind=kind,
        role=role,
        source_type=source_type,
        sync_role=sync_role,
        status=ProjectAssetStatus.READY,
        is_primary=is_primary,
        filename=filename,
        original_filename=file.filename or filename,
        file_path=file_path,
        file_size_bytes=file_size,
        mime_type=file.content_type,
        duration_seconds=media_metadata.get("duration"),
        sync_offset_seconds=user_sync_offset or 0.0,
        metadata_json=metadata_json,
    )
    db.add(asset)

    if project.status == ProjectStatus.DRAFT:
        project.status = ProjectStatus.READY
    if asset_type != "video" or not is_primary:
        project.source_mode = ProjectSourceMode.MULTI_SOURCE

    await db.commit()
    await db.refresh(asset)

    return ProjectAssetUploadResponse(
        id=asset.id,
        project_id=asset.project_id,
        kind=asset.kind,
        role=asset.role,
        source_type=asset.source_type,
        sync_role=asset.sync_role,
        status=asset.status,
        is_primary=asset.is_primary,
        filename=asset.filename,
        original_filename=asset.original_filename,
        file_path=asset.file_path,
        file_size_bytes=asset.file_size_bytes,
        mime_type=asset.mime_type,
        duration_seconds=asset.duration_seconds,
        sync_offset_seconds=asset.sync_offset_seconds,
        metadata_json=asset.metadata_json or {},
        error_message=asset.error_message,
        created_at=asset.created_at,
        updated_at=asset.updated_at,
        file_size_mb=round(file_size / 1024 / 1024, 1),
        message=f"{source_type.value.replace('_', ' ').title()} asset uploaded to project.",
    )


@router.post("", response_model=ProjectDetailResponse, tags=["Projects"])
async def create_project(
    request: ProjectCreateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create a project workspace that can receive one or more source assets."""
    project = Project(
        title=request.title.strip(),
        description=request.description,
        status=ProjectStatus.DRAFT,
        source_mode=request.source_mode,
        project_type=request.project_type,
        metadata_json=request.metadata,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return ProjectDetailResponse.model_validate(
        {
            "id": project.id,
            "title": project.title,
            "description": project.description,
            "status": project.status,
            "source_mode": project.source_mode,
            "project_type": project.project_type,
            "metadata_json": project.metadata_json or {},
            "error_message": project.error_message,
            "created_at": project.created_at,
            "updated_at": project.updated_at,
            "assets": [],
        }
    )


@router.get("", response_model=list[ProjectResponse], tags=["Projects"])
async def list_projects(db: AsyncSession = Depends(get_db)):
    """List project workspaces."""
    result = await db.execute(select(Project).order_by(Project.created_at.desc()))
    return result.scalars().all()


@router.get("/{project_id}/readiness", response_model=ProjectReadinessResponse, tags=["Workflow"])
async def get_project_readiness(project_id: UUID, db: AsyncSession = Depends(get_db)):
    """Run a non-destructive preflight for a project in either runtime mode."""
    result = await db.execute(
        select(Project)
        .options(selectinload(Project.assets), selectinload(Project.videos))
        .where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(404, "Project not found")
    videos = list(project.videos or [])
    video = next((item for item in videos if item.project_asset_id and any(
        str(asset.id) == str(item.project_asset_id) for asset in project.assets or []
    )), None)
    video = video or (videos[0] if videos else None)
    return build_project_readiness(
        project,
        video=video,
        assets=list(project.assets or []),
        settings=settings,
    )


@router.get("/{project_id}", response_model=ProjectDetailResponse, tags=["Projects"])
async def get_project(project_id: UUID, db: AsyncSession = Depends(get_db)):
    """Get a project with its uploaded assets."""
    result = await db.execute(
        select(Project)
        .options(selectinload(Project.assets))
        .where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(404, "Project not found")
    return project


@router.patch("/{project_id}", response_model=ProjectDetailResponse, tags=["Projects"])
async def update_project(
    project_id: UUID,
    request: ProjectUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update project workspace metadata such as title, type, and source mode."""
    project = await _load_project_with_assets(project_id, db)
    fields = request.model_fields_set

    if "title" in fields:
        title = (request.title or "").strip()
        if not title:
            raise HTTPException(400, "Project title cannot be empty")
        project.title = title
    if "description" in fields:
        project.description = request.description.strip() if request.description else None
    if "source_mode" in fields and request.source_mode is not None:
        project.source_mode = request.source_mode
    if "project_type" in fields:
        project.project_type = (request.project_type or "lecture").strip() or "lecture"
    if "metadata" in fields and request.metadata is not None:
        project.metadata_json = request.metadata

    await db.commit()
    project = await _load_project_with_assets(project_id, db)
    return project


@router.delete("/{project_id}", tags=["Projects"])
async def delete_project(project_id: UUID, db: AsyncSession = Depends(get_db)):
    """Delete a project and its project-owned assets, videos, and generated artifacts."""
    result = await db.execute(
        select(Project)
        .options(selectinload(Project.assets), selectinload(Project.videos))
        .where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(404, "Project not found")

    removed_files: set[str] = set()
    videos = list(project.videos or [])
    assets = list(project.assets or [])

    active_videos = [
        video for video in videos
        if video.status in {
            VideoStatus.PROCESSING,
            VideoStatus.TRANSCRIBING,
            VideoStatus.ANALYZING,
            VideoStatus.PLANNING,
            VideoStatus.RENDERING,
        }
        or get_active_render_job(str(video.id))
    ]
    if active_videos:
        raise HTTPException(
            409,
            "This project cannot be deleted while analysis or export is active. Cancel or finish the job first.",
            headers={"X-AIVE-Error-Code": "PROJECT_JOB_ACTIVE"},
        )

    for video in videos:
        _remove_file_if_present(video.file_path, removed_files)
        _remove_file_if_present(video.audio_path, removed_files)
        _remove_file_if_present(video.processed_video_path, removed_files)
        _remove_video_artifacts(video.id, removed_files)
        await db.delete(video)

    for asset in assets:
        _remove_file_if_present(asset.file_path, removed_files)

    await db.delete(project)
    await db.commit()
    return {
        "status": "deleted",
        "project_id": str(project_id),
        "videos_deleted": len(videos),
        "assets_deleted": len(assets),
        "files_deleted": len(removed_files),
    }


@router.get("/{project_id}/assets", response_model=list[ProjectAssetResponse], tags=["Project Assets"])
async def list_project_assets(project_id: UUID, db: AsyncSession = Depends(get_db)):
    """List uploaded assets for a project."""
    if not await db.get(Project, project_id):
        raise HTTPException(404, "Project not found")

    result = await db.execute(
        select(ProjectAsset)
        .where(ProjectAsset.project_id == project_id)
        .order_by(ProjectAsset.created_at.desc())
    )
    return result.scalars().all()


async def _load_project_with_assets(project_id: UUID, db: AsyncSession) -> Project:
    result = await db.execute(
        select(Project)
        .options(selectinload(Project.assets))
        .where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(404, "Project not found")
    return project


def _project_source_sync_plan(project: Project) -> ProjectSourceSyncPlanResponse:
    reference_asset, recommendations = recommend_sync_offsets(project.assets)
    recommendation_by_asset_id = {item.asset_id: item for item in recommendations}
    warnings: list[str] = []

    if reference_asset is None:
        warnings.append("No screen, camera, audio, or primary media assets are available for synchronization.")
        return ProjectSourceSyncPlanResponse(project_id=project.id, assets=[], warnings=warnings)

    sync_assets: list[ProjectSourceSyncAsset] = []
    for asset in project.assets:
        recommendation = recommendation_by_asset_id.get(str(asset.id))
        if recommendation is None:
            continue

        current_offset = float(asset.sync_offset_seconds or 0.0)
        recommended_offset = recommendation.recommended_offset_seconds
        sync_assets.append(
            ProjectSourceSyncAsset(
                asset=ProjectAssetResponse.model_validate(asset),
                reference_asset_id=reference_asset.id,
                recommended_offset_seconds=recommended_offset,
                current_offset_seconds=current_offset,
                manual_adjustment_seconds=round(current_offset - recommended_offset, 3),
                confidence=recommendation.confidence,
                method=recommendation.method,
                reason=recommendation.reason,
                needs_user_review=recommendation.needs_user_review,
                waveform_sync_ready=True,
                metadata_anchor=recommendation.metadata_anchor,
            )
        )

    if len(sync_assets) < 2:
        warnings.append("Only one syncable source is present; offsets will matter after another source is uploaded.")
    if any(item.method == "default_zero_offset" for item in sync_assets):
        warnings.append("Some sources lack comparable recording start metadata and need manual offset review.")

    return ProjectSourceSyncPlanResponse(
        project_id=project.id,
        reference_asset_id=reference_asset.id,
        sync_basis="metadata",
        assets=sync_assets,
        warnings=warnings,
    )


@router.get("/{project_id}/source-sync", response_model=ProjectSourceSyncPlanResponse, tags=["Project Source Sync"])
async def get_project_source_sync_plan(project_id: UUID, db: AsyncSession = Depends(get_db)):
    """Return metadata-based sync recommendations and current user offsets."""
    project = await _load_project_with_assets(project_id, db)
    return _project_source_sync_plan(project)


@router.post("/{project_id}/source-sync/apply-metadata", response_model=ProjectSourceSyncPlanResponse, tags=["Project Source Sync"])
async def apply_project_source_sync_metadata(
    project_id: UUID,
    request: ProjectSourceSyncApplyRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Apply metadata-derived offsets to project sources, preserving manual edits unless forced."""
    project = await _load_project_with_assets(project_id, db)
    _, recommendations = recommend_sync_offsets(project.assets)
    recommendation_by_asset_id = {item.asset_id: item for item in recommendations}
    apply_request = request or ProjectSourceSyncApplyRequest()

    for asset in project.assets:
        recommendation = recommendation_by_asset_id.get(str(asset.id))
        if recommendation is None:
            continue

        stored_sync = (asset.metadata_json or {}).get(SYNC_METADATA_KEY)
        was_user_adjusted = isinstance(stored_sync, dict) and bool(stored_sync.get("user_adjusted"))
        if was_user_adjusted and not apply_request.force:
            continue

        asset.sync_offset_seconds = recommendation.recommended_offset_seconds
        merge_sync_metadata(
            asset,
            build_sync_metadata(recommendation, applied_by="metadata_sync", note=apply_request.note),
        )

    await db.commit()
    await db.refresh(project)
    project = await _load_project_with_assets(project_id, db)
    return _project_source_sync_plan(project)


@router.post("/{project_id}/assets/upload", response_model=ProjectAssetUploadResponse, tags=["Project Assets"])
async def upload_project_asset(
    project_id: UUID,
    asset_type: AssetUploadType = Form(...),
    is_primary: bool = Form(False),
    metadata: str | None = Form(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload a project asset using an explicit asset_type form field."""
    return await _upload_project_asset(
        project_id,
        asset_type,
        file,
        is_primary,
        db,
        metadata=_parse_metadata_form(metadata),
    )


@router.post("/{project_id}/videos/upload", response_model=VideoUploadResponse, tags=["Project Videos"])
async def upload_project_primary_video(
    project_id: UUID,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload the primary mixed video for an existing project and create its legacy-compatible Video."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    ext = _validate_asset_upload(file, "video")
    asset_id = uuid.uuid4()
    video_id = uuid.uuid4()
    filename, file_path = _asset_storage_path(project_id, asset_id, ext)

    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "wb") as saved_file:
        shutil.copyfileobj(file.file, saved_file, length=UPLOAD_COPY_BUFFER_BYTES)

    file_size = os.path.getsize(file_path)
    if file_size > max_upload_size_bytes(settings):
        os.remove(file_path)
        raise HTTPException(413, f"File too large. Maximum: {upload_limit_label(settings)}")

    media_metadata = await _media_metadata(file_path, "video")

    existing_primary_result = await db.execute(
        select(ProjectAsset).where(
            ProjectAsset.project_id == project_id,
            ProjectAsset.is_primary.is_(True),
        )
    )
    for existing_asset in existing_primary_result.scalars():
        existing_asset.is_primary = False

    asset = ProjectAsset(
        id=asset_id,
        project_id=project_id,
        kind=ProjectAssetKind.MIXED_VIDEO,
        role=ProjectAssetRole.PRIMARY,
        source_type=ProjectMediaSourceType.MIXED_VIDEO,
        sync_role=ProjectAssetSyncRole.PRIMARY_TIMELINE,
        status=ProjectAssetStatus.READY,
        is_primary=True,
        filename=filename,
        original_filename=file.filename or filename,
        file_path=file_path,
        file_size_bytes=file_size,
        mime_type=file.content_type,
        duration_seconds=media_metadata.get("duration"),
        metadata_json={
            "legacy_video_id": str(video_id),
            "source_type": ProjectMediaSourceType.MIXED_VIDEO.value,
            "sync_role": ProjectAssetSyncRole.PRIMARY_TIMELINE.value,
            "upload_type": "video",
            "storage_scope": "project_primary_video",
            "extension": ext,
            "resolution": (
                f"{media_metadata.get('width')}x{media_metadata.get('height')}"
                if media_metadata.get("width") and media_metadata.get("height")
                else None
            ),
            "fps": media_metadata.get("fps"),
        },
    )
    db.add(asset)

    video = Video(
        id=video_id,
        project_id=project_id,
        project_asset_id=asset_id,
        filename=filename,
        original_filename=file.filename or filename,
        file_path=file_path,
        file_size_bytes=file_size,
        duration_seconds=media_metadata.get("duration"),
        resolution=(
            f"{media_metadata.get('width')}x{media_metadata.get('height')}"
            if media_metadata.get("width") and media_metadata.get("height")
            else None
        ),
        fps=media_metadata.get("fps"),
        status=VideoStatus.UPLOADED,
    )
    db.add(video)

    if project.status == ProjectStatus.DRAFT:
        project.status = ProjectStatus.READY
    if project.source_mode != ProjectSourceMode.MULTI_SOURCE:
        project.source_mode = ProjectSourceMode.SINGLE_VIDEO

    await db.commit()

    # Normalize large 4K/MOV sources while the user adds notes and reviews the
    # project. Export then reuses this proxy instead of paying for a second
    # full-length transcode at render time.
    background_tasks.add_task(_prewarm_primary_video_proxy, file_path)

    return VideoUploadResponse(
        id=video_id,
        project_id=project.id,
        project_asset_id=asset.id,
        filename=file.filename or filename,
        status=VideoStatus.UPLOADED,
        duration_seconds=media_metadata.get("duration"),
        resolution=video.resolution,
        file_size_mb=round(file_size / 1024 / 1024, 1),
        message=f"Video uploaded to {project.title}. Add course materials, then start processing.",
    )


@router.post(
    "/{project_id}/imports/native/primary/init",
    response_model=NativeImportInitResponse,
    tags=["Project Videos"],
)
async def init_native_project_primary_import(
    project_id: UUID,
    request: NativeImportInitRequest,
    db: AsyncSession = Depends(get_db),
):
    """Initialize a native desktop import session for a very large primary video."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    ext = _extension(request.original_filename)
    if ext not in VIDEO_EXTENSIONS:
        allowed = ", ".join(sorted(VIDEO_EXTENSIONS))
        raise HTTPException(
            400,
            f"Unsupported primary video type: {ext or 'missing extension'}. Allowed: {allowed}",
        )

    try:
        session, free_bytes, required_bytes = create_native_import_session(
            settings=settings,
            project_id=str(project_id),
            original_filename=request.original_filename,
            file_size_bytes=request.file_size_bytes,
            mime_type=request.mime_type,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 507 if "Insufficient disk space" in detail else 400
        raise HTTPException(status_code, detail) from exc

    warnings: list[str] = []
    orphan_records, orphan_warnings = list_native_import_orphans(settings, str(project_id))
    if orphan_records:
        warnings.append(
            f"{len(orphan_records)} orphaned or stale staged import file(s) already exist. Review diagnostics before cleanup."
        )
    warnings.extend(orphan_warnings)

    return NativeImportInitResponse(
        token=session.token,
        project_id=project_id,
        original_filename=request.original_filename,
        mime_type=request.mime_type,
        file_size_bytes=request.file_size_bytes,
        max_size_bytes=max_upload_size_bytes(settings),
        available_disk_bytes=free_bytes,
        required_free_bytes=required_bytes,
        staging_relative_path=session.staging_relative_path,
        staging_part_relative_path=session.staging_part_relative_path,
        warnings=warnings,
    )


@router.post(
    "/{project_id}/imports/browser/primary/init",
    response_model=NativeImportInitResponse,
    tags=["Project Videos"],
)
async def init_browser_project_primary_import(
    project_id: UUID,
    request: NativeImportInitRequest,
    db: AsyncSession = Depends(get_db),
):
    """Initialize a resumable browser upload session for a very large primary video."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    ext = _extension(request.original_filename)
    if ext not in VIDEO_EXTENSIONS:
        allowed = ", ".join(sorted(VIDEO_EXTENSIONS))
        raise HTTPException(
            400,
            f"Unsupported primary video type: {ext or 'missing extension'}. Allowed: {allowed}",
        )

    try:
        session, free_bytes, required_bytes = create_native_import_session(
            settings=settings,
            project_id=str(project_id),
            original_filename=request.original_filename,
            file_size_bytes=request.file_size_bytes,
            mime_type=request.mime_type,
        )
    except ValueError as exc:
        detail = str(exc)
        status_code = 507 if "Insufficient disk space" in detail else 400
        raise HTTPException(status_code, detail) from exc

    warnings: list[str] = []
    orphan_records, orphan_warnings = list_native_import_orphans(settings, str(project_id))
    if orphan_records:
        warnings.append(
            f"{len(orphan_records)} orphaned or stale staged import file(s) already exist. Review diagnostics before cleanup."
        )
    warnings.extend(orphan_warnings)

    return NativeImportInitResponse(
        token=session.token,
        project_id=project_id,
        original_filename=request.original_filename,
        mime_type=request.mime_type,
        file_size_bytes=request.file_size_bytes,
        max_size_bytes=max_upload_size_bytes(settings),
        available_disk_bytes=free_bytes,
        required_free_bytes=required_bytes,
        staging_relative_path=session.staging_relative_path,
        staging_part_relative_path=session.staging_part_relative_path,
        warnings=warnings,
    )


@router.post(
    "/{project_id}/imports/native/primary/{token}/finalize",
    response_model=VideoUploadResponse,
    tags=["Project Videos"],
)
async def finalize_native_project_primary_import(
    project_id: UUID,
    token: str,
    request: NativeImportFinalizeRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Finalize a native desktop import after the Tauri shell finishes copying the file."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    try:
        session = load_native_import_session(settings, token)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc

    if session.project_id != str(project_id):
        raise HTTPException(409, "Import session does not belong to this project")

    return await _finalize_project_primary_import_session(
        project=project,
        session=session,
        request=request,
        upload_type="native_primary_import",
        success_message=f"Video imported natively into {project.title}. Add course materials, then start processing.",
        background_tasks=background_tasks,
        db=db,
    )


@router.post(
    "/{project_id}/imports/native/primary/{token}/cancel",
    response_model=NativeImportCancelResponse,
    tags=["Project Videos"],
)
async def cancel_native_project_primary_import(
    project_id: UUID,
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Cancel a native desktop import and remove any staged partial files."""
    if not await db.get(Project, project_id):
        raise HTTPException(404, "Project not found")

    try:
        session, removed_files = cancel_native_import_session(settings, token)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc

    if session.project_id != str(project_id):
        raise HTTPException(409, "Import session does not belong to this project")

    return NativeImportCancelResponse(
        token=token,
        project_id=project_id,
        cancelled=True,
        removed_files=removed_files,
    )


@router.get(
    "/{project_id}/imports/browser/primary/{token}",
    response_model=PrimaryImportStatusResponse,
    tags=["Project Videos"],
)
async def get_browser_project_primary_import_status(
    project_id: UUID,
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Return resumable browser upload progress for a primary video import session."""
    if not await db.get(Project, project_id):
        raise HTTPException(404, "Project not found")

    try:
        session = load_native_import_session(settings, token)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc

    if session.project_id != str(project_id):
        raise HTTPException(409, "Import session does not belong to this project")

    return _import_session_status_response(session, project_id=project_id)


@router.put(
    "/{project_id}/imports/browser/primary/{token}/chunk",
    response_model=PrimaryImportChunkResponse,
    tags=["Project Videos"],
)
async def append_browser_project_primary_import_chunk(
    project_id: UUID,
    token: str,
    request: Request,
    offset: int = Query(..., ge=0),
    db: AsyncSession = Depends(get_db),
):
    """Append one browser upload chunk to a staged primary video import session."""
    if not await db.get(Project, project_id):
        raise HTTPException(404, "Project not found")

    try:
        session = load_native_import_session(settings, token)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc

    if session.project_id != str(project_id):
        raise HTTPException(409, "Import session does not belong to this project")

    chunk = await request.body()
    try:
        session, bytes_received, complete = append_native_import_chunk(
            settings,
            session,
            offset=offset,
            chunk=chunk,
        )
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except OSError as exc:
        raise HTTPException(500, f"Could not persist upload chunk: {exc}") from exc

    percent = round((bytes_received / session.file_size_bytes) * 100, 3) if session.file_size_bytes else 0.0
    return PrimaryImportChunkResponse(
        token=token,
        project_id=project_id,
        filename=session.original_filename,
        status=session.status,
        bytes_received=bytes_received,
        total_bytes=session.file_size_bytes,
        percent=percent,
        complete=complete,
        updated_at=session.updated_at,
        warnings=_import_session_warnings(session),
        next_offset=bytes_received,
    )


@router.post(
    "/{project_id}/imports/browser/primary/{token}/finalize",
    response_model=VideoUploadResponse,
    tags=["Project Videos"],
)
async def finalize_browser_project_primary_import(
    project_id: UUID,
    token: str,
    request: NativeImportFinalizeRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Finalize a resumable browser upload after all chunks reach staged storage."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    try:
        session = load_native_import_session(settings, token)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc

    if session.project_id != str(project_id):
        raise HTTPException(409, "Import session does not belong to this project")

    return await _finalize_project_primary_import_session(
        project=project,
        session=session,
        request=request,
        upload_type="browser_chunked_primary_import",
        success_message=f"Video uploaded to {project.title}. Add course materials, then start processing.",
        background_tasks=background_tasks,
        db=db,
    )


@router.post(
    "/{project_id}/imports/browser/primary/{token}/cancel",
    response_model=NativeImportCancelResponse,
    tags=["Project Videos"],
)
async def cancel_browser_project_primary_import(
    project_id: UUID,
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Cancel a resumable browser upload and remove any staged partial files."""
    if not await db.get(Project, project_id):
        raise HTTPException(404, "Project not found")

    try:
        session, removed_files = cancel_native_import_session(settings, token)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc

    if session.project_id != str(project_id):
        raise HTTPException(409, "Import session does not belong to this project")

    return NativeImportCancelResponse(
        token=token,
        project_id=project_id,
        cancelled=True,
        removed_files=removed_files,
    )


@router.get(
    "/{project_id}/imports/native/orphans",
    response_model=NativeImportOrphanReport,
    tags=["Project Videos"],
)
async def list_native_project_import_orphans(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Report orphaned or stale staged import files without deleting them."""
    if not await db.get(Project, project_id):
        raise HTTPException(404, "Project not found")

    orphan_records, warnings = list_native_import_orphans(settings, str(project_id))
    return NativeImportOrphanReport(
        project_id=project_id,
        orphans=orphan_records,
        warnings=warnings,
    )


async def _prewarm_primary_video_proxy(file_path: str) -> None:
    try:
        await prewarm_render_proxy(file_path)
        logger.info("Editing proxy ready for %s", file_path)
    except Exception as exc:
        logger.warning("Editing proxy prewarm failed for %s: %s", file_path, exc)


@router.post("/{project_id}/assets/video", response_model=ProjectAssetUploadResponse, tags=["Project Assets"])
async def upload_project_video_asset(
    project_id: UUID,
    is_primary: bool = Form(True),
    metadata: str | None = Form(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload a primary or secondary video source for a project."""
    return await _upload_project_asset(project_id, "video", file, is_primary, db, metadata=_parse_metadata_form(metadata))


@router.post("/{project_id}/assets/screen", response_model=ProjectAssetUploadResponse, tags=["Project Assets"])
async def upload_project_screen_asset(
    project_id: UUID,
    metadata: str | None = Form(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload a separate screen recording source for a project."""
    return await _upload_project_asset(project_id, "screen", file, False, db, metadata=_parse_metadata_form(metadata))


@router.post("/{project_id}/assets/camera", response_model=ProjectAssetUploadResponse, tags=["Project Assets"])
async def upload_project_camera_asset(
    project_id: UUID,
    metadata: str | None = Form(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload a separate webcam or camera recording source for a project."""
    return await _upload_project_asset(project_id, "camera", file, False, db, metadata=_parse_metadata_form(metadata))


@router.post("/{project_id}/assets/webcam", response_model=ProjectAssetUploadResponse, tags=["Project Assets"])
async def upload_project_webcam_asset(
    project_id: UUID,
    metadata: str | None = Form(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload a separate webcam recording source for a project."""
    return await _upload_project_asset(project_id, "webcam", file, False, db, metadata=_parse_metadata_form(metadata))


@router.post("/{project_id}/assets/phone-camera", response_model=ProjectAssetUploadResponse, tags=["Project Assets"])
async def upload_project_phone_camera_asset(
    project_id: UUID,
    metadata: str | None = Form(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload a phone camera recording source for a project."""
    return await _upload_project_asset(project_id, "phone_camera", file, False, db, metadata=_parse_metadata_form(metadata))


@router.post("/{project_id}/assets/audio", response_model=ProjectAssetUploadResponse, tags=["Project Assets"])
async def upload_project_audio_asset(
    project_id: UUID,
    is_primary: bool = Form(False),
    metadata: str | None = Form(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload a separate audio recording for a project."""
    return await _upload_project_asset(project_id, "audio", file, is_primary, db, metadata=_parse_metadata_form(metadata))


@router.post("/{project_id}/assets/slides", response_model=ProjectAssetUploadResponse, tags=["Project Assets"])
async def upload_project_slide_asset(
    project_id: UUID,
    metadata: str | None = Form(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload a slide deck or slide PDF for a project."""
    return await _upload_project_asset(project_id, "slides", file, False, db, metadata=_parse_metadata_form(metadata))


@router.post("/{project_id}/assets/notes", response_model=ProjectAssetUploadResponse, tags=["Project Assets"])
async def upload_project_notes_asset(
    project_id: UUID,
    metadata: str | None = Form(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload notes such as PDF, DOCX, TXT, or Markdown."""
    return await _upload_project_asset(project_id, "notes", file, False, db, metadata=_parse_metadata_form(metadata))


@router.post("/{project_id}/assets/materials", response_model=ProjectAssetUploadResponse, tags=["Project Assets"])
async def upload_project_supporting_material_asset(
    project_id: UUID,
    metadata: str | None = Form(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload supporting material for later RAG, structure, or evaluation workflows."""
    return await _upload_project_asset(project_id, "materials", file, False, db, metadata=_parse_metadata_form(metadata))


@router.get("/{project_id}/assets/{asset_id}", response_model=ProjectAssetResponse, tags=["Project Assets"])
async def get_project_asset(
    project_id: UUID,
    asset_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get metadata for one project asset."""
    asset = await db.get(ProjectAsset, asset_id)
    if not asset or asset.project_id != project_id:
        raise HTTPException(404, "Project asset not found")
    return asset


@router.put("/{project_id}/assets/{asset_id}/sync", response_model=ProjectAssetResponse, tags=["Project Source Sync"])
async def update_project_asset_sync_offset(
    project_id: UUID,
    asset_id: UUID,
    request: ProjectAssetSyncUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Persist a user-adjusted sync offset for one screen, camera, or audio source."""
    asset = await db.get(ProjectAsset, asset_id)
    if not asset or asset.project_id != project_id:
        raise HTTPException(404, "Project asset not found")

    project = await _load_project_with_assets(project_id, db)
    _, recommendations = recommend_sync_offsets(project.assets)
    recommendation = next((item for item in recommendations if item.asset_id == str(asset_id)), None)

    asset.sync_offset_seconds = request.sync_offset_seconds
    metadata_json = dict(asset.metadata_json or {})
    source_sync_metadata = dict(metadata_json.get(SYNC_METADATA_KEY) or {})
    source_sync_metadata.update(
        {
            "method": "manual_offset",
            "confidence": 1.0,
            "applied_offset_seconds": request.sync_offset_seconds,
            "user_adjusted": True,
            "applied_by": "user",
            "waveform_sync_ready": True,
            "needs_user_review": False,
        }
    )
    if recommendation is not None:
        source_sync_metadata.update(
            {
                "recommended_offset_seconds": recommendation.recommended_offset_seconds,
                "manual_adjustment_seconds": round(
                    request.sync_offset_seconds - recommendation.recommended_offset_seconds,
                    3,
                ),
            }
        )
    if request.note:
        source_sync_metadata["note"] = request.note
    metadata_json[SYNC_METADATA_KEY] = source_sync_metadata
    asset.metadata_json = metadata_json

    await db.commit()
    await db.refresh(asset)
    return asset


@router.patch("/{project_id}/assets/{asset_id}/metadata", response_model=ProjectAssetResponse, tags=["Project Assets"])
async def update_project_asset_metadata(
    project_id: UUID,
    asset_id: UUID,
    request: ProjectAssetMetadataUpdateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Assign the page range from a shared deck that belongs to this project video."""
    asset = await db.get(ProjectAsset, asset_id)
    if not asset or asset.project_id != project_id:
        raise HTTPException(404, "Project asset not found")
    if not _asset_matches_structure(asset):
        raise HTTPException(400, "Page scope can only be assigned to a slide or PDF structure asset")

    try:
        scope = request.validated_page_scope()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    metadata_json = dict(asset.metadata_json or {})
    user_metadata = dict(metadata_json.get("user_metadata") or {})
    if scope is None:
        user_metadata.pop("slide_page_start", None)
        user_metadata.pop("slide_page_end", None)
    else:
        user_metadata["slide_page_start"], user_metadata["slide_page_end"] = scope
    metadata_json["user_metadata"] = user_metadata
    asset.metadata_json = metadata_json
    await db.commit()
    await db.refresh(asset)
    return asset


@router.get("/{project_id}/assets/{asset_id}/download", tags=["Project Assets"])
async def download_project_asset(
    project_id: UUID,
    asset_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Download or preview an uploaded project asset."""
    asset = await db.get(ProjectAsset, asset_id)
    if not asset or asset.project_id != project_id:
        raise HTTPException(404, "Project asset not found")
    if not asset.file_path or not os.path.exists(asset.file_path):
        raise HTTPException(404, "Project asset file not found")

    return FileResponse(
        path=asset.file_path,
        media_type=asset.mime_type or "application/octet-stream",
        filename=asset.original_filename,
    )


@router.delete("/{project_id}/assets/{asset_id}", tags=["Project Assets"])
async def delete_project_asset(
    project_id: UUID,
    asset_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Delete a project asset record and its stored file."""
    asset = await db.get(ProjectAsset, asset_id)
    if not asset or asset.project_id != project_id:
        raise HTTPException(404, "Project asset not found")

    if asset.file_path and os.path.exists(asset.file_path):
        os.remove(asset.file_path)

    await db.delete(asset)
    await db.commit()
    return {"status": "deleted", "project_id": str(project_id), "asset_id": str(asset_id)}
