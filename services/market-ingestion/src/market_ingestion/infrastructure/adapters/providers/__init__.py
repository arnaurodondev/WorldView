"""Provider adapter registry and implementations."""

from __future__ import annotations

from typing import Any

import httpx

from market_ingestion.infrastructure.adapters.providers.registry import ProviderRegistry


def _secret_value(raw: Any, default: str = "") -> str:
    """Extract the plain string from a SecretStr or fallback to str()."""
    if hasattr(raw, "get_secret_value"):
        return raw.get_secret_value()  # type: ignore[no-any-return]
    return str(raw) if raw else default


def build_provider_registry(
    settings: object | None = None,
    *,
    http_timeout: float | None = None,
) -> ProviderRegistry:
    """Build and return a ProviderRegistry populated with live adapters.

    Concrete adapters are imported lazily to avoid circular imports and to
    allow test code to skip real HTTP clients.

    Args:
    ----
        settings: Service configuration object (used for API keys/URLs).
        http_timeout: Optional timeout in seconds for ``httpx.AsyncClient``
            instances.  Defaults to httpx's built-in 5 s timeout when *None*.

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
        api_key = _secret_value(getattr(settings, "eodhd_api_key", "demo"), "demo")
        base_url = getattr(settings, "eodhd_base_url", "https://eodhd.com/api")

    client = httpx.AsyncClient(timeout=http_timeout) if http_timeout else httpx.AsyncClient()
    registry.register(EODHDProviderAdapter(api_key=api_key, client=client, base_url=base_url))
    registry.register(YahooFinanceProviderAdapter())

    # Finnhub — registered only when API key is configured
    finnhub_api_key = _secret_value(getattr(settings, "finnhub_api_key", ""))
    if finnhub_api_key:
        from market_ingestion.infrastructure.adapters.providers.finnhub import FinnhubProviderAdapter

        # Finnhub per-request timeout is 30s (in FinnhubProviderAdapter._get),
        # so set the client-level timeout to match to avoid competing defaults.
        finnhub_timeout = http_timeout if http_timeout else 30.0
        finnhub_client = httpx.AsyncClient(timeout=finnhub_timeout)
        registry.register(FinnhubProviderAdapter(api_key=finnhub_api_key, client=finnhub_client))

    return registry


__all__ = ["ProviderRegistry", "build_provider_registry"]
