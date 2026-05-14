"""Provider placeholders for capabilities that will be implemented in later tasks."""

from providers.interfaces import (
    LocalModelRuntimeProvider,
    LocalRuntimeRequest,
    LocalRuntimeResponse,
    ProviderCapability,
    ProviderHealth,
    ProviderHealthStatus,
    ProviderKind,
    ProviderMetadata,
    TranscriptionProvider,
    TranscriptionRequest,
    TranscriptionResponse,
    VisionProvider,
    VisionRequest,
    VisionResponse,
)


class RegistryPlaceholderProvider:
    def __init__(self, metadata: ProviderMetadata, message: str):
        self._metadata = metadata
        self._message = message

    @property
    def metadata(self) -> ProviderMetadata:
        return self._metadata

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            status=ProviderHealthStatus.NOT_CONFIGURED,
            message=self._message,
        )

    def _raise_not_configured(self) -> None:
        raise RuntimeError(self._message)


class ExistingPipelineTranscriptionProvider(
    RegistryPlaceholderProvider,
    TranscriptionProvider,
):
    """Registry entry for the current transcription pipeline.

    The existing TranscriptionService still owns chunking and Voxtral/Whisper
    fallback for Phase 1 Chat 1. A later routing task can move those calls
    behind this provider without changing the public contract.
    """

    def __init__(
        self,
        *,
        provider_id: str,
        label: str,
        provider_name: str,
        default_model: str,
    ):
        super().__init__(
            ProviderMetadata(
                provider_id=provider_id,
                kind=ProviderKind.TRANSCRIPTION,
                label=label,
                provider_name=provider_name,
                default_model=default_model,
                capabilities=(
                    ProviderCapability("audio_transcription", "Speech-to-text transcription."),
                    ProviderCapability("timestamps", "Word and segment timestamps when available."),
                ),
            ),
            "Transcription routing still uses services.transcription for this phase.",
        )

    async def transcribe(self, request: TranscriptionRequest) -> TranscriptionResponse:
        self._raise_not_configured()


class UnconfiguredVisionProvider(RegistryPlaceholderProvider, VisionProvider):
    def __init__(self):
        super().__init__(
            ProviderMetadata(
                provider_id="vision-unconfigured",
                kind=ProviderKind.VISION,
                label="Vision Provider",
                provider_name="unconfigured",
                capabilities=(
                    ProviderCapability("image_analysis", "Analyze video frames or images."),
                ),
            ),
            "Vision provider is not configured yet.",
        )

    async def analyze(self, request: VisionRequest) -> VisionResponse:
        self._raise_not_configured()


class UnconfiguredLocalRuntimeProvider(
    RegistryPlaceholderProvider,
    LocalModelRuntimeProvider,
):
    def __init__(self):
        super().__init__(
            ProviderMetadata(
                provider_id="local-runtime-unconfigured",
                kind=ProviderKind.LOCAL_RUNTIME,
                label="Local Model Runtime",
                provider_name="unconfigured",
                is_local=True,
                capabilities=(
                    ProviderCapability("local_models", "Run local model operations."),
                ),
            ),
            "Local model runtime is not configured yet.",
        )

    async def run(self, request: LocalRuntimeRequest) -> LocalRuntimeResponse:
        self._raise_not_configured()
