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
        "entity_id": instrument_raw.get("id", company_id),
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

    ``headers`` are forwarded to S5 for ``X-Internal-JWT`` authentication.
    """
    return await _checked_get(
        clients.content_store,
        "content-store",
        "/v1/articles/relevant",
        headers=headers,
        params={"limit": limit},
    )


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
    """
    import json as _json

    body = _json.dumps(
        {
            "filters": [{"metric": "daily_return", "min_value": -100, "max_value": 100, "sector": sector}],
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
    headers: dict[str, str] | None = None,
    make_headers: Callable[[], dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Compute sector heatmap from S3 screener data.

    Makes 11 parallel S3 screener calls (one per GICS sector), computes average
    daily_return per sector. Uses asyncio.gather with return_exceptions=True
    so partial failures don't crash the whole heatmap (BP-114).

    ``make_headers`` factory is called once per sector so each parallel call
    gets a unique JTI, preventing replay detection on market-data.
    ``headers`` is the fallback for backwards compatibility.
    """
    import asyncio

    _h = make_headers if make_headers is not None else (lambda: (headers or {}))
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
                "change_pct": round(avg_change, 4) if avg_change is not None else None,
                "instrument_count": len(instruments),
            }
        )

    return {"sectors": sectors}


async def get_top_movers(
    clients: ServiceClients,
    mover_type: str = "gainers",
    limit: int = 10,
    *,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Get top gainers or losers from the screener.

    Composes a single S3 screener call with sort_by=daily_return and the appropriate
    sort order (desc for gainers, asc for losers).

    ``headers`` are forwarded so ``X-Internal-JWT`` reaches S3's
    InternalJWTMiddleware.
    """
    import json as _json

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
