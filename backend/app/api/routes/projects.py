"""
Project-first API routes for source assets and teaching materials.
"""

import logging
import os
import shutil
import uuid
from typing import Literal
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
    ProjectAssetKind,
    ProjectAssetRole,
    ProjectAssetStatus,
    ProjectSourceMode,
    ProjectStatus,
)
from models.schemas import (
    ProjectAssetResponse,
    ProjectAssetUploadResponse,
    ProjectCreateRequest,
    ProjectDetailResponse,
    ProjectResponse,
)
from services.ffmpeg import ffmpeg_service


router = APIRouter(prefix="/projects")
logger = logging.getLogger(__name__)

AssetUploadType = Literal["video", "audio", "slides", "notes", "materials"]

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
        "audio": ProjectAssetRole.AUDIO,
        "slides": ProjectAssetRole.SLIDES,
        "notes": ProjectAssetRole.NOTES,
        "materials": ProjectAssetRole.SUPPORTING_MATERIAL,
    }[asset_type]


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
    if asset_type not in {"video", "audio"}:
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

    metadata = await _media_metadata(file_path, asset_type)
    kind = _asset_kind_for_upload(asset_type, file.filename)
    role = _asset_role_for_upload(asset_type)

    if is_primary:
        existing_primary_result = await db.execute(
            select(ProjectAsset).where(
                ProjectAsset.project_id == project_id,
                ProjectAsset.is_primary.is_(True),
            )
        )
        for existing_asset in existing_primary_result.scalars():
            existing_asset.is_primary = False

    metadata_json = {
        "upload_type": asset_type,
        "extension": ext,
        "storage_scope": "project_asset",
    }
    if metadata:
        metadata_json.update(
            {
                "format": metadata.get("format"),
                "resolution": (
                    f"{metadata.get('width')}x{metadata.get('height')}"
                    if metadata.get("width") and metadata.get("height")
                    else None
                ),
                "fps": metadata.get("fps"),
                "video_codec": metadata.get("video_codec"),
                "audio_codec": metadata.get("audio_codec"),
                "audio_sample_rate": metadata.get("audio_sample_rate"),
            }
        )

    asset = ProjectAsset(
        id=asset_id,
        project_id=project_id,
        kind=kind,
        role=role,
        status=ProjectAssetStatus.READY,
        is_primary=is_primary,
        filename=filename,
        original_filename=file.filename or filename,
        file_path=file_path,
        file_size_bytes=file_size,
        mime_type=file.content_type,
        duration_seconds=metadata.get("duration"),
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
        message=f"{asset_type.title()} asset uploaded to project.",
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


@router.post("/{project_id}/assets/upload", response_model=ProjectAssetUploadResponse, tags=["Project Assets"])
async def upload_project_asset(
    project_id: UUID,
    asset_type: AssetUploadType = Form(...),
    is_primary: bool = Form(False),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload a project asset using an explicit asset_type form field."""
    return await _upload_project_asset(project_id, asset_type, file, is_primary, db)


@router.post("/{project_id}/assets/video", response_model=ProjectAssetUploadResponse, tags=["Project Assets"])
async def upload_project_video_asset(
    project_id: UUID,
    is_primary: bool = Form(True),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload a primary or secondary video source for a project."""
    return await _upload_project_asset(project_id, "video", file, is_primary, db)


@router.post("/{project_id}/assets/audio", response_model=ProjectAssetUploadResponse, tags=["Project Assets"])
async def upload_project_audio_asset(
    project_id: UUID,
    is_primary: bool = Form(False),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload a separate audio recording for a project."""
    return await _upload_project_asset(project_id, "audio", file, is_primary, db)


@router.post("/{project_id}/assets/slides", response_model=ProjectAssetUploadResponse, tags=["Project Assets"])
async def upload_project_slide_asset(
    project_id: UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload a slide deck or slide PDF for a project."""
    return await _upload_project_asset(project_id, "slides", file, False, db)


@router.post("/{project_id}/assets/notes", response_model=ProjectAssetUploadResponse, tags=["Project Assets"])
async def upload_project_notes_asset(
    project_id: UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload notes such as PDF, DOCX, TXT, or Markdown."""
    return await _upload_project_asset(project_id, "notes", file, False, db)


@router.post("/{project_id}/assets/materials", response_model=ProjectAssetUploadResponse, tags=["Project Assets"])
async def upload_project_supporting_material_asset(
    project_id: UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload supporting material for later RAG, structure, or evaluation workflows."""
    return await _upload_project_asset(project_id, "materials", file, False, db)


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
