"""Instrument, search, and map routes for the API Gateway.

Handles /v1/companies/*, /v1/instruments/*, /v1/search/*, /v1/map/*
Split from proxy.py (PLAN-0089 B-3).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from api_gateway.application.http_utils import downstream_to_http
from api_gateway.clients import DownstreamError, get_map_layers, get_relevant_news
from api_gateway.resolution import (
    InstrumentNotFoundError,
    resolve_security_id,
)
from api_gateway.routes.helpers import _auth_headers, _clients, _system_headers, proxy_json_response
from api_gateway.schemas import InstrumentSearchResult
from observability.logging import get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]

router = APIRouter(prefix="/v1")

# WHY 300s cooldown: prevents a single user from hammering EODHD via the manual
# refresh button. Each instrument gets a per-instrument 5-minute gate. This is
# independent of the automatic cadence — a user pressing refresh ALSO counts
# against the monthly quota (quota check happens in S2's ExecuteTaskUseCase).
_REFRESH_COOLDOWN_SECONDS = 300


# ── Company ───────────────────────────────────────────────


@router.get("/companies/{company_id}/overview")
async def company_overview(company_id: str, request: Request) -> dict[str, Any]:
    """Composed endpoint: instrument + quote + OHLCV + (optional) fundamentals.

    Passes a JWT factory so each of the 4 parallel downstream calls gets a fresh
    JWT with a unique JTI, preventing replay detection on market-data.

    PLAN-0089 B-1: delegates to CompanyOverviewUseCase (application layer).
    The external behaviour is identical — the use case wraps get_company_overview.
    """
    if getattr(request.state, "user", None) is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    # PRD-0089 F2: resolve_security_id accepts BOTH a UUID and a ticker.
    # The legacy F-026 UUID-only guard is gone — the resolver validates
    # the input shape (UUID regex or live ticker lookup) and raises
    # InstrumentNotFoundError on miss, which we map to 404.
    try:
        resolved = await resolve_security_id(
            company_id,
            clients=_clients(request),
            headers=_auth_headers(request),
        )
    except InstrumentNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail=f"Instrument not found: {e.identifier}",
        ) from e

    from api_gateway.application.use_cases.company_overview import CompanyOverviewUseCase

    use_case = CompanyOverviewUseCase(
        # http_client not used directly (ServiceClients holds the per-service clients),
        # but GatewayUseCase requires it — pass a dummy reference for now.
        http_client=_clients(request).market_data,
        settings=request.app.state.settings,
        service_clients=_clients(request),
    )
    try:
        # Downstream now always receives a canonical instrument_id UUID
        # string (no ticker, no entity_id). The translation dance in
        # clients.get_company_overview has been deleted.
        # WHY include_ohlcv=True: the single-instrument overview is requested
        # by the instruments detail page which renders a chart.  The dashboard
        # batch endpoint (overviews:batch) passes include_ohlcv=False instead
        # to skip the OHLCV leg and save 1-3 s per instrument on page load.
        return await use_case.execute(
            company_id=str(resolved.instrument_id),
            make_headers=lambda: _auth_headers(request),
            include_ohlcv=True,
        )
    except DownstreamError as e:
        raise downstream_to_http(e) from e


# ── Batched company overview (FIX F-1) ──────────────────────────────────────
#
# WHY THIS EXISTS: dashboard widgets (PreMarketMoversWidget, SectorHeatmapWidget,
# PortfolioSummary) previously fired one /v1/companies/{id}/overview per ticker
# via TanStack `useQueries`. For a default page that meant 10-50+ parallel HTTP
# round-trips just to look up GICS sector + ticker/name fields. This batch
# endpoint fans-in to one POST request: the gateway runs the N legs in parallel
# server-side and returns a `{ uuid: CompanyOverview | null }` map.
#
# WHY return_exceptions=True + null per-leg: each individual leg may fail
# independently (instrument tombstoned, market-data slow, etc). The caller
# treats `null` as "missing data, render placeholder" rather than failing the
# whole widget. This mirrors the per-leg degradation policy in
# `/v1/instruments/{id}/page-bundle`.
#
# WHY make_headers PER LEG (not a single header dict): InternalJWTMiddleware on
# every downstream service enforces JTI replay detection. If we reused one
# X-Internal-JWT across N parallel legs, all but one would be rejected.


_BATCH_OVERVIEW_MAX_IDS = 50


class _CompanyOverviewBatchRequest(BaseModel):
    """Request body for POST /v1/companies/overviews:batch.

    WHY max 50: 50 covers every legitimate use case today (the dashboard
    widgets call with ≤20 ids) and bounds worst-case fan-out so a single
    request can never DDoS market-data with hundreds of legs.
    """

    instrument_ids: list[str] = Field(..., min_length=1, max_length=_BATCH_OVERVIEW_MAX_IDS)


@router.post("/companies/overviews:batch")
async def company_overviews_batch(
    body: _CompanyOverviewBatchRequest,
    request: Request,
) -> dict[str, dict[str, dict[str, Any] | None]]:
    """Fan-in N company-overview lookups into one round-trip.

    Returns ``{ "overviews": { "<uuid>": CompanyOverview | null, ... } }`` —
    null for any leg that errored (downstream 404/500/timeout). The shape
    preserves request mapping via id-keyed map so callers don't need to align
    indices.

    Auth: same as the single-overview route — 401 when unauthenticated.
    """
    if getattr(request.state, "user", None) is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Dedupe in case the caller passes the same id twice (cheap insurance
    # against burning extra downstream calls). dict.fromkeys preserves order.
    unique_ids: list[str] = list(dict.fromkeys(body.instrument_ids))

    from api_gateway.application.use_cases.company_overview import CompanyOverviewUseCase

    clients = _clients(request)
    use_case = CompanyOverviewUseCase(
        http_client=clients.market_data,
        settings=request.app.state.settings,
        service_clients=clients,
    )

    async def _one(instrument_id: str) -> dict[str, Any]:
        # WHY resolve per id: callers may pass tickers OR UUIDs (the single-id
        # route accepts both via PRD-0089 F2). Resolving here keeps batch
        # behaviour symmetric with the single-id endpoint.
        try:
            resolved = await resolve_security_id(
                instrument_id,
                clients=clients,
                headers=_auth_headers(request),
            )
        except InstrumentNotFoundError as exc:
            raise DownstreamError("market-data", 404, f"Not found: {exc.identifier}") from exc

        return await use_case.execute(
            company_id=str(resolved.instrument_id),
            # WHY lambda calling _auth_headers afresh: each leg mints a unique
            # JTI so InternalJWTMiddleware's replay detection accepts the fan-out.
            make_headers=lambda: _auth_headers(request),
        )

    # asyncio.gather with return_exceptions=True so a single failure doesn't
    # tank the whole batch — we map exceptions to null below.
    results = await asyncio.gather(
        *(_one(_id) for _id in unique_ids),
        return_exceptions=True,
    )

    overviews: dict[str, dict[str, Any] | None] = {}
    for original_id, result in zip(unique_ids, results, strict=True):
        if isinstance(result, BaseException):
            logger.info(
                "company_overviews_batch_leg_failed",
                instrument_id=original_id,
                error=str(result),
            )
            overviews[original_id] = None
        else:
            overviews[original_id] = result

    return {"overviews": overviews}


@router.get("/instruments/{instrument_id}/page-bundle")
async def instrument_page_bundle(instrument_id: str, request: Request) -> dict[str, Any]:
    """PLAN-0059 I-5 — instrument-detail page initial-load composite.

    Collapses the overview-tab waterfall (overview + fundamentals + technicals
    + insider + top-news) into a single round-trip. Each downstream call uses
    its own freshly-issued internal JWT so InternalJWTMiddleware's JTI replay
    detection accepts the parallel fan-out.

    Per-call failures degrade gracefully — failed sub-resources return null
    fields rather than failing the whole bundle. The FE renders partial UIs.

    QA-iter1: explicit auth guard. OIDCAuthMiddleware does not 401 on its own
    — individual routes enforce auth. The bundle exposes 6 downstream
    sub-resources (including insider transactions which can be sensitive),
    so unauthenticated access is rejected here.
    """
    if getattr(request.state, "user", None) is None:
        raise HTTPException(status_code=401, detail="Authentication required")

    # PRD-0089 F2: ticker-friendly path — accept either a UUID or a
    # ticker symbol. resolve_security_id canonicalises both to an
    # instrument_id UUID so the use case + downstream legs always
    # receive the right id shape.
    try:
        resolved = await resolve_security_id(
            instrument_id,
            clients=_clients(request),
            headers=_auth_headers(request),
        )
    except InstrumentNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail=f"Instrument not found: {e.identifier}",
        ) from e

    # PLAN-0089 B-2: delegates to InstrumentPageBundleUseCase (application layer).
    # The external behaviour is identical — the use case wraps get_instrument_page_bundle.
    from api_gateway.application.use_cases.instrument_page_bundle import InstrumentPageBundleUseCase

    use_case = InstrumentPageBundleUseCase(
        # http_client not used directly (ServiceClients holds the per-service clients),
        # but GatewayUseCase requires it — pass a dummy reference for now.
        http_client=_clients(request).market_data,
        settings=request.app.state.settings,
        service_clients=_clients(request),
    )
    return await use_case.execute(
        instrument_id=str(resolved.instrument_id),
        make_headers=lambda: _auth_headers(request),
    )


# ── Paginated OHLCV (PLAN-0099 W4-I) ─────────────────────────────────────────
#
# WHY this endpoint exists: the instruments page currently fetches 60/90 days of
# bars via the page-bundle and has no way to scroll into the past.  This endpoint
# adds cursor-based backwards pagination so the chart can lazy-load more history
# without re-fetching recent bars.
#
# Cursor design: ``before`` is an exclusive ISO-date upper bound.  The caller
# receives ``cursor`` in the response pointing at the oldest bar returned; the
# next page is fetched as ``?before=<cursor>``.  This mirrors the "load older"
# UX pattern used by most financial chart libraries.
#
# WHY ``limit`` cap at 500: 300 bars is ~1 year of daily data — more than enough
# for a single chart view.  Capping at 500 prevents accidentally returning the
# entire multi-year dataset in one call.


@router.get("/instruments/{instrument_id}/ohlcv")
async def instrument_ohlcv_paginated(
    instrument_id: str,
    request: Request,
    timeframe: str = Query("1d", pattern=r"^(1m|5m|15m|30m|1h|4h|1d|1w|1M)$"),
    limit: int = Query(300, ge=1, le=500, description="Number of bars to return"),
    before: str | None = Query(
        None,
        description="ISO date cursor (exclusive upper bound). "
        "Omit to get the most recent `limit` bars. "
        "Pass the `cursor` from a previous response to page backwards.",
    ),
) -> Any:
    """Paginated OHLCV bars for a single instrument (PLAN-0099 W4-I).

    Returns ``{ "bars": [...], "cursor": "<oldest_bar_date>" }`` so the frontend
    can call ``?before=<cursor>`` to load older history without re-fetching
    recent bars.

    Query params:
      - ``timeframe``: bar resolution (default ``1d``).
      - ``limit``: number of bars (default 300, max 500).
      - ``before``: exclusive ISO-date upper bound.  Omit to get the most
        recent ``limit`` bars.

    WHY resolve_security_id: PRD-0089 F2 — the URL slug may be a ticker
    (e.g. "AAPL").  market-data OHLCV only accepts UUIDs.

    Requires authentication.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")

    try:
        resolved = await resolve_security_id(
            instrument_id,
            clients=_clients(request),
            headers=_auth_headers(request),
        )
    except InstrumentNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"Instrument not found: {e.identifier}") from e

    # Build S3 query params.
    # WHY compute start from limit when before is set: S3 accepts start/end
    # date-range params, not a bare row count.  When the caller supplies a
    # ``before`` cursor we compute a start date far enough back to cover
    # ``limit`` trading days (using 1.5x calendar-day multiplier to account
    # for weekends + holidays) and use before as the exclusive end date.
    # When no cursor is given, we compute start relative to today instead.
    #
    # The S3 ``limit`` param (default 200, no declared upper cap) is forwarded
    # to ensure no silent truncation below our requested bar count.
    params: dict[str, Any] = {"timeframe": timeframe, "limit": limit}

    if timeframe in ("1m", "5m", "15m", "30m"):
        # Intraday: 1 calendar day ≈ 1 trading day of bars
        cal_days_per_bar = 1
    elif timeframe == "1h":
        cal_days_per_bar = 1
    else:
        # Daily / weekly / monthly: use 1.5 calendar-day factor to cover
        # weekends and public holidays so we don't under-fetch.
        cal_days_per_bar = 2  # conservative: 2 calendar days per trading day

    lookback_days = limit * cal_days_per_bar

    if before is not None:
        # Cursor-based page: [start, before) window sized to cover ``limit`` bars.
        # WHY fromisoformat: before is user-supplied; parse strictly to validate
        # the date format before forwarding to S3.
        try:
            before_date = datetime.fromisoformat(before).date()
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid `before` date format: {before!r}. Use ISO format YYYY-MM-DD.",
            ) from exc
        start_date = before_date - timedelta(days=lookback_days)
        params["start"] = start_date.isoformat()
        params["end"] = before_date.isoformat()
    else:
        # Most-recent page: look back far enough from today to cover ``limit`` bars.
        params["start"] = (datetime.now(tz=UTC) - timedelta(days=lookback_days)).date().isoformat()

    clients = _clients(request)
    resp = await clients.market_data.get(
        f"/api/v1/ohlcv/{resolved.instrument_id}",
        params=params,
        headers=_auth_headers(request),
    )

    if resp.status_code >= 400:
        # Forward 4xx verbatim (caller-safe) and sanitize 5xx (BUG-7).
        return proxy_json_response(request, resp)

    raw = resp.json()
    items: list[dict[str, Any]] = raw.get("items") or []

    # Normalise S3 OHLCV bar shape → frontend-friendly float-typed bars.
    # WHY normalise here (not in the frontend): keeps the TypeScript types
    # simple (all numeric fields are number, not string | number).
    bars: list[dict[str, Any]] = [
        {
            "timestamp": item.get("bar_date", ""),
            "open": float(item["open"]) if item.get("open") else 0.0,
            "high": float(item["high"]) if item.get("high") else 0.0,
            "low": float(item["low"]) if item.get("low") else 0.0,
            "close": float(item["close"]) if item.get("close") else 0.0,
            "volume": item.get("volume") or 0,
        }
        for item in items
    ]

    # Cursor: the timestamp of the oldest (first) bar in the sorted result.
    # WHY oldest bar: the frontend pages backwards (loads older history), so
    # passing the oldest returned date as ``before`` on the next call yields
    # the next earlier page without overlap.
    cursor: str | None = bars[0]["timestamp"] if bars else None

    return {
        "instrument_id": str(resolved.instrument_id),
        "timeframe": timeframe,
        "bars": bars,
        # ``cursor`` is None when there are no bars (exhausted history).
        "cursor": cursor,
    }


# ── News (public) ─────────────────────────────────────────


@router.get("/news/relevant")
async def relevant_news(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    """Most relevant news articles across all sources.

    Public endpoint — issues a system JWT so S5's InternalJWTMiddleware
    accepts the request.
    """
    try:
        return await get_relevant_news(_clients(request), limit=limit, headers=_system_headers(request))
    except DownstreamError as e:
        raise downstream_to_http(e) from e


# ── Map ───────────────────────────────────────────────────


@router.get("/map/layers")
async def map_layers(request: Request) -> dict[str, Any]:
    """Available map overlay layers."""
    return await get_map_layers(_clients(request))


# ── Instrument lookup (PRD-0073 Wave D-1) ────────────────────────────────────


@router.get("/instruments/lookup")
async def instruments_lookup(request: Request) -> Any:
    """Proxy GET /api/v1/instruments/lookup → S3 Market Data.

    Unified instrument lookup by symbol, ISIN, or UUID.  Forwards `symbol`, `isin`,
    `id`, and `extra_info` query params to S3 unchanged.

    Requires authentication.  Returns 404 when no instrument matches.

    WHY registered as a separate route (not pass-through via /{instrument_id}/...):
    S3's /instruments/lookup uses query params for lookup, not path params.  Registering
    it explicitly before any path-param route prevents `lookup` being misread as a UUID.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.market_data.get(
        "/api/v1/instruments/lookup",
        params=dict(request.query_params),
        headers=headers,
    )
    return proxy_json_response(request, resp)


# ── Batch ticker → instrument_id resolve (PLAN-0099 W4) ─────────────────────


class _TickerResolveBatchRequest(BaseModel):
    tickers: list[str] = Field(..., min_length=1, max_length=30, description="Ticker symbols to resolve")


@router.post("/instruments/resolve-tickers")
async def resolve_tickers_batch(body: _TickerResolveBatchRequest, request: Request) -> Any:
    """Batch-resolve ticker symbols → instrument_id in one round-trip.

    WHY THIS EXISTS: MarketSnapshotWidget used to fire N parallel
    GET /v1/search/instruments?q={ticker} requests (one per ticker) which
    each take 2-4s on cold start because the search does an ILIKE '%AAPL%'
    scan. This endpoint fans out to GET /api/v1/instruments/lookup?symbol=X
    (exact indexed match, ~20ms) for each ticker concurrently and returns
    a single {ticker: instrument_id | null} map. On a 9-ticker dashboard
    snapshot this reduces 9 serial-start 2-4s calls to one ~200ms call.

    Requires authentication. Returns null for tickers not found in S3.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)

    async def _resolve_one(ticker: str) -> tuple[str, str | None]:
        try:
            resp = await clients.market_data.get(
                "/api/v1/instruments/lookup",
                params={"symbol": ticker},
                headers=headers,
            )
            if resp.status_code == 200:
                data = resp.json()
                return ticker, data.get("instrument_id") or data.get("id")
            return ticker, None
        except Exception:
            return ticker, None

    pairs = await asyncio.gather(*[_resolve_one(t) for t in body.tickers])
    return dict(pairs)


# ── Peers (W5-T-S9-01) ───────────────────────────────────────────────────────


@router.get("/instruments/{instrument_id}/peers")
async def instrument_peers(instrument_id: str, request: Request) -> Any:
    """Proxy GET /v1/instruments/{id}/peers → S3 Market Data /peers.

    Returns the top-N market-cap peers in the same GICS industry.

    WHY proxy-only (no S9 transform): the peers response shape is already
    frontend-friendly (`PeersResponse` from T-S2-01). S9 just gates auth
    and forwards query params (limit=) to S3 unchanged. S3 handles the 24h
    Valkey cache and the GICS industry lookup.

    WHY resolve_security_id: PRD-0089 F2 — the URL slug is a ticker (e.g.
    "AAPL"), not a UUID. market-data peers endpoint only accepts UUIDs.
    Resolution canonicalises the ticker before forwarding.

    Requires authentication. Returns 404 if the instrument is not found.
    S3 returns 200 + empty peers list for ETFs with no GICS industry.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        resolved = await resolve_security_id(
            instrument_id,
            clients=_clients(request),
            headers=_auth_headers(request),
        )
    except InstrumentNotFoundError as e:
        raise HTTPException(status_code=404, detail=f"Instrument not found: {e.identifier}") from e
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.market_data.get(
        f"/api/v1/instruments/{resolved.instrument_id}/peers",
        params=dict(request.query_params),
        headers=headers,
    )
    return proxy_json_response(request, resp)


# ── Manual price refresh (PLAN-0036 W1-11) ────────────────────────────────────


@router.post("/instruments/{instrument_id}/refresh-price", status_code=200)
async def refresh_instrument_price(instrument_id: str, request: Request) -> Any:
    """Trigger a manual price refresh for a single instrument.

    Requires authentication. Enforces a per-instrument 5-minute cooldown via
    Valkey (key: ``refresh_cooldown:{instrument_id}``) to prevent EODHD credit
    exhaustion from rapid user clicks.

    Returns 202 when the refresh is accepted (S2 will fetch soon).
    Returns 429 when on cooldown, with ``cooldown_remaining_sec`` in the body.

    WHY proxy to S2: market-ingestion (S2) owns the EODHD fetch pipeline.
    S9 just gates the request and delegates; S9 has no EODHD credentials.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")

    import json as _json
    import time

    clients = _clients(request)
    headers = _auth_headers(request)

    # PRD-0089 F2: accept either a UUID or ticker. Resolved id is used
    # for cooldown keying so a ticker refresh and a UUID refresh share
    # the same gate (preventing duplicate EODHD spend).
    try:
        resolved = await resolve_security_id(
            instrument_id,
            clients=clients,
            headers=headers,
        )
    except InstrumentNotFoundError as e:
        raise HTTPException(
            status_code=404,
            detail=f"Instrument not found: {e.identifier}",
        ) from e
    instrument_id = str(resolved.instrument_id)

    # ── Cooldown check via Valkey ─────────────────────────────────────────────
    valkey = getattr(request.app.state, "valkey", None)
    cooldown_key = f"refresh_cooldown:{instrument_id}"

    if valkey is not None:
        try:
            cooldown_val = await valkey.get(cooldown_key)
        except Exception as exc:
            logger.warning("refresh_cooldown_check_failed", instrument_id=instrument_id, error=str(exc))
            cooldown_val = None  # fail-open: if Valkey is down, allow the refresh

        if cooldown_val is not None:
            # Decode remaining TTL: we stored epoch of expiry
            try:
                expiry_ts = int(cooldown_val)
                remaining = max(0, expiry_ts - int(time.time()))
            except (ValueError, TypeError):
                remaining = _REFRESH_COOLDOWN_SECONDS  # conservative default

            if remaining > 0:
                return Response(
                    content=_json.dumps(
                        {
                            "instrument_id": instrument_id,
                            "status": "cooldown",
                            "cooldown_remaining_sec": remaining,
                            "message": f"Manual refresh available in {remaining}s",
                        }
                    ).encode(),
                    status_code=429,
                    media_type="application/json",
                )

    # ── Resolve instrument symbol for S2 trigger ─────────────────────────────
    # S2's trigger endpoint needs symbol + exchange; resolve from S3.
    instr_resp = await clients.market_data.get(
        f"/api/v1/instruments/lookup?id={instrument_id}",
        headers=headers,
    )
    if instr_resp.status_code != 200:
        raise HTTPException(
            status_code=404,
            detail=f"Instrument {instrument_id} not found",
        )

    instr = instr_resp.json()
    symbol = instr.get("symbol", "")
    exchange = instr.get("exchange", "")

    # ── Trigger S2 fetch ──────────────────────────────────────────────────────
    trigger_body = _json.dumps(
        {
            "symbols": [symbol],
            "exchange": exchange or None,
            "dataset_types": ["quotes"],
            "priority": "high",
        }
    ).encode()

    s2_resp = await clients.market_ingestion.post(
        "/api/v1/ingest/trigger",
        content=trigger_body,
        headers={"Content-Type": "application/json", **headers},
    )

    # ── Set cooldown regardless of S2 outcome ────────────────────────────────
    # WHY set cooldown even on S2 failure: prevents hammering S2 when it's down.
    if valkey is not None:
        try:
            expiry_ts = int(time.time()) + _REFRESH_COOLDOWN_SECONDS
            await valkey.set(cooldown_key, str(expiry_ts), ttl=_REFRESH_COOLDOWN_SECONDS)
        except Exception as exc:
            logger.warning("refresh_cooldown_set_failed", instrument_id=instrument_id, error=str(exc))
            # fail-open: cooldown is best-effort

    if s2_resp.status_code >= 500:
        raise HTTPException(status_code=503, detail="Ingestion service unavailable")

    return Response(
        content=_json.dumps(
            {
                "instrument_id": instrument_id,
                "status": "accepted",
                "message": "Price refresh queued — data will update within 30 seconds",
            }
        ).encode(),
        status_code=202,
        media_type="application/json",
    )


# ── Search (PRD-0028 Wave S9-3, OQ-01) ──────────────────────────────────────


@router.get(
    "/search/instruments",
    response_model=list[InstrumentSearchResult],
    response_model_exclude_none=True,
)
async def search_instruments(
    request: Request,
    q: str = Query("", max_length=200, description="Search query"),
    limit: int = Query(10, ge=1, le=50),
) -> Any:
    """Instrument search for the top-bar command palette.

    Proxies to S3 GET /api/v1/instruments with query filter.
    No auth required — public endpoint.  Issues a system JWT so S3's
    InternalJWTMiddleware accepts the request.
    """
    clients = _clients(request)
    resp = await clients.market_data.get(
        "/api/v1/instruments",
        params={"query": q, "limit": limit},
        headers=_system_headers(request),
    )
    return proxy_json_response(request, resp)


# ── Document Search (PLAN-0064 Wave 4) ──────────────────────────────────────


@router.get("/search")
async def search_documents(request: Request) -> Any:
    """Proxy GET /api/v1/search/documents → S6 NLP Pipeline (PLAN-0064 W6).

    Full-text search across articles + EDGAR filings with entity facets.
    Requires authentication — anonymous callers receive 401.
    Forwards all query params (q, entity_id, scope, source_type, date_from,
    date_to, date_preset, page, page_size) unchanged.
    Issues a fresh RS256 internal JWT per _auth_headers() so S6's
    InternalJWTMiddleware accepts the request (re-uses the user's identity).
    Returns 503 on httpx.TimeoutException so the frontend can show a retry
    message rather than a generic 500 error.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    clients = _clients(request)
    try:
        resp = await clients.nlp_pipeline.get(
            "/api/v1/search/documents",
            params=dict(request.query_params),
            headers=_auth_headers(request),
        )
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise HTTPException(status_code=503, detail="Search backend unavailable") from exc
    return proxy_json_response(request, resp)
