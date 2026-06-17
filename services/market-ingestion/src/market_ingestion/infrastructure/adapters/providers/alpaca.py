"""AlpacaProviderAdapter — OHLCV bars via Alpaca Markets REST API.

Alpaca provides free real-time and historical stock bars via their v2 multi-bar
endpoint.  API keys are sent exclusively as HTTP headers (APCA-API-KEY-ID and
APCA-API-SECRET-KEY) — they must NEVER appear in URLs or log fields.

Free tier: unlimited API calls; IEX feed (15-min delayed); SIP feed available on
paid plans.  The ``feed`` constructor parameter selects IEX by default.

Crypto routing: symbols ending in ``-USD`` (e.g. ``BTC-USD``) are automatically
routed to the v1beta3 crypto endpoint (``/v1beta3/crypto/us/bars``) and their
symbols are converted to Alpaca's ``COIN/USD`` slash format (e.g. ``BTC/USD``).
The ``feed`` parameter is NOT sent for crypto requests.
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


# ---------------------------------------------------------------------------
# Pagination safety cap.
#
# Alpaca's `limit` is a PER-RESPONSE total across ALL symbols in the call (NOT
# per-symbol), so a multi-symbol or multi-day intraday request must follow the
# response's `next_page_token` until it is absent — otherwise the tail symbols
# (and the oldest bars of long catch-ups) are silently dropped.
#
# `_MAX_PAGES` bounds the loop: Alpaca has a known historical quirk where
# `next_page_token` can be self-referential / non-terminating, so we stop after
# this many pages and emit a `warning` ("alpaca_pagination_cap_hit") to make a
# runaway visible rather than silently looping. 20 pages x 10000 = 200,000 data
# points, which comfortably covers any realistic multi-day catch-up window.
# ---------------------------------------------------------------------------
_MAX_PAGES: int = 20


def _is_crypto_symbol(symbol: str) -> bool:
    """True for crypto tickers in our ``COIN-USD`` house format (e.g. ``BTC-USD``)."""
    return symbol.upper().endswith("-USD")


def _to_alpaca_crypto_symbol(symbol: str) -> str:
    """Convert ``BTC-USD`` → ``BTC/USD`` for Alpaca's crypto bars endpoint."""
    return symbol.upper().replace("-", "/")


def _to_alpaca_equity_symbol(symbol: str) -> str:
    """Normalize equity symbols for Alpaca's stock endpoint.

    Alpaca requires dot-separated class shares (``BRK.B``) but our house format
    uses dashes (``BRK-B``).  Only non-crypto dashes are converted — crypto
    symbols are handled separately by ``_to_alpaca_crypto_symbol``.
    """
    if _is_crypto_symbol(symbol):
        return symbol
    return symbol.replace("-", ".")


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
                f"Alpaca does not support timeframe {timeframe!r}; supported: {', '.join(sorted(_TIMEFRAME_MAP))}"
            )

        # Crypto symbols use a different endpoint and slash-separated format.
        if _is_crypto_symbol(symbol):
            alpaca_sym = _to_alpaca_crypto_symbol(symbol)
            url = f"{self._base_url}/v1beta3/crypto/us/bars"
            params: dict[str, Any] = {
                "symbols": alpaca_sym,
                "timeframe": alpaca_tf,
                "limit": 10000,
                "sort": "asc",
            }
        else:
            alpaca_sym = _to_alpaca_equity_symbol(symbol)
            url = f"{self._base_url}/v2/stocks/bars"
            params = {
                "symbols": alpaca_sym,
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
        # Follow next_page_token to completion — a single response only carries up
        # to `limit` total data points, so long catch-ups span multiple pages.
        bars_map = await self._get_paginated(url, params)
        duration_ms = int((time.monotonic() - t0) * 1000)

        # Merged map is keyed by Alpaca-format symbol (BTC/USD for crypto). Normalise
        # the one symbol's bars; fall back to the house-format key in case Alpaca
        # mirrors formats. Concatenation across pages already preserves chronology.
        raw_bars = bars_map.get(alpaca_sym)
        if not raw_bars and alpaca_sym != symbol:
            raw_bars = bars_map.get(symbol)
        bars = self._normalize_bars(raw_bars or [])
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
                f"Alpaca does not support timeframe {timeframe!r}; supported: {', '.join(sorted(_TIMEFRAME_MAP))}"
            )

        results: dict[str, ProviderFetchResult] = {}

        # Split into equity vs crypto — each needs a different endpoint.
        equity_symbols = [s for s in symbols if not _is_crypto_symbol(s)]
        crypto_symbols = [s for s in symbols if _is_crypto_symbol(s)]

        async def _fetch_chunk(chunk: list[str], *, is_crypto: bool) -> None:
            if is_crypto:
                alpaca_syms = [_to_alpaca_crypto_symbol(s) for s in chunk]
                chunk_csv = ",".join(alpaca_syms)
                url = f"{self._base_url}/v1beta3/crypto/us/bars"
                params: dict[str, Any] = {
                    "symbols": chunk_csv,
                    "timeframe": alpaca_tf,
                    "limit": 10000,
                    "sort": "asc",
                }
            else:
                alpaca_syms = [_to_alpaca_equity_symbol(s) for s in chunk]
                chunk_csv = ",".join(alpaca_syms)
                url = f"{self._base_url}/v2/stocks/bars"
                params = {
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
            # Paginate within this chunk's HTTP call sequence. Alpaca's `limit` is a
            # per-RESPONSE total across all symbols, so without following the token
            # the tail symbols (symbol-sorted) would silently get zero bars.
            bars_map = await self._get_paginated(url, params)
            duration_ms = int((time.monotonic() - t0) * 1000)

            for sym, alpaca_sym in zip(chunk, alpaca_syms, strict=False):
                sym_bars = self._normalize_bars(bars_map.get(alpaca_sym) or bars_map.get(sym, []))
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

        for i in range(0, len(equity_symbols), self._BATCH_SIZE):
            await _fetch_chunk(equity_symbols[i : i + self._BATCH_SIZE], is_crypto=False)

        for i in range(0, len(crypto_symbols), self._BATCH_SIZE):
            await _fetch_chunk(crypto_symbols[i : i + self._BATCH_SIZE], is_crypto=True)

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

    # ── Quotes via latest 1-minute bar ───────────────────────────────────────

    async def fetch_quotes(self, symbol: str, exchange: str | None = None) -> ProviderFetchResult:
        """Return the latest quote for *symbol* derived from the most recent 1-minute bar.

        Alpaca's free tier does not have a dedicated real-time quotes endpoint.
        Instead we hit ``/v2/stocks/latest/bars`` which returns the last completed
        1-minute bar.  The bar's close price is used as the last price; bid/ask are
        omitted (``None``) since Alpaca IEX feed does not expose them.  Downstream
        ``_remap_quote()`` in ``execute_task.py`` falls back to the close price for
        bid/ask automatically.

        Crypto symbols raise ``ProviderUnavailable`` — crypto tickers do not have
        traditional bid/ask quotes and are better served by OHLCV data directly.
        """
        if _is_crypto_symbol(symbol):
            raise ProviderUnavailable("Alpaca fetch_quotes: crypto quotes not supported; use OHLCV data instead")

        alpaca_sym = _to_alpaca_equity_symbol(symbol)
        # Alpaca has no "latest bar" multi-symbol endpoint that accepts a symbols param.
        # Instead: fetch the most recent 1-minute bar using the standard bars endpoint
        # with limit=1 and sort=desc (newest first).  This reuses the same endpoint
        # and parsing logic as fetch_ohlcv(), so there are no new failure modes.
        url = f"{self._base_url}/v2/stocks/bars"
        params: dict[str, Any] = {
            "symbols": alpaca_sym,
            "timeframe": "1Min",
            "limit": 1,
            "sort": "desc",
            "feed": self._feed,
        }

        t0 = time.monotonic()
        raw_bytes = await self._get(url, params)
        duration_ms = int((time.monotonic() - t0) * 1000)

        try:
            data = json.loads(raw_bytes)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ProviderDataError(f"Alpaca returned non-JSON response: {type(exc).__name__}") from exc

        bars_map: dict[str, list[dict[str, Any]]] = data.get("bars") or {}
        # The bars map returns a list; take the first (and only) bar since limit=1.
        raw_bars: list[dict[str, Any]] = bars_map.get(alpaca_sym) or bars_map.get(symbol) or []
        bar: dict[str, Any] = raw_bars[0] if raw_bars else {}

        # Map the bar fields to a dict that _remap_quote() understands:
        # close → last (via "close" fallback in _remap_quote)
        # Alpaca IEX feed does not provide bid/ask → left as None, _remap_quote
        # falls back to close for both.
        quote_dict: dict[str, Any] = {
            "close": float(bar["c"]) if bar.get("c") is not None else None,
            "timestamp": bar.get("t") or datetime.now(tz=UTC).isoformat(),
            "volume": int(bar["v"]) if bar.get("v") is not None else None,
            "high": float(bar["h"]) if bar.get("h") is not None else None,
            "low": float(bar["l"]) if bar.get("l") is not None else None,
            "open": float(bar["o"]) if bar.get("o") is not None else None,
        }

        self._record_api_call(
            dataset_type=DatasetType.QUOTES.value,
            symbol=symbol,
            exchange=exchange or "",
            timeframe="",
            bars_returned=1 if bar else 0,
            latency_ms=duration_ms,
            credit_cost=0,
        )

        return ProviderFetchResult(
            provider=Provider.ALPACA,
            dataset_type=DatasetType.QUOTES,
            symbol=symbol,
            raw_data=json.dumps(quote_dict).encode(),
            content_type="application/json",
            fetched_at=datetime.now(tz=UTC),
            duration_ms=duration_ms,
            bars_returned=1 if bar else 0,
        )

    async def fetch_fundamentals(
        self,
        symbol: str,
        variant: str = "annual",
        exchange: str | None = None,
    ) -> ProviderFetchResult:
        raise ProviderUnavailable("Alpaca does not provide fundamentals; use EODHD")

    # ── Private helpers ──────────────────────────────────────────────────────

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

    async def _get_paginated(self, url: str, params: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        """Fetch a bars request, following Alpaca's ``next_page_token`` to completion.

        Alpaca's ``limit`` parameter is the TOTAL number of data points across ALL
        symbols in a single response (not per-symbol). To get the complete result a
        client MUST keep re-issuing the same request with ``page_token`` set to the
        previous response's ``next_page_token`` until that token is null/absent.

        This method accumulates the multi-symbol ``bars`` map across every page by
        concatenating each symbol's raw bar list in page order. Because we always
        request ``sort=asc`` and Alpaca emits all of one symbol's bars (in ascending
        time) before moving to the next symbol, list-extending per symbol preserves
        chronological order. The returned map keys are Alpaca-format symbol keys
        (e.g. ``BTC/USD`` for crypto); callers re-key to house format.

        A hard ``_MAX_PAGES`` cap guards against a non-terminating / self-referential
        ``next_page_token`` (a known Alpaca quirk). When the cap is hit we log a
        ``warning`` so a runaway is observable, and return whatever was accumulated.

        Args:
            url:    The bars endpoint URL (equity or crypto).
            params: Base query params (symbols/timeframe/limit/sort/start/end/feed).
                    NOT mutated — a per-page copy carries the ``page_token``.

        Returns:
            Merged per-symbol bars map: ``{alpaca_symbol: [raw_bar_dict, ...]}``.

        Raises:
            ProviderDataError: A page response is not valid JSON.
            (plus the HTTP error mapping from ``_get``).
        """
        merged: dict[str, list[dict[str, Any]]] = {}
        page_token: str | None = None

        for page_index in range(_MAX_PAGES):
            # Copy the base params per page so the shared dict is never mutated and
            # the page_token only applies to the follow-up requests (page 1 omits it).
            page_params = dict(params)
            if page_token is not None:
                # Request key is "page_token"; response key is "next_page_token".
                page_params["page_token"] = page_token

            raw_json = await self._get(url, page_params)
            try:
                data = json.loads(raw_json)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise ProviderDataError(f"Alpaca returned non-JSON response: {type(exc).__name__}") from exc

            bars_map: dict[str, list[dict[str, Any]]] = data.get("bars") or {}
            for sym, sym_bars in bars_map.items():
                # Concatenate in page order — asc sort keeps each symbol chronological.
                merged.setdefault(sym, []).extend(sym_bars or [])

            page_token = data.get("next_page_token")
            if not page_token:
                # No more pages — the result is complete.
                return merged

            if page_index == _MAX_PAGES - 1:
                # Token still present after the final allowed page → likely a runaway
                # / self-referential token. Stop and surface it rather than loop.
                logger.warning(
                    "alpaca_pagination_cap_hit",
                    symbols=params.get("symbols"),
                    timeframe=params.get("timeframe"),
                    pages=_MAX_PAGES,
                )

        return merged

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
