"""Market data routes for the API Gateway.

Handles /v1/ohlcv/*, /v1/quotes/*, /v1/market/*, /v1/fundamentals/* (screener + timeseries
+ section endpoints), /v1/signals/ai — proxies to S3 Market Data and S7 KG.
Split from proxy.py (PLAN-0089 B-3).
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from api_gateway.clients import (
    DownstreamError,
    get_market_heatmap,
    get_top_movers,
)
from api_gateway.routes.helpers import _auth_headers, _clients, _system_headers
from api_gateway.schemas import (
    EarningsCalendarResponse,
    FundamentalsResponse,
    OHLCVResponse,
    QuoteResponse,
)
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Callable

logger = get_logger(__name__)  # type: ignore[no-any-return]

router = APIRouter(prefix="/v1")


# ── Screener + Timeseries (PRD-0017 Wave C-1) ─────────────────────────────────


def _flatten_screener_result(item: dict[str, Any]) -> dict[str, Any]:
    """Transform S3 ScreenInstrumentResponse → frontend-friendly flat ScreenerResult.

    WHY transform at the BFF layer: S3 stores metrics in a nested dict keyed on
    metric name (e.g. {"market_capitalization": 4.01e12}).  The frontend TypeScript
    ScreenerResult expects flat top-level fields (market_cap, pe_ratio, …) with
    renamed keys.  Applying the mapping once here avoids duplicating the logic in
    every frontend component that reads screener data.

    Mapping table (S3 metric key → frontend field name):
      market_capitalization → market_cap
      pe_ratio              → pe_ratio          (same)
      daily_return          → daily_return       (same)
      beta                  → beta               (same)
      dividend_yield        → dividend_yield     (same)
      quarterly_revenue_growth_yoy → revenue_growth_yoy
      roe_ttm               → roe
      profit_margin         → net_margin (not in ScreenerResult yet; forwarded raw)
      sector (top-level)    → gics_sector

    Any metric key not listed above is forwarded under its original name so new
    S3 metrics are surfaced without a gateway schema change.
    """
    metrics: dict[str, float | None] = item.get("metrics") or {}

    # Rename specific metric keys to match TypeScript ScreenerResult
    _renames: dict[str, str] = {
        "market_capitalization": "market_cap",
        "quarterly_revenue_growth_yoy": "revenue_growth_yoy",
        "roe_ttm": "roe",
    }

    flat: dict[str, Any] = {
        "instrument_id": item.get("instrument_id", ""),
        "entity_id": item.get("entity_id", item.get("instrument_id", "")),
        "ticker": item.get("ticker"),
        "name": item.get("name"),
        "exchange": item.get("exchange"),
        # WHY gics_sector (not sector): TypeScript ScreenerResult uses gics_sector;
        # S3 returns sector. The rename makes the TS interface the single source of truth.
        "gics_sector": item.get("sector"),
    }

    # Flatten all metric keys, applying renames where applicable
    for key, value in metrics.items():
        flat_key = _renames.get(key, key)
        flat[flat_key] = value

    return flat


@router.post("/fundamentals/screen")
async def screen_instruments(request: Request) -> Any:
    """Proxy POST /api/v1/fundamentals/screen → S3 Market Data with response transform.

    WHY transform (not raw proxy): S3 ScreenInstrumentResponse has metrics nested in
    a dict keyed by metric name.  The frontend TypeScript ScreenerResult expects flat
    top-level fields (market_cap, pe_ratio, …) with renamed keys.
    _flatten_screener_result() applies the mapping at the BFF layer so the frontend
    reads `row.market_cap` rather than `row.metrics?.market_capitalization`.

    Pass-through on error: S3 400/422/500 are forwarded unchanged so the frontend
    can display the correct error message (e.g. "invalid metric name").
    """
    body = await request.body()
    clients = _clients(request)
    resp = await clients.market_data.post(
        "/api/v1/fundamentals/screen",
        content=body,
        headers={"Content-Type": "application/json", **_system_headers(request)},
    )
    if resp.status_code >= 400:
        return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")

    raw = json.loads(resp.content)
    transformed = {
        "results": [_flatten_screener_result(item) for item in raw.get("results", [])],
        "total": raw.get("total", 0),
        "count": raw.get("count", 0),
        "offset": raw.get("offset", 0),
        "limit": raw.get("limit", 50),
    }
    return JSONResponse(transformed)


@router.get("/fundamentals/screen/fields")
async def get_screen_fields(request: Request) -> Any:
    """Proxy GET /api/v1/fundamentals/screen/fields → S3 Market Data.

    Public endpoint — issues a system JWT for backend authentication.
    Returns screener field metadata (Valkey-backed, 6h refresh).
    """
    clients = _clients(request)
    resp = await clients.market_data.get(
        "/api/v1/fundamentals/screen/fields",
        headers=_system_headers(request),
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/fundamentals/timeseries")
async def get_fundamentals_timeseries(request: Request) -> Any:
    """Proxy GET /api/v1/fundamentals/timeseries → S3 Market Data.

    Public endpoint — issues a system JWT for backend authentication.
    Forwards query parameters unchanged.
    """
    clients = _clients(request)
    resp = await clients.market_data.get(
        "/api/v1/fundamentals/timeseries",
        params=dict(request.query_params),
        headers=_system_headers(request),
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# NOTE: /fundamentals/economic-calendar MUST be registered before /fundamentals/{instrument_id}
# to avoid the path parameter matching "economic-calendar" as an instrument_id.
@router.get("/fundamentals/economic-calendar")
async def economic_calendar(request: Request) -> Any:
    """Proxy GET /api/v1/temporal-events → S7 Knowledge Graph.

    Returns upcoming macro economic events for the EconomicCalendar dashboard widget.
    Filters for economic event type from S7's temporal events store (PRD-0018).
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.knowledge_graph.get(
        "/api/v1/temporal-events",
        # R-002 (revise-prd 2026-04-22): S7's list_temporal_events endpoint uses
        # the query param name `event_type`, not `type`.  Passing `type=economic`
        # was silently ignored by FastAPI, meaning no type filter was applied and
        # ALL temporal events were returned regardless of type.
        # Also strip any user-supplied `event_type` to prevent overriding the filter.
        # BP-340: EventType.MACRO = "macro" — economic events are stored as "macro",
        # not "economic". "economic" matched no rows, silently returning empty list.
        params={"event_type": "macro", **{k: v for k, v in dict(request.query_params).items() if k != "event_type"}},
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# NOTE: /fundamentals/earnings-calendar MUST be registered before /fundamentals/{instrument_id}
# (same reason as economic-calendar above — literal sub-paths shadow path params in FastAPI
# only when registered FIRST in the same router).
# PLAN-0068 Wave A-2.
@router.get(
    "/fundamentals/earnings-calendar",
    response_model=EarningsCalendarResponse,
    response_model_exclude_none=True,
)
async def earnings_calendar(request: Request) -> Any:
    """Proxy GET /api/v1/temporal-events → S7 Knowledge Graph (corporate earnings).

    Returns upcoming company earnings events for the EarningsCalendarWidget on
    the dashboard.  Injects ``event_type=corporate`` so only earnings events from
    the EarningsCalendarDatasetConsumer (13D-9) are returned — prevents the
    widget accidentally showing macro/geopolitical events.

    Auth: JWT required (same pattern as economic-calendar endpoint above).

    Passes through optional query params from the caller:
      - from_date (date): earliest active_from to include
      - to_date   (date): latest active_from to include
      - limit     (int):  max rows to return (S7 default: 20)

    WHY response_model=EarningsCalendarResponse: S7 TemporalEventsListResponse
    returns {events: list[TemporalEventResponse], total: int}. EarningsCalendarResponse
    mirrors that shape with EarningsEvent matching TemporalEventResponse fields.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.knowledge_graph.get(
        "/api/v1/temporal-events",
        # WHY strip event_type from caller params: we must always inject
        # event_type=corporate here.  A malicious or misconfigured caller
        # passing event_type=macro would see the wrong data.  Stripping it
        # ensures the filter cannot be overridden from outside.
        params={
            "event_type": "corporate",
            **{k: v for k, v in dict(request.query_params).items() if k != "event_type"},
        },
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# NOTE: Section routes MUST be registered before /fundamentals/{instrument_id}
# to prevent FastAPI matching sub-paths (e.g. "technicals") as an instrument_id.
# FastAPI matches in registration order; more-specific paths registered first win.
# PLAN-0041 Wave A-1 — proxy 6 S3 section endpoints that were missing from S9.


@router.get("/fundamentals/{instrument_id}/technicals")
async def get_technicals(instrument_id: str, request: Request) -> Any:
    """Proxy GET /v1/fundamentals/{id}/technicals → S3 /technicals-snapshot.

    WHY: S3 stores beta, SMA 50/200, 52W range, short interest under the
    "technicals_snapshot" section.  S9 exposes this as /technicals for the
    instrument page's TechnicalSnapshot component.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.market_data.get(
        f"/api/v1/fundamentals/{instrument_id}/technicals-snapshot",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/fundamentals/{instrument_id}/share-statistics")
async def get_share_statistics(instrument_id: str, request: Request) -> Any:
    """Proxy GET /v1/fundamentals/{id}/share-statistics → S3 /share-statistics.

    WHY: Shares outstanding, float, short interest, insider/institutional
    ownership percentages — used by the Ownership sidebar panel.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.market_data.get(
        f"/api/v1/fundamentals/{instrument_id}/share-statistics",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/fundamentals/{instrument_id}/insider-transactions")
async def get_insider_transactions(instrument_id: str, request: Request) -> Any:
    """Proxy GET /v1/fundamentals/{id}/insider-transactions → S3 /insider-transactions-snapshot.

    WHY: Recent insider buys/sells — used by InsiderTransactionsTable.
    S3 stores this as "insider_transactions_snapshot"; S9 shortens the path.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.market_data.get(
        f"/api/v1/fundamentals/{instrument_id}/insider-transactions-snapshot",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/fundamentals/{instrument_id}/earnings-trend")
async def get_earnings_trend(instrument_id: str, request: Request) -> Any:
    """Proxy GET /v1/fundamentals/{id}/earnings-trend → S3 /earnings-trend.

    WHY: Forward EPS/revenue analyst estimates by quarter — used by
    EarningsHistoryChart's estimate bars.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.market_data.get(
        f"/api/v1/fundamentals/{instrument_id}/earnings-trend",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/fundamentals/{instrument_id}/earnings-annual-trend")
async def get_earnings_annual_trend(instrument_id: str, request: Request) -> Any:
    """Proxy GET /v1/fundamentals/{id}/earnings-annual-trend → S3 /earnings-annual-trend.

    WHY: Annual earnings projections — supplementary to quarterly earnings-trend
    when quarterly data is insufficient (e.g. small-cap stocks).
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.market_data.get(
        f"/api/v1/fundamentals/{instrument_id}/earnings-annual-trend",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/fundamentals/{instrument_id}/splits-dividends")
async def get_splits_dividends(instrument_id: str, request: Request) -> Any:
    """Proxy GET /v1/fundamentals/{id}/splits-dividends → S3 /splits-dividends.

    WHY: Dividend history (dates, amounts, frequency) and stock split history —
    used by the Dividends section of FundamentalsTab.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.market_data.get(
        f"/api/v1/fundamentals/{instrument_id}/splits-dividends",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/fundamentals/{instrument_id}/income-statement")
async def get_income_statement(instrument_id: str, request: Request) -> Any:
    """Proxy GET /v1/fundamentals/{id}/income-statement → S3 /income-statement.

    WHY: Annual income-statement records (Revenue, Gross Profit, Operating Income,
    Net Income, EBITDA, EPS) per fiscal year — used by IncomeStatementFY component
    (PLAN-0088 Wave G-1) to render the Finviz-style FY-column table on the
    Fundamentals tab.  Returns FundamentalsResponse with period_type=ANNUAL records
    ordered most-recent-first from S3.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.market_data.get(
        f"/api/v1/fundamentals/{instrument_id}/income-statement",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# NOTE: /snapshot MUST be registered before /{instrument_id} to prevent FastAPI
# matching "snapshot" as an instrument_id path parameter value.
@router.get("/fundamentals/{instrument_id}/snapshot")
async def get_fundamentals_snapshot(instrument_id: str, request: Request) -> Any:
    """Proxy GET /v1/fundamentals/{id}/snapshot → S3 /api/v1/fundamentals/{id}/snapshot.

    WHY THIS ENDPOINT: The InstrumentKeyMetrics sidebar and FundamentalsTab need
    10 pre-computed derived metrics (eps_ttm, beta, avg_volume_30d, FCF, interest
    coverage, etc.) in a single flat typed response.  The S3 instrument_fundamentals_snapshot
    table pre-computes these at backfill time; this proxy exposes them to the frontend
    via S9 without duplicating the derivation logic.

    WHY ALWAYS 200: S3 returns a valid response even when the instrument has no
    snapshot row — it returns all fields as null.  The frontend displays "—" for
    nulls rather than showing an error.  This avoids confusing 404s for instruments
    that are valid but simply haven't been through the backfill yet.

    PLAN-0050 Wave D (T-D-4-04).
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.market_data.get(
        f"/api/v1/fundamentals/{instrument_id}/snapshot",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get(
    "/fundamentals/{instrument_id}",
    response_model=FundamentalsResponse,
    response_model_exclude_none=True,
)
async def get_fundamentals(instrument_id: str, request: Request) -> Any:
    """Proxy GET /api/v1/fundamentals/{instrument_id} → S3 Market Data.

    Requires authentication. Forwards query parameters (fields, etc.) to S3 for
    fundamentals data retrieval. Distinct from the public screener endpoints.

    WHY response_model=FundamentalsResponse: S3 returns {security_id, records[]}.
    FundamentalsResponse mirrors that shape. Note: S3 uses security_id (not
    instrument_id) as the primary key — the frontend resolves via the overview
    endpoint's instrument_id → security_id mapping.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.market_data.get(
        f"/api/v1/fundamentals/{instrument_id}",
        params=dict(request.query_params),
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# ── OHLCV + Quotes + Fundamentals (PRD-0028 Wave S9-1) ──────────────────────


@router.get("/ohlcv/{instrument_id}", response_model=OHLCVResponse, response_model_exclude_none=True)
async def get_ohlcv(instrument_id: str, request: Request) -> Any:
    """Proxy GET /api/v1/ohlcv/{instrument_id} → S3 Market Data.

    Requires authentication. Forwards query parameters to S3 for OHLCV bar
    data retrieval.

    Default ``start`` date injection: S3 accepts ``start``/``end`` date params
    (not a bare row-count limit).  When the frontend omits ``start``, we inject
    a sensible look-back window based on the requested timeframe so the chart
    always gets enough history without returning the entire multi-year dataset:

      - 1m / 5m intraday  → 3 days back
      - 1h hourly          → 30 days back
      - 1d / 1w / 1M daily → 90 days back  (default when timeframe is absent)

    The frontend can always override by passing an explicit ``start`` parameter.
    """
    from datetime import UTC, datetime, timedelta

    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)

    params = dict(request.query_params)

    # Inject a default start date only when the caller has not supplied one.
    # This prevents returning the entire historical dataset (potentially thousands
    # of bars) when the frontend just wants a chart view.
    # Use UTC-aware datetime per project UTC-only convention (CLAUDE.md Rule 7).
    if "start" not in params:
        timeframe = params.get("timeframe", "1d")
        if timeframe in ("1m", "5m"):
            lookback_days = 3
        elif timeframe == "1h":
            lookback_days = 30
        else:
            # 1d, 1w, 1M and any unknown timeframe: 90 calendar days ≈ 63 trading days
            lookback_days = 90
        params["start"] = (datetime.now(tz=UTC) - timedelta(days=lookback_days)).date().isoformat()

    resp = await clients.market_data.get(
        f"/api/v1/ohlcv/{instrument_id}",
        params=params,
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# ── Batch OHLCV (PLAN-0049 T-A-1-05) ─────────────────────────────────────────
#
# WHY: the dashboard renders mini-charts for ~10-15 watched instruments at once.
# Issuing one round-trip per symbol meant ~10x sequential RTT on the cold path
# (audit F-B-009). This endpoint fans out to S3 in parallel via asyncio.gather
# and returns a single response with one entry per requested instrument.
#
# Hard caps: max 50 instruments per request (BP-026 — bound external blast
# radius). 5-minute Cache-Control for daily bars (BP-027).


_BATCH_OHLCV_MAX_SYMBOLS = 50


class _BatchOHLCVRequestItem(BaseModel):
    """One symbol+timeframe spec inside a batch OHLCV request."""

    instrument_id: str = Field(..., min_length=1, max_length=64)
    timeframe: str = Field("1d", pattern=r"^(1m|5m|15m|30m|1h|4h|1d|1w|1M)$")
    start: str | None = None
    end: str | None = None
    limit: int | None = Field(default=None, ge=1, le=2000)


class _BatchOHLCVRequest(BaseModel):
    """Body for POST /v1/ohlcv/batch."""

    requests: list[_BatchOHLCVRequestItem] = Field(..., min_length=1, max_length=_BATCH_OHLCV_MAX_SYMBOLS)


async def _fetch_one_ohlcv(
    *,
    clients: Any,
    headers: dict[str, str] | None = None,
    make_headers: Callable[[], dict[str, str]] | None = None,
    item: _BatchOHLCVRequestItem,
) -> dict[str, Any]:
    """Fetch one symbol's bars; return ``{instrument_id, timeframe, bars, error?}``.

    Failures are caught and reported as a string in ``error`` so the batch as
    a whole always returns 200 — partial success is preferable to all-or-nothing
    for dashboard widgets.
    """
    # T-A-1-02: resolve header factory once per call so each per-instrument
    # request gets a fresh JWT with a unique JTI.  Prevents replay-detection
    # rejection when the batch fan-out issues many parallel requests that would
    # otherwise share the single token captured at batch-start time.
    _h: dict[str, str] = make_headers() if make_headers is not None else (headers or {})

    # Module-level UTC/datetime/timedelta imports are reused — no local re-import.
    params: dict[str, Any] = {"timeframe": item.timeframe}
    # Mirror the singular endpoint's lookback defaults so each batch call gets a
    # sensible window when start/end are absent.
    if item.start:
        params["start"] = item.start
    else:
        if item.timeframe in ("1m", "5m"):
            lookback = 3
        elif item.timeframe == "1h":
            lookback = 30
        else:
            lookback = 90
        params["start"] = (datetime.now(tz=UTC) - timedelta(days=lookback)).date().isoformat()
    if item.end:
        params["end"] = item.end
    if item.limit is not None:
        params["limit"] = item.limit

    try:
        resp = await clients.market_data.get(
            f"/api/v1/ohlcv/{item.instrument_id}",
            params=params,
            headers=_h,
        )
        if resp.status_code != 200:
            return {
                "instrument_id": item.instrument_id,
                "timeframe": item.timeframe,
                "bars": [],
                "error": f"market-data returned {resp.status_code}",
            }
        body = resp.json()
        # market-data returns {"items": [...]} or {"bars": [...]} depending on
        # endpoint version; pick the first non-empty list-like field.
        bars = body.get("bars") or body.get("items") or body.get("data") or []
        return {
            "instrument_id": item.instrument_id,
            "timeframe": item.timeframe,
            "bars": bars,
        }
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        # Narrow catch — httpx.HTTPError covers connect/read/timeout failures;
        # ValueError/KeyError covers JSON-parse and missing-field bugs from the
        # downstream response. Anything broader (e.g. asyncio.CancelledError)
        # propagates so genuine bugs aren't silently masked as a string error.
        return {
            "instrument_id": item.instrument_id,
            "timeframe": item.timeframe,
            "bars": [],
            "error": f"{type(exc).__name__}: {exc}",
        }


@router.post("/ohlcv/batch")
async def batch_ohlcv(payload: _BatchOHLCVRequest, request: Request) -> Response:
    """Fan-out OHLCV fetch for up to 50 symbols in parallel (PLAN-0049 T-A-1-05).

    Returns ``{results: [{instrument_id, timeframe, bars[], error?}], fetched_at}``.
    Per-symbol failures populate ``error`` instead of failing the whole batch.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    clients = _clients(request)

    # T-A-1-02: pass the header factory (not a captured static dict) into each
    # per-symbol fetch so every parallel S3 call gets a fresh JTI.  A batch of
    # 50 symbols would otherwise share one JWT and trigger replay-detection on
    # InternalJWTMiddleware (BP-146 variant).
    # T-A-1-01: wrap the entire gather in asyncio.wait_for(30s) — the per-symbol
    # httpx timeout (5s default) handles individual slow symbols; the outer budget
    # guards against the edge case where many symbols stall simultaneously.
    tasks = [
        _fetch_one_ohlcv(
            clients=clients,
            make_headers=lambda: _auth_headers(request),
            item=item,
        )
        for item in payload.requests
    ]
    try:
        # F-012: return_exceptions=True so one failed symbol doesn't raise for all.
        # Each result is then checked: if it's an Exception, it is logged and
        # replaced with a null sentinel so the frontend can render partial data.
        raw_results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=30.0)
    except TimeoutError:
        raise HTTPException(status_code=504, detail="Upstream timeout")  # noqa: B904

    results: list[Any] = []
    for r in raw_results:
        if isinstance(r, Exception):
            logger.warning("batch_ohlcv_leg_failed", exc_info=r)
            results.append(None)
        else:
            results.append(r)

    body = {"results": results, "fetched_at": datetime.now(tz=UTC).isoformat()}
    # Cache-Control: 5 minutes, ``private`` so a shared CDN/edge cache CANNOT
    # serve one user's response to another — bars are public data but the
    # batch composition is per-user. (BP-027 / QA F-QA improvement.)
    return Response(
        content=json.dumps(body),
        media_type="application/json",
        headers={"Cache-Control": "private, max-age=300"},
    )


def _map_price_snapshot_to_quote(snap: dict[str, Any], instrument_id: str) -> dict[str, Any]:
    """Map a S3 PriceSnapshotResponse → frontend Quote shape.

    WHY here and not in S3: S9 owns the frontend contract. S3 returns its domain
    model (PriceSnapshot); S9 shapes it to the Quote interface the frontend expects.

    WHY price from snapshot.price not snap.last: PriceSnapshotResolver already
    chose the best available price via the fallback chain (FRESH_QUOTE →
    BULK_QUOTE → INTRADAY → DAILY_CLOSE → STALE). We trust that resolution.
    """

    price_str = snap.get("price") or "0"
    try:
        price = float(price_str)
    except (ValueError, TypeError):
        price = 0.0

    change_str = snap.get("price_change")
    try:
        change = float(change_str) if change_str is not None else 0.0
    except (ValueError, TypeError):
        change = 0.0

    change_pct_str = snap.get("price_change_pct")
    try:
        change_pct = float(change_pct_str) if change_pct_str is not None else 0.0
    except (ValueError, TypeError):
        change_pct = 0.0

    return {
        "instrument_id": snap.get("instrument_id", instrument_id),
        "ticker": snap.get("symbol", ""),
        "price": price,
        "change": change,
        "change_pct": change_pct,
        "timestamp": snap.get("timestamp", ""),
        "volume": None,  # PriceSnapshot does not carry volume — that's in OHLCV
        # Freshness fields (PLAN-0036 Wave 1 — optional on older clients)
        "freshness_status": snap.get("freshness_status"),
        "source": snap.get("source"),
        "data_as_of": snap.get("timestamp"),  # alias for clarity in the frontend
        "stale_reason": snap.get("stale_reason"),
        "refresh_available": snap.get("refresh_available", True),
        "refresh_cooldown_remaining_sec": snap.get("refresh_cooldown_remaining_sec", 0),
    }


async def _get_enriched_quote(
    instrument_id: str,
    clients: Any,
    headers: dict[str, str],
) -> tuple[bytes, int]:
    """Try S3's PriceSnapshot endpoint; fall back to legacy quote endpoint.

    Returns (response_body_bytes, http_status_code).

    WHY try/fallback: PriceSnapshot endpoint (GET /internal/v1/price/{id}) is
    new in Wave 1.  During rollout, or if S3 has not yet ingested the instrument,
    it returns 404 or 503.  We fall back to the legacy /api/v1/quotes/{id} route
    so the UI is never left with an empty response.
    """
    import json as _json

    # 1. Try the new PriceSnapshot endpoint (PLAN-0036 W1-9)
    snap_resp = await clients.market_data.get(
        f"/internal/v1/price/{instrument_id}",
        headers=headers,
    )
    if snap_resp.status_code == 200:
        try:
            snap = snap_resp.json()
            quote = _map_price_snapshot_to_quote(snap, instrument_id)
            return _json.dumps(quote).encode(), 200
        except Exception as exc:
            logger.warning("price_snapshot_parse_failed", instrument_id=instrument_id, error=str(exc))
            # fall through to legacy path

    # 2. Fall back to legacy quote endpoint (backward compat during rollout)
    legacy_resp = await clients.market_data.get(
        f"/api/v1/quotes/{instrument_id}",
        headers=headers,
    )
    return legacy_resp.content, legacy_resp.status_code


# PLAN-0059 W0 fix F-011 (2026-04-30): explicit stub for /quotes/stream so a
# literal "stream" path doesn't fall through to /quotes/{instrument_id} and
# 500 against market-data. The real WebSocket route lands in PLAN-0059-D
# (Wave D) — until then, return 503 with a clear payload so the frontend
# fallback path (polling) kicks in cleanly instead of bouncing 500s.
@router.get("/quotes/stream")
async def get_quote_stream_stub(request: Request) -> Response:
    """Stub for the not-yet-implemented quote tick stream (Wave D)."""
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    # SEC-FIX-002 fix (2026-04-30): use top-level `json` import; the bare
    # `_json` reference relied on a function-local rebind that the surrounding
    # routes do but this stub didn't, causing NameError → 500. Also adds
    # Retry-After per DS-FIX-002 so over-eager polling clients back off.
    return Response(
        content=json.dumps(
            {
                "error": "not_implemented",
                "detail": "WebSocket quote stream lands in PLAN-0059 Wave D. "
                "Use polling on /v1/quotes/{instrument_id} until then.",
                "wave": "D",
            }
        ).encode(),
        status_code=503,
        media_type="application/json",
        headers={"Retry-After": "60"},
    )


@router.get("/quotes/{instrument_id}", response_model=QuoteResponse, response_model_exclude_none=True)
async def get_quote(instrument_id: str, request: Request) -> Any:
    """Proxy GET /api/v1/quotes/{instrument_id} → S3 PriceSnapshot (with fallback).

    Requires authentication. Returns the latest quote enriched with freshness fields
    when the S3 PriceSnapshot endpoint is available (PLAN-0036 Wave 1). Falls back
    to the legacy S3 quote endpoint during rollout or if no snapshot exists yet.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    body, status = await _get_enriched_quote(instrument_id, clients, headers)
    return Response(content=body, status_code=status, media_type="application/json")


@router.post("/quotes/batch")
async def get_quotes_batch(request: Request) -> Any:
    """Proxy POST /api/v1/quotes/batch → S3 PriceSnapshot batch (with fallback).

    Requires authentication. Fetches enriched quotes for each instrument_id,
    attempting the PriceSnapshot endpoint first (PLAN-0036 Wave 1) with graceful
    fallback to the legacy batch quote endpoint.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    import json as _json

    body_bytes = await request.body()
    headers = _auth_headers(request)
    clients = _clients(request)

    # 1. Try the new PriceSnapshot batch endpoint
    snap_resp = await clients.market_data.post(
        "/internal/v1/price/batch",
        content=body_bytes,
        headers={"Content-Type": "application/json", **headers},
    )
    if snap_resp.status_code == 200:
        try:
            snap_list = snap_resp.json()
            # The batch endpoint returns a JSON array of PriceSnapshotResponse objects.
            # If the response is not a list (e.g., legacy error dict), fall through.
            if isinstance(snap_list, list):
                quotes: dict[str, Any] = {}
                for snap in snap_list:
                    if not isinstance(snap, dict):
                        continue
                    iid = snap.get("instrument_id", "")
                    if iid:
                        quotes[iid] = _map_price_snapshot_to_quote(snap, iid)
                return Response(
                    content=_json.dumps({"quotes": quotes}).encode(),
                    status_code=200,
                    media_type="application/json",
                )
        except Exception as exc:
            logger.warning("price_snapshot_batch_parse_failed", error=str(exc))
            # fall through to legacy path

    # 2. Fall back to legacy batch endpoint
    legacy_resp = await clients.market_data.post(
        "/api/v1/quotes/batch",
        content=body_bytes,
        headers={"Content-Type": "application/json", **headers},
    )
    return Response(
        content=legacy_resp.content,
        status_code=legacy_resp.status_code,
        media_type="application/json",
    )


# ── Market Heatmap (PRD-0028 Wave S9-3, OQ-02) ──────────────────────────────


@router.get("/market/heatmap")
async def market_heatmap(
    request: Request,
    period: str = Query("1D", description="Period: 1D, 1W, or 1M"),
) -> dict[str, Any]:
    """Sector heatmap — aggregated daily_return per GICS sector.

    For 1D: composed endpoint using 11 parallel S3 screener calls (one per sector).
    For 1W/1M: delegates to S3 /api/v1/market/sector-returns (OHLCV-based aggregate).
    Uses asyncio.gather with return_exceptions=True (BP-114).
    Auth required. Forwards X-Internal-JWT to all downstream calls.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    if period not in ("1D", "1W", "1M"):
        raise HTTPException(status_code=400, detail="period must be '1D', '1W', or '1M'")
    try:
        return await get_market_heatmap(
            _clients(request),
            period=period,
            make_headers=lambda: _auth_headers(request),
        )
    except DownstreamError as e:
        raise HTTPException(status_code=e.status, detail=e.detail) from e


# ── Top Movers (PRD-0028 Wave S9-3, OQ-03) ──────────────────────────────────


@router.get("/market/top-movers")
async def top_movers(
    request: Request,
    mover_type: str = Query("gainers", alias="type", description="gainers or losers"),
    limit: int = Query(10, ge=1, le=20),
    period: str = Query("1D", description="Period: 1D, 1W, or 1M"),
) -> dict[str, Any]:
    """Top gainers or losers — screener sorted by daily_return (1D) or OHLCV bars (1W/1M).

    For 1D: single S3 screener call with sort_by=daily_return.
    For 1W/1M: delegates to S3 /api/v1/market/period-movers (OHLCV-based).
    Auth required. Forwards X-Internal-JWT to the downstream call.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    if mover_type not in ("gainers", "losers"):
        raise HTTPException(status_code=400, detail="type must be 'gainers' or 'losers'")
    if period not in ("1D", "1W", "1M"):
        raise HTTPException(status_code=400, detail="period must be '1D', '1W', or '1M'")
    try:
        return await get_top_movers(
            _clients(request),
            mover_type=mover_type,
            limit=limit,
            period=period,
            # T-A-1-02: pass factory so each downstream call issues a fresh JWT.
            make_headers=lambda: _auth_headers(request),
        )
    except DownstreamError as e:
        raise HTTPException(status_code=e.status, detail=e.detail) from e


# ── AI Signals (PRD-0028 Wave S9-3 → real proxy to S6) ────────────────────

# Maps S6 claim_type values to frontend AiSignal label.
# Positive events: mergers, beats, upgrades, capital allocation, strategic growth.
# Negative events: misses, downgrades, regulatory/legal risk, distress.
_POSITIVE_SIGNAL_TYPES = frozenset(
    {
        # Legacy broker-event labels (kept for backward compatibility)
        "M_AND_A",
        "EARNINGS_BEAT",
        "UPGRADE",
        "BUYBACK",
        "ACQUISITION",
        "DIVIDEND",
        "EXPANSION",
        "PARTNERSHIP",
        "JOINT_VENTURE",
        "IPO",
        "REVENUE_BEAT",
        "GUIDANCE_RAISE",
        "CONTRACT_WIN",
        # NLP deep-extraction event_type enum (deep_extraction.py JSON schema)
        "PRODUCT_LAUNCH",
        "CAPITAL_RAISE",
    }
)
_NEGATIVE_SIGNAL_TYPES = frozenset(
    {
        # Legacy broker-event labels (kept for backward compatibility)
        "EARNINGS_MISS",
        "DOWNGRADE",
        "REGULATORY_ACTION",
        "LAWSUIT",
        "BANKRUPTCY",
        "RESTRUCTURING",
        "GUIDANCE_CUT",
        "REVENUE_MISS",
        "INVESTIGATION",
        "FINE",
        "RECALL",
        "LAYOFF",
        # NLP deep-extraction event_type enum (deep_extraction.py JSON schema)
        "LEGAL",
        "NATURAL_DISASTER",
        "GEOPOLITICAL",
        "SANCTIONS",
    }
)


def _signal_type_to_label(signal_type: str) -> str:
    st = signal_type.upper()
    if st in _POSITIVE_SIGNAL_TYPES:
        return "POSITIVE"
    if st in _NEGATIVE_SIGNAL_TYPES:
        return "NEGATIVE"
    return "NEUTRAL"


@router.get("/signals/ai")
async def ai_signals(request: Request) -> Any:
    """Proxy GET /api/v1/signals → S6 NLP Pipeline, transforming to frontend shape.

    S6 returns {items: [...], total, limit, offset} with signal_type/confidence/detected_at.
    The frontend expects {signals: [...]} with label/score/article_title/created_at.
    This transform bridges the two without changing the S6 contract.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.nlp_pipeline.get(
        "/api/v1/signals",
        params=dict(request.query_params),
        headers=headers,
    )
    if resp.status_code != 200:
        return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")

    try:
        body = json.loads(resp.content)
        items = body.get("items", [])

        # Batch-resolve entity_ids → tickers from KG to show "AAPL" instead of entity_id prefix.
        ticker_map: dict[str, str | None] = {}
        entity_ids = list({str(item.get("entity_id", "")) for item in items if item.get("entity_id")})
        if entity_ids:
            try:
                kg_batch_resp = await clients.knowledge_graph.post(
                    "/api/v1/entities/batch",
                    json={"entity_ids": entity_ids},
                    headers=headers,
                )
                if kg_batch_resp.status_code == 200:
                    kg_body = json.loads(kg_batch_resp.content)
                    for ent in kg_body.get("entities", []):
                        ticker_map[str(ent["entity_id"])] = ent.get("ticker")
            except Exception:
                logger.warning("ai_signals_ticker_enrichment_failed", exc_info=True)

        # Batch-resolve doc_ids → article titles via content-store.
        # S6 includes doc_id in every signal; content-store /documents/batch returns
        # title, url, published_at, source_name per doc_id in a single query.
        article_map: dict[str, dict[str, str | None]] = {}
        doc_ids = list({str(item.get("doc_id", "")) for item in items if item.get("doc_id")})
        if doc_ids:
            try:
                cs_resp = await clients.content_store.post(
                    "/api/v1/documents/batch",
                    json={"doc_ids": doc_ids},
                    headers=headers,
                )
                if cs_resp.status_code == 200:
                    cs_body = json.loads(cs_resp.content)
                    for doc in cs_body.get("documents", []):
                        article_map[str(doc["doc_id"])] = {
                            "title": doc.get("title"),
                            "url": doc.get("url"),
                            "source_name": doc.get("source_name"),
                            "published_at": doc.get("published_at"),
                        }
            except Exception:
                logger.warning("ai_signals_article_enrichment_failed", exc_info=True)

        signals = [
            {
                "signal_id": str(item.get("signal_id", "")),
                "entity_id": str(item.get("entity_id", "")),
                "ticker": ticker_map.get(str(item.get("entity_id", ""))),
                # Map signal_type (LLM event_type enum: PRODUCT_LAUNCH, LEGAL, etc.)
                # to POSITIVE/NEGATIVE/NEUTRAL via _signal_type_to_label which covers
                # both the legacy broker-event types and the NLP deep-extraction enum.
                # This works for both existing and new outbox rows, unlike the polarity
                # field which was hardcoded to "neutral" in earlier outbox writers.
                "label": _signal_type_to_label(str(item.get("signal_type", ""))),
                "score": float(item.get("confidence", 0.0)),
                "article_title": article_map.get(str(item.get("doc_id", "")), {}).get("title"),
                "article_url": article_map.get(str(item.get("doc_id", "")), {}).get("url"),
                "source_name": article_map.get(str(item.get("doc_id", "")), {}).get("source_name"),
                "created_at": str(item.get("detected_at", "")),
            }
            for item in items
        ]
        return {"signals": signals}
    except Exception:
        logger.warning("ai_signals_transform_failed", exc_info=True)
        return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")
