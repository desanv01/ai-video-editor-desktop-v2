"""Default provider registry wiring for the current backend."""

from typing import Optional

from providers.openai_compatible import (
    OpenAICompatibleChatProvider,
    OpenAIEmbeddingProvider,
)
from providers.placeholders import (
    ExistingPipelineTranscriptionProvider,
    UnconfiguredLocalRuntimeProvider,
    UnconfiguredVisionProvider,
)
from providers.processing_modes import build_processing_mode_config
from providers.registry import ProviderRegistry

_registry: Optional[ProviderRegistry] = None


def build_provider_registry(settings) -> ProviderRegistry:
    registry = ProviderRegistry()

    registry.register(
        ExistingPipelineTranscriptionProvider(
            provider_id=settings.ASR_PROVIDER.lower(),
            label=f"{settings.ASR_PROVIDER.title()} Transcription",
            provider_name=settings.ASR_PROVIDER.lower(),
            default_model=(
                settings.VOXTRAL_MODEL
                if settings.ASR_PROVIDER.lower() == "voxtral"
                else settings.WHISPER_MODEL
            ),
        ),
        set_default=True,
    )

    registry.register(
        OpenAICompatibleChatProvider(
            provider_id="deepseek-chat",
            label="DeepSeek Chat",
            provider_name="deepseek",
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_BASE_URL,
            default_model=settings.AGENT2_MODEL,
        ),
        set_default=True,
    )

    registry.register(
        OpenAIEmbeddingProvider(
            provider_id="openai-embeddings",
            label="OpenAI Embeddings",
            api_key=settings.OPENAI_API_KEY,
            default_model=settings.EMBEDDING_MODEL,
            default_dimensions=settings.EMBEDDING_DIMENSIONS,
        ),
        set_default=True,
    )

    registry.register(UnconfiguredVisionProvider(), set_default=True)
    registry.register(UnconfiguredLocalRuntimeProvider(), set_default=True)
    registry.set_processing_modes(build_processing_mode_config(settings, registry))

    return registry


def get_provider_registry() -> ProviderRegistry:
    global _registry
    if _registry is None:
        from config import settings

        _registry = build_provider_registry(settings)
    return _registry
