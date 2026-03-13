"""Provider adapter registry and implementations."""

from __future__ import annotations

import httpx

from market_ingestion.infrastructure.adapters.providers.registry import ProviderRegistry


def build_provider_registry(settings: object | None = None) -> ProviderRegistry:
    """Build and return a ProviderRegistry populated with live adapters.

    Concrete adapters are imported lazily to avoid circular imports and to
    allow test code to skip real HTTP clients.
    """
    from market_ingestion.infrastructure.adapters.providers.alpha_vantage import (
        AlphaVantageProviderAdapter,
    )
    from market_ingestion.infrastructure.adapters.providers.eodhd import EODHDProviderAdapter
    from market_ingestion.infrastructure.adapters.providers.polygon import PolygonProviderAdapter
    from market_ingestion.infrastructure.adapters.providers.yahoo import YahooFinanceProviderAdapter

    registry = ProviderRegistry()

    api_key: str = "demo"
    if settings is not None:
        api_key = getattr(settings, "eodhd_api_key", "demo")

    client = httpx.AsyncClient()
    registry.register(EODHDProviderAdapter(api_key=api_key, client=client))
    registry.register(PolygonProviderAdapter())
    registry.register(YahooFinanceProviderAdapter())
    registry.register(AlphaVantageProviderAdapter())
    return registry


__all__ = ["ProviderRegistry", "build_provider_registry"]
