"""PolygonProviderAdapter — OHLCV bars via Polygon.io REST API.

Polygon provides historical and real-time OHLCV aggregates via the v2 aggs
endpoint (single-ticker only).  The free tier allows 5 requests/minute, enforced
by an asyncio.Semaphore(5).  The API key travels as a query parameter
(``?apiKey=...``); it is stripped from all log fields via ``_sanitize_url_slug``
to prevent credential leakage (BP-025).
"""

from __future__ import annotations

import asyncio
import json
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, ClassVar

from market_ingestion.application.ports.adapters import ProviderFetchResult
from market_ingestion.domain.enums import DatasetType, Provider
from market_ingestion.domain.errors import (
    ProviderDataError,
    ProviderRateLimited,
    ProviderUnavailable,
)
from market_ingestion.infrastructure.adapters.providers.base import BaseProviderAdapter
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    import httpx
    from pydantic import SecretStr

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# Timeframe mapping — internal codes to Polygon (multiplier, timespan) pairs.
# ---------------------------------------------------------------------------
_TIMEFRAME_MAP: dict[str, tuple[int, str]] = {
    "1m": (1, "minute"),
    "5m": (5, "minute"),
    "15m": (15, "minute"),
    "30m": (30, "minute"),
    "1h": (1, "hour"),
    "4h": (4, "hour"),
    "1d": (1, "day"),
    "1w": (1, "week"),
}


class PolygonProviderAdapter(BaseProviderAdapter):
    """Polygon.io adapter for OHLCV aggregate bar data.

    Uses ``GET /v2/aggs/ticker/{ticker}/range/{mult}/{span}/{from}/{to}`` with
    ``?adjusted=true&sort=asc&limit=50000&apiKey=<key>``.

    Rate limiter: free tier = 5 requests/minute.  An ``asyncio.Semaphore(5)``
    is shared across all concurrent calls from this adapter instance.  On HTTP
    429 the semaphore is released and ``ProviderRateLimited`` is raised.

    Security: ``apiKey`` lives only in the URL query string; it is stripped from
    every log field via ``_sanitize_url_slug`` (strip=True path).  The raw URL
    is NEVER passed to any log event.
    """

    # Free tier: 5 requests per minute.  Semaphore limits concurrent in-flight
    # requests; callers back off naturally when all 5 slots are held.
    _RATE_LIMIT: ClassVar[int] = 5

    def __init__(
        self,
        api_key: SecretStr,
        client: httpx.AsyncClient,
        base_url: str = "https://api.polygon.io",
    ) -> None:
        # SecretStr: .get_secret_value() is called only at HTTP request time.
        self._api_key = api_key
        self._client = client
        self._base_url = base_url.rstrip("/")
        # Semaphore limits concurrent requests to respect the free-tier rate limit.
        self._rate_limiter: asyncio.Semaphore = asyncio.Semaphore(self._RATE_LIMIT)

    @property
    def provider(self) -> Provider:
        return Provider.POLYGON

    # ── OHLCV (primary capability) ────────────────────────────────────────────

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start: datetime | None,
        end: datetime | None,
        exchange: str | None = None,
    ) -> ProviderFetchResult:
        """Fetch OHLCV aggregate bars for *symbol* at *timeframe*.

        Polygon v2 aggs endpoint: single ticker per request.  Handles pagination
        via ``next_url`` when Polygon returns more results than ``limit``.

        Args:
            symbol:    Ticker (e.g. "AAPL").  Exchange suffix not used.
            timeframe: One of "1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w".
            start:     Inclusive start (UTC).  Defaults to 1 year ago if None.
            end:       Exclusive end (UTC).  Defaults to today if None.
            exchange:  Ignored — Polygon does not use exchange suffixes.

        Returns:
            ProviderFetchResult with JSON-encoded list of normalised bar dicts.

        Raises:
            ProviderUnavailable: Unsupported timeframe or HTTP 403/5xx.
            ProviderRateLimited: HTTP 429.
            ProviderDataError: Unexpected response shape.
        """
        params = _TIMEFRAME_MAP.get(timeframe)
        if params is None:
            raise ProviderUnavailable(
                f"Polygon does not support timeframe {timeframe!r}; " f"supported: {', '.join(sorted(_TIMEFRAME_MAP))}"
            )
        multiplier, timespan = params

        # Default date range: last 30 days if not specified.
        from_date = start.strftime("%Y-%m-%d") if start else "2020-01-01"
        to_date = end.strftime("%Y-%m-%d") if end else datetime.now(tz=UTC).strftime("%Y-%m-%d")

        url = f"{self._base_url}/v2/aggs/ticker/{symbol}/range" f"/{multiplier}/{timespan}/{from_date}/{to_date}"
        query_params: dict[str, Any] = {
            "adjusted": "true",
            "sort": "asc",
            "limit": 50000,
            # apiKey added at request time so it never appears in variable assignments
            # above — keeps the URL template free of secrets until the last moment.
            "apiKey": self._api_key.get_secret_value(),
        }

        t0 = time.monotonic()
        all_results: list[dict[str, Any]] = []

        # Paginate through all result pages via next_url.
        current_url: str | None = url
        current_params: dict[str, Any] | None = query_params
        while current_url is not None:
            raw_json = await self._get(current_url, current_params)
            duration_ms = int((time.monotonic() - t0) * 1000)

            try:
                data: dict[str, Any] = json.loads(raw_json)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise ProviderDataError(f"Polygon returned non-JSON response: {type(exc).__name__}") from exc

            results: list[dict[str, Any]] = data.get("results") or []
            all_results.extend(_normalize_bars(results))

            # Polygon pagination: follow next_url when present.
            next_url: str | None = data.get("next_url")
            if next_url:
                # next_url already contains apiKey — pass None params to avoid duplication.
                current_url = next_url
                current_params = None
            else:
                current_url = None

        raw_bytes = json.dumps(all_results).encode()

        # Sanitize URL for logging — strips query params including ?apiKey=...
        safe_endpoint = self._sanitize_url_slug(url)
        self._record_api_call(
            dataset_type=DatasetType.OHLCV.value,
            symbol=symbol,
            exchange=exchange or "",
            timeframe=timeframe,
            bars_returned=len(all_results),
            latency_ms=duration_ms,
            credit_cost=0,
        )
        logger.debug(
            "polygon_fetch_complete",
            symbol=symbol,
            timeframe=timeframe,
            bars=len(all_results),
            endpoint=safe_endpoint,
        )

        return ProviderFetchResult(
            provider=Provider.POLYGON,
            dataset_type=DatasetType.OHLCV,
            symbol=symbol,
            raw_data=raw_bytes,
            content_type="application/json",
            fetched_at=datetime.now(tz=UTC),
            duration_ms=duration_ms,
            range_start=start,
            range_end=end,
            bars_returned=len(all_results),
        )

    # ── Unsupported methods ──────────────────────────────────────────────────

    async def fetch_quotes(self, symbol: str, exchange: str | None = None) -> ProviderFetchResult:
        raise ProviderUnavailable("Polygon does not provide quotes via this adapter; use EODHD")

    async def fetch_fundamentals(
        self,
        symbol: str,
        variant: str = "annual",
        exchange: str | None = None,
    ) -> ProviderFetchResult:
        raise ProviderUnavailable("Polygon does not provide fundamentals via this adapter; use EODHD")

    # ── Private helpers ──────────────────────────────────────────────────────

    async def _get(self, url: str, params: dict[str, Any] | None) -> bytes:
        """Execute a GET request with rate-limit semaphore enforcement.

        The semaphore limits concurrent in-flight requests to ``_RATE_LIMIT`` (5).
        On 429 the semaphore is released and ``ProviderRateLimited`` is raised.
        On 403 → ``ProviderUnavailable`` (fatal — bad key).
        On 5xx → ``ProviderUnavailable`` (retryable).

        The raw URL (which contains ?apiKey=...) is NEVER passed to any log event.
        Use ``_sanitize_url_slug`` on the base URL (without query params) for logging.
        """
        # Safe endpoint slug for logging — no query params, no secrets.
        safe_endpoint = self._sanitize_url_slug(url)

        async with self._rate_limiter:
            try:
                response = await self._client.get(url, params=params, timeout=30.0)
            except Exception as exc:
                self._record_error(reason="connection_error", endpoint=safe_endpoint)
                raise ProviderUnavailable(f"Polygon connection error: {type(exc).__name__}") from exc

            status = response.status_code

            if status == 429:
                self._record_rate_limited(endpoint=safe_endpoint)
                retry_after: float | None = None
                raw_header = response.headers.get("Retry-After")
                if raw_header is not None:
                    import contextlib

                    with contextlib.suppress(ValueError):
                        retry_after = float(raw_header)
                raise ProviderRateLimited("Polygon rate limit exceeded (5 req/min free tier)", retry_after=retry_after)

            if status == 403:
                self._record_error(reason="auth_error", endpoint=safe_endpoint)
                raise ProviderUnavailable("Polygon: forbidden (403) — check API key permissions")

            if status >= 500:
                self._record_error(reason=f"http_{status}", endpoint=safe_endpoint)
                raise ProviderUnavailable(f"Polygon server error HTTP {status}")

            if status >= 400:
                self._record_error(reason=f"http_{status}", endpoint=safe_endpoint)
                raise ProviderDataError(f"Polygon client error HTTP {status}")

            return bytes(response.content)


# ---------------------------------------------------------------------------
# Module-level normalizer (pure — no I/O)
# ---------------------------------------------------------------------------


def _normalize_bars(raw_bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Convert Polygon bar dicts to the canonical {timestamp, open, high, low, close, volume} format.

    Polygon bar shape: {t: <ms_epoch>, o, h, l, c, v, vw, n}
    ``t`` is milliseconds since Unix epoch — convert to ISO-8601 UTC string.
    ``vw`` (volume-weighted average price) and ``n`` (number of transactions) are
    included as optional metadata fields for downstream consumers.
    """
    normalised: list[dict[str, Any]] = []
    for bar in raw_bars:
        # Convert millisecond epoch to UTC ISO-8601 string.
        t_ms: int = int(bar.get("t", 0))
        ts = datetime.fromtimestamp(t_ms / 1000.0, tz=UTC).isoformat()
        normalised.append(
            {
                "timestamp": ts,
                "open": float(bar.get("o", 0)),
                "high": float(bar.get("h", 0)),
                "low": float(bar.get("l", 0)),
                "close": float(bar.get("c", 0)),
                "volume": int(bar.get("v", 0)),
            }
        )
    return normalised
