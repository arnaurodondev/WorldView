"""Finnhub provider adapter — NEWS_SENTIMENT, EARNINGS_CALENDAR, INSIDER_TRANSACTIONS."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any, cast

import httpx

from common.time import utc_now  # type: ignore[import-untyped]
from market_ingestion.application.ports.adapters import ProviderFetchResult
from market_ingestion.domain.enums import DatasetType, Provider
from market_ingestion.domain.errors import (
    ProviderAuthError,
    ProviderDataError,
    ProviderRateLimited,
    ProviderUnavailable,
)
from market_ingestion.infrastructure.adapters.providers.base import BaseProviderAdapter

_BASE_URL = "https://finnhub.io/api/v1"

# Finnhub free tier: 60 req/min = 1 req/second
# Sleep slightly over 1s to stay safely under the limit
_RATE_LIMIT_SLEEP = 1.1

# Process-level lock to serialize Finnhub requests.  Without this, multiple
# concurrent tasks (e.g. from asyncio.gather in the worker loop) can fire
# overlapping requests and exceed the 60 req/min free-tier cap.  The lock
# does NOT coordinate across OS processes — for multi-replica deployments,
# the distributed Valkey rate limiter handles cross-process coordination.
_FINNHUB_LOCK = asyncio.Lock()


class FinnhubProviderAdapter(BaseProviderAdapter):
    """Finnhub adapter for NEWS_SENTIMENT, EARNINGS_CALENDAR, INSIDER_TRANSACTIONS.

    Free tier: 60 req/min. API key required.
    All supported methods emit 'provider_api_call' structlog events via BaseProviderAdapter.
    Credit cost is always 0 (free provider).
    """

    def __init__(self, api_key: str, client: httpx.AsyncClient) -> None:
        self._api_key = api_key
        self._client = client

    @property
    def provider(self) -> Provider:
        return Provider.FINNHUB

    # ── Unsupported methods (raise ProviderUnavailable) ────────────────────────

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str,
        start: Any,
        end: Any,
        exchange: str | None = None,
    ) -> ProviderFetchResult:
        raise ProviderUnavailable("Finnhub does not provide OHLCV; use EODHD or Yahoo Finance")

    async def fetch_quotes(self, symbol: str, exchange: str | None = None) -> ProviderFetchResult:
        raise ProviderUnavailable("Finnhub real-time quotes require paid tier")

    async def fetch_fundamentals(
        self, symbol: str, variant: str = "annual", exchange: str | None = None
    ) -> ProviderFetchResult:
        raise ProviderUnavailable("Finnhub fundamentals not in scope for Wave A-2")

    # ── Supported methods ──────────────────────────────────────────────────────

    async def fetch_news_sentiment(
        self,
        symbol: str,
        from_date: str,
        to_date: str,
    ) -> ProviderFetchResult:
        """Fetch company news for *symbol* over [from_date, to_date].

        Finnhub: GET /company-news?symbol=AAPL&from=2024-01-01&to=2024-01-07&token=<key>
        """
        url = f"{_BASE_URL}/company-news"
        params = {
            "symbol": symbol,
            "from": from_date,
            "to": to_date,
            "token": self._api_key,
        }
        t0 = time.monotonic()
        raw = await self._get(url, params)
        duration_ms = int((time.monotonic() - t0) * 1000)

        try:
            parsed = json.loads(raw)
            bars_returned = len(parsed) if isinstance(parsed, list) else 1
        except Exception:
            bars_returned = 0

        self._record_api_call(
            dataset_type=DatasetType.NEWS_SENTIMENT.value,
            symbol=symbol,
            timeframe="",
            bars_returned=bars_returned,
            latency_ms=duration_ms,
            credit_cost=0,
        )
        return ProviderFetchResult(
            provider=Provider.FINNHUB,
            dataset_type=DatasetType.NEWS_SENTIMENT,
            symbol=symbol,
            raw_data=raw,
            content_type="application/json",
            fetched_at=utc_now(),
            duration_ms=duration_ms,
            bars_returned=bars_returned,
        )

    async def fetch_earnings_calendar(
        self,
        from_date: str,
        to_date: str,
    ) -> ProviderFetchResult:
        """Fetch all earnings events over [from_date, to_date] (no symbol filter on free tier).

        Finnhub: GET /calendar/earnings?from=2024-01-01&to=2024-01-14&token=<key>
        """
        url = f"{_BASE_URL}/calendar/earnings"
        params: dict[str, Any] = {
            "from": from_date,
            "to": to_date,
            "token": self._api_key,
        }
        t0 = time.monotonic()
        raw = await self._get(url, params)
        duration_ms = int((time.monotonic() - t0) * 1000)

        try:
            parsed = json.loads(raw)
            # Response shape: {"earningsCalendar": [...]}
            items = parsed.get("earningsCalendar", []) if isinstance(parsed, dict) else []
            bars_returned = len(items)
        except Exception:
            bars_returned = 0

        self._record_api_call(
            dataset_type=DatasetType.EARNINGS_CALENDAR.value,
            symbol="CALENDAR",
            timeframe="",
            bars_returned=bars_returned,
            latency_ms=duration_ms,
            credit_cost=0,
        )
        return ProviderFetchResult(
            provider=Provider.FINNHUB,
            dataset_type=DatasetType.EARNINGS_CALENDAR,
            symbol="CALENDAR",
            raw_data=raw,
            content_type="application/json",
            fetched_at=utc_now(),
            duration_ms=duration_ms,
            bars_returned=bars_returned,
        )

    async def fetch_insider_transactions(self, ticker: str) -> ProviderFetchResult:
        """Fetch insider transactions for *ticker*.

        Finnhub: GET /stock/insider-transactions?symbol=AAPL&token=<key>
        Note: parameter name is 'ticker' per execute_task.py call site.
        """
        url = f"{_BASE_URL}/stock/insider-transactions"
        params: dict[str, Any] = {
            "symbol": ticker,
            "token": self._api_key,
        }
        t0 = time.monotonic()
        raw = await self._get(url, params)
        duration_ms = int((time.monotonic() - t0) * 1000)

        try:
            parsed = json.loads(raw)
            # Response shape: {"data": [...], "symbol": "AAPL"}
            items = parsed.get("data", []) if isinstance(parsed, dict) else []
            bars_returned = len(items)
        except Exception:
            bars_returned = 0

        self._record_api_call(
            dataset_type=DatasetType.INSIDER_TRANSACTIONS.value,
            symbol=ticker,
            timeframe="",
            bars_returned=bars_returned,
            latency_ms=duration_ms,
            credit_cost=0,
        )
        return ProviderFetchResult(
            provider=Provider.FINNHUB,
            dataset_type=DatasetType.INSIDER_TRANSACTIONS,
            symbol=ticker,
            raw_data=raw,
            content_type="application/json",
            fetched_at=utc_now(),
            duration_ms=duration_ms,
            bars_returned=bars_returned,
        )

    # ── Private HTTP helper ────────────────────────────────────────────────────

    async def _get(self, url: str, params: dict[str, Any]) -> bytes:
        """Execute GET request, map HTTP errors to domain errors.

        Acquires ``_FINNHUB_LOCK`` so that only one Finnhub request is in
        flight per process at any time, then sleeps ``_RATE_LIMIT_SLEEP``
        seconds before releasing the lock.
        """
        # Never log url with params — contains api_token
        endpoint = self._sanitize_url_slug(url)
        async with _FINNHUB_LOCK:
            try:
                response = await self._client.get(url, params=params, timeout=30.0)
            except httpx.ConnectError as exc:
                self._record_error(reason="connection_error", endpoint=endpoint)
                raise ProviderUnavailable(f"Finnhub connection error: {type(exc).__name__}") from exc
            except httpx.TimeoutException as exc:
                self._record_error(reason="timeout", endpoint=endpoint)
                raise ProviderUnavailable(f"Finnhub request timeout: {type(exc).__name__}") from exc

            # Sleep inside the lock so the next request cannot start until the
            # rate-limit cooldown has elapsed.
            await asyncio.sleep(_RATE_LIMIT_SLEEP)

        if response.status_code == 429:
            self._record_rate_limited(endpoint=endpoint)
            retry_after: float | None = None
            if "Retry-After" in response.headers:
                import contextlib

                with contextlib.suppress(ValueError):
                    retry_after = float(response.headers["Retry-After"])
            raise ProviderRateLimited("Finnhub rate limit exceeded", retry_after=retry_after)

        if response.status_code in (401, 403):
            self._record_error(reason="auth_error", endpoint=endpoint)
            raise ProviderAuthError(f"Finnhub auth error HTTP {response.status_code}")

        if response.status_code >= 500:
            self._record_error(reason=f"http_{response.status_code}", endpoint=endpoint)
            raise ProviderUnavailable(f"Finnhub server error HTTP {response.status_code}")

        if response.status_code != 200:
            self._record_error(reason=f"http_{response.status_code}", endpoint=endpoint)
            raise ProviderDataError(f"Finnhub unexpected status {response.status_code}")

        return cast("bytes", response.content)
