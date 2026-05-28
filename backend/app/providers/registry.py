"""Provider registry for AI capability routing."""

from __future__ import annotations

from typing import Optional

from providers.interfaces import AIProvider, ProviderKind
from providers.processing_modes import ProcessingModeConfig


class ProviderRegistry:
    """In-memory registry of AI providers grouped by capability kind."""

    def __init__(self, processing_modes: Optional[ProcessingModeConfig] = None):
        self._providers: dict[ProviderKind, dict[str, AIProvider]] = {
            kind: {} for kind in ProviderKind
        }
        self._defaults: dict[ProviderKind, str] = {}
        self._processing_modes = processing_modes or ProcessingModeConfig()

    def register(
        self,
        provider: AIProvider,
        *,
        set_default: bool = False,
        replace: bool = False,
    ) -> AIProvider:
        metadata = provider.metadata
        providers = self._providers[metadata.kind]
        if metadata.provider_id in providers and not replace:
            raise ValueError(
                f"Provider already registered for {metadata.kind.value}: "
                f"{metadata.provider_id}"
            )

        providers[metadata.provider_id] = provider
        if set_default or metadata.kind not in self._defaults:
            self._defaults[metadata.kind] = metadata.provider_id

        return provider

    def get(
        self,
        kind: ProviderKind,
        provider_id: Optional[str] = None,
    ) -> AIProvider:
        provider_key = provider_id or self._defaults.get(kind)
        if not provider_key:
            raise KeyError(f"No default provider registered for {kind.value}")

        try:
            return self._providers[kind][provider_key]
        except KeyError as exc:
            raise KeyError(
                f"Provider not registered for {kind.value}: {provider_key}"
            ) from exc

    def list(self, kind: Optional[ProviderKind] = None) -> list[AIProvider]:
        if kind:
            return list(self._providers[kind].values())

        providers: list[AIProvider] = []
        for group in self._providers.values():
            providers.extend(group.values())
        return providers

    def default_provider_id(self, kind: ProviderKind) -> Optional[str]:
        return self._defaults.get(kind)

    def set_default(self, kind: ProviderKind, provider_id: str) -> None:
        if provider_id not in self._providers[kind]:
            raise KeyError(f"Provider not registered for {kind.value}: {provider_id}")
        self._defaults[kind] = provider_id

    @property
    def processing_modes(self) -> ProcessingModeConfig:
        return self._processing_modes

    def set_processing_modes(self, processing_modes: ProcessingModeConfig) -> None:
        self._processing_modes = processing_modes

    def processing_mode_for(self, kind: ProviderKind):
        return self._processing_modes.for_kind(kind)

    def describe_processing_modes(self) -> dict:
        return self._processing_modes.describe()

    def describe(self) -> dict[str, list[dict]]:
        """Return serializable registry metadata for diagnostics/settings UI."""
        description: dict[str, list[dict]] = {}
        for kind, providers in self._providers.items():
            mode_config = self._processing_modes.for_kind(kind)
            description[kind.value] = [
                {
                    "provider_id": provider.metadata.provider_id,
                    "label": provider.metadata.label,
                    "provider_name": provider.metadata.provider_name,
                    "default_model": provider.metadata.default_model,
                    "is_local": provider.metadata.is_local,
                    "is_default": self._defaults.get(kind) == provider.metadata.provider_id,
                    "configured_processing_mode": mode_config.mode.value,
                    "capabilities": [
                        {
                            "name": capability.name,
                            "description": capability.description,
                        }
                        for capability in provider.metadata.capabilities
                    ],
                }
                for provider in providers.values()
            ]
        return description
