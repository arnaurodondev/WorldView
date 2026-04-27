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

    # Alpaca — registered when both API key and secret key are configured.
    # Alpaca provides free intraday OHLCV bars (IEX feed, 15-min delayed).
    alpaca_api_key_raw = getattr(settings, "alpaca_api_key", None)
    alpaca_secret_key_raw = getattr(settings, "alpaca_secret_key", None)
    alpaca_api_key_val = _secret_value(alpaca_api_key_raw)
    alpaca_secret_key_val = _secret_value(alpaca_secret_key_raw)
    if alpaca_api_key_val and alpaca_secret_key_val:
        from pydantic import SecretStr

        from market_ingestion.infrastructure.adapters.providers.alpaca import AlpacaProviderAdapter

        alpaca_timeout = http_timeout if http_timeout else 30.0
        alpaca_client = httpx.AsyncClient(timeout=alpaca_timeout)
        registry.register(
            AlpacaProviderAdapter(
                api_key=SecretStr(alpaca_api_key_val),
                secret_key=SecretStr(alpaca_secret_key_val),
                client=alpaca_client,
                base_url=getattr(settings, "alpaca_base_url", "https://data.alpaca.markets"),
                feed=getattr(settings, "alpaca_feed", "iex"),
            )
        )

    # Polygon — registered when API key is configured.
    # Polygon provides single-ticker OHLCV bars; free tier is 5 req/min.
    polygon_api_key_raw = getattr(settings, "polygon_api_key", None)
    polygon_api_key_val = _secret_value(polygon_api_key_raw)
    if polygon_api_key_val:
        from pydantic import SecretStr as _SecretStr

        from market_ingestion.infrastructure.adapters.providers.polygon import PolygonProviderAdapter

        polygon_timeout = http_timeout if http_timeout else 30.0
        polygon_client = httpx.AsyncClient(timeout=polygon_timeout)
        registry.register(
            PolygonProviderAdapter(
                api_key=_SecretStr(polygon_api_key_val),
                client=polygon_client,
                base_url=getattr(settings, "polygon_base_url", "https://api.polygon.io"),
            )
        )

    return registry


__all__ = ["ProviderRegistry", "build_provider_registry"]
