"""
Project-first API routes for source assets and teaching materials.
"""

import logging
import json
import os
import shutil
import uuid
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
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
    ProjectAssetResponse,
    ProjectAssetSyncUpdateRequest,
    ProjectAssetUploadResponse,
    ProjectCreateRequest,
    ProjectDetailResponse,
    ProjectResponse,
    ProjectSourceSyncApplyRequest,
    ProjectSourceSyncAsset,
    ProjectSourceSyncPlanResponse,
    VideoUploadResponse,
)
from services.ffmpeg import ffmpeg_service
from services.source_sync import (
    SYNC_METADATA_KEY,
    build_sync_metadata,
    extract_user_sync_offset,
    merge_sync_metadata,
    recommend_sync_offsets,
)


router = APIRouter(prefix="/projects")
logger = logging.getLogger(__name__)

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
AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
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


async def _media_metadata(file_path: str, asset_type: AssetUploadType) -> dict:
    if asset_type not in {"video", "screen", "camera", "webcam", "phone_camera", "audio"}:
        return {}
    try:
        return await ffmpeg_service.get_video_metadata(file_path)
    except Exception as exc:
        logger.warning("Could not read media metadata for %s: %s", file_path, exc)
        return {}


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
        shutil.copyfileobj(file.file, saved_file)

    file_size = os.path.getsize(file_path)
    max_size_bytes = settings.MAX_VIDEO_SIZE_MB * 1024 * 1024
    if file_size > max_size_bytes:
        os.remove(file_path)
        raise HTTPException(413, f"File too large. Maximum: {settings.MAX_VIDEO_SIZE_MB}MB")

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
    return project


@router.get("", response_model=list[ProjectResponse], tags=["Projects"])
async def list_projects(db: AsyncSession = Depends(get_db)):
    """List project workspaces."""
    result = await db.execute(select(Project).order_by(Project.created_at.desc()))
    return result.scalars().all()


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
        shutil.copyfileobj(file.file, saved_file)

    file_size = os.path.getsize(file_path)
    max_size_bytes = settings.MAX_VIDEO_SIZE_MB * 1024 * 1024
    if file_size > max_size_bytes:
        os.remove(file_path)
        raise HTTPException(413, f"File too large. Maximum: {settings.MAX_VIDEO_SIZE_MB}MB")

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
