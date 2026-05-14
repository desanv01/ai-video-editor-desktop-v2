"""OpenAI-compatible provider adapters."""

from typing import Optional

from openai import AsyncOpenAI

from providers.interfaces import (
    ChatProvider,
    ChatRequest,
    ChatResponse,
    EmbeddingProvider,
    EmbeddingRequest,
    EmbeddingResponse,
    ProviderCapability,
    ProviderHealth,
    ProviderHealthStatus,
    ProviderKind,
    ProviderMetadata,
)


class OpenAICompatibleChatProvider(ChatProvider):
    """Chat provider for OpenAI-compatible completion APIs such as DeepSeek."""

    def __init__(
        self,
        *,
        provider_id: str,
        label: str,
        provider_name: str,
        api_key: str,
        default_model: str,
        base_url: Optional[str] = None,
    ):
        self._api_key = api_key
        self._default_model = default_model
        self._client = AsyncOpenAI(
            api_key=api_key or "not-configured",
            base_url=base_url,
        )
        self._metadata = ProviderMetadata(
            provider_id=provider_id,
            kind=ProviderKind.CHAT,
            label=label,
            provider_name=provider_name,
            default_model=default_model,
            capabilities=(
                ProviderCapability("chat", "General chat/reasoning completions."),
                ProviderCapability("json", "Structured JSON response format when supported."),
            ),
        )

    @property
    def metadata(self) -> ProviderMetadata:
        return self._metadata

    async def health(self) -> ProviderHealth:
        if not self._api_key:
            return ProviderHealth(
                status=ProviderHealthStatus.NOT_CONFIGURED,
                message=f"{self.metadata.label} API key is not configured.",
            )
        return await super().health()

    async def chat(self, request: ChatRequest) -> ChatResponse:
        model = request.model or self._default_model
        kwargs = {
            "model": model,
            "messages": request.messages,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.response_format:
            kwargs["response_format"] = request.response_format

        response = await self._client.chat.completions.create(**kwargs)
        return ChatResponse(
            text=response.choices[0].message.content or "",
            provider_id=self.metadata.provider_id,
            model=model,
            raw=response,
        )


class OpenAIEmbeddingProvider(EmbeddingProvider):
    """Embedding provider backed by OpenAI's embedding API."""

    def __init__(
        self,
        *,
        provider_id: str,
        label: str,
        api_key: str,
        default_model: str,
        default_dimensions: int,
    ):
        self._api_key = api_key
        self._default_model = default_model
        self._default_dimensions = default_dimensions
        self._client = AsyncOpenAI(api_key=api_key or "not-configured")
        self._metadata = ProviderMetadata(
            provider_id=provider_id,
            kind=ProviderKind.EMBEDDING,
            label=label,
            provider_name="openai",
            default_model=default_model,
            capabilities=(
                ProviderCapability("embed", "Text embedding vectors."),
                ProviderCapability("batching", "Multiple texts per embedding call."),
            ),
        )

    @property
    def metadata(self) -> ProviderMetadata:
        return self._metadata

    async def health(self) -> ProviderHealth:
        if not self._api_key:
            return ProviderHealth(
                status=ProviderHealthStatus.NOT_CONFIGURED,
                message="OpenAI API key is not configured.",
            )
        return await super().health()

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        model = request.model or self._default_model
        dimensions = request.dimensions or self._default_dimensions
        response = await self._client.embeddings.create(
            model=model,
            input=request.texts,
            dimensions=dimensions,
        )
        return EmbeddingResponse(
            embeddings=[item.embedding for item in response.data],
            provider_id=self.metadata.provider_id,
            model=model,
            dimensions=dimensions,
            raw=response,
        )
