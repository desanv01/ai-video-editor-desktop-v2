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

    # DeepSeek V4 Flash — fast reasoning (Agents 2, 3)
    registry.register(
        OpenAICompatibleChatProvider(
            provider_id="deepseek-v4-flash",
            label="DeepSeek V4 Flash",
            provider_name="deepseek",
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_BASE_URL,
            default_model=settings.AGENT2_MODEL,
        ),
        set_default=True,
    )

    # DeepSeek V4 Pro — strongest reasoning (Agent 5)
    registry.register(
        OpenAICompatibleChatProvider(
            provider_id="deepseek-v4-pro",
            label="DeepSeek V4 Pro",
            provider_name="deepseek",
            api_key=settings.DEEPSEEK_API_KEY,
            base_url=settings.DEEPSEEK_BASE_URL,
            default_model=settings.AGENT5_MODEL,  # deepseek-v4-pro from .env
        ),
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

    # Alibaba Qwen 3.7 Plus — vision model (not default chat provider)
    registry.register(
        OpenAICompatibleChatProvider(
            provider_id="qwen-3.7-plus",
            label="Qwen 3.7 Plus (Alibaba)",
            provider_name="alibaba",
            api_key=settings.ALIBABA_API_KEY,
            base_url=settings.ALIBABA_BASE_URL,
            default_model="qwen3.7-plus-2026-05-26",
        ),
    )

    # Unconfigured vision fallback — replaced when a real vision provider is used
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
