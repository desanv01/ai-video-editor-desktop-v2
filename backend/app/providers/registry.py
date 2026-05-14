"""Provider registry for AI capability routing."""

from typing import Optional

from providers.interfaces import AIProvider, ProviderKind


class ProviderRegistry:
    """In-memory registry of AI providers grouped by capability kind."""

    def __init__(self):
        self._providers: dict[ProviderKind, dict[str, AIProvider]] = {
            kind: {} for kind in ProviderKind
        }
        self._defaults: dict[ProviderKind, str] = {}

    def register(self, provider: AIProvider, *, set_default: bool = False) -> AIProvider:
        metadata = provider.metadata
        providers = self._providers[metadata.kind]
        if metadata.provider_id in providers:
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

    def describe(self) -> dict[str, list[dict]]:
        """Return serializable registry metadata for diagnostics/settings UI."""
        description: dict[str, list[dict]] = {}
        for kind, providers in self._providers.items():
            description[kind.value] = [
                {
                    "provider_id": provider.metadata.provider_id,
                    "label": provider.metadata.label,
                    "provider_name": provider.metadata.provider_name,
                    "default_model": provider.metadata.default_model,
                    "is_local": provider.metadata.is_local,
                    "is_default": self._defaults.get(kind) == provider.metadata.provider_id,
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
