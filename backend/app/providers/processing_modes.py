"""Processing mode configuration for AI provider routing.

This module is intentionally configuration-only for Phase 1 Chat 2. The
current pipeline keeps using the same default providers until a later routing
task starts honoring these mode choices at runtime.
"""

import json
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


def _setting_provider_id(settings, field_name: str) -> Optional[str]:
    value = getattr(settings, field_name, None)
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _setting_mode_order(
    settings,
    field_name: str,
    default: tuple[ProcessingMode, ...],
) -> tuple[ProcessingMode, ...]:
    value = getattr(settings, field_name, None)
    if not value:
        return default

    if isinstance(value, (list, tuple)):
        raw_modes = [str(item) for item in value]
    else:
        text = str(value).strip()
        if not text:
            return default
        if text.startswith("["):
            try:
                parsed = [str(item) for item in json.loads(text)]
            except Exception as exc:
                raise ValueError(f"{field_name} must be a list of processing modes") from exc
            raw_modes = parsed
        else:
            raw_modes = [item.strip() for item in text.split(",") if item.strip()]

    if not raw_modes:
        return default

    return tuple(
        parse_processing_mode(mode, field_name=field_name)
        for mode in raw_modes
    )


def _setting_fallback_enabled(settings, field_name: str, default: bool) -> bool:
    value = getattr(settings, field_name, None)
    return default if value is None else bool(value)


def _provider_id_for_kind(registry, kind: ProviderKind, *, is_local: bool) -> Optional[str]:
    if not registry:
        return None

    default_id = registry.default_provider_id(kind)
    if default_id:
        default_provider = registry.get(kind, default_id)
        if default_provider.metadata.is_local == is_local:
            return default_id

    for provider in registry.list(kind):
        if provider.metadata.is_local == is_local:
            return provider.metadata.provider_id
    return None


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
    provider_id_fields = {
        ProviderKind.TRANSCRIPTION: (
            "AI_TRANSCRIPTION_API_PROVIDER_ID",
            "AI_TRANSCRIPTION_LOCAL_PROVIDER_ID",
        ),
    }
    fallback_fields = {
        ProviderKind.TRANSCRIPTION: "AI_TRANSCRIPTION_FALLBACK_ENABLED",
    }
    hybrid_order_fields = {
        ProviderKind.TRANSCRIPTION: "AI_TRANSCRIPTION_HYBRID_FALLBACK_ORDER",
    }

    capabilities: dict[ProviderKind, CapabilityModeConfig] = {}
    for kind, field_name in mode_fields.items():
        mode = _setting_mode(
            settings,
            field_name,
            DEFAULT_CAPABILITY_MODES.get(kind, default_mode),
        )
        api_provider_field, local_provider_field = provider_id_fields.get(
            kind,
            ("", ""),
        )
        configured_api_provider_id = (
            _setting_provider_id(settings, api_provider_field)
            if api_provider_field
            else None
        )
        configured_local_provider_id = (
            _setting_provider_id(settings, local_provider_field)
            if local_provider_field
            else None
        )
        fallback_for_kind = _setting_fallback_enabled(
            settings,
            fallback_fields.get(kind, ""),
            fallback_enabled,
        )
        default_order = DEFAULT_HYBRID_FALLBACK_ORDER.get(kind, (mode,))
        hybrid_fallback_order = _setting_mode_order(
            settings,
            hybrid_order_fields.get(kind, ""),
            default_order,
        )
        capabilities[kind] = CapabilityModeConfig(
            kind=kind,
            mode=mode,
            api_provider_id=(
                configured_api_provider_id
                or _provider_id_for_kind(registry, kind, is_local=False)
                if registry and mode in (ProcessingMode.API, ProcessingMode.HYBRID)
                else None
            ),
            local_provider_id=(
                configured_local_provider_id
                or _provider_id_for_kind(registry, kind, is_local=True)
                if registry and mode in (ProcessingMode.LOCAL, ProcessingMode.HYBRID)
                else None
            ),
            fallback_enabled=fallback_for_kind,
            hybrid_fallback_order=hybrid_fallback_order,
        )

    return ProcessingModeConfig(
        default_mode=default_mode,
        fallback_enabled=fallback_enabled,
        capabilities=capabilities,
    )
