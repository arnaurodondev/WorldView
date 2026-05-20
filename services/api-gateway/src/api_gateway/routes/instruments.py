"""Instrument, search, and map routes for the API Gateway.

Handles /v1/companies/*, /v1/instruments/*, /v1/search/*, /v1/map/*
Split from proxy.py (PLAN-0089 B-3).
"""

from __future__ import annotations

import uuid as _uuid
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, Response

from api_gateway.clients import DownstreamError, get_map_layers, get_relevant_news
from api_gateway.routes.helpers import _auth_headers, _clients, _system_headers
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
    # F-026: validate company_id is a UUID to prevent path traversal attacks.
    try:
        _uuid.UUID(company_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid company_id — must be a UUID")  # noqa: B904

    from api_gateway.application.use_cases.company_overview import CompanyOverviewUseCase

    use_case = CompanyOverviewUseCase(
        # http_client not used directly (ServiceClients holds the per-service clients),
        # but GatewayUseCase requires it — pass a dummy reference for now.
        http_client=_clients(request).market_data,
        settings=request.app.state.settings,
        service_clients=_clients(request),
    )
    try:
        return await use_case.execute(
            company_id=company_id,
            make_headers=lambda: _auth_headers(request),
        )
    except DownstreamError as e:
        raise HTTPException(status_code=e.status, detail=e.detail) from e


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
    # F-026: validate instrument_id is a UUID to prevent path traversal attacks.
    try:
        _uuid.UUID(instrument_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid instrument_id — must be a UUID")  # noqa: B904

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
        instrument_id=instrument_id,
        make_headers=lambda: _auth_headers(request),
    )


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
        raise HTTPException(status_code=e.status, detail=e.detail) from e


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
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


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
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


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
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")
