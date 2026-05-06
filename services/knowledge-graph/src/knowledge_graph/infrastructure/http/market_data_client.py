"""HTTP client for the S3 market-data service (PRD-0073 §9.5, T-C-1-03).

Calls two endpoints:
  GET /api/v1/instruments/lookup?extra_info=true   — DB-backed instrument data
  GET /api/v1/instruments/on-demand-profile        — DB-first + EODHD on-demand (internal JWT)

BP-235 guard: httpx.Timeout set explicitly; never rely on httpx default 5 s.
"""

from __future__ import annotations

from uuid import UUID

import httpx


class MarketDataClient:
    """Async HTTP client wrapping the two S3 enrichment endpoints.

    Args:
        base_url: Base URL of the market-data service (e.g. ``http://market-data:8003``).
        internal_jwt: RS256-signed system JWT attached to all requests as ``X-Internal-JWT``.
    """

    def __init__(self, base_url: str, internal_jwt: str) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(15.0),
            headers={"X-Internal-JWT": internal_jwt},
        )

    async def lookup(
        self,
        ticker: str | None = None,
        isin: str | None = None,
        entity_id: UUID | None = None,
    ) -> dict[str, object] | None:
        """Fetch an instrument row with enrichment fields from S3 DB.

        Always requests ``extra_info=true`` so the caller gets description/sector/etc.
        ``ticker`` maps to the ``symbol`` query param on the S3 endpoint (S3 spec uses
        ``symbol`` for case-insensitive ticker lookup).

        Returns the parsed JSON dict, or ``None`` if S3 returns 404.
        Raises ``httpx.HTTPStatusError`` for other non-2xx responses.
        """
        params: dict[str, str] = {"extra_info": "true"}
        if ticker:
            params["symbol"] = ticker
        if isin:
            params["isin"] = isin
        if entity_id:
            params["id"] = str(entity_id)

        resp = await self._client.get("/api/v1/instruments/lookup", params=params)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]

    async def on_demand_profile(
        self,
        ticker: str | None = None,
        isin: str | None = None,
    ) -> dict[str, object] | None:
        """Fetch (and persist) an EODHD on-demand profile via S3.

        Returns the parsed JSON dict, or ``None`` if S3 returns 404 (neither DB
        nor EODHD has a profile for this identifier).

        Raises ``httpx.HTTPStatusError`` on 429 (EODHD rate limit propagated by S3)
        — the caller must treat this as a retryable failure (PRD-0073 §13.2).
        """
        params = {k: v for k, v in [("ticker", ticker), ("isin", isin)] if v}
        resp = await self._client.get("/api/v1/instruments/on-demand-profile", params=params)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()  # 429 propagates as HTTPStatusError
        return resp.json()  # type: ignore[no-any-return]

    async def aclose(self) -> None:
        """Close the underlying httpx client connection pool."""
        await self._client.aclose()
