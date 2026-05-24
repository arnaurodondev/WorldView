"""HTTP adapter for the Market Data service (S3) OHLCV API (PRD-0020 §6.5).

Calls ``GET /api/v1/market-data/ohlcv/{symbol}?start={date}&end={date}`` and
returns a typed ``OHLCVBar`` dataclass (or ``None`` on 404 / any HTTP error).

No exceptions are propagated to the caller — all errors are swallowed and
logged as warnings so a single bad symbol never aborts the labelling cycle.

PRD-0025 / F-101 fix (2026-04-30): every backend service is guarded by
``InternalJWTMiddleware`` and rejects requests lacking a valid X-Internal-JWT
header with HTTP 401. The worker mints its JWT against S9 and forwards the
resulting RS256 token as ``X-Internal-JWT`` on every OHLCV call; the
receiver verifies it against the gateway's JWKS endpoint just like any
user-initiated request.

Token-mint paths (in order of preference):
  1. ``service_account_token`` set → ``POST /internal/v1/service-token``
     (PLAN-0057 Wave A-1 / BP-303). The endpoint is available in production
     because the shared secret IS the auth boundary; no ``app_env`` guard.
  2. Fallback → ``POST /v1/auth/dev-login``. Only works in non-production
     (dev-login is hard-blocked when ``app_env == 'production'``); kept as
     a backwards-compatible local-dev convenience.
  3. Neither configured → no header sent (legacy 401-and-warn fallback).

Note: ``_token_lock`` is created in ``__init__`` and is therefore loop-bound.
Use a single ``MarketDataClient`` instance per asyncio loop.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import urllib.parse
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    import httpx

    from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]


# Refresh the internal JWT at most this often — S9 dev-login mints 5-minute
# tokens; refreshing every 240 s leaves a 60 s safety margin.
_TOKEN_REFRESH_S: float = 240.0

# PLAN-0093 T-C-3-02: persistent 404 backoff for symbol resolution.
# After 3 consecutive 404s for the same ticker we mark it as "unknown" in
# Valkey for 7 days so subsequent worker cycles skip the round-trip. This
# prevents the 404 storms the audit (F-NPL-FUNDAMENTALS-001) flagged when a
# ticker is genuinely unmapped (delisted, foreign exchange, etc.).
_UNKNOWN_TICKER_KEY_PREFIX: str = "nlp:price_impact:unknown_tickers"
_UNKNOWN_TICKER_FAIL_KEY_PREFIX: str = "nlp:price_impact:unknown_tickers:fails"
_UNKNOWN_TICKER_TTL_S: int = 7 * 24 * 60 * 60  # 7 days
_UNKNOWN_TICKER_FAIL_TTL_S: int = 24 * 60 * 60  # 1 day rolling counter
_UNKNOWN_TICKER_FAIL_THRESHOLD: int = 3


@dataclass(frozen=True)
class OHLCVBar:
    """Typed OHLCV bar returned by the Market Data service."""

    symbol: str
    date: date
    open: Decimal
    close: Decimal
    high: Decimal
    low: Decimal
    volume: int | None


class MarketDataClient:
    """Async HTTP client for the internal Market Data (S3) OHLCV API.

    Usage::

        async with httpx.AsyncClient(timeout=10.0) as http:
            client = MarketDataClient(http, "http://market-data:8003",
                                      api_gateway_url="http://api-gateway:8000")
            bar = await client.get_ohlcv("AAPL", date(2026, 4, 1))
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        *,
        api_gateway_url: str | None = None,
        service_account_token: str | None = None,
        service_name: str = "nlp-pipeline-price-impact",
        valkey_client: ValkeyClient | None = None,
    ) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")
        # PLAN-0093 T-C-3-02: optional Valkey client for the 7-day unknown-ticker
        # skip-set. When None, the worker still uses the existing in-process
        # negative cache (so unit tests + dev workflows continue to work).
        self._valkey: ValkeyClient | None = valkey_client
        # F-101: api-gateway base URL for token bootstrap. When None we fall
        # back to the legacy "no headers" behaviour — which still produces
        # 401s on a guarded receiver but lets unit tests run without mocking
        # the auth round-trip.
        self._api_gateway_url = (api_gateway_url or "").rstrip("/")
        # PLAN-0057 Wave A-1 / BP-303: when set, prefer the production-safe
        # ``POST /internal/v1/service-token`` path over ``POST /v1/auth/dev-login``.
        # Empty string is normalised to None so callers can pass either flavour.
        self._service_account_token: str | None = service_account_token or None
        self._service_name = service_name
        self._token: str | None = None
        self._token_minted_at: float = 0.0
        self._token_lock = asyncio.Lock()

    async def _get_internal_jwt(self) -> str | None:
        """Return a fresh X-Internal-JWT, minting one if cached token is stale.

        F-101 / BP-303: workers don't have the gateway's RS256 private key
        mounted, so we call S9 to mint a signed JWT.

        - When ``service_account_token`` is configured → call
          ``POST /internal/v1/service-token`` with the shared secret. This
          path works in production (no ``app_env`` guard).
        - Otherwise → fall back to ``POST /v1/auth/dev-login`` (production
          returns 403, dev returns a JWT — kept for local-dev convenience).

        Returns ``None`` if api-gateway is unreachable or refuses to mint a
        token, in which case the caller falls back to unauthenticated requests
        (preserving the legacy 401-and-warn behaviour rather than crashing).
        """
        if not self._api_gateway_url:
            return None

        async with self._token_lock:
            now = time.monotonic()
            if self._token and (now - self._token_minted_at) < _TOKEN_REFRESH_S:
                return self._token

            # Pick the auth path based on configuration. Both endpoints
            # respond with the same ``{"access_token": "...", ...}`` shape.
            if self._service_account_token:
                url = f"{self._api_gateway_url}/internal/v1/service-token"
                payload = {
                    "service_name": self._service_name,
                    "secret": self._service_account_token,
                }
                mint_path = "service-token"
            else:
                url = f"{self._api_gateway_url}/v1/auth/dev-login"
                payload = {}  # type: ignore[assignment]
                mint_path = "dev-login"

            try:
                resp = await self._client.post(url, json=payload, timeout=5.0)
                if resp.status_code != 200:
                    logger.warning(
                        "market_data_client_token_mint_failed",
                        mint_path=mint_path,
                        status_code=resp.status_code,
                        body=resp.text[:200],
                    )
                    return None
                token = resp.json().get("access_token")
                if not isinstance(token, str) or not token:
                    return None
                self._token = token
                self._token_minted_at = now
                logger.debug("market_data_client_token_refreshed", mint_path=mint_path)
                return token
            except Exception as exc:
                logger.warning(
                    "market_data_client_token_mint_error",
                    mint_path=mint_path,
                    error=str(exc),
                )
                return None

    async def _resolve_instrument_id(self, ticker: str) -> str | None:
        """Resolve a ticker to its instrument_id UUID via market-data lookup.

        PLAN-0052 platform-QA round 4 (2026-05-01): the prior version of
        ``get_ohlcv`` called ``/api/v1/market-data/ohlcv/{TICKER}`` with
        the ticker symbol — but the actual market-data route is
        ``/api/v1/ohlcv/{instrument_id}`` keyed on a UUID. Result: every
        single price-impact lookup 404'd silently → ``article_impact_windows``
        was always empty → news-relevance scoring couldn't use price
        signal at all.

        Fix: resolve the ticker once via market-data's
        ``GET /api/v1/instruments/lookup?symbol={ticker}`` endpoint
        (PLAN-0073 B-1 renamed the old ``/instruments/symbol/{ticker}``
        route; it no longer exists and returns 404).  Cache in process
        memory keyed on ticker so the next call within the same labelling
        cycle is free. The cache is bounded to 1024 entries (LRU-ish via
        dict ordering) — we typically resolve <100 distinct tickers per cycle.

        Returns ``None`` on any failure (auth, 404, network) so the
        outer ``get_ohlcv`` falls back to its existing "no data" path
        without surfacing a new error class.
        """
        # In-process cache (initialised on first call). One-day key cache
        # is fine: tickers don't change identity within a single labelling
        # cycle, and each cycle re-creates the client fresh.
        cache: dict[str, str] = getattr(self, "_ticker_cache", None) or {}
        if not hasattr(self, "_ticker_cache"):
            self._ticker_cache = cache  # type: ignore[attr-defined]
        cached: str | None = cache.get(ticker)
        if cached is not None:
            # Empty string is the negative-cache sentinel: ticker is known
            # to be unresolvable. Treat it as None for the caller's purposes.
            return cached if cached else None

        # PLAN-0093 T-C-3-02: cross-process unknown-ticker skip-set in Valkey.
        # Survives worker restarts (the in-process cache does not). 7-day TTL
        # so newly-mapped tickers eventually retry without manual flush.
        if self._valkey is not None and await self._is_in_unknown_set(ticker):
            cache[ticker] = ""  # warm the in-process negative cache
            return None

        # PLAN-0073 B-1: /instruments/symbol/{ticker} was removed; use the
        # unified /instruments/lookup?symbol= endpoint instead.
        url = f"{self._base_url}/api/v1/instruments/lookup"
        token = await self._get_internal_jwt()
        headers = {"X-Internal-JWT": token} if token else {}
        try:
            # PLAN-0052 platform-QA round 7 (2026-05-01): defense-in-depth — set
            # an explicit per-call timeout (10s) so the worker can never hang
            # indefinitely if the outer AsyncClient default timeout is ever
            # cleared by a future refactor (BP-235 pattern).
            # Pass symbol as a query parameter to match /instruments/lookup signature.
            response = await self._client.get(
                url,
                params={"symbol": ticker},
                headers=headers,
                timeout=10.0,
            )
        except Exception as exc:
            logger.warning(  # type: ignore[no-any-return]
                "market_data_resolve_request_error",
                ticker=ticker,
                error=str(exc),
            )
            return None
        if response.status_code != 200:
            # 404 = unknown ticker (legitimately unmapped); other status =
            # logged so we can spot upstream regressions.
            if response.status_code != 404:
                logger.warning(  # type: ignore[no-any-return]
                    "market_data_resolve_unexpected_status",
                    ticker=ticker,
                    status=response.status_code,
                )
            cache[ticker] = ""  # negative cache so we don't retry per-bar
            # PLAN-0093 T-C-3-02: increment cross-process fail counter on 404;
            # once we cross the threshold we promote into the 7-day skip-set so
            # the next worker cycle (and every cycle for 7 days after) skips
            # the round-trip entirely.
            if self._valkey is not None and response.status_code == 404:
                await self._record_unknown_ticker_failure(ticker)
            return None
        try:
            body = response.json()
            # InstrumentLookupResponse returns "id", not "instrument_id".
            # /instruments/lookup?symbol= → {"id": "<uuid>", "symbol": ..., ...}
            instrument_id = body.get("id")
            if not instrument_id:
                cache[ticker] = ""
                return None
            # Bound the cache.
            if len(cache) > 1024:
                # Drop the oldest 256 entries (Python 3.7+ dict preserves
                # insertion order — pop from the head).
                for _ in range(256):
                    try:
                        cache.pop(next(iter(cache)))
                    except StopIteration:
                        break
            cache[ticker] = str(instrument_id)
            return str(instrument_id)
        except Exception as exc:
            logger.warning(  # type: ignore[no-any-return]
                "market_data_resolve_parse_error",
                ticker=ticker,
                error=str(exc),
            )
            return None

    # ── PLAN-0093 T-C-3-02 helpers — Valkey unknown-ticker skip-set ─────────

    async def _is_in_unknown_set(self, ticker: str) -> bool:
        """Return True if *ticker* is currently in the unknown-ticker skip-set.

        Best-effort: any Valkey error returns False so we fall through to a
        normal lookup attempt (degraded but functional). We never let a Valkey
        outage cascade into a worker failure.
        """
        if self._valkey is None:
            return False
        try:
            return await self._valkey.exists(f"{_UNKNOWN_TICKER_KEY_PREFIX}:{ticker.upper()}")
        except Exception as exc:
            logger.debug(  # type: ignore[no-any-return]
                "market_data_unknown_set_check_failed", ticker=ticker, error=str(exc)
            )
            return False

    async def _record_unknown_ticker_failure(self, ticker: str) -> None:
        """Increment per-ticker 404 counter; promote to skip-set after threshold.

        Implements the plan's "3 consecutive 404s → 7-day skip" semantics:
          - INCR a counter at ``…:fails:<ticker>``; on first hit set TTL to 1 day
            (rolling window — sporadic 404s never accumulate forever)
          - When counter >= threshold, write a separate marker key at
            ``…:unknown_tickers:<ticker>`` with 7-day TTL → checked by
            ``_is_in_unknown_set`` at the top of ``_resolve_instrument_id``

        Best-effort: Valkey errors are swallowed.
        """
        if self._valkey is None:
            return
        try:
            key = ticker.upper()
            fail_key = f"{_UNKNOWN_TICKER_FAIL_KEY_PREFIX}:{key}"
            new_count = await self._valkey.incr(fail_key)
            # On the FIRST increment, attach a TTL so the counter expires if
            # the failures stop (e.g. ticker becomes resolvable again).
            if new_count == 1:
                with contextlib.suppress(Exception):
                    await self._valkey.expire(fail_key, _UNKNOWN_TICKER_FAIL_TTL_S)
            if new_count >= _UNKNOWN_TICKER_FAIL_THRESHOLD:
                # Promote: write the long-TTL skip marker so future calls bypass
                # the network entirely. Using set() with ex= so the TTL is set
                # atomically with the value (avoids a race where the key exists
                # without a TTL).
                await self._valkey.set(f"{_UNKNOWN_TICKER_KEY_PREFIX}:{key}", "1", ex=_UNKNOWN_TICKER_TTL_S)
                logger.info(  # type: ignore[no-any-return]
                    "market_data_ticker_marked_unknown",
                    ticker=ticker,
                    consecutive_404s=new_count,
                    ttl_seconds=_UNKNOWN_TICKER_TTL_S,
                )
        except Exception as exc:
            logger.debug(  # type: ignore[no-any-return]
                "market_data_unknown_set_write_failed", ticker=ticker, error=str(exc)
            )

    async def get_ohlcv(self, symbol: str, bar_date: date) -> OHLCVBar | None:
        """Return the daily OHLCV bar for *symbol* on *bar_date*, or ``None``.

        Returns ``None`` on:
          - HTTP 404 (symbol/date not found — normal for non-listed instruments)
          - Any ``httpx.RequestError`` (timeout, connection refused, …)
          - Non-200/404 HTTP status code
          - Unexpected response format (parsing error)

        Callers should treat ``None`` as "no data" and create a zero-impact label.
        """
        # PLAN-0052 platform-QA round 4 (2026-05-01): resolve ticker → UUID
        # via market-data's existing /api/v1/instruments/symbol/{ticker}
        # before making the OHLCV call. Without this, every call hit
        # /api/v1/market-data/ohlcv/{TICKER} → 404 → silent "no data".
        instrument_id = await self._resolve_instrument_id(symbol)
        if not instrument_id:
            # Unknown ticker — graceful no-data return; matches prior behavior.
            return None

        url = f"{self._base_url}/api/v1/ohlcv/{urllib.parse.quote(instrument_id, safe='')}"
        params = {"start": bar_date.isoformat(), "end": bar_date.isoformat()}

        # F-101: market-data InternalJWTMiddleware rejects unauthenticated
        # requests with HTTP 401. Inject a fresh dev-login-issued internal JWT.
        # On token-mint failure we still fire the request without a header so
        # the existing 401 warn-and-skip path stays as a fallback.
        token = await self._get_internal_jwt()
        headers = {"X-Internal-JWT": token} if token else {}

        try:
            # PLAN-0052 platform-QA round 7 (2026-05-01): explicit per-call
            # timeout ensures the worker cannot stall waiting on a half-open
            # market-data connection. The outer AsyncClient also sets 10s but
            # we mirror it here so this guarantee is co-located with the call.
            response = await self._client.get(url, params=params, headers=headers, timeout=10.0)
        except Exception as exc:
            logger.warning(  # type: ignore[no-any-return]
                "market_data_client_request_error",
                symbol=symbol,
                date=bar_date.isoformat(),
                error=str(exc),
            )
            return None

        if response.status_code == 404:
            return None

        if response.status_code != 200:
            logger.warning(  # type: ignore[no-any-return]
                "market_data_client_unexpected_status",
                symbol=symbol,
                date=bar_date.isoformat(),
                status_code=response.status_code,
            )
            return None

        try:
            data = response.json()
            items = data.get("items", [])
            if not items:
                return None
            bar = items[0]
            price_open = Decimal(str(bar["open"]))
            price_close = Decimal(str(bar["close"]))
            if price_open <= Decimal("0") or price_close <= Decimal("0"):
                logger.warning(  # type: ignore[no-any-return]
                    "market_data_client_invalid_prices",
                    symbol=symbol,
                    date=bar_date.isoformat(),
                    open=str(price_open),
                    close=str(price_close),
                )
                return None
            return OHLCVBar(
                symbol=symbol,
                date=bar_date,
                open=price_open,
                close=price_close,
                high=Decimal(str(bar["high"])),
                low=Decimal(str(bar["low"])),
                volume=bar.get("volume"),
            )
        except Exception as exc:
            logger.warning(  # type: ignore[no-any-return]
                "market_data_client_parse_error",
                symbol=symbol,
                date=bar_date.isoformat(),
                error=str(exc),
            )
            return None
