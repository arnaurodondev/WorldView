"""Async EODHD fundamentals client.

Only the ``get_fundamentals`` method is needed for PLAN-0073 Worker 13J —
it fetches the General section of the EODHD fundamentals API and returns the
raw JSON dict, leaving field extraction to the application layer.

BP-235: httpx.Timeout MUST be set explicitly (httpx default 5 s fires before
asyncio.wait_for timeout and raises ReadTimeout instead of CancelledError,
which is not caught as a transient error).
"""

from __future__ import annotations

import httpx
import structlog

from market_data.domain.errors import EodhRateLimitError

logger: structlog.stdlib.BoundLogger = structlog.get_logger(__name__)  # type: ignore[no-any-return]


class EodhHdClient:
    """Thin async wrapper around the EODHD REST fundamentals endpoint."""

    def __init__(self, api_key: str, base_url: str = "https://eodhd.com") -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        # BP-235: explicit timeout prevents httpx 5 s default from firing before
        # any asyncio.wait_for wrapper and producing an uncaught ReadTimeout.
        # F-D10: cap the connection pool to 5 concurrent / 2 keep-alive so that
        # bursty traffic (e.g. KG enrichment Worker 13J fan-out) cannot
        # accidentally exceed EODHD's per-IP concurrency tier.  Anything beyond
        # that queues inside httpx instead of being rejected by EODHD's edge.
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(10.0),
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=2),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_fundamentals(self, ticker: str, exchange: str) -> dict | None:
        """Fetch EODHD fundamentals for ``{ticker}.{exchange}``; return raw JSON.

        Returns ``None`` when the symbol is not found (HTTP 404).
        Raises ``EodhRateLimitError`` on HTTP 429.
        Raises ``httpx.HTTPStatusError`` for any other 4xx/5xx.
        """
        url = f"{self._base_url}/api/fundamentals/{ticker}.{exchange}"
        params = {"api_token": self._api_key, "fmt": "json"}

        log = logger.bind(ticker=ticker, exchange=exchange)
        try:
            resp = await self._client.get(url, params=params)
        except httpx.RequestError as exc:
            log.warning("eodhd_request_error", error=str(exc))
            raise

        if resp.status_code == 404:
            log.info("eodhd_symbol_not_found")
            return None

        if resp.status_code == 429:
            log.warning("eodhd_rate_limited")
            raise EodhRateLimitError("EODHD rate limit exceeded")

        resp.raise_for_status()

        data: dict = resp.json()
        log.debug("eodhd_fundamentals_fetched")
        return data
