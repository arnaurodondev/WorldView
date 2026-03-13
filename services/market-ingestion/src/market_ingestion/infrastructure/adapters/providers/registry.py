"""Provider registry — maps Provider enum values to ProviderAdapter instances."""

from __future__ import annotations

from typing import TYPE_CHECKING

from market_ingestion.domain.errors import ProviderUnavailable

if TYPE_CHECKING:
    from market_ingestion.application.ports.adapters import ProviderAdapter
    from market_ingestion.domain.enums import Provider


class ProviderRegistry:
    """Registry mapping Provider enum values to ProviderAdapter instances.

    Adapters are registered at service startup and looked up by use cases
    at execution time.

    Usage::

        registry = ProviderRegistry()
        registry.register(EODHDProviderAdapter(api_key=..., client=...))
        adapter = registry.get(Provider.EODHD)
    """

    def __init__(self) -> None:
        self._adapters: dict[str, ProviderAdapter] = {}

    def register(self, adapter: ProviderAdapter) -> None:
        """Register a provider adapter."""
        self._adapters[adapter.provider.value] = adapter

    def get(self, provider: Provider) -> ProviderAdapter:
        """Return the adapter for *provider*.

        Raises:
            ProviderUnavailable: if no adapter is registered for the provider.
        """
        adapter = self._adapters.get(provider.value)
        if adapter is None:
            raise ProviderUnavailable(f"No adapter registered for provider {provider!r}")
        return adapter

    def all_providers(self) -> list[str]:
        """Return a list of all registered provider values."""
        return list(self._adapters.keys())
