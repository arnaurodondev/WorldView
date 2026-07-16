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

    PREDICTION-MARKET AUTH GAP (2026-07-16, BP-73x): most methods reach S3 through
    the S9 api-gateway (``base_url``). In PROD the gateway's OIDC middleware only
    populates ``request.state.user`` from a real Zitadel ``Authorization: Bearer``
    token — it IGNORES the internal JWT that rag-chat forwards (the FIX-LIVE-S
    ``Authorization: Bearer <internal-jwt>`` shim in BaseUpstreamClient is a
    documented no-op in prod). So every S9-proxied catalog route that gates on
    ``request.state.user`` (incl. ``GET /v1/signals/prediction-markets``) returns
    401 → the tool yields [] → the chat pipeline refuses ("couldn't retrieve any
    data"). This IS the persistent prediction-market chat refusal: the routing/
    prompt fix (tool_use v1.25) correctly INVOKES the tool, but the tool's gateway
    call is then 401'd. ``get_prediction_markets`` therefore bypasses the gateway
    and speaks DIRECTLY to market-data's ``GET /api/v1/prediction-markets`` (which
    accepts the forwarded X-Internal-JWT via InternalJWTMiddleware) — the exact
    proven service-to-service pattern ``MarketTapeClient`` / ``S1Client`` already
    use. ``market_data_base_url`` is optional so existing tests/dev keep the
    gateway path unchanged when it is not wired.
    """

    def __init__(
        self,
        base_url: str,
        timeout: float = 5.0,
        *,
        market_data_base_url: str | None = None,
    ) -> None:
        super().__init__(base_url=base_url, timeout=timeout)
        # Dedicated direct-to-market-data client for the prediction-market tool
        # (see class docstring: the S9 gateway 401s the forwarded internal JWT in
        # prod). Reusing BaseUpstreamClient keeps the internal-JWT ContextVar
        # propagation + the 4xx→{} / 5xx→UpstreamTransportError taxonomy identical.
        self._md_direct: BaseUpstreamClient | None = (
            BaseUpstreamClient(base_url=market_data_base_url, timeout=timeout) if market_data_base_url else None
        )

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

    async def get_prediction_markets(
        self,
        query: str | None = None,
        category: str | None = None,
        status: str = "open",
        limit: int = 10,
    ) -> list[dict]:
        """Fetch Polymarket markets list → market-data ``GET /api/v1/prediction-markets``.

        ROUTING: when a direct market-data client is wired (``market_data_base_url``,
        the prod/default path) this calls market-data's ``/api/v1/prediction-markets``
        DIRECTLY with the forwarded X-Internal-JWT — bypassing the S9 gateway, whose
        OIDC middleware 401s a non-Zitadel Bearer in prod (the persistent
        prediction-market chat refusal; see class docstring). When it is NOT wired
        (dev/tests) it falls back to the S9 proxy route ``/v1/signals/prediction-markets``.
        Both hit the SAME market-data handler and forward ALL query params verbatim.

        Market-data's list endpoint supports a free-text (word-tokenised) ``query``
        filter on the market question plus ``category`` / ``status`` / ``limit``, so
        a keyword/topic/entity search needs NO new upstream endpoint. Wire shape:
        ``{"items": [...], "total", "limit", "offset"}``.

        Returns [] on any error (R9 safe degradation). ``query``/``category``
        are only sent when non-empty so an empty search lists the most
        recently-updated open markets.
        """
        params: dict = {"status": status, "limit": limit}
        if query:
            params["query"] = query
        if category:
            params["category"] = category
        # PROD AUTH GAP (see class docstring): the S9 gateway 401s the forwarded
        # internal JWT, so when a direct market-data client is wired we skip the
        # gateway and hit ``GET /api/v1/prediction-markets`` (the exact route S9
        # proxies to) with the same X-Internal-JWT market-data already accepts.
        # Falls back to the gateway path only when ``market_data_base_url`` was
        # not configured (dev/tests) to preserve existing behaviour.
        if self._md_direct is not None:
            raw = await self._md_direct._get("/api/v1/prediction-markets", params=params)
        else:
            raw = await self._get("/v1/signals/prediction-markets", params=params)
        if not raw:
            return []
        # S3/S9 wrap the rows in "items"; tolerate a "data" alias defensively.
        return raw.get("items") or raw.get("data") or []  # type: ignore[return-value]
