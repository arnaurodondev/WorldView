"""S3BriefClient — S9-proxied screener/movers/calendars HTTP adapter (PLAN-0081 Wave A).

WHY S9-proxied (not S3 direct): R14/R7 — all internal service-to-service calls go through
S9 for auth and rate limiting. The concrete endpoint paths are S9 proxy routes that
forward to S3 (Market Data) behind authentication.
"""

from __future__ import annotations

from rag_chat.infrastructure.clients.base import BaseUpstreamClient


class S3BriefClient(BaseUpstreamClient):
    """Concrete HTTP adapter for S9-proxied screener, movers, and calendar endpoints.

    Implements S3BriefPort Protocol (application/ports/upstream_clients.py).
    All methods return empty dicts/lists on any HTTP or network error (R9 safe degradation).
    Inherits X-Internal-JWT propagation from BaseUpstreamClient._get / _post.
    """

    async def screen_instruments(self, filters: dict) -> dict:
        """POST /v1/fundamentals/screen with JSON body → screener results.

        Returns {} on any error (R9). Caller checks for "instruments"/"results"/"data" key.
        """
        return await self._post("/v1/fundamentals/screen", payload=filters)

    async def get_top_movers(self, mover_type: str = "gainers", limit: int = 10, period: str = "1D") -> dict:
        """GET /v1/market/top-movers → top gainers/losers.

        C-2: period is uppercased before sending — S9 contract requires uppercase ("1D", "1W", "1M").
        Returns {} on any error (R9). Caller checks for "movers"/"data" key.
        """
        # WHY .upper(): S9 /v1/market/top-movers requires uppercase period tokens ("1D", "1W", "1M").
        # The LLM may pass lowercase values; normalise here so the contract is always satisfied.
        params: dict = {"type": mover_type, "limit": limit, "period": period.upper()}
        return await self._get("/v1/market/top-movers", params=params)

    async def get_economic_calendar(
        self,
        from_date: str | None = None,
        to_date: str | None = None,
        region: str | None = None,
    ) -> list[dict]:
        """GET /v1/fundamentals/economic-calendar → macro events list.

        S9 returns {"events": [...], "total": N}. Returns [] on any error (R9 safe degradation).
        """
        params: dict = {}
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        if region:
            params["region"] = region
        raw = await self._get("/v1/fundamentals/economic-calendar", params=params)
        if not raw:
            return []
        # H-1: _get() always returns dict; isinstance(raw, list) was dead code — removed.
        return raw.get("events") or raw.get("data") or []  # type: ignore[return-value]

    async def get_earnings_calendar(
        self,
        from_date: str | None = None,
        to_date: str | None = None,
    ) -> list[dict]:
        """GET /v1/fundamentals/earnings-calendar → earnings release dates list.

        C-1: S9 returns {"events": [...], "total": N} — NOT {"earnings": [...]}. Fixed.
        Returns [] on any error (R9 safe degradation).
        """
        params: dict = {}
        if from_date:
            params["from"] = from_date
        if to_date:
            params["to"] = to_date
        raw = await self._get("/v1/fundamentals/earnings-calendar", params=params)
        if not raw:
            return []
        # H-1: _get() always returns dict; isinstance(raw, list) was dead code — removed.
        # C-1: use "events" key (matches S9 contract), NOT "earnings" (never set by S9).
        return raw.get("events") or raw.get("data") or []  # type: ignore[return-value]
