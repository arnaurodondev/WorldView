"""AlpacaProviderAdapter — OHLCV bars via Alpaca Markets REST API.

Alpaca provides free real-time and historical stock bars via their v2 multi-bar
endpoint.  API keys are sent exclusively as HTTP headers (APCA-API-KEY-ID and
APCA-API-SECRET-KEY) — they must NEVER appear in URLs or log fields.

Free tier: unlimited API calls; IEX feed (15-min delayed); SIP feed available on
paid plans.  The ``feed`` constructor parameter selects IEX by default.
"""

from __future__ import annotations

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
# Alpaca timeframe mapping — internal timeframe codes to Alpaca API format.
# Alpaca uses "1Min", "5Min", etc. for intraday and "1Day" for daily.
# ---------------------------------------------------------------------------
_TIMEFRAME_MAP: dict[str, str] = {
    "1m": "1Min",
    "5m": "5Min",
    "15m": "15Min",
    "30m": "30Min",
    "1h": "1Hour",
    "4h": "4Hour",
}


class AlpacaProviderAdapter(BaseProviderAdapter):
    """Alpaca Markets adapter for OHLCV bar data.

    Uses the v2 multi-symbol bars endpoint which supports batching up to 1000
    symbols per request.  API keys are passed as HTTP headers, never in the URL.

    Credit cost is always 0 — Alpaca does not charge per API call.
    """

    # Maximum symbols per single HTTP request (Alpaca API limit).
    _BATCH_SIZE: ClassVar[int] = 1000

    def __init__(
        self,
        api_key: SecretStr,
        secret_key: SecretStr,
        client: httpx.AsyncClient,
        base_url: str = "https://data.alpaca.markets",
        feed: str = "iex",
    ) -> None:
        # Store SecretStr references — .get_secret_value() called only at HTTP
        # request time to minimise window of secret exposure in memory.
        self._api_key = api_key
        self._secret_key = secret_key
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._feed = feed

    @property
    def provider(self) -> Provider:
        return Provider.ALPACA

    @property
    def supports_batch(self) -> bool:
        """Alpaca's v2 multi-bar endpoint natively supports up to 1000 symbols per request."""
        return True

    # ── OHLCV (primary capability) ────────────────────────────────────────────

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start: datetime | None,
        end: datetime | None,
        exchange: str | None = None,
    ) -> ProviderFetchResult:
        """Fetch OHLCV bars for a single *symbol* at the given *timeframe*.

        Alpaca v2 endpoint: GET /v2/stocks/bars with query params.
        API keys go in headers only — NEVER in the URL.

        Args:
            symbol:    Ticker (e.g. "AAPL").
            timeframe: One of "1m", "5m", "15m", "30m", "1h", "4h".
            start:     Inclusive start (UTC); None = earliest available.
            end:       Exclusive end (UTC); None = latest available.
            exchange:  Ignored — Alpaca does not use exchange suffixes.

        Returns:
            ProviderFetchResult with JSON-encoded list of normalised bar dicts.

        Raises:
            ProviderRateLimited: HTTP 429.
            ProviderUnavailable: HTTP 403 (fatal) or 5xx (retryable).
            ProviderDataError: Unexpected response shape.
        """
        alpaca_tf = _TIMEFRAME_MAP.get(timeframe)
        if alpaca_tf is None:
            raise ProviderUnavailable(
                f"Alpaca does not support timeframe {timeframe!r}; " f"supported: {', '.join(sorted(_TIMEFRAME_MAP))}"
            )

        url = f"{self._base_url}/v2/stocks/bars"
        params: dict[str, Any] = {
            "symbols": symbol,
            "timeframe": alpaca_tf,
            "limit": 10000,
            "feed": self._feed,
            "sort": "asc",
        }
        if start is not None:
            params["start"] = start.strftime("%Y-%m-%dT%H:%M:%SZ")
        if end is not None:
            params["end"] = end.strftime("%Y-%m-%dT%H:%M:%SZ")

        t0 = time.monotonic()
        raw_json = await self._get(url, params)
        duration_ms = int((time.monotonic() - t0) * 1000)

        # Parse the Alpaca response — shape: {"bars": {"AAPL": [...]}, ...}
        bars = self._parse_bars(raw_json, symbol)
        raw_bytes = json.dumps(bars).encode()

        self._record_api_call(
            dataset_type=DatasetType.OHLCV.value,
            symbol=symbol,
            exchange=exchange or "",
            timeframe=timeframe,
            bars_returned=len(bars),
            latency_ms=duration_ms,
            credit_cost=0,
        )

        return ProviderFetchResult(
            provider=Provider.ALPACA,
            dataset_type=DatasetType.OHLCV,
            symbol=symbol,
            raw_data=raw_bytes,
            content_type="application/json",
            fetched_at=datetime.now(tz=UTC),
            duration_ms=duration_ms,
            range_start=start,
            range_end=end,
            bars_returned=len(bars),
        )

    # ── Batch OHLCV ──────────────────────────────────────────────────────────

    async def fetch_ohlcv_batch(
        self,
        symbols: list[str],
        timeframe: str,
        start: datetime | None,
        end: datetime | None,
    ) -> dict[str, ProviderFetchResult]:
        """Fetch OHLCV bars for multiple symbols, chunked by _BATCH_SIZE.

        Alpaca's multi-bar endpoint accepts up to 1000 comma-separated symbols.
        If *symbols* exceeds 1000, the list is split into multiple HTTP calls.

        Returns:
            Dict keyed by symbol, each value a ProviderFetchResult.
        """
        alpaca_tf = _TIMEFRAME_MAP.get(timeframe)
        if alpaca_tf is None:
            raise ProviderUnavailable(
                f"Alpaca does not support timeframe {timeframe!r}; " f"supported: {', '.join(sorted(_TIMEFRAME_MAP))}"
            )

        results: dict[str, ProviderFetchResult] = {}

        # Chunk symbols into groups of _BATCH_SIZE (1000).
        for i in range(0, len(symbols), self._BATCH_SIZE):
            chunk = symbols[i : i + self._BATCH_SIZE]
            chunk_csv = ",".join(chunk)

            url = f"{self._base_url}/v2/stocks/bars"
            params: dict[str, Any] = {
                "symbols": chunk_csv,
                "timeframe": alpaca_tf,
                "limit": 10000,
                "feed": self._feed,
                "sort": "asc",
            }
            if start is not None:
                params["start"] = start.strftime("%Y-%m-%dT%H:%M:%SZ")
            if end is not None:
                params["end"] = end.strftime("%Y-%m-%dT%H:%M:%SZ")

            t0 = time.monotonic()
            raw_json = await self._get(url, params)
            duration_ms = int((time.monotonic() - t0) * 1000)

            # Parse response — shape: {"bars": {"AAPL": [...], "MSFT": [...]}, ...}
            try:
                data = json.loads(raw_json)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise ProviderDataError(f"Alpaca returned non-JSON response: {type(exc).__name__}") from exc

            bars_map: dict[str, list[dict[str, Any]]] = data.get("bars") or {}

            for sym in chunk:
                sym_bars = self._normalize_bars(bars_map.get(sym, []))
                raw_bytes = json.dumps(sym_bars).encode()

                self._record_api_call(
                    dataset_type=DatasetType.OHLCV.value,
                    symbol=sym,
                    timeframe=timeframe,
                    bars_returned=len(sym_bars),
                    latency_ms=duration_ms,
                    credit_cost=0,
                )

                results[sym] = ProviderFetchResult(
                    provider=Provider.ALPACA,
                    dataset_type=DatasetType.OHLCV,
                    symbol=sym,
                    raw_data=raw_bytes,
                    content_type="application/json",
                    fetched_at=datetime.now(tz=UTC),
                    duration_ms=duration_ms,
                    range_start=start,
                    range_end=end,
                    bars_returned=len(sym_bars),
                )

        return results

    # ── Intraday alias ────────────────────────────────────────────────────────

    async def fetch_intraday(
        self,
        symbol: str,
        interval: str,
        exchange: str | None = None,
    ) -> ProviderFetchResult:
        """Alias for fetch_ohlcv — Alpaca uses the same bars endpoint for all timeframes."""
        return await self.fetch_ohlcv(
            symbol=symbol,
            timeframe=interval,
            start=None,
            end=None,
            exchange=exchange,
        )

    # ── Unsupported methods ──────────────────────────────────────────────────

    async def fetch_quotes(self, symbol: str, exchange: str | None = None) -> ProviderFetchResult:
        raise ProviderUnavailable("Alpaca does not provide quotes; use EODHD")

    async def fetch_fundamentals(
        self,
        symbol: str,
        variant: str = "annual",
        exchange: str | None = None,
    ) -> ProviderFetchResult:
        raise ProviderUnavailable("Alpaca does not provide fundamentals; use EODHD")

    # ── Private helpers ──────────────────────────────────────────────────────

    def _parse_bars(self, raw: bytes, symbol: str) -> list[dict[str, Any]]:
        """Parse the Alpaca multi-bar response and return normalised bars for *symbol*.

        Alpaca response shape::

            {
                "bars": {
                    "AAPL": [{"t": "2024-01-02T09:30:00Z", "o": 100.0, ...}, ...],
                },
                "next_page_token": null
            }

        Each bar dict is normalised to: {timestamp, open, high, low, close, volume}.
        """
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProviderDataError(f"Alpaca returned non-JSON response: {type(exc).__name__}") from exc

        bars_map: dict[str, list[dict[str, Any]]] = data.get("bars") or {}
        raw_bars = bars_map.get(symbol, [])
        return self._normalize_bars(raw_bars)

    @staticmethod
    def _normalize_bars(raw_bars: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert Alpaca bar dicts to the canonical {datetime, open, high, low, close, volume} format.

        Alpaca uses single-char keys (t/o/h/l/c/v); we rename them to the canonical
        format used by CanonicalOHLCVBar.from_dict():
          - "t" → "datetime"  (CanonicalOHLCVBar accepts "date" or "datetime")
          - "o/h/l/c" → "open/high/low/close"
          - "v" → "volume"

        BP-NEW-alpaca-timestamp-key: previously used "timestamp" key which is not
        recognised by CanonicalOHLCVBar.from_dict() → "Invalid isoformat string: ''"
        on bars where the "t" field is missing.
        """
        normalised: list[dict[str, Any]] = []
        for bar in raw_bars:
            t_val = bar.get("t")
            if not t_val:
                # Skip bars with missing timestamp — cannot canonicalize without a date.
                continue
            normalised.append(
                {
                    # Use "datetime" key so CanonicalOHLCVBar.from_dict() recognises it.
                    "datetime": t_val,
                    "open": float(bar.get("o", 0)),
                    "high": float(bar.get("h", 0)),
                    "low": float(bar.get("l", 0)),
                    "close": float(bar.get("c", 0)),
                    "volume": int(bar.get("v", 0)),
                }
            )
        return normalised

    async def _get(self, url: str, params: dict[str, Any]) -> bytes:
        """Execute authenticated GET request with Alpaca API key headers.

        API keys go ONLY in headers — never in URL query params or log fields.
        Error mapping: 429 -> ProviderRateLimited, 403 -> ProviderUnavailable
        (fatal), 5xx -> ProviderUnavailable (retryable).
        """
        endpoint = self._sanitize_url_slug(url)
        headers = {
            "APCA-API-KEY-ID": self._api_key.get_secret_value(),
            "APCA-API-SECRET-KEY": self._secret_key.get_secret_value(),
        }

        try:
            response = await self._client.get(url, params=params, headers=headers, timeout=30.0)
        except Exception as exc:
            self._record_error(reason="connection_error", endpoint=endpoint)
            raise ProviderUnavailable(f"Alpaca connection error: {type(exc).__name__}") from exc

        status = response.status_code

        if status == 429:
            self._record_rate_limited(endpoint=endpoint)
            retry_after: float | None = None
            raw_header = response.headers.get("Retry-After")
            if raw_header is not None:
                import contextlib

                with contextlib.suppress(ValueError):
                    retry_after = float(raw_header)
            raise ProviderRateLimited("Alpaca rate limit exceeded", retry_after=retry_after)

        if status == 403:
            self._record_error(reason="auth_error", endpoint=endpoint)
            raise ProviderUnavailable("Alpaca: forbidden (403) — check API key permissions")

        if status >= 500:
            self._record_error(reason=f"http_{status}", endpoint=endpoint)
            raise ProviderUnavailable(f"Alpaca server error HTTP {status}")

        if status >= 400:
            self._record_error(reason=f"http_{status}", endpoint=endpoint)
            raise ProviderDataError(f"Alpaca client error HTTP {status}")

        return bytes(response.content)
