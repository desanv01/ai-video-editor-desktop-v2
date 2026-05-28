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
from providers.whisper_cpp import (
    WhisperCppTranscriptionProvider,
    resolve_whisper_cpp_model_selection,
)

_registry: Optional[ProviderRegistry] = None


def build_provider_registry(settings) -> ProviderRegistry:
    registry = ProviderRegistry()

    default_asr_provider = settings.ASR_PROVIDER.lower()
    for provider_id, label, provider_name, model in (
        ("voxtral", "Voxtral Transcription", "mistral", settings.VOXTRAL_MODEL),
        ("whisper", "Whisper Transcription", "openai", settings.WHISPER_MODEL),
    ):
        registry.register(
            ExistingPipelineTranscriptionProvider(
                provider_id=provider_id,
                label=label,
                provider_name=provider_name,
                default_model=model,
            ),
            set_default=provider_id == default_asr_provider,
        )

    whisper_cpp_selection = resolve_whisper_cpp_model_selection(settings)
    registry.register(
        WhisperCppTranscriptionProvider(
            binary_path=whisper_cpp_selection.binary_path,
            model_path=whisper_cpp_selection.model_path,
            model_id=whisper_cpp_selection.model_id,
            work_dir=getattr(settings, "TEMP_PATH", None),
        ),
        set_default=default_asr_provider == "whisper-cpp",
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


def reset_provider_registry() -> None:
    global _registry
    _registry = None
