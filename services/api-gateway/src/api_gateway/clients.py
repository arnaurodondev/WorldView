"""Typed HTTP clients for downstream services.

The gateway never calls services by raw URL — it uses these client classes
which provide typed method signatures and handle errors consistently.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Callable

    import httpx


class DownstreamError(Exception):
    """Raised when a downstream service returns an error."""

    def __init__(self, service: str, status: int, detail: str) -> None:
        self.service = service
        self.status = status
        self.detail = detail
        super().__init__(f"{service} returned {status}: {detail}")


@dataclass(frozen=True)
class ServiceClients:
    """Container for all downstream service HTTP clients."""

    portfolio: httpx.AsyncClient
    market_data: httpx.AsyncClient
    market_ingestion: httpx.AsyncClient
    content_ingestion: httpx.AsyncClient
    content_store: httpx.AsyncClient
    nlp_pipeline: httpx.AsyncClient
    knowledge_graph: httpx.AsyncClient
    rag_chat: httpx.AsyncClient
    alert: httpx.AsyncClient


async def _checked_get(
    client: httpx.AsyncClient,
    service_name: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """GET with error translation.

    ``headers`` are merged into the request so callers can forward
    ``X-Internal-JWT`` or other auth headers to downstream services.
    """
    resp = await client.get(path, headers=headers, **kwargs)
    if resp.status_code >= 400:
        # F-005: truncate error detail to avoid leaking internal service details to frontend
        raise DownstreamError(service_name, resp.status_code, resp.text[:200])
    return cast("dict[str, Any]", resp.json())


async def _checked_post(
    client: httpx.AsyncClient,
    service_name: str,
    path: str,
    *,
    headers: dict[str, str] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """POST with error translation.

    ``headers`` are merged into the request so callers can forward
    ``X-Internal-JWT`` or other auth headers to downstream services.
    """
    resp = await client.post(path, headers=headers, **kwargs)
    if resp.status_code >= 400:
        # F-005: truncate error detail to avoid leaking internal service details to frontend
        raise DownstreamError(service_name, resp.status_code, resp.text[:200])
    return cast("dict[str, Any]", resp.json())


# ── Typed wrappers ────────────────────────────────────────────────


async def get_company_overview(
    clients: ServiceClients,
    company_id: str,
    *,
    headers: dict[str, str] | None = None,
    make_headers: Callable[[], dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Compose CompanyOverview from Market Data.

    Returns the shape the frontend CompanyOverview TypeScript type expects:
      { instrument, quote, fundamentals, ohlcv }

    ``make_headers`` is a factory called once per downstream request, producing
    a fresh JWT with a unique JTI each time.  This prevents ``InternalJWTMiddleware``
    replay detection when all 4 parallel calls share the same JWT.

    ``headers`` is kept for backwards compatibility (tests, single calls).  If both
    are provided ``make_headers`` takes precedence.

    Parallel calls:
      - /api/v1/instruments/{id}                       → instrument metadata (required)
      - /api/v1/fundamentals/{id}/company-profile       → name / currency / GICS (optional)
      - /api/v1/ohlcv/{id}?timeframe=1d&start=<90d ago> → ~90 trading days chart (optional)
      - /api/v1/quotes/{id}                              → latest quote snapshot (optional)

    WHY start= instead of limit=: S3's OHLCV route accepts date-range parameters
    (start/end), not a bare row-count limit. Passing ``limit=30`` was silently
    ignored by FastAPI because the parameter name did not match any declared
    query param — only 2 bars were ever returned (the entire DB content at the
    time of the bug).  Using ``start=90 days ago`` guarantees ~90 trading-day
    bars of 1D data are returned regardless of ingestion timing, while S3's
    own ``limit`` param (default 200) provides a safe upper cap.
    """
    import asyncio
    from datetime import UTC, datetime, timedelta

    def _h() -> dict[str, str]:
        return make_headers() if make_headers is not None else (headers or {})

    async def _safe(path: str, **kwargs: Any) -> dict[str, Any]:
        """_checked_get variant that returns {} on any DownstreamError."""
        try:
            return await _checked_get(clients.market_data, "market-data", path, headers=_h(), **kwargs)
        except DownstreamError:
            return {}

    # Request 90 days of daily bars so the chart has enough history to render
    # meaningful trends even when markets are closed for holidays/weekends.
    # 90 calendar days ≈ 63 trading days — well above any 30-bar chart window.
    # Use UTC-aware datetime (.date()) per project UTC-only convention (CLAUDE.md Rule 7).
    start_90d_ago = (datetime.now(tz=UTC) - timedelta(days=90)).date().isoformat()

    # Instrument metadata is required; the rest degrade gracefully to null.
    # Each call gets its own fresh JWT via _h() so parallel calls don't share JTIs.
    # WHY 5 parallel calls (was 4): highlights gives us the header stats
    # (market_cap, pe_ratio) and technicals gives us the 52w range without
    # an extra round-trip after render. The general fundamentals endpoint
    # returns all sections in one call; we filter by section name below.
    instrument_raw, profile_raw, ohlcv_raw, quote_raw, all_fundamentals_raw = await asyncio.gather(
        _checked_get(clients.market_data, "market-data", f"/api/v1/instruments/{company_id}", headers=_h()),
        _safe(f"/api/v1/fundamentals/{company_id}/company-profile"),
        _safe(f"/api/v1/ohlcv/{company_id}", params={"timeframe": "1d", "start": start_90d_ago}),
        _safe(f"/api/v1/quotes/{company_id}"),
        _safe(f"/api/v1/fundamentals/{company_id}"),
    )

    # WHY KG entity_id lookup (not instrument_id): ADR-F-12 — KG entity_id ≠ instrument_id.
    # The market-data service (S3) has no entity_id; entity linking lives in S7.
    # We resolve instrument ticker → KG entity_id via the KG lookup endpoint so that
    # briefing/graph/news endpoints on the instrument page receive the correct KG id.
    # Falls back to company_id when the ticker isn't seeded in the KG.
    ticker_symbol: str = instrument_raw.get("symbol", "")
    kg_entity_id: str = company_id  # default: fall back to company_id (instrument_id)
    if ticker_symbol:
        try:
            kg_resp = await _checked_get(
                clients.knowledge_graph,
                "knowledge-graph",
                "/api/v1/entities/lookup",
                headers=_h(),
                params={"ticker": ticker_symbol},
            )
            if kg_resp.get("entity_id"):
                kg_entity_id = str(kg_resp["entity_id"])
        except Exception:  # noqa: S110
            pass  # KG lookup is best-effort; fall back to company_id

    # Extract name / currency / sector from the first company-profile record's data blob.
    profile_data: dict[str, Any] = {}
    for rec in profile_raw.get("records", []):
        profile_data = rec.get("data") or {}
        if profile_data:
            break

    # Extract highlights (market_cap, pe_ratio) and technicals (52w range) from
    # the all-sections fundamentals response. The general endpoint returns records
    # with a "section" field so we can filter without additional API calls.
    highlights_data: dict[str, Any] = {}
    technicals_data: dict[str, Any] = {}
    for rec in all_fundamentals_raw.get("records", []):
        section = rec.get("section", "")
        data = rec.get("data") or {}
        if section == "highlights" and not highlights_data:
            highlights_data = data
        elif section == "technicals_snapshot" and not technicals_data:
            technicals_data = data

    # Build the frontend Instrument shape.
    # WHY description from profile_data["Description"]: EODHD stores company
    # descriptions in the General.Description field of the fundamentals payload.
    # market-data persists this in company_profiles.data JSONB under key "Description".
    # S9 extracts it here so the frontend gets description in the same CompanyOverview
    # response — no extra round-trip needed (UI-004 fix, 2026-04-24).
    instrument: dict[str, Any] = {
        "instrument_id": instrument_raw.get("id", company_id),
        "entity_id": kg_entity_id,
        "ticker": instrument_raw.get("symbol", ""),
        "name": profile_data.get("Name") or instrument_raw.get("symbol", ""),
        "exchange": instrument_raw.get("exchange", ""),
        "currency": profile_data.get("Currency", "USD"),
        "gics_sector": profile_data.get("GicSector"),
        "gics_industry": profile_data.get("GicGroup"),
        "isin": profile_data.get("ISIN"),
        "country": profile_data.get("CountryISO"),
        "description": profile_data.get("Description") or None,
    }

    # Map the market-data QuoteResponse → frontend Quote shape (best-effort; no change/change_pct).
    quote: dict[str, Any] | None = None
    if quote_raw:
        last = quote_raw.get("last")
        quote = {
            "instrument_id": quote_raw.get("instrument_id", company_id),
            "ticker": instrument_raw.get("symbol", ""),
            "price": float(last) if last else 0.0,
            "change": 0.0,  # market-data QuoteResponse has no intraday change field
            "change_pct": 0.0,
            "timestamp": str(quote_raw.get("timestamp", "")),
            "volume": quote_raw.get("volume"),
        }

    # Normalize market-data OHLCVListResponse → frontend OHLCVResponse shape.
    # S3 returns: {items: [{bar_date, open: str, high: str, ...}], total, timeframe}
    # Frontend expects: {instrument_id, ticker, timeframe, bars: [{timestamp, open: float, ...}]}
    ohlcv_out: dict[str, Any] | None = None
    if ohlcv_raw:
        raw_items: list[dict[str, Any]] = ohlcv_raw.get("items") or []
        ohlcv_out = {
            "instrument_id": company_id,
            "ticker": instrument_raw.get("symbol", ""),
            "timeframe": "1D",
            "bars": [
                {
                    "timestamp": item.get("bar_date", ""),
                    "open": float(item["open"]) if item.get("open") else 0.0,
                    "high": float(item["high"]) if item.get("high") else 0.0,
                    "low": float(item["low"]) if item.get("low") else 0.0,
                    "close": float(item["close"]) if item.get("close") else 0.0,
                    "volume": item.get("volume") or 0,
                }
                for item in raw_items
            ],
        }

    # Build the overview fundamentals snapshot for the instrument detail header.
    # WHY here (not in FundamentalsTab): the header stats (market_cap, pe_ratio,
    # 52w range, daily_return) need to load with the initial overview request so
    # they appear before the user selects the Fundamentals tab. The FundamentalsTab
    # fetches a full detailed breakdown separately on tab activation.
    # daily_return is computed from the last two OHLCV bars (no dedicated endpoint).
    overview_fundamentals: dict[str, Any] | None = None
    if highlights_data or technicals_data:
        raw_bars = (ohlcv_out or {}).get("bars") or []
        daily_return: float | None = None
        if len(raw_bars) >= 2:
            prev_close = raw_bars[-2].get("close") or 0.0
            last_close = raw_bars[-1].get("close") or 0.0
            if prev_close > 0:
                daily_return = (last_close - prev_close) / prev_close

        market_cap_raw = highlights_data.get("MarketCapitalization")
        pe_raw = highlights_data.get("PERatio")
        w52_high_raw = technicals_data.get("52WeekHigh")
        w52_low_raw = technicals_data.get("52WeekLow")

        overview_fundamentals = {
            "market_cap": float(market_cap_raw) if market_cap_raw is not None else None,
            "pe_ratio": float(pe_raw) if pe_raw is not None else None,
            "week_52_high": float(w52_high_raw) if w52_high_raw is not None else None,
            "week_52_low": float(w52_low_raw) if w52_low_raw is not None else None,
            "daily_return": daily_return,
        }

    return {
        "instrument": instrument,
        "quote": quote,
        # Overview fundamentals: key header stats. FundamentalsTab fetches the
        # full per-section breakdown separately on tab activation.
        "fundamentals": overview_fundamentals,
        "ohlcv": ohlcv_out,
    }


async def get_relevant_news(
    clients: ServiceClients,
    limit: int = 20,
    *,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Get most relevant news articles.

    Proxies to S6 nlp-pipeline GET /news/top which provides display_relevance_score
    ranked articles.  Adds ``offset`` and ``limit`` envelope fields for frontend
    NewsResponse compatibility (the frontend expects {articles, total, offset, limit}).

    NOTE: S5 content-store never implemented /v1/articles/relevant; S6 /news/top
    is the canonical ranked-news source (PRD-0026).
    """
    raw = await _checked_get(
        clients.nlp_pipeline,
        "nlp-pipeline",
        "/api/v1/news/top",
        headers=headers,
        params={"limit": limit},
    )
    # Ensure envelope fields expected by the frontend NewsResponse type
    raw.setdefault("offset", 0)
    raw.setdefault("limit", limit)
    return raw


async def get_map_layers(
    clients: ServiceClients,
) -> dict[str, Any]:
    """Get map overlay layers (placeholder: returns available layer types)."""
    return {
        "layers": [
            {"id": "news", "label": "News Events", "enabled": True},
            {"id": "signals", "label": "NLP Signals", "enabled": False},
            {"id": "sentiment", "label": "Sentiment Heatmap", "enabled": False},
        ],
    }


# ── Composed endpoints (PRD-0028 Wave S9-3) ────────────────────────────────


# F-015: GICS official sector order (not alphabetical) — matches S&P GICS 2.0 hierarchy
GICS_SECTORS = [
    "Energy",
    "Materials",
    "Industrials",
    "Consumer Discretionary",
    "Consumer Staples",
    "Health Care",
    "Financials",
    "Information Technology",
    "Communication Services",
    "Utilities",
    "Real Estate",
]

# F-016: DB sector names come from EODHD/Yahoo Finance fundamentals and do NOT match
# GICS 2.0 display names. This map translates from GICS_SECTORS display names → DB values
# so the screener filter finds records. Without this map every query returns 0 results.
# Source of truth: SELECT DISTINCT sector FROM securities in market_data_db.
_GICS_TO_DB_SECTOR: dict[str, str] = {
    "Information Technology": "Technology",
    "Health Care": "Healthcare",
    "Consumer Discretionary": "Consumer Cyclical",
    "Consumer Staples": "Consumer Defensive",
    "Financials": "Financial Services",
    # These match exactly between GICS and DB:
    # "Energy", "Materials", "Industrials", "Communication Services",
    # "Utilities", "Real Estate"
}


async def _screener_for_sector(
    client: httpx.AsyncClient,
    sector: str,
    *,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Screen instruments for a single GICS sector sorted by daily_return.

    ``headers`` are forwarded so ``X-Internal-JWT`` reaches S3's
    InternalJWTMiddleware.
    Returns the raw S3 response or an error dict on failure.

    WHY _GICS_TO_DB_SECTOR: the DB stores Yahoo Finance-style sector names
    (e.g. "Technology"), but GICS_SECTORS uses official S&P GICS 2.0 names
    (e.g. "Information Technology"). Without this translation, 5 of 11 sectors
    return 0 results because the screener WHERE sector = 'Information Technology'
    matches nothing.
    """
    import json as _json

    db_sector = _GICS_TO_DB_SECTOR.get(sector, sector)
    body = _json.dumps(
        {
            "filters": [{"metric": "daily_return", "min_value": -100, "max_value": 100, "sector": db_sector}],
            "sort_by": "daily_return",
            "sort_order": "desc",
            "limit": 20,
        }
    )
    resp = await client.post(
        "/api/v1/fundamentals/screen",
        content=body.encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    if resp.status_code >= 400:
        return {"error": True, "sector": sector}
    # F-006: catch malformed JSON from downstream (e.g., HTML error page from reverse proxy)
    try:
        return cast("dict[str, Any]", resp.json())
    except Exception:
        return {"error": True, "sector": sector}


async def get_market_heatmap(
    clients: ServiceClients,
    *,
    period: str = "1D",
    headers: dict[str, str] | None = None,
    make_headers: Callable[[], dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Compute sector heatmap from S3 screener data (1D) or OHLCV aggregate (1W/1M).

    For 1D: makes 11 parallel S3 screener calls (one per GICS sector), computes
    average daily_return per sector. Uses asyncio.gather with return_exceptions=True
    so partial failures don't crash the whole heatmap (BP-114).

    For 1W/1M: calls the dedicated S3 /api/v1/market/sector-returns endpoint that
    computes period returns from OHLCV bars using LATERAL JOINs — far more efficient
    than 11 parallel screener calls, and uses proper weekly/monthly bar data.

    ``make_headers`` factory is called once per sector so each parallel call
    gets a unique JTI, preventing replay detection on market-data.
    ``headers`` is the fallback for backwards compatibility.
    """
    import asyncio

    # For weekly/monthly periods, call the dedicated S3 aggregate endpoint
    # rather than making 11 parallel screener calls. The S3 endpoint computes
    # averages from OHLCV bars for these longer timeframes.
    if period in ("1W", "1M"):
        _h = make_headers if make_headers is not None else (lambda: headers or {})
        resp = await clients.market_data.get(
            f"/api/v1/market/sector-returns?period={period}",
            headers=_h(),
        )
        if resp.status_code >= 400:
            raise DownstreamError("market-data", resp.status_code, resp.text)
        return cast("dict[str, Any]", resp.json())

    _h = make_headers if make_headers is not None else (lambda: headers or {})
    # _h() called 11x in the comprehension (before gather), each producing a
    # fresh JWT — coroutine objects capture the headers value at creation time.
    calls = [_screener_for_sector(clients.market_data, sector, headers=_h()) for sector in GICS_SECTORS]
    results = await asyncio.gather(*calls, return_exceptions=True)

    sectors = []
    # F-012: strict=True ensures len(results) == len(GICS_SECTORS) — catches gather bugs
    for sector_name, result in zip(GICS_SECTORS, results, strict=True):
        if isinstance(result, BaseException) or (isinstance(result, dict) and result.get("error")):
            sectors.append({"name": sector_name, "change_pct": None, "instrument_count": 0})
            continue
        instruments = result.get("results", [])
        daily_returns = [
            inst["metrics"]["daily_return"]
            for inst in instruments
            if inst.get("metrics", {}).get("daily_return") is not None
        ]
        avg_change = sum(daily_returns) / len(daily_returns) if daily_returns else None
        sectors.append(
            {
                "name": sector_name,
                # WHY * 100: S3 stores daily_return as a decimal fraction (0.031 = 3.1%).
                # The frontend HeatmapSector.change_pct field is treated as a percentage
                # value (0.16 = 0.16%) — multiply here so the display shows correct values.
                "change_pct": round(avg_change * 100, 2) if avg_change is not None else None,
                "instrument_count": len(instruments),
            }
        )

    return {"sectors": sectors}


async def get_top_movers(
    clients: ServiceClients,
    mover_type: str = "gainers",
    limit: int = 10,
    period: str = "1D",
    *,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Get top gainers or losers from the screener (1D) or OHLCV bars (1W/1M).

    For 1D: composes a single S3 screener call with sort_by=daily_return and the
    appropriate sort order (desc for gainers, asc for losers).

    For 1W/1M: calls the dedicated S3 /api/v1/market/period-movers endpoint that
    computes period returns from OHLCV bars — more accurate than screener which
    only has the current day's daily_return metric.

    ``headers`` are forwarded so ``X-Internal-JWT`` reaches S3's
    InternalJWTMiddleware.
    """
    import json as _json

    # For weekly/monthly periods, call the dedicated S3 period-movers endpoint.
    if period in ("1W", "1M"):
        resp = await clients.market_data.get(
            f"/api/v1/market/period-movers?period={period}&type={mover_type}&limit={limit}",
            headers=headers or {},
        )
        if resp.status_code >= 400:
            raise DownstreamError("market-data", resp.status_code, resp.text)
        return cast("dict[str, Any]", resp.json())

    sort_order = "desc" if mover_type == "gainers" else "asc"
    body = _json.dumps(
        {
            "filters": [{"metric": "daily_return", "min_value": -100, "max_value": 100}],
            "sort_by": "daily_return",
            "sort_order": sort_order,
            "limit": limit,
        }
    )
    resp = await clients.market_data.post(
        "/api/v1/fundamentals/screen",
        content=body.encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    if resp.status_code >= 400:
        raise DownstreamError("market-data", resp.status_code, resp.text)
    return cast("dict[str, Any]", resp.json())


# ── Watchlist insights composer (PLAN-0050 Wave B / T-B-2-01) ──────────────────


async def get_watchlist_insights(
    clients: ServiceClients,
    watchlist_id: str,
    *,
    make_headers: Callable[[], dict[str, str]],
    member_overview_cap: int = 25,
    news_lookback_hours: int = 24,
) -> dict[str, Any]:
    """Composite insights for a single watchlist (PLAN-0050 T-B-2-01).

    Returns one payload that combines members, live quotes, sector breakdown,
    24h news linkage, and pending alerts — replacing the WatchlistMoversWidget's
    prior 4-query fan-out (S1 members, S3 quotes, S3 overviews per member, S6
    news, S10 alerts) with a single round-trip from the frontend's perspective.

    Why a composite (not 5 frontend hooks):
      - Cuts dashboard initial-load round-trips by ~80% for users with a
        non-trivial watchlist (10+ tickers ⇒ 11 requests collapse to 1).
      - Lets the gateway dedupe overview lookups across members that share a
        sector and short-circuit the news/alert filters once we know the
        member set — the browser cannot do either as cheaply.
      - Keeps the frontend free of any cross-service JOIN logic, matching
        ADR-F-XX (frontend talks only to S9; never composes downstream data).

    Why best-effort sub-calls (each downstream wrapped in _safe-style try/except):
      - A flaky news service must not break the dashboard's gainers/losers
        list. Each enrichment degrades gracefully to an empty default so the
        primary information (movers) always renders.

    Response shape (frontend `WatchlistInsightsResponse` type — see
    apps/worldview-web/types/api.ts):
      {
        "watchlist_id": str,
        "members_count": int,
        "movers": [
          {
            "instrument_id", "ticker", "name", "sector", "price",
            "change_pct", "news_count_24h", "has_active_alert",
            "top_news_title": str | None,
            "top_news_url": str | None
          }
        ],
        "weighted_return_1d": float | None,    # equal-weight avg over members with quotes
        "sectors": [ { "sector": str, "weight": float, "count": int } ],
        "biggest_news": { … } | None,          # highest-impact article touching any member
        "alerts_count": int                    # count of pending alerts that match members
      }
    """
    import asyncio

    def _h() -> dict[str, str]:
        return make_headers()

    async def _safe_get(
        client: httpx.AsyncClient,
        service: str,
        path: str,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Best-effort GET — returns {} on any DownstreamError."""
        try:
            return await _checked_get(client, service, path, headers=_h(), **kwargs)
        except DownstreamError:
            return {}

    # ── 1. Members + news + alerts in parallel ─────────────────────────────────
    # WHY parallel: members controls the rest of the composition, but news +
    # alerts are watchlist-agnostic until we know the member set, so we can
    # speculatively fetch the global lists in the same window. We filter by
    # member identity once members resolves.
    #
    # F-QA-01 fix: members MUST use _checked_get (not _safe_get). S1 enforces
    # ownership on /watchlists/{id}/members — a 403/404 from S1 means "this is
    # not your watchlist (or it doesn't exist)". The prior _safe_get swallowed
    # those errors and returned an empty 200, which is BOTH a correctness bug
    # (user sees their own watchlist as empty) AND a contract leak (the
    # gateway silently overrides S1's permission decision). Best-effort policy
    # is correct only for ENRICHMENT sub-calls (news/alerts/quotes/overviews).
    async def _members() -> dict[str, Any]:
        return await _checked_get(
            clients.portfolio,
            "portfolio",
            f"/api/v1/watchlists/{watchlist_id}/members",
            headers=_h(),
        )

    members_raw, news_raw, alerts_raw = await asyncio.gather(
        _members(),
        # 30 articles is enough to find a few hits for a typical 5-25-ticker
        # watchlist while staying within the S6 endpoint's healthy range.
        _safe_get(clients.nlp_pipeline, "nlp-pipeline", "/api/v1/news/top", params={"limit": 30}),
        _safe_get(clients.alert, "alert", "/api/v1/alerts/pending", params={"limit": 50}),
    )

    members: list[dict[str, Any]] = members_raw.get("members") or []
    # Filter to members with a resolved instrument_id — matches the widget's
    # client-side filter so we never compute insights against unresolved rows.
    resolved_members = [m for m in members if m.get("instrument_id")]
    members_count = len(resolved_members)
    instrument_ids = [str(m["instrument_id"]) for m in resolved_members]
    entity_ids = {str(m.get("entity_id")) for m in resolved_members if m.get("entity_id")}

    # ── 2. Per-member quote + overview (parallel, capped) ──────────────────────
    # WHY cap at 25: users with a 100-symbol watchlist would otherwise fan out
    # 200 downstream requests. The widget renders only top-5 gainers + losers,
    # so 25 is more than enough to find the extremes without amplifying load.
    capped_ids = instrument_ids[:member_overview_cap]

    async def _quote(iid: str) -> dict[str, Any]:
        # F-Q1-02 fix (PLAN-0050 QA iter-1): switch from the legacy internal
        # QuoteResponse endpoint (/api/v1/quotes/{iid}) to the PriceSnapshot
        # endpoint (/internal/v1/price/{iid}).
        #
        # WHY: the legacy endpoint returns {last, bid, ask, volume, timestamp}
        # which has NO change_pct field.  Every mover was showing change_pct=null
        # because quote.get("change_pct") always returned None.  The PriceSnapshot
        # endpoint is the authoritative price source for S9 (used by the /v1/quotes
        # proxy) and returns {price, price_change, price_change_pct, ...}.
        #
        # WHY not call S9's own /v1/quotes/{iid}: that would add a loopback HTTP
        # hop (gateway → gateway).  Calling S3 directly via the market_data client
        # is cheaper and already the pattern used by the /v1/quotes proxy route.
        #
        # F-Q1-08 closed by this same fix: the stale `last` price from the legacy
        # quote table (e.g. NVDA 199.64 vs 209.53) came from reading the wrong
        # field.  PriceSnapshot's `price` field is resolved via the freshness chain
        # (FRESH_QUOTE → BULK_QUOTE → INTRADAY → DAILY_CLOSE → STALE) — same
        # authoritative source that the instrument detail page uses.
        snap = await _safe_get(clients.market_data, "market-data", f"/internal/v1/price/{iid}")
        if not snap:
            return {}
        # Map PriceSnapshot fields → the shape the composer reads below:
        #   price       ← snap["price"]          (best available price string)
        #   change_pct  ← snap["price_change_pct"] (signed % change string or None)
        price_str = snap.get("price")
        pct_str = snap.get("price_change_pct")
        try:
            price = float(price_str) if price_str is not None else None
        except (ValueError, TypeError):
            price = None
        try:
            change_pct = float(pct_str) if pct_str is not None else None
        except (ValueError, TypeError):
            change_pct = None
        # Return a normalised dict that uses the same field names the loop below
        # reads so we do not have to touch the per-member construction block.
        return {"price": price, "change_pct": change_pct}

    async def _overview(iid: str) -> dict[str, Any]:
        # Just the instrument record gives us GICS sector — the per-member
        # `getCompanyOverview` would also fetch fundamentals + OHLCV which we
        # don't need here. Saves ~3x the per-member load.
        return await _safe_get(clients.market_data, "market-data", f"/api/v1/instruments/{iid}")

    quote_results, overview_results = await asyncio.gather(
        asyncio.gather(*[_quote(iid) for iid in capped_ids]),
        asyncio.gather(*[_overview(iid) for iid in capped_ids]),
    )

    # ── 3. Index news + alerts by entity for O(1) per-member lookup ────────────
    # WHY entity_id (not instrument_id): articles + alerts are tagged with KG
    # entity_id (ADR-F-12). Matching against instrument_id would silently miss
    # everything because instrument_id ≠ entity_id by design.
    news_articles = news_raw.get("articles") or []
    # Cutoff for the "news_count_24h" badge. The frontend cares about
    # "did this name make the news today?" — older articles inflate the count.
    from datetime import UTC, datetime, timedelta

    cutoff = datetime.now(tz=UTC) - timedelta(hours=news_lookback_hours)
    news_by_entity: dict[str, list[dict[str, Any]]] = {}
    for art in news_articles:
        # F-QA2-01 fix: S6's RankedArticleResponse emits `primary_entity_id`
        # (singular, optional UUID) — NOT a `entity_ids` list. The prior
        # implementation read a non-existent field, so news_by_entity was
        # always empty and every member's news_count_24h was 0 in
        # production. We also accept a fallback `entity_ids` list shape
        # so tests and any future schema change that introduces multiple
        # tagged entities still flow through.
        primary_eid = art.get("primary_entity_id")
        ents: list[str] = []
        if isinstance(primary_eid, str) and primary_eid:
            ents.append(primary_eid)
        legacy = art.get("entity_ids")
        if isinstance(legacy, list):
            ents.extend(str(x) for x in legacy if x)
        if not ents:
            continue
        # Apply the 24h cutoff. published_at is ISO 8601 — best-effort parse.
        published = art.get("published_at")
        in_window = True
        if isinstance(published, str):
            try:
                # Accept both with/without timezone — assume UTC if naive.
                ts = datetime.fromisoformat(published.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=UTC)
                in_window = ts >= cutoff
            except ValueError:
                in_window = True  # malformed date → keep it
        if not in_window:
            continue
        for eid in ents:
            news_by_entity.setdefault(eid, []).append(art)

    # Pending alerts indexed by entity_id (each alert may reference one).
    alerts_by_entity: dict[str, int] = {}
    pending_alerts = alerts_raw.get("alerts") or []
    for alert in pending_alerts:
        eid = alert.get("entity_id")
        if eid:
            alerts_by_entity[str(eid)] = alerts_by_entity.get(str(eid), 0) + 1

    # ── 4. Build per-member rows ───────────────────────────────────────────────
    # We zip the parallel quote + overview results back to the resolved-member
    # list. Anything past member_overview_cap gets a price-only row (no
    # sector / news / alert lookup) — those rows still render but without
    # enrichment, which is the right tradeoff for very large watchlists.
    movers_out: list[dict[str, Any]] = []
    for idx, member in enumerate(resolved_members):
        iid = str(member["instrument_id"])
        ticker = member.get("ticker") or "—"
        name = member.get("name") or ticker
        eid = str(member.get("entity_id") or "")

        if idx < len(quote_results):
            quote = quote_results[idx]
            overview = overview_results[idx]
            # F-Q1-02: _quote() now returns {"price": float|None, "change_pct": float|None}
            # normalised from PriceSnapshot (not the legacy QuoteResponse {last, bid, ask}).
            last = quote.get("price")
            change_pct = quote.get("change_pct")
            sector = (overview or {}).get("gics_sector") or member.get("sector")
        else:
            last = None
            change_pct = None
            sector = member.get("sector")

        # Top news for this member, if any. We pick the highest impact_score.
        member_news = news_by_entity.get(eid, []) if eid else []
        member_news_sorted = sorted(
            member_news,
            key=lambda a: float(a.get("market_impact_score") or a.get("display_relevance_score") or 0.0),
            reverse=True,
        )
        top_news = member_news_sorted[0] if member_news_sorted else None

        movers_out.append(
            {
                "instrument_id": iid,
                "entity_id": eid or None,
                "ticker": ticker,
                "name": name,
                "sector": sector,
                # F-Q1-02: `last` is already a float|None from the PriceSnapshot
                # normalisation in _quote().  The float() cast remains for the
                # fallback path (idx >= member_overview_cap) where last is still None.
                "price": float(last) if last is not None else None,
                "change_pct": float(change_pct) if change_pct is not None else None,
                "news_count_24h": len(member_news),
                # F-QA-06 fix: defensive against an empty-string entity_id
                # accidentally matching all members without an entity_id. The
                # alerts_by_entity build already filters falsy keys, but the
                # explicit `bool(eid)` guard means a future regression that
                # lets "" through cannot reintroduce the false-positive.
                "has_active_alert": bool(eid) and eid in alerts_by_entity,
                "top_news_title": (top_news or {}).get("title"),
                "top_news_url": (top_news or {}).get("url"),
            }
        )

    # ── 5. Aggregates ─────────────────────────────────────────────────────────
    # Equal-weighted return: average change_pct across members for which we
    # actually got a live quote. Members without a quote do not contribute
    # (treating them as 0 would lie about the watchlist's day).
    contributing = [m["change_pct"] for m in movers_out if m["change_pct"] is not None]
    weighted_return_1d: float | None = sum(contributing) / len(contributing) if contributing else None

    # Sector breakdown — count of members in each GICS bucket. The widget
    # renders this as a stacked horizontal mini-bar so we return both count
    # and weight (count / members_count) for convenience.
    sector_counts: dict[str, int] = {}
    for m in movers_out:
        s = m["sector"] or "Unknown"
        sector_counts[s] = sector_counts.get(s, 0) + 1
    total_with_sector = sum(sector_counts.values()) or 1
    sectors_out: list[dict[str, Any]] = sorted(
        ({"sector": s, "count": c, "weight": c / total_with_sector} for s, c in sector_counts.items()),
        key=lambda x: cast("int", x["count"]),
        reverse=True,
    )

    # Biggest news (T-B-2-06): highest-impact article whose entity touches ANY
    # watchlist member. Falls back to None on a quiet news day.
    member_news_pool: list[dict[str, Any]] = []
    for eid in entity_ids:
        member_news_pool.extend(news_by_entity.get(eid, []))
    # Dedup by article_id (an article can mention multiple watchlist members).
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for art in member_news_pool:
        aid = str(art.get("article_id") or "")
        if aid and aid in seen:
            continue
        if aid:
            seen.add(aid)
        deduped.append(art)
    biggest_news_article = max(
        deduped,
        key=lambda a: float(a.get("market_impact_score") or a.get("display_relevance_score") or 0.0),
        default=None,
    )
    biggest_news_out: dict[str, Any] | None = None
    if biggest_news_article is not None:
        biggest_news_out = {
            "article_id": biggest_news_article.get("article_id"),
            "title": biggest_news_article.get("title"),
            "url": biggest_news_article.get("url"),
            "published_at": biggest_news_article.get("published_at"),
            "ticker": biggest_news_article.get("ticker"),
            "impact_score": (
                float(biggest_news_article["market_impact_score"])
                if biggest_news_article.get("market_impact_score") is not None
                else None
            ),
        }

    # Pending alert count restricted to members.
    alerts_count = sum(alerts_by_entity.get(eid, 0) for eid in entity_ids)

    # F-Q1-13 fix (PLAN-0050 QA iter-1): sort movers by absolute change_pct
    # descending so the WatchlistMoversWidget's gainers/losers split always
    # shows the MOST moved instruments, not whatever order S1 returns members.
    #
    # WHY server-side (not client-side): the frontend renders the top-N from
    # this list without re-sorting; the gateway cap (member_overview_cap=25) means
    # an alphabetically-first watchlist member would monopolise top-5 slots if
    # we returned them unsorted.  Sorting here guarantees the extremes appear
    # first regardless of watchlist member order.
    #
    # WHY abs(): a -5% mover is equally "interesting" as a +5% mover for the
    # purpose of identifying the most volatile names.  Members with null
    # change_pct (no price data) are pushed to the end.
    movers_out.sort(
        key=lambda m: abs(m["change_pct"]) if m["change_pct"] is not None else -1.0,
        reverse=True,
    )

    return {
        "watchlist_id": watchlist_id,
        "members_count": members_count,
        "movers": movers_out,
        "weighted_return_1d": weighted_return_1d,
        "sectors": sectors_out,
        "biggest_news": biggest_news_out,
        "alerts_count": alerts_count,
    }
