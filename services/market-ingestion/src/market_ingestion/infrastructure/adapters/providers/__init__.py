"""Provider adapter registry and implementations."""

from __future__ import annotations

import httpx

from market_ingestion.infrastructure.adapters.providers.registry import ProviderRegistry


def build_provider_registry(settings: object | None = None) -> ProviderRegistry:
    """Build and return a ProviderRegistry populated with live adapters.

    Concrete adapters are imported lazily to avoid circular imports and to
    allow test code to skip real HTTP clients.

    NOTE: Polygon and AlphaVantage are intentionally NOT registered (D-006).
    Their stub adapters raise confusing errors; they will be re-added when
    real implementations are complete.
    """
    from market_ingestion.infrastructure.adapters.providers.eodhd import EODHDProviderAdapter
    from market_ingestion.infrastructure.adapters.providers.yahoo import YahooFinanceProviderAdapter

    registry = ProviderRegistry()

    api_key: str = "demo"
    base_url: str = "https://eodhd.com/api"
    if settings is not None:
        api_key = getattr(settings, "eodhd_api_key", "demo")
        base_url = getattr(settings, "eodhd_base_url", "https://eodhd.com/api")

    client = httpx.AsyncClient()
    registry.register(EODHDProviderAdapter(api_key=api_key, client=client, base_url=base_url))
    registry.register(YahooFinanceProviderAdapter())
    return registry


__all__ = ["ProviderRegistry", "build_provider_registry"]
