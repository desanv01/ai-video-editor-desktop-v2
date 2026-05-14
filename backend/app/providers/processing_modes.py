"""Processing mode configuration for AI provider routing.

This module is intentionally configuration-only for Phase 1 Chat 2. The
current pipeline keeps using the same default providers until a later routing
task starts honoring these mode choices at runtime.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from providers.interfaces import ProviderKind


class ProcessingMode(str, Enum):
    API = "api"
    LOCAL = "local"
    HYBRID = "hybrid"


DEFAULT_CAPABILITY_MODES: dict[ProviderKind, ProcessingMode] = {
    ProviderKind.TRANSCRIPTION: ProcessingMode.API,
    ProviderKind.CHAT: ProcessingMode.API,
    ProviderKind.EMBEDDING: ProcessingMode.API,
    ProviderKind.VISION: ProcessingMode.API,
    ProviderKind.LOCAL_RUNTIME: ProcessingMode.LOCAL,
}


DEFAULT_HYBRID_FALLBACK_ORDER: dict[ProviderKind, tuple[ProcessingMode, ...]] = {
    ProviderKind.TRANSCRIPTION: (ProcessingMode.LOCAL, ProcessingMode.API),
    ProviderKind.CHAT: (ProcessingMode.API, ProcessingMode.LOCAL),
    ProviderKind.EMBEDDING: (ProcessingMode.API, ProcessingMode.LOCAL),
    ProviderKind.VISION: (ProcessingMode.API, ProcessingMode.LOCAL),
    ProviderKind.LOCAL_RUNTIME: (ProcessingMode.LOCAL,),
}


@dataclass(frozen=True)
class CapabilityModeConfig:
    kind: ProviderKind
    mode: ProcessingMode
    api_provider_id: Optional[str] = None
    local_provider_id: Optional[str] = None
    fallback_enabled: bool = True
    hybrid_fallback_order: tuple[ProcessingMode, ...] = field(default_factory=tuple)

    def mode_order(self) -> tuple[ProcessingMode, ...]:
        if self.mode == ProcessingMode.HYBRID:
            return self.hybrid_fallback_order or DEFAULT_HYBRID_FALLBACK_ORDER[self.kind]
        return (self.mode,)

    def describe(self) -> dict[str, Any]:
        return {
            "capability": self.kind.value,
            "mode": self.mode.value,
            "api_provider_id": self.api_provider_id,
            "local_provider_id": self.local_provider_id,
            "fallback_enabled": self.fallback_enabled,
            "mode_order": [mode.value for mode in self.mode_order()],
        }


@dataclass(frozen=True)
class ProcessingModeConfig:
    default_mode: ProcessingMode = ProcessingMode.HYBRID
    fallback_enabled: bool = True
    capabilities: dict[ProviderKind, CapabilityModeConfig] = field(default_factory=dict)

    def for_kind(self, kind: ProviderKind) -> CapabilityModeConfig:
        if kind in self.capabilities:
            return self.capabilities[kind]

        mode = DEFAULT_CAPABILITY_MODES.get(kind, self.default_mode)
        return CapabilityModeConfig(
            kind=kind,
            mode=mode,
            fallback_enabled=self.fallback_enabled,
            hybrid_fallback_order=DEFAULT_HYBRID_FALLBACK_ORDER.get(kind, (mode,)),
        )

    def describe(self) -> dict[str, Any]:
        return {
            "default_mode": self.default_mode.value,
            "fallback_enabled": self.fallback_enabled,
            "capabilities": {
                kind.value: self.for_kind(kind).describe()
                for kind in ProviderKind
            },
        }


def parse_processing_mode(value: str, *, field_name: str) -> ProcessingMode:
    try:
        return ProcessingMode(value.strip().lower())
    except ValueError as exc:
        valid_modes = ", ".join(mode.value for mode in ProcessingMode)
        raise ValueError(
            f"{field_name} must be one of: {valid_modes}. Received: {value!r}"
        ) from exc


def _setting_mode(settings, field_name: str, default: ProcessingMode) -> ProcessingMode:
    return parse_processing_mode(
        str(getattr(settings, field_name, default.value)),
        field_name=field_name,
    )


def build_processing_mode_config(settings, registry=None) -> ProcessingModeConfig:
    default_mode = _setting_mode(settings, "AI_PROCESSING_MODE", ProcessingMode.HYBRID)
    fallback_enabled = bool(getattr(settings, "AI_PROVIDER_FALLBACK_ENABLED", True))
    mode_fields = {
        ProviderKind.TRANSCRIPTION: "AI_TRANSCRIPTION_MODE",
        ProviderKind.CHAT: "AI_CHAT_MODE",
        ProviderKind.EMBEDDING: "AI_EMBEDDING_MODE",
        ProviderKind.VISION: "AI_VISION_MODE",
        ProviderKind.LOCAL_RUNTIME: "AI_LOCAL_RUNTIME_MODE",
    }

    capabilities: dict[ProviderKind, CapabilityModeConfig] = {}
    for kind, field_name in mode_fields.items():
        mode = _setting_mode(
            settings,
            field_name,
            DEFAULT_CAPABILITY_MODES.get(kind, default_mode),
        )
        capabilities[kind] = CapabilityModeConfig(
            kind=kind,
            mode=mode,
            api_provider_id=(
                registry.default_provider_id(kind)
                if registry and mode in (ProcessingMode.API, ProcessingMode.HYBRID)
                else None
            ),
            local_provider_id=(
                registry.default_provider_id(kind)
                if registry and mode == ProcessingMode.LOCAL
                else None
            ),
            fallback_enabled=fallback_enabled,
            hybrid_fallback_order=DEFAULT_HYBRID_FALLBACK_ORDER.get(kind, (mode,)),
        )

    return ProcessingModeConfig(
        default_mode=default_mode,
        fallback_enabled=fallback_enabled,
        capabilities=capabilities,
    )
