"""Model catalog routes for local AI runtimes."""

from fastapi import APIRouter

from config import settings
from models.schemas import (
    LocalTranscriptionModelCatalogItem,
    LocalTranscriptionModelCatalogResponse,
)
from providers.whisper_cpp import (
    WHISPER_CPP_PROVIDER_ID,
    build_whisper_cpp_model_catalog,
    resolve_whisper_cpp_model_selection,
)

router = APIRouter(tags=["Settings"])


@router.get(
    "/settings/models/local-transcription",
    response_model=LocalTranscriptionModelCatalogResponse,
)
async def get_local_transcription_model_catalog():
    """Return UI-ready local transcription model metadata and status."""
    catalog = build_whisper_cpp_model_catalog(settings)
    selection = resolve_whisper_cpp_model_selection(settings)

    return LocalTranscriptionModelCatalogResponse(
        provider_id=WHISPER_CPP_PROVIDER_ID,
        active_model_id=selection.model_id,
        models=[
            LocalTranscriptionModelCatalogItem(
                model_id=model.model_id,
                provider_id=WHISPER_CPP_PROVIDER_ID,
                tier=model.tier,
                label=model.label,
                expected_filename=model.expected_filename,
                description=model.description,
                size=model.size_label,
                size_mb=model.size_mb,
                speed=model.speed,
                quality=model.quality,
                active=model.active,
                downloaded=model.downloaded,
                file_path=model.file_path,
            )
            for model in catalog
        ],
    )
