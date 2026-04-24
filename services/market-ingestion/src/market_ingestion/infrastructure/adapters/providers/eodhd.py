"""EODHDProviderAdapter — fetches market data from the EOD Historical Data API."""

from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar, cast
from urllib.parse import urlparse

from market_ingestion.application.ports.adapters import ProviderAdapter, ProviderFetchResult
from market_ingestion.domain.enums import DatasetType, Provider
from market_ingestion.domain.errors import (
    ProviderAuthError,
    ProviderDataError,
    ProviderRateLimited,
    ProviderUnavailable,
)
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    import httpx

logger = get_logger(__name__)


def _endpoint_slug(url: str) -> str:
    """Extract a safe endpoint label for metrics/logs (no query params, no secrets).

    Examples:
        "https://eodhd.com/api/real-time/AAPL.US" → "real-time"
        "https://eodhd.com/api/eod/MSFT.US"       → "eod"
        "https://eodhd.com/api/fundamentals/TSLA"  → "fundamentals"
    """
    path = urlparse(url).path
    # Split on "/" and take the first non-empty segment after "api".
    segments = [p for p in path.split("/") if p and p != "api"]
    return segments[0] if segments else "unknown"


def _parse_retry_after(header_value: str | None) -> float | None:
    """Parse a ``Retry-After`` HTTP header value into seconds.

    Supports two formats defined in RFC 7231 §7.1.3:
    - Integer delta-seconds: ``"120"``
    - HTTP-date: ``"Wed, 01 Jan 2026 12:00:00 GMT"``

    Returns:
        Seconds to wait (≥ 0.0), or ``None`` if the header is absent or
        unparseable.  Does NOT clamp to a maximum — callers apply their own cap.
    """
    if header_value is None:
        return None
    # Try integer/float delta-seconds first (most common).
    try:
        return max(0.0, float(header_value.strip()))
    except ValueError:
        pass
    # Try HTTP-date format.
    from email.utils import parsedate_to_datetime

    try:
        target = parsedate_to_datetime(header_value)
        delta = (target - datetime.now(tz=UTC)).total_seconds()
        return max(0.0, delta)
    except Exception:
        return None


_TIMEFRAME_MAP = {
    "1m": "1m",
    "5m": "5m",
    "1h": "1h",
    "1d": "d",
    "1w": "w",
    "1mo": "m",
    "1M": "m",
}


class EODHDProviderAdapter(ProviderAdapter):
    """Fetches OHLCV, quotes, and fundamentals from the EODHD (EOD Historical Data) API.

    All HTTP errors are mapped to domain errors:
    - 401/403 → ProviderAuthError
    - 429     → ProviderRateLimited
    - 5xx     → ProviderUnavailable
    - Bad JSON / missing fields → ProviderDataError
    """

    def __init__(self, api_key: str, client: httpx.AsyncClient, base_url: str = "https://eodhd.com/api") -> None:
        self._api_key = api_key
        self._client = client
        self._base_url = base_url

    _INTRADAY_INTERVAL_MAP: ClassVar[dict[str, str]] = {"1m": "1m", "5m": "5m", "1h": "1h"}

    _YIELD_SERIES_MAP: ClassVar[dict[str, str]] = {
        "UST.yield": "ust/yield-rates",
        "UST.bill": "ust/bill-rates",
        "UST.longterm": "ust/long-term-rates",
    }

    @property
    def provider(self) -> Provider:
        return Provider.EODHD

    # -------------------------------------------------------------------------
    # Public interface
    # -------------------------------------------------------------------------

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start: datetime | None = None,
        end: datetime | None = None,
        exchange: str | None = None,
    ) -> ProviderFetchResult:
        """Fetch OHLCV bars for *symbol* over [*start*, *end*]."""
        ticker = _build_ticker(symbol, exchange)
        eodhd_period = _TIMEFRAME_MAP.get(timeframe, "d")
        params: dict[str, Any] = {
            "api_token": self._api_key,
            "fmt": "json",
            "period": eodhd_period,
        }
        if start:
            params["from"] = start.strftime("%Y-%m-%d")
        if end:
            params["to"] = end.strftime("%Y-%m-%d")

        url = f"{self._base_url}/eod/{ticker}"
        t0 = time.monotonic()
        raw = await self._get(url, params)
        duration_ms = int((time.monotonic() - t0) * 1000)

        return ProviderFetchResult(
            provider=Provider.EODHD,
            dataset_type=DatasetType.OHLCV,
            symbol=symbol,
            raw_data=raw,
            content_type="application/json",
            fetched_at=datetime.now(tz=UTC),
            duration_ms=duration_ms,
            range_start=start,
            range_end=end,
        )

    async def fetch_quotes(
        self,
        symbol: str,
        exchange: str | None = None,
    ) -> ProviderFetchResult:
        """Fetch real-time quote for *symbol*."""
        ticker = _build_ticker(symbol, exchange)
        params = {"api_token": self._api_key, "fmt": "json"}
        url = f"{self._base_url}/real-time/{ticker}"

        t0 = time.monotonic()
        raw = await self._get(url, params)
        duration_ms = int((time.monotonic() - t0) * 1000)

        return ProviderFetchResult(
            provider=Provider.EODHD,
            dataset_type=DatasetType.QUOTES,
            symbol=symbol,
            raw_data=raw,
            content_type="application/json",
            fetched_at=datetime.now(tz=UTC),
            duration_ms=duration_ms,
        )

    async def fetch_fundamentals(
        self,
        symbol: str,
        variant: str = "annual",
        exchange: str | None = None,
    ) -> ProviderFetchResult:
        """Fetch full company fundamentals for *symbol*.

        Fetches the complete EODHD response (no section filter) so all sections
        (Income_Statement, Balance_Sheet, Technicals, AnalystRatings, etc.) are
        available for the canonical mapper.  ``variant`` is stored in metadata
        but does not restrict which sections are fetched.
        """
        ticker = _build_ticker(symbol, exchange)
        params: dict = {
            "api_token": self._api_key,
            "fmt": "json",
        }
        url = f"{self._base_url}/fundamentals/{ticker}"

        t0 = time.monotonic()
        raw = await self._get(url, params)
        duration_ms = int((time.monotonic() - t0) * 1000)

        return ProviderFetchResult(
            provider=Provider.EODHD,
            dataset_type=DatasetType.FUNDAMENTALS,
            symbol=symbol,
            raw_data=raw,
            content_type="application/json",
            fetched_at=datetime.now(tz=UTC),
            duration_ms=duration_ms,
            provider_metadata={"variant": variant},
        )

    async def health_check(self) -> bool:
        """Verify the API key is valid by hitting the exchange list endpoint."""
        try:
            params = {"api_token": self._api_key, "fmt": "json"}
            await self._get(f"{self._base_url}/exchanges-list", params)
            return True
        except (ProviderAuthError, ProviderUnavailable, ProviderRateLimited):
            return False

    # -------------------------------------------------------------------------
    # Part B — additional endpoints
    # -------------------------------------------------------------------------

    async def fetch_intraday(
        self,
        symbol: str,
        interval: str,
        from_ts: int | None = None,
        to_ts: int | None = None,
        exchange: str | None = None,
    ) -> ProviderFetchResult:
        """Fetch intraday bars for *symbol* at the given *interval*."""
        ticker = _build_ticker(symbol, exchange)
        eodhd_interval = self._INTRADAY_INTERVAL_MAP.get(interval, interval)
        params: dict[str, Any] = {
            "api_token": self._api_key,
            "fmt": "json",
            "interval": eodhd_interval,
        }
        if from_ts is not None:
            params["from"] = from_ts
        if to_ts is not None:
            params["to"] = to_ts

        url = f"{self._base_url}/intraday/{ticker}"
        t0 = time.monotonic()
        raw = await self._get(url, params)
        duration_ms = int((time.monotonic() - t0) * 1000)

        return ProviderFetchResult(
            provider=Provider.EODHD,
            dataset_type=DatasetType.OHLCV,
            symbol=symbol,
            raw_data=raw,
            content_type="application/json",
            fetched_at=datetime.now(tz=UTC),
            duration_ms=duration_ms,
            provider_metadata={"interval": eodhd_interval},
        )

    async def fetch_earnings_calendar(
        self,
        from_date: str,
        to_date: str,
        symbols: list[str] | None = None,
    ) -> ProviderFetchResult:
        """Fetch earnings calendar events over [*from_date*, *to_date*]."""
        params: dict[str, Any] = {
            "api_token": self._api_key,
            "fmt": "json",
            "from": from_date,
            "to": to_date,
        }
        if symbols:
            params["symbols"] = ",".join(symbols)

        url = f"{self._base_url}/calendar/earnings"
        t0 = time.monotonic()
        raw = await self._get(url, params)
        duration_ms = int((time.monotonic() - t0) * 1000)

        return ProviderFetchResult(
            provider=Provider.EODHD,
            dataset_type=DatasetType.EARNINGS_CALENDAR,
            symbol="CALENDAR",
            raw_data=raw,
            content_type="application/json",
            fetched_at=datetime.now(tz=UTC),
            duration_ms=duration_ms,
        )

    async def fetch_economic_events(
        self,
        from_date: str,
        to_date: str,
        country: str = "USA",
        comparison: str | None = None,
        limit: int = 1000,
        offset: int = 0,
    ) -> ProviderFetchResult:
        """Fetch economic events over [*from_date*, *to_date*] for *country*."""
        params: dict[str, Any] = {
            "api_token": self._api_key,
            "fmt": "json",
            "from": from_date,
            "to": to_date,
            "country": country,
            "limit": limit,
            "offset": offset,
        }
        if comparison:
            params["comparison"] = comparison

        url = f"{self._base_url}/economic-events"
        t0 = time.monotonic()
        raw = await self._get(url, params)
        duration_ms = int((time.monotonic() - t0) * 1000)

        return ProviderFetchResult(
            provider=Provider.EODHD,
            dataset_type=DatasetType.ECONOMIC_EVENTS,
            symbol=country,
            raw_data=raw,
            content_type="application/json",
            fetched_at=datetime.now(tz=UTC),
            duration_ms=duration_ms,
        )

    async def fetch_macro_indicator(self, symbol: str) -> ProviderFetchResult:
        """Fetch a macro indicator.

        *symbol* encodes ``COUNTRY.indicator`` (e.g. ``USA.gdp_current_usd``).
        """
        country, _, indicator = symbol.partition(".")
        params: dict[str, Any] = {
            "api_token": self._api_key,
            "fmt": "json",
            "indicator": indicator,
        }

        url = f"{self._base_url}/macro-indicator/{country}"
        t0 = time.monotonic()
        raw = await self._get(url, params)
        duration_ms = int((time.monotonic() - t0) * 1000)

        return ProviderFetchResult(
            provider=Provider.EODHD,
            dataset_type=DatasetType.MACRO_INDICATOR,
            symbol=symbol,
            raw_data=raw,
            content_type="application/json",
            fetched_at=datetime.now(tz=UTC),
            duration_ms=duration_ms,
            provider_metadata={"country": country, "indicator": indicator},
        )

    async def fetch_news_sentiment(
        self,
        symbol: str,
        from_date: str | None = None,
        to_date: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ProviderFetchResult:
        """Fetch news articles with inline sentiment for *symbol*. (EXT-05)"""
        params: dict[str, Any] = {
            "api_token": self._api_key,
            "fmt": "json",
            "s": symbol,
            "limit": limit,
            "offset": offset,
        }
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date

        url = f"{self._base_url}/news"
        t0 = time.monotonic()
        raw = await self._get(url, params)
        duration_ms = int((time.monotonic() - t0) * 1000)

        return ProviderFetchResult(
            provider=Provider.EODHD,
            dataset_type=DatasetType.NEWS_SENTIMENT,
            symbol=symbol,
            raw_data=raw,
            content_type="application/json",
            fetched_at=datetime.now(tz=UTC),
            duration_ms=duration_ms,
        )

    async def fetch_insider_transactions(
        self,
        ticker: str,
        from_date: str | None = None,
        to_date: str | None = None,
        limit: int = 100,
    ) -> ProviderFetchResult:
        """Fetch insider transactions for *ticker*."""
        params: dict[str, Any] = {
            "api_token": self._api_key,
            "fmt": "json",
            "limit": limit,
        }
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date

        url = f"{self._base_url}/insider-transactions"
        params["code"] = ticker
        t0 = time.monotonic()
        raw = await self._get(url, params)
        duration_ms = int((time.monotonic() - t0) * 1000)

        return ProviderFetchResult(
            provider=Provider.EODHD,
            dataset_type=DatasetType.INSIDER_TRANSACTIONS,
            symbol=ticker,
            raw_data=raw,
            content_type="application/json",
            fetched_at=datetime.now(tz=UTC),
            duration_ms=duration_ms,
        )

    async def fetch_yield_curve(
        self,
        series_symbol: str,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> ProviderFetchResult:
        """Fetch US Treasury yield curve data for *series_symbol*.

        Raises
        ------
            ProviderDataError: If *series_symbol* is not a recognised series key.

        """
        path = self._YIELD_SERIES_MAP.get(series_symbol)
        if path is None:
            valid = ", ".join(sorted(self._YIELD_SERIES_MAP))
            raise ProviderDataError(f"Unknown yield series '{series_symbol}'. Valid keys: {valid}")

        params: dict[str, Any] = {
            "api_token": self._api_key,
            "fmt": "json",
        }
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date

        url = f"{self._base_url}/{path}"
        t0 = time.monotonic()
        raw = await self._get(url, params)
        duration_ms = int((time.monotonic() - t0) * 1000)

        return ProviderFetchResult(
            provider=Provider.EODHD,
            dataset_type=DatasetType.YIELD_CURVE,
            symbol=series_symbol,
            raw_data=raw,
            content_type="application/json",
            fetched_at=datetime.now(tz=UTC),
            duration_ms=duration_ms,
        )

    async def fetch_historical_market_cap(
        self,
        ticker: str,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> ProviderFetchResult:
        """Fetch historical market capitalisation for *ticker*."""
        params: dict[str, Any] = {
            "api_token": self._api_key,
            "fmt": "json",
        }
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date

        url = f"{self._base_url}/historical-market-cap/{ticker}"
        t0 = time.monotonic()
        raw = await self._get(url, params)
        duration_ms = int((time.monotonic() - t0) * 1000)

        return ProviderFetchResult(
            provider=Provider.EODHD,
            dataset_type=DatasetType.MARKET_CAP,
            symbol=ticker,
            raw_data=raw,
            content_type="application/json",
            fetched_at=datetime.now(tz=UTC),
            duration_ms=duration_ms,
        )

    # -------------------------------------------------------------------------
    # Internal HTTP helper
    # -------------------------------------------------------------------------

    async def _get(self, url: str, params: dict[str, Any]) -> bytes:
        """Execute a GET request and return the raw response bytes.

        The API key is passed via *params* (a separate query-param dict) and is
        **never** included in error messages or logs — only the URL path is used.

        Raises
        ------
            ProviderAuthError: HTTP 401/403.
            ProviderRateLimited: HTTP 429; carries ``retry_after`` seconds when
                the ``Retry-After`` header is present.
            ProviderUnavailable: HTTP 5xx or network error.
            ProviderDataError: Non-JSON response when JSON is expected.

        """
        # Use the endpoint slug (no host, no query-params) so API key never leaks.
        slug = _endpoint_slug(url)
        try:
            response = await self._client.get(url, params=params)
        except Exception as exc:
            logger.warning(
                "eodhd_connection_error",
                endpoint=slug,
                error=str(exc),
            )
            raise ProviderUnavailable(f"EODHD connection error on {slug}: {exc}") from exc

        status = response.status_code
        if status in (401, 403):
            raise ProviderAuthError(f"EODHD auth failed: HTTP {status} for endpoint '{slug}'")
        if status == 429:
            retry_after = _parse_retry_after(response.headers.get("Retry-After"))
            logger.warning(
                "eodhd_rate_limited",
                endpoint=slug,
                retry_after_seconds=retry_after,
            )
            raise ProviderRateLimited(
                f"EODHD rate limited: HTTP 429 for endpoint '{slug}'",
                retry_after=retry_after,
            )
        if status >= 500:
            raise ProviderUnavailable(f"EODHD server error: HTTP {status} for endpoint '{slug}'")
        if status >= 400:
            raise ProviderDataError(f"EODHD client error: HTTP {status} for endpoint '{slug}'")

        return cast("bytes", response.content)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_ticker(symbol: str, exchange: str | None) -> str:
    """Build EODHD ticker format: ``SYMBOL.EXCHANGE`` or just ``SYMBOL``."""
    if exchange:
        return f"{symbol}.{exchange}"
    return symbol
