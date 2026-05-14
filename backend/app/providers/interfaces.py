"""
Typed provider contracts for AI capabilities.

These interfaces define the stable boundary between the processing pipeline and
model backends. Early Phase 1 keeps the existing API behavior, while later tasks
can add routing, user settings, and local adapters behind these same contracts.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


class ProviderKind(str, Enum):
    TRANSCRIPTION = "transcription"
    CHAT = "chat"
    EMBEDDING = "embedding"
    VISION = "vision"
    LOCAL_RUNTIME = "local_runtime"


class ProviderHealthStatus(str, Enum):
    AVAILABLE = "available"
    NOT_CONFIGURED = "not_configured"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class ProviderCapability:
    name: str
    description: str = ""


@dataclass(frozen=True)
class ProviderMetadata:
    provider_id: str
    kind: ProviderKind
    label: str
    provider_name: str
    default_model: Optional[str] = None
    is_local: bool = False
    capabilities: tuple[ProviderCapability, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class ProviderHealth:
    status: ProviderHealthStatus
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChatRequest:
    messages: list[dict[str, Any]]
    model: Optional[str] = None
    temperature: float = 0.3
    max_tokens: int = 4096
    response_format: Optional[dict[str, Any]] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChatResponse:
    text: str
    provider_id: str
    model: str
    raw: Any = None


@dataclass(frozen=True)
class EmbeddingRequest:
    texts: list[str]
    model: Optional[str] = None
    dimensions: Optional[int] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class EmbeddingResponse:
    embeddings: list[list[float]]
    provider_id: str
    model: str
    dimensions: Optional[int] = None
    raw: Any = None


@dataclass(frozen=True)
class TranscriptionRequest:
    audio_path: str
    language: Optional[str] = None
    domain_terms: Optional[list[str]] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TranscriptionResponse:
    transcript: dict[str, Any]
    provider_id: str
    model: Optional[str] = None
    raw: Any = None


@dataclass(frozen=True)
class VisionRequest:
    prompt: str
    image_paths: list[str] = field(default_factory=list)
    model: Optional[str] = None
    max_tokens: int = 2048
    response_format: Optional[dict[str, Any]] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class VisionResponse:
    text: str
    provider_id: str
    model: Optional[str] = None
    raw: Any = None


@dataclass(frozen=True)
class LocalRuntimeRequest:
    operation: str
    payload: dict[str, Any]
    model: Optional[str] = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LocalRuntimeResponse:
    result: dict[str, Any]
    provider_id: str
    model: Optional[str] = None
    raw: Any = None


class AIProvider(ABC):
    @property
    @abstractmethod
    def metadata(self) -> ProviderMetadata:
        """Static provider identity and capability metadata."""

    async def health(self) -> ProviderHealth:
        return ProviderHealth(
            status=ProviderHealthStatus.AVAILABLE,
            message="Provider is configured.",
        )


class TranscriptionProvider(AIProvider):
    @abstractmethod
    async def transcribe(self, request: TranscriptionRequest) -> TranscriptionResponse:
        """Transcribe an audio file into the app's unified transcript format."""


class ChatProvider(AIProvider):
    @abstractmethod
    async def chat(self, request: ChatRequest) -> ChatResponse:
        """Run chat/reasoning completion."""


class EmbeddingProvider(AIProvider):
    @abstractmethod
    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        """Generate embedding vectors for one or more texts."""


class VisionProvider(AIProvider):
    @abstractmethod
    async def analyze(self, request: VisionRequest) -> VisionResponse:
        """Analyze images or video frames."""


class LocalModelRuntimeProvider(AIProvider):
    @abstractmethod
    async def run(self, request: LocalRuntimeRequest) -> LocalRuntimeResponse:
        """Run an operation against a local model runtime."""
