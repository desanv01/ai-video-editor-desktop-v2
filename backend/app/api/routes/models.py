"""Model catalog routes for local AI runtimes."""

import asyncio
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from db.database import get_db
from models.schemas import (
    LocalTranscriptionModelCatalogItem,
    LocalTranscriptionModelCatalogResponse,
    LocalTranscriptionModelDownloadRequest,
    LocalTranscriptionModelDownloadResponse,
    LocalTranscriptionModelRemoveResponse,
)
from providers.whisper_cpp import (
    WHISPER_CPP_PROVIDER_ID,
    build_whisper_cpp_model_catalog,
    resolve_whisper_cpp_runtime_status,
    resolve_whisper_cpp_model_selection,
)
from services.app_settings import load_and_apply_persisted_ai_settings
from services.local_transcription_models import local_transcription_model_service

router = APIRouter(tags=["Settings"])


@router.get(
    "/settings/models/local-transcription",
    response_model=LocalTranscriptionModelCatalogResponse,
)
async def get_local_transcription_model_catalog(db: AsyncSession = Depends(get_db)):
    """Return UI-ready local transcription model metadata and status."""
    await load_and_apply_persisted_ai_settings(db)
    if settings.is_native_desktop:
        from desktop_native.model_manager import native_catalog_snapshot
        from desktop_native.model_store import ModelStoreError
        try:
            return LocalTranscriptionModelCatalogResponse(**native_catalog_snapshot(settings))
        except (ModelStoreError, OSError, ValueError) as exc:
            # A missing mandatory bundle keeps its honest repair catalog visible.
            from desktop_native.model_catalog import lookup
            models = []
            for model in build_whisper_cpp_model_catalog(settings):
                spec = lookup(model.model_id)
                models.append(LocalTranscriptionModelCatalogItem(
                    model_id=model.model_id, tier=model.tier, label=model.label,
                    expected_filename=spec.filename, download_url=spec.url,
                    description=model.description, size=model.size_label, size_mb=model.size_mb,
                    speed=model.speed, quality=model.quality, size_bytes=spec.size_bytes,
                    sha256=spec.sha256, bundled=model.model_id == "small", downloaded=False,
                    can_download=False, can_remove=False, active=model.model_id == "small"))
            return LocalTranscriptionModelCatalogResponse(native=True, active_model_id="small",
                runtime_configured=False, runtime_status="missing", runtime_message=f"Prepare or repair Whisper: {exc}", models=models)
    catalog = build_whisper_cpp_model_catalog(settings)
    selection = resolve_whisper_cpp_model_selection(settings)
    runtime_status = resolve_whisper_cpp_runtime_status(settings)

    return LocalTranscriptionModelCatalogResponse(
        provider_id=WHISPER_CPP_PROVIDER_ID,
        active_model_id=selection.model_id,
        runtime_configured=runtime_status.configured,
        runtime_status="ready" if runtime_status.configured else "missing",
        runtime_message=runtime_status.message,
        runtime_binary_path=runtime_status.binary_path or None,
        models=[
            LocalTranscriptionModelCatalogItem(
                model_id=model.model_id,
                provider_id=WHISPER_CPP_PROVIDER_ID,
                tier=model.tier,
                label=model.label,
                expected_filename=model.expected_filename,
                download_url=model.download_url,
                description=model.description,
                size=model.size_label,
                size_mb=model.size_mb,
                speed=model.speed,
                quality=model.quality,
                active=model.active,
                downloaded=model.downloaded,
                status=_model_status(model.model_id, model.downloaded),
                can_download=_can_download(model.model_id, model.downloaded),
                can_remove=_can_remove(model.model_id, model.downloaded),
                download_bytes_downloaded=_download_bytes(model.model_id),
                download_total_bytes=_download_total_bytes(model.model_id),
                download_progress_percent=_download_progress(model.model_id),
                download_speed_bytes_per_second=_download_speed(model.model_id),
                download_eta_seconds=_download_eta(model.model_id),
                file_path=model.file_path,
            )
            for model in catalog
        ],
    )


@router.post(
    "/settings/models/local-transcription/{model_id}/download",
    response_model=LocalTranscriptionModelDownloadResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def download_local_transcription_model(
    model_id: str,
    request: LocalTranscriptionModelDownloadRequest | None = None,
):
    """Start or resume a managed local transcription model download."""
    if settings.is_native_desktop:
        store = _native_store(model_id)
        try:
            job = store.start_download(model_id, make_active=(request or LocalTranscriptionModelDownloadRequest()).make_active)
        except (RuntimeError, OSError, ValueError) as exc:
            raise HTTPException(409, str(exc)) from exc
        return _native_download_response(job)
    download_request = request or LocalTranscriptionModelDownloadRequest()
    job = local_transcription_model_service.start_download(
        model_id,
        activate_on_complete=download_request.make_active,
    )
    return _download_response(job)


@router.get(
    "/settings/models/local-transcription/{model_id}/download",
    response_model=LocalTranscriptionModelDownloadResponse,
)
async def get_local_transcription_model_download(model_id: str):
    """Return current model download progress for UI polling."""
    if settings.is_native_desktop:
        job = _native_store(model_id).get_job(model_id)
        if job is None:
            raise HTTPException(404, f"No native model job for '{model_id}'")
        return _native_download_response(job)
    job = local_transcription_model_service.get_job(model_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No download job found for local transcription model '{model_id}'.",
        )
    return _download_response(job)


@router.delete(
    "/settings/models/local-transcription/{model_id}",
    response_model=LocalTranscriptionModelRemoveResponse,
)
async def remove_local_transcription_model(model_id: str):
    """Remove a managed local transcription model file if it is present."""
    if settings.is_native_desktop:
        store = _native_store(model_id)
        try:
            await asyncio.to_thread(store.remove, model_id)
            from desktop_native.model_manager import apply_native_selection
            from services.app_settings import reset_provider_registry_cache
            apply_native_selection(settings)
            reset_provider_registry_cache()
        except (RuntimeError, OSError, ValueError) as exc:
            raise HTTPException(409, str(exc)) from exc
        return LocalTranscriptionModelRemoveResponse(model_id=model_id, removed=True,
            file_path=None, message="Optional model removed; protected small remains available.")
    try:
        result = local_transcription_model_service.remove_model(model_id)
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    return LocalTranscriptionModelRemoveResponse(
        provider_id=result.provider_id,
        model_id=result.model_id,
        removed=result.removed,
        file_path=result.file_path,
        message=result.message,
    )


def _model_status(model_id: str, downloaded: bool) -> str:
    if settings.is_native_desktop:
        return "downloaded" if downloaded else "not_downloaded"
    job = local_transcription_model_service.get_job(model_id)
    if job and job.status in {"queued", "downloading", "failed"}:
        return job.status
    return "downloaded" if downloaded else "not_downloaded"


def _can_download(model_id: str, downloaded: bool) -> bool:
    if settings.is_native_desktop:
        return False
    job = local_transcription_model_service.get_job(model_id)
    if job and job.status in {"queued", "downloading"}:
        return False
    return not downloaded


def _can_remove(model_id: str, downloaded: bool) -> bool:
    if settings.is_native_desktop:
        return False
    job = local_transcription_model_service.get_job(model_id)
    return downloaded and not (job and job.status in {"queued", "downloading"})


def _download_progress(model_id: str) -> float | None:
    if settings.is_native_desktop:
        return None
    job = local_transcription_model_service.get_job(model_id)
    if not job or job.status not in {"queued", "downloading"}:
        return None
    return job.progress_percent


def _download_bytes(model_id: str) -> int:
    if settings.is_native_desktop:
        return 0
    job = local_transcription_model_service.get_job(model_id)
    if not job or job.status not in {"queued", "downloading"}:
        return 0
    return job.bytes_downloaded


def _download_total_bytes(model_id: str) -> int | None:
    if settings.is_native_desktop:
        return None
    job = local_transcription_model_service.get_job(model_id)
    if not job or job.status not in {"queued", "downloading"}:
        return None
    return job.total_bytes


def _download_speed(model_id: str) -> float | None:
    if settings.is_native_desktop:
        return None
    job = local_transcription_model_service.get_job(model_id)
    if not job or job.status not in {"queued", "downloading"}:
        return None
    return job.speed_bytes_per_second


def _download_eta(model_id: str) -> float | None:
    if settings.is_native_desktop:
        return None
    job = local_transcription_model_service.get_job(model_id)
    if not job or job.status not in {"queued", "downloading"}:
        return None
    return job.eta_seconds


def _download_response(job) -> LocalTranscriptionModelDownloadResponse:
    selection = resolve_whisper_cpp_model_selection(settings)
    return LocalTranscriptionModelDownloadResponse(
        job_id=job.job_id,
        provider_id=job.provider_id,
        model_id=job.model_id,
        status=job.status,
        file_path=job.file_path,
        download_url=job.download_url,
        total_bytes=job.total_bytes,
        bytes_downloaded=job.bytes_downloaded,
        progress_percent=job.progress_percent,
        speed_bytes_per_second=job.speed_bytes_per_second,
        eta_seconds=job.eta_seconds,
        message=job.message,
        error=job.error,
        active=selection.model_id == job.model_id,
    )


def _native_store(model_id):
    from desktop_native.model_catalog import lookup
    from desktop_native.model_manager import get_native_model_store
    try:
        lookup(model_id)
    except ValueError as exc:
        raise HTTPException(404, str(exc)) from exc
    try:
        return get_native_model_store(settings)
    except (RuntimeError, OSError, ValueError) as exc:
        raise HTTPException(409, f"Prepare or repair Whisper: {exc}") from exc


def _native_download_response(job):
    return LocalTranscriptionModelDownloadResponse(
        job_id=job["id"], model_id=job["model_id"], status=job["status"],
        file_path=job["file_path"], download_url=job["download_url"],
        total_bytes=job["total_bytes"], bytes_downloaded=job["bytes_downloaded"],
        progress_percent=job["progress"] * 100, message=job["message"],
        error=job["error"], active=job["active"])


@router.post("/settings/models/local-transcription/{model_id}/cancel",
             response_model=LocalTranscriptionModelDownloadResponse)
async def cancel_native_model_download(model_id: str):
    if not settings.is_native_desktop:
        raise HTTPException(409, "Model cancellation is available in the native Desktop model manager")
    store = _native_store(model_id)
    job = store.cancel(model_id)
    if job is None:
        raise HTTPException(404, f"No native model job for '{model_id}'")
    return _native_download_response(job)


@router.post("/settings/models/local-transcription/{model_id}/activate")
async def activate_native_model(model_id: str):
    if not settings.is_native_desktop:
        raise HTTPException(409, "Use legacy transcription settings to select a local model")
    store = _native_store(model_id)
    from desktop_native.model_store import _Paused
    try:
        selection = await asyncio.to_thread(store.activate, model_id)
        from desktop_native.model_manager import apply_native_selection
        from services.app_settings import reset_provider_registry_cache
        apply_native_selection(settings)
        reset_provider_registry_cache()
        return selection
    except _Paused as exc:
        raise HTTPException(409, "Model verification/activation was paused; the retained file can be verified later") from exc
    except (RuntimeError, OSError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc
