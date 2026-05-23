"""Portfolio, holdings, transactions, watchlist, brokerage, and feedback routes.

Handles /v1/portfolios/*, /v1/portfolio/*, /v1/dashboard/*, /v1/holdings/*,
/v1/transactions, /v1/watchlists/*, /v1/brokerage-connections/*, /v1/admin/*,
/v1/feedback/* — primarily proxies to S1 Portfolio service.
Split from proxy.py (PLAN-0089 B-3).
"""

from __future__ import annotations

import asyncio
import json
import uuid as _uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, Response

from api_gateway.clients import DownstreamError, get_watchlist_insights
from api_gateway.routes.helpers import _auth_headers, _clients, _portfolio_headers, _system_headers
from api_gateway.schemas import (
    DashboardSnapshotResponse,
    PortfolioBundleResponse,
    PortfolioResponse,
    PortfolioSectorAttributionResponse,
    SectorBucket,
    WatchlistResponse,
)
from observability.logging import get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]

router = APIRouter(prefix="/v1")


# ── Brokerage Connections (PRD-0022 Wave D-2) ─────────────────────────────────


@router.post("/brokerage-connections")
async def initiate_brokerage_connection(request: Request) -> Any:
    """Proxy POST /api/v1/brokerage-connections → S1 Portfolio service.

    Requires authentication. Registers a SnapTrade user and creates a PENDING
    brokerage connection. Rate-limited at 30/min (involves external API calls).
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    body = await request.body()
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.portfolio.post(
        "/api/v1/brokerage-connections",
        content=body,
        headers={"Content-Type": "application/json", **headers},
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/brokerage-connections")
async def list_brokerage_connections(request: Request) -> Any:
    """Proxy GET /api/v1/brokerage-connections → S1 Portfolio service.

    Requires authentication. Lists brokerage connections for the authenticated user.
    Forwards optional `portfolio_id` query parameter.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.portfolio.get(
        "/api/v1/brokerage-connections",
        params=dict(request.query_params),
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.delete("/brokerage-connections/{connection_id}", status_code=200)
async def disconnect_brokerage_connection(connection_id: str, request: Request) -> Any:
    """Proxy DELETE /api/v1/brokerage-connections/{id} → S1 Portfolio service.

    Requires authentication. Revokes the SnapTrade authorization and marks the
    connection as DISCONNECTED. Rate-limited at 30/min (involves external API calls).
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.portfolio.delete(
        f"/api/v1/brokerage-connections/{connection_id}",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/brokerage-connections/{connection_id}/callback")
async def brokerage_connection_callback(connection_id: str, request: Request) -> Any:
    """Proxy GET /api/v1/brokerage-connections/{id}/callback → S1 Portfolio service.

    Requires authentication. Handles the OAuth callback from SnapTrade after the
    user completes the authorization flow. Forwards authorizationId query param.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.portfolio.get(
        f"/api/v1/brokerage-connections/{connection_id}/callback",
        params=dict(request.query_params),
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/brokerage-connections/{connection_id}/sync-errors")
async def get_brokerage_sync_errors(connection_id: str, request: Request) -> Any:
    """Proxy GET /api/v1/brokerage-connections/{id}/sync-errors → S1 Portfolio service.

    Requires authentication. Returns transaction sync errors for a connection.
    Forwards `limit` query parameter. raw_transaction is excluded from S1 response
    (PRD-0022 §6.4 privacy invariant).
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.portfolio.get(
        f"/api/v1/brokerage-connections/{connection_id}/sync-errors",
        params=dict(request.query_params),
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.post("/brokerage-connections/{connection_id}/sync", status_code=202)
async def trigger_brokerage_connection_sync(connection_id: str, request: Request) -> Any:
    """Proxy POST /api/v1/brokerage-connections/{id}/sync → S1 Portfolio service.

    Triggers an immediate sync cycle for a single brokerage connection.
    Returns 202 immediately — sync runs in the background.
    Rate-limited at 30 req/min (same as other brokerage endpoints).
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.portfolio.post(
        f"/api/v1/brokerage-connections/{connection_id}/sync",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/brokerage-connections/{connection_id}/balance")
async def get_brokerage_connection_balance(connection_id: str, request: Request) -> Any:
    """Proxy GET /api/v1/brokerage-connections/{id}/balance → S1 Portfolio service.

    Returns cash/buying-power balance for the primary brokerage account linked
    to this connection.  Returns ``{"available": false}`` (not 500) when SnapTrade
    cannot provide balance data, so the frontend renders an em-dash truthfully.
    Requires authentication.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.portfolio.get(
        f"/api/v1/brokerage-connections/{connection_id}/balance",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# ── Portfolio + Holdings + Transactions (PRD-0028 Wave S9-2) ─────────────────


@router.get("/portfolios", response_model=list[PortfolioResponse], response_model_exclude_none=True)
async def list_portfolios(request: Request) -> Any:
    """Proxy GET /api/v1/portfolios → S1 Portfolio service.

    Requires authentication. Returns all portfolios owned by the authenticated user.
    Uses _portfolio_headers() to map X-User-Id → X-Owner-ID as S1 expects.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _portfolio_headers(request)
    clients = _clients(request)
    resp = await clients.portfolio.get(
        "/api/v1/portfolios",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.post("/portfolios", status_code=201)
async def create_portfolio(request: Request) -> Any:
    """Proxy POST /api/v1/portfolios → S1 Portfolio service.

    Requires authentication. Creates a new portfolio for the authenticated user.
    S1's PortfolioCreateRequest requires owner_user_id which we inject from the
    JWT claim so the frontend never needs to pass it explicitly — the server
    always uses the verified identity from the JWT (not client-supplied data).
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")

    # Read the frontend's request body (just {name, currency})
    raw_body = await request.body()
    try:
        frontend_body: dict[str, Any] = json.loads(raw_body) if raw_body else {}
    except Exception:
        frontend_body = {}

    # Inject owner_user_id from the verified JWT claim — never trust the client to
    # supply their own user_id (that would allow account takeover via forged ID).
    # WHY dict.get() not getattr(): request.state.user is always a plain dict (set by
    # OIDCAuthMiddleware), never a Pydantic model or dataclass. getattr() only works on
    # object attributes, not dict keys, so it silently returned None and caused 422.
    user = request.state.user
    user_id = (
        (user.get("user_id") if isinstance(user, dict) else getattr(user, "user_id", None))
        or (user.get("sub") if isinstance(user, dict) else getattr(user, "sub", None))
        or ""
    )
    enriched_body: dict[str, Any] = {
        **frontend_body,
        "owner_user_id": str(user_id),
    }

    headers = _portfolio_headers(request)
    clients = _clients(request)
    resp = await clients.portfolio.post(
        "/api/v1/portfolios",
        content=json.dumps(enriched_body).encode(),
        headers={"Content-Type": "application/json", **headers},
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# F-013 (QA 2026-04-28) — DELETE proxy. S1 already exposes the handler
# (``/api/v1/portfolios/{id}`` DELETE) and rejects ROOT portfolios with
# RootPortfolioNotArchivableError. The gateway just needs to forward the
# call so the frontend Delete button can wire up.
@router.delete("/portfolios/{portfolio_id}", status_code=204)
async def delete_portfolio(portfolio_id: str, request: Request) -> Response:
    """Proxy DELETE /api/v1/portfolios/{id} → S1 Portfolio service.

    Returns 204 No Content on success. S1 returns 400 with
    RootPortfolioNotArchivableError when the user attempts to delete the
    root aggregate — the frontend disables the button for root anyway,
    but the server-side guard is the authoritative check.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _portfolio_headers(request)
    clients = _clients(request)
    resp = await clients.portfolio.delete(
        f"/api/v1/portfolios/{portfolio_id}",
        headers=headers,
    )
    # S1 returns 204 with no body on success. Pass status + body through
    # so the frontend can read the error envelope on failures.
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# ── PLAN-0070 C-1: Portfolio page bundle ─────────────────────────────────────


@router.get(
    "/portfolio/{portfolio_id}/bundle",
    response_model=PortfolioBundleResponse,
    response_model_exclude_none=True,
)
async def get_portfolio_bundle_endpoint(
    portfolio_id: str,
    request: Request,
) -> dict[str, Any]:
    """Portfolio page bundle — collapses 4 portfolio queries into 1 round-trip.

    PLAN-0070 C-1 / T-C-1-02. Returns:
      - portfolio: portfolio metadata (GET /api/v1/portfolios/{id})
      - holdings: holdings list (GET /api/v1/holdings/{id})
      - transactions: recent 30 transactions (GET /api/v1/portfolios/{id}/transactions)
      - value_history: equity curve data (GET /api/v1/portfolios/{id}/value-history)

    Each sub-resource degrades independently — failed legs return null so the
    frontend can render partial UIs while showing "—" for unavailable data.
    _meta.partial=True when any leg failed; _meta.legs_failed counts the misses.

    WHY auth required: all portfolio sub-resources are tenant-scoped; unauthenticated
    access would expose financial data. OIDCAuthMiddleware does NOT enforce auth
    by itself — individual routes must check.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")

    # WHY UUID validation: prevents path injection. portfolio_id appears in
    # 4 downstream URLs; a crafted string like "../../etc" could traverse paths
    # on services with naive routing. UUID format is the only valid S1 ID shape.
    try:
        _uuid.UUID(portfolio_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid portfolio_id — must be a UUID")  # noqa: B904

    # PLAN-0089 B-2: delegates to PortfolioBundleUseCase (application layer).
    # The external behaviour is identical — the use case wraps get_portfolio_bundle.
    from api_gateway.application.use_cases.portfolio_bundle import PortfolioBundleUseCase

    use_case = PortfolioBundleUseCase(
        # http_client not used directly (ServiceClients holds the per-service clients),
        # but GatewayUseCase requires it — pass a dummy reference for now.
        http_client=_clients(request).portfolio,
        settings=request.app.state.settings,
        service_clients=_clients(request),
    )
    result = await use_case.execute(
        portfolio_id=portfolio_id,
        # WHY lambda (not _auth_headers() called once): each downstream leg needs
        # a fresh JWT with a unique JTI. Calling _auth_headers() once and sharing
        # the result would trigger JTI replay detection on all 4 parallel calls.
        make_headers=lambda: _auth_headers(request),
    )
    return result  # type: ignore[no-any-return]


# ── Dashboard snapshot bundle (PLAN-0070 C-2) ─────────────────────────────────


@router.get(
    "/dashboard/snapshot",
    response_model=DashboardSnapshotResponse,
    response_model_exclude_none=True,
)
async def get_dashboard_snapshot_endpoint(request: Request) -> dict[str, Any]:
    """Dashboard snapshot — collapses 6+ initial queries into 1 round-trip.

    PLAN-0070 C-2 / T-C-2-02. Returns all data needed for the dashboard page
    initial cold-start load:
      - news              : top 8 ranked articles (S6 nlp-pipeline)
      - heatmap           : GICS sector heatmap (S3 market-data, 11-sector fan-out)
      - prediction_markets: top 5 prediction markets (S3 market-data)
      - earnings_calendar : upcoming 7-day company earnings (S7 knowledge-graph)
      - alerts            : top 10 pending alerts (S10 alert)
      - morning_brief     : AI-generated morning briefing (S8 rag-chat)

    NOT included (require per-instrument lookups or are lazy-loaded):
      - top movers (requires N individual quote calls after screener)
      - watchlist insights (requires portfolio service member lookup)

    Each sub-resource degrades independently — failed legs return null so the
    frontend can render partial UIs while showing "—" for unavailable data.
    _meta.partial=True when any leg failed; _meta.legs_failed counts the misses.

    WHY auth required: all sub-resources are tenant-scoped (alerts, briefings)
    or rely on the X-Internal-JWT header being forwarded to downstream services.
    OIDCAuthMiddleware does NOT enforce auth by itself — individual routes must check.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")

    # PLAN-0089 B-2: delegates to DashboardSnapshotUseCase (application layer).
    # The external behaviour is identical — the use case wraps get_dashboard_snapshot.
    from api_gateway.application.use_cases.dashboard_snapshot import DashboardSnapshotUseCase

    use_case = DashboardSnapshotUseCase(
        # http_client not used directly (ServiceClients holds the per-service clients),
        # but GatewayUseCase requires it — pass a dummy reference for now.
        http_client=_clients(request).market_data,
        settings=request.app.state.settings,
        service_clients=_clients(request),
    )
    result = await use_case.execute(
        # WHY lambda (not _auth_headers() called once): each of the 6 downstream
        # legs needs a fresh JWT with a unique JTI. Calling _auth_headers() once
        # and sharing the result would trigger JTI replay detection.
        make_headers=lambda: _auth_headers(request),
    )
    return result  # type: ignore[no-any-return]


@router.get("/holdings/{portfolio_id}")
async def get_holdings(
    portfolio_id: str,
    request: Request,
    include_closed: bool = Query(
        default=False,
        description=(
            "F-303 (QA iter-3): forward to S1 so the caller can opt in to"
            " seeing zero-quantity (closed) positions. Default false."
        ),
    ),
) -> Any:
    """Proxy GET /api/v1/holdings/{portfolio_id} → S1 Portfolio service.

    Requires authentication. Returns all holdings for the specified portfolio.

    F-303 (QA iter-3): forwards ``?include_closed`` query param so the
    backend can filter zero-quantity holdings by default. Without this
    forward the proxy strips the param and the user always sees the
    default-filtered list — defeating the opt-in for tax/audit views.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _portfolio_headers(request)
    clients = _clients(request)
    resp = await clients.portfolio.get(
        f"/api/v1/holdings/{portfolio_id}",
        headers=headers,
        params={"include_closed": "true"} if include_closed else None,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/portfolios/{portfolio_id}/performance")
async def get_portfolio_performance(
    portfolio_id: str,
    period: str = Query(default="1D", pattern="^(1D|1W|1M)$"),
    request: Request = ...,  # type: ignore[assignment]
) -> Any:
    """Composition endpoint — portfolio period return.

    WHY a composition endpoint (not a proxy): S1 holds position sizes but not
    prices; S3 (market-data) holds OHLCV but not portfolio weights. Computing a
    weighted portfolio return requires data from both services simultaneously.
    The frontend cannot safely call two services itself (CORS + auth complexity),
    so S9 stitches the two data sources here.

    Algorithm:
      1. Fetch holdings from S1 — gives us quantity + average_cost per instrument
      2. Fetch the last N OHLCV bars from S3 for all instrument_ids in bulk
         (1D → 2 bars; 1W → 6 bars; 1M → 23 bars)
      3. For each holding: weight = cost_basis_value / total_cost_basis
         period_return_i = close_end / close_start - 1
      4. Weighted sum → portfolio period return

    Graceful degradation: if S3 has no bars for an instrument (e.g. a new
    ticker not yet ingested), that position is excluded from the calculation.
    The response includes a `covered_pct` field so the frontend can show a
    caveat when coverage is partial.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")

    headers = _portfolio_headers(request)
    clients = _clients(request)

    # Step 1 — fetch holdings from S1
    holdings_resp = await clients.portfolio.get(
        f"/api/v1/holdings/{portfolio_id}",
        headers=headers,
    )
    if holdings_resp.status_code != 200:
        return Response(
            content=holdings_resp.content,
            status_code=holdings_resp.status_code,
            media_type="application/json",
        )

    try:
        holdings_data_raw = json.loads(holdings_resp.content)
    except Exception:
        raise HTTPException(status_code=502, detail="Invalid response from portfolio service")  # noqa: B904

    # F-011 (QA 2026-04-28): S1 now returns ``{items, total, limit, offset}``.
    # Accept both shapes here so a partial roll-out (gateway upgraded but
    # portfolio service not yet restarted) doesn't break the performance
    # endpoint. Older gateway-tests that mock the bare-array shape stay
    # green for the same reason.
    holdings_data = (
        holdings_data_raw
        if isinstance(holdings_data_raw, list)
        else (holdings_data_raw.get("items") or [])
        if isinstance(holdings_data_raw, dict)
        else []
    )

    if not holdings_data:
        return {
            "portfolio_id": portfolio_id,
            "period": period,
            "return_pct": 0.0,
            "return_abs": 0.0,
            "covered_pct": 0.0,
        }

    # Period → calendar-day lookback for the OHLCV start date.
    # WHY calendar days (not trading days): the S3 bulk endpoint filters by start/end
    # date (not count). We use calendar days with buffer for weekends/holidays so the
    # range always covers the required number of trading days.
    # 1D → 5 days back (covers Mon→last-close; e.g. Mon Apr 28 → Fri Apr 25 has bars)
    # 1W → 10 calendar days (~5 trading days with weekend buffer)
    # 1M → 35 calendar days (~22 trading days with buffer)
    period_lookback = {"1D": 5, "1W": 10, "1M": 35}
    lookback_days = period_lookback[period]
    today = datetime.now(tz=UTC).date()
    start_date = today - timedelta(days=lookback_days)

    instrument_ids = [str(h["instrument_id"]) for h in holdings_data if h.get("instrument_id")]
    if not instrument_ids:
        return {
            "portfolio_id": portfolio_id,
            "period": period,
            "return_pct": 0.0,
            "return_abs": 0.0,
            "covered_pct": 0.0,
        }

    # Step 2 — fetch OHLCV bulk from S3 (one request for all instruments)
    # WHY start/end date params (not limit): the S3 bulk endpoint doesn't accept limit.
    # Using a calendar-day window ensures each period shows distinct return values.
    s3_headers = _auth_headers(request)
    try:
        ohlcv_params: list[tuple[str, str]] = [("instrument_ids", iid) for iid in instrument_ids] + [
            ("timeframe", "1d"),
            ("start", start_date.isoformat()),
            ("end", today.isoformat()),
        ]
        ohlcv_resp = await clients.market_data.get(
            "/api/v1/ohlcv/bulk",
            params=ohlcv_params,  # type: ignore[arg-type]
            headers=s3_headers,
        )
    except Exception:
        logger.warning("portfolio_performance_ohlcv_fetch_failed", portfolio_id=portfolio_id, exc_info=True)
        raise HTTPException(status_code=502, detail="Market data unavailable")  # noqa: B904

    if ohlcv_resp.status_code != 200:
        logger.warning(
            "portfolio_performance_ohlcv_non200",
            portfolio_id=portfolio_id,
            status=ohlcv_resp.status_code,
        )
        raise HTTPException(status_code=502, detail="Market data returned an error")

    try:
        ohlcv_data = json.loads(ohlcv_resp.content)
    except Exception:
        raise HTTPException(status_code=502, detail="Invalid OHLCV response")  # noqa: B904

    # Build a map: instrument_id → sorted list of close prices (oldest first)
    price_map: dict[str, list[float]] = {}
    for series in ohlcv_data:
        items = series.get("items", [])
        if not items:
            continue
        # items are newest-first from S3 (limit=N returns last N bars); sort ascending
        sorted_bars = sorted(items, key=lambda b: b.get("bar_date", ""))
        closes = [float(b["close"]) for b in sorted_bars if b.get("close") is not None]
        if len(closes) >= 2:
            # Use index [0] as start price and [-1] as end price within the window
            # S3 may return fewer bars than requested for recently-listed instruments
            instrument_id = str(sorted_bars[0].get("instrument_id", ""))
            if instrument_id:
                price_map[instrument_id] = closes

    # Step 3 — compute weighted portfolio return
    total_cost_basis = 0.0
    covered_cost_basis = 0.0
    weighted_return_sum = 0.0
    weighted_abs_sum = 0.0

    for h in holdings_data:
        iid = str(h.get("instrument_id", ""))
        try:
            qty = float(h.get("quantity", 0))
            cost = float(h.get("average_cost", 0))
        except (TypeError, ValueError):
            continue
        cost_basis = qty * cost
        total_cost_basis += cost_basis

        closes = price_map.get(iid) or []
        if len(closes) < 2:
            continue

        period_return = closes[-1] / closes[0] - 1
        covered_cost_basis += cost_basis
        weighted_return_sum += period_return * cost_basis
        weighted_abs_sum += period_return * cost_basis  # same factor, in cost-basis units

    if total_cost_basis <= 0:
        return {
            "portfolio_id": portfolio_id,
            "period": period,
            "return_pct": 0.0,
            "return_abs": 0.0,
            "covered_pct": 0.0,
        }

    covered_pct = covered_cost_basis / total_cost_basis if total_cost_basis > 0 else 0.0
    portfolio_return_pct = (weighted_return_sum / covered_cost_basis * 100) if covered_cost_basis > 0 else 0.0
    # Return in absolute USD is the return % applied to covered cost basis
    portfolio_return_abs = weighted_abs_sum if covered_cost_basis > 0 else 0.0

    return {
        "portfolio_id": portfolio_id,
        "period": period,
        "return_pct": round(portfolio_return_pct, 4),
        "return_abs": round(portfolio_return_abs, 2),
        "covered_pct": round(covered_pct, 4),
    }


# ── PLAN-0046 Wave 5 — Portfolio analytics proxies ──────────────────────────


@router.get("/portfolios/{portfolio_id}/value-history")
async def get_portfolio_value_history(portfolio_id: str, request: Request) -> Any:
    """Proxy GET /api/v1/portfolios/{id}/value-history → S1 Portfolio service.

    PLAN-0046 Wave 5 / T-46-5-01. Forwards ``from`` / ``to`` / ``granularity``
    query params unchanged. S1 returns 404 if the portfolio is missing or
    not owned by the caller's tenant — surface that to the frontend.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _portfolio_headers(request)
    clients = _clients(request)
    resp = await clients.portfolio.get(
        f"/api/v1/portfolios/{portfolio_id}/value-history",
        params=dict(request.query_params),
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# F-204 (QA iter-2): admin trigger so an operator can rebuild today's
# portfolio_value_snapshots row after a manual data fix. The frontend does
# not call this — the gateway exposes it for ops use through curl/dev tools
# with the operator's own JWT. S1 enforces tenant ownership.
@router.post("/admin/portfolios/{portfolio_id}/recompute-snapshot")
async def recompute_portfolio_snapshot(portfolio_id: str, request: Request) -> Any:
    """Proxy POST /api/v1/admin/portfolios/{id}/recompute-snapshot → S1.

    Idempotent on the S1 side (upsert keyed on
    ``(portfolio_id, snapshot_date)``). Auth required — any authenticated
    user can trigger this for portfolios in their own tenant; we accept
    the broad authorization because the auth-roles wiring (admin tier) is
    deferred (PRD-0025) and the operation is non-destructive.
    """
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    # F-013: require admin role — this endpoint triggers a server-side computation
    # and should not be accessible to regular authenticated users.
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    headers = _portfolio_headers(request)
    clients = _clients(request)
    resp = await clients.portfolio.post(
        f"/api/v1/admin/portfolios/{portfolio_id}/recompute-snapshot",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# ── PLAN-0051 Wave A — realised P&L (T-A-1-04) ───────────────────────────────


@router.get("/portfolios/{portfolio_id}/realized-pnl")
async def get_portfolio_realized_pnl(portfolio_id: str, request: Request) -> Any:
    """Proxy GET /api/v1/portfolios/{id}/realized-pnl → S1 Portfolio service.

    PLAN-0051 / T-A-1-04. Forwards ``from`` / ``to`` query params unchanged.
    The S1 use case computes FIFO realised P&L over the full transaction
    history (including fully-closed positions) and returns the result with
    a per-instrument breakdown the frontend renders as the totals row.

    Cache hint: ``Cache-Control: max-age=300`` — realised P&L only changes
    when a new SELL is recorded, so 5 minutes of edge caching is safe and
    cuts back on the FIFO walk for read-heavy dashboards.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _portfolio_headers(request)
    clients = _clients(request)
    resp = await clients.portfolio.get(
        f"/api/v1/portfolios/{portfolio_id}/realized-pnl",
        params=dict(request.query_params),
        headers=headers,
    )
    # Mirror S1's status code, body, and content-type. Add the cache header
    # only on 200 — error responses (404 / 400) must not be cached.
    response_headers: dict[str, str] = {}
    if resp.status_code == 200:
        response_headers["Cache-Control"] = "max-age=300"
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type="application/json",
        headers=response_headers,
    )


@router.get("/portfolios/{portfolio_id}/exposure")
async def get_portfolio_exposure(portfolio_id: str, request: Request) -> Any:
    """Proxy GET /api/v1/portfolios/{id}/exposure → S1 Portfolio service.

    PLAN-0046 Wave 5 / T-46-5-02. S1 itself reaches out to S3 over REST
    to fetch current prices (R9-compliant — no cross-service DB).
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _portfolio_headers(request)
    clients = _clients(request)
    resp = await clients.portfolio.get(
        f"/api/v1/portfolios/{portfolio_id}/exposure",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# ── PLAN-0088 Wave E — Holdings redesign ──────────────────────────────────────


@router.get("/portfolios/{portfolio_id}/holdings/{instrument_id}/lots")
async def get_holding_lots(portfolio_id: str, instrument_id: str, request: Request) -> Any:
    """PLAN-0088 E-2 — proxy FIFO open-lots for a single holding.

    Forwards optional ``current_price`` query param so each lot's
    ``unrealised_pnl`` can be computed server-side without a follow-up
    quote round-trip.

    Cache hint: ``Cache-Control: max-age=60`` — lots rarely change between
    transactions; 1 minute is safe for a drill-down view.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    # WHY UUID validation: both path params reach a downstream URL — defensive
    # parsing prevents path injection if validation upstream is loosened.
    try:
        _uuid.UUID(portfolio_id)
        _uuid.UUID(instrument_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="portfolio_id and instrument_id must be UUIDs")  # noqa: B904
    headers = _portfolio_headers(request)
    clients = _clients(request)
    resp = await clients.portfolio.get(
        f"/api/v1/portfolios/{portfolio_id}/holdings/{instrument_id}/lots",
        params=dict(request.query_params),
        headers=headers,
    )
    response_headers: dict[str, str] = {}
    if resp.status_code == 200:
        response_headers["Cache-Control"] = "max-age=60"
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type="application/json",
        headers=response_headers,
    )


@router.get("/portfolios/{portfolio_id}/concentration")
async def get_portfolio_concentration(portfolio_id: str, request: Request) -> Any:
    """PLAN-0088 E-3 — proxy HHI + top-3 share concentration metrics.

    No body params; no query params. Cached for 5 minutes — concentration
    only meaningfully changes when the holdings table changes (rare in a
    user-session window).
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        _uuid.UUID(portfolio_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="portfolio_id must be a UUID")  # noqa: B904
    headers = _portfolio_headers(request)
    clients = _clients(request)
    resp = await clients.portfolio.get(
        f"/api/v1/portfolios/{portfolio_id}/concentration",
        headers=headers,
    )
    response_headers: dict[str, str] = {}
    if resp.status_code == 200:
        response_headers["Cache-Control"] = "max-age=300"
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type="application/json",
        headers=response_headers,
    )


# ── Portfolio Sector Attribution (PLAN-0091 Wave A-2, T-A-2-03) ──────────────


@router.get("/portfolios/{portfolio_id}/sector-attribution", response_model=PortfolioSectorAttributionResponse)
async def get_portfolio_sector_attribution(portfolio_id: str, request: Request) -> PortfolioSectorAttributionResponse:
    """Composition: holdings (S1) + batch quotes (S3) + per-instrument sector (S3).

    Algorithm:
      1. Fetch all holdings from S1 — quantity + average_cost per instrument
      2. Fetch current price + day_change_pct via S3 /internal/v1/price/batch
      3. Fetch sector for each unique instrument via S3 /api/v1/fundamentals/{id}
         (parallel asyncio.gather, graceful degradation to "Unknown" on failure)
      4. Group by sector → compute market_value, sector_weight_pct, sector_day_pnl
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")

    headers = _portfolio_headers(request)
    s3_headers = _auth_headers(request)
    clients = _clients(request)

    # Step 1 — holdings from S1
    holdings_resp = await clients.portfolio.get(f"/api/v1/holdings/{portfolio_id}", headers=headers)
    if holdings_resp.status_code != 200:
        return Response(  # type: ignore[return-value, no-any-return]
            content=holdings_resp.content,
            status_code=holdings_resp.status_code,
            media_type="application/json",
        )
    try:
        raw = json.loads(holdings_resp.content)
    except Exception:
        raise HTTPException(status_code=502, detail="Invalid response from portfolio service")  # noqa: B904

    holdings: list[dict[str, Any]] = (
        raw if isinstance(raw, list) else (raw.get("items") or []) if isinstance(raw, dict) else []
    )
    if not holdings:
        return PortfolioSectorAttributionResponse(portfolio_id=portfolio_id)

    instrument_ids = [str(h["instrument_id"]) for h in holdings if h.get("instrument_id")]

    # Step 2 — batch price snapshots from S3
    price_map: dict[str, dict[str, Any]] = {}
    try:
        snap_resp = await clients.market_data.post(
            "/internal/v1/price/batch",
            json={"instrument_ids": instrument_ids},
            headers={"Content-Type": "application/json", **s3_headers},
        )
        if snap_resp.status_code == 200:
            snap_list = snap_resp.json()
            if isinstance(snap_list, list):
                for snap in snap_list:
                    iid = str(snap.get("instrument_id", ""))
                    if iid:
                        price_map[iid] = snap
    except Exception:
        logger.warning("sector_attribution_price_fetch_failed", portfolio_id=portfolio_id, exc_info=True)

    # Step 3 — sector per instrument (parallel)
    async def _fetch_sector(iid: str) -> tuple[str, str]:
        try:
            r = await clients.market_data.get(
                f"/api/v1/fundamentals/{iid}",
                params={"sections": "General"},
                headers=s3_headers,
            )
            if r.status_code == 200:
                data = r.json()
                sector = str(data.get("General", {}).get("Sector") or data.get("sector") or "Unknown")
                return iid, sector
        except Exception:
            logger.debug("sector_attribution_fetch_sector_failed", instrument_id=iid, exc_info=True)
        return iid, "Unknown"

    sector_results = await asyncio.gather(*[_fetch_sector(iid) for iid in instrument_ids], return_exceptions=True)
    sector_map: dict[str, str] = {}
    for result in sector_results:
        if isinstance(result, tuple):
            sector_map[result[0]] = result[1]

    # Step 4 — aggregate by sector
    buckets_raw: dict[str, dict[str, float]] = defaultdict(lambda: {"market_value": 0.0, "day_pnl": 0.0, "count": 0.0})
    total_market_value = 0.0
    covered_value = 0.0

    for h in holdings:
        iid = str(h.get("instrument_id", ""))
        try:
            qty = float(h.get("quantity", 0))
        except (TypeError, ValueError):
            continue

        snap = price_map.get(iid, {})
        price = float(snap.get("price") or snap.get("close") or 0.0)
        if price <= 0:
            continue

        market_val = qty * price
        day_change_pct = float(snap.get("day_change_pct") or snap.get("change_percent") or 0.0)
        day_pnl = market_val * day_change_pct / 100.0

        sector = sector_map.get(iid, "Unknown")
        buckets_raw[sector]["market_value"] += market_val
        buckets_raw[sector]["day_pnl"] += day_pnl
        buckets_raw[sector]["count"] += 1.0
        total_market_value += market_val
        if sector != "Unknown":
            covered_value += market_val

    buckets = [
        SectorBucket(
            sector=sector,
            holding_count=int(vals["count"]),
            market_value=round(vals["market_value"], 2),
            sector_weight_pct=round(vals["market_value"] / total_market_value * 100, 4)
            if total_market_value > 0
            else 0.0,
            sector_day_pnl=round(vals["day_pnl"], 2),
        )
        for sector, vals in sorted(buckets_raw.items(), key=lambda x: -x[1]["market_value"])
    ]

    covered_pct = covered_value / total_market_value if total_market_value > 0 else 0.0
    return PortfolioSectorAttributionResponse(
        portfolio_id=portfolio_id,
        buckets=buckets,
        covered_pct=round(covered_pct, 4),
    )


@router.get("/transactions")
async def list_transactions(request: Request) -> Any:
    """Proxy GET /api/v1/transactions → S1 Portfolio service.

    Requires authentication. S1 expects portfolio_id as the X-Portfolio-ID header
    (not as a query parameter).  We extract it from query params and inject it as
    a header so S1 can authenticate portfolio ownership.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _portfolio_headers(request)
    clients = _clients(request)
    # API-004: portfolio_id must be forwarded as X-Portfolio-ID header, not query param.
    # S1 validates X-Portfolio-ID to ensure portfolio belongs to the authenticated tenant.
    qp = dict(request.query_params)
    portfolio_id = qp.pop("portfolio_id", None)
    if portfolio_id:
        headers["X-Portfolio-ID"] = portfolio_id
    resp = await clients.portfolio.get(
        "/api/v1/transactions",
        params=qp,
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# F-012 (QA 2026-04-28) — nested transactions form mirrors the analytics
# routes (``/portfolios/{id}/value-history``, ``/exposure``, ``/risk-metrics``)
# so REST consumers can stay consistent. The flat ``/v1/transactions`` route
# above remains as the canonical path for backward compatibility.
@router.get("/portfolios/{portfolio_id}/transactions")
async def list_transactions_nested(portfolio_id: str, request: Request) -> Any:
    """Proxy GET /api/v1/portfolios/{id}/transactions → S1 Portfolio service.

    F-012: nested alias preferred for new clients. S1 owns both the nested
    and the flat handlers (see ``services/portfolio/.../transaction.py``).
    Forwards limit/offset query params unchanged.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _portfolio_headers(request)
    clients = _clients(request)
    resp = await clients.portfolio.get(
        f"/api/v1/portfolios/{portfolio_id}/transactions",
        params=dict(request.query_params),
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.post("/transactions")
async def create_transaction(request: Request) -> Any:
    """Proxy POST /api/v1/transactions → S1 Portfolio service.

    Requires authentication. Forwards the request body containing the transaction
    details to S1.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    body = await request.body()
    headers = _portfolio_headers(request)
    clients = _clients(request)
    resp = await clients.portfolio.post(
        "/api/v1/transactions",
        content=body,
        headers={"Content-Type": "application/json", **headers},
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# ── Watchlists (PRD-0028 Wave S9-2) ─────────────────────────────────────────


@router.patch("/watchlists/{watchlist_id}")
async def rename_watchlist(watchlist_id: str, request: Request) -> Any:
    """Proxy PATCH /api/v1/watchlists/{watchlist_id} → S1 Portfolio service.

    Requires authentication. Renames the watchlist (body: {"name": "New Name"}).
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    body = await request.body()
    headers = _portfolio_headers(request)
    clients = _clients(request)
    resp = await clients.portfolio.patch(
        f"/api/v1/watchlists/{watchlist_id}",
        content=body,
        headers={"Content-Type": "application/json", **headers},
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/watchlists", response_model=list[WatchlistResponse], response_model_exclude_none=True)
async def list_watchlists(request: Request) -> Any:
    """Proxy GET /api/v1/watchlists → S1 Portfolio service.

    Requires authentication. Returns all watchlists owned by the authenticated user.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _portfolio_headers(request)
    clients = _clients(request)
    resp = await clients.portfolio.get(
        "/api/v1/watchlists",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.post("/watchlists")
async def create_watchlist(request: Request) -> Any:
    """Proxy POST /api/v1/watchlists → S1 Portfolio service.

    Requires authentication. Forwards the request body for watchlist creation.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    body = await request.body()
    headers = _portfolio_headers(request)
    clients = _clients(request)
    resp = await clients.portfolio.post(
        "/api/v1/watchlists",
        content=body,
        headers={"Content-Type": "application/json", **headers},
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/watchlists/{watchlist_id}")
async def get_watchlist(watchlist_id: str, request: Request) -> Any:
    """Proxy GET /api/v1/watchlists/{watchlist_id} → S1 Portfolio service.

    Requires authentication. Returns a single watchlist with its members.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _portfolio_headers(request)
    clients = _clients(request)
    resp = await clients.portfolio.get(
        f"/api/v1/watchlists/{watchlist_id}",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.delete("/watchlists/{watchlist_id}", status_code=200)
async def delete_watchlist(watchlist_id: str, request: Request) -> Any:
    """Proxy DELETE /api/v1/watchlists/{watchlist_id} → S1 Portfolio service.

    Uses status_code=200 (BP-064: FastAPI ≤0.111 validation error with 204+body).
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _portfolio_headers(request)
    clients = _clients(request)
    resp = await clients.portfolio.delete(
        f"/api/v1/watchlists/{watchlist_id}",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/watchlists/{watchlist_id}/members")
async def list_watchlist_members(watchlist_id: str, request: Request) -> Any:
    """Proxy GET /api/v1/watchlists/{watchlist_id}/members → S1 Portfolio service.

    Requires authentication. Forwards the standard ``limit``/``offset`` query
    string straight through. PLAN-0046 / T-46-2-02 — replaces the old client
    behaviour where the gateway hard-coded ``members: []`` (BP-265).
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _portfolio_headers(request)
    clients = _clients(request)
    # Preserve the inbound query string so pagination params reach S1 verbatim.
    qs = request.url.query
    target_path = f"/api/v1/watchlists/{watchlist_id}/members"
    if qs:
        target_path = f"{target_path}?{qs}"
    resp = await clients.portfolio.get(
        target_path,
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.post("/watchlists/{watchlist_id}/members")
async def add_watchlist_member(watchlist_id: str, request: Request) -> Any:
    """Proxy POST /api/v1/watchlists/{watchlist_id}/members → S1 Portfolio service.

    Requires authentication. Forwards the entity to add as a watchlist member.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    body = await request.body()
    headers = _portfolio_headers(request)
    clients = _clients(request)
    resp = await clients.portfolio.post(
        f"/api/v1/watchlists/{watchlist_id}/members",
        content=body,
        headers={"Content-Type": "application/json", **headers},
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.delete("/watchlists/{watchlist_id}/members/{entity_id}", status_code=200)
async def remove_watchlist_member(watchlist_id: str, entity_id: str, request: Request) -> Any:
    """Proxy DELETE /api/v1/watchlists/{wid}/members/{eid} → S1 Portfolio service.

    Uses status_code=200 (BP-064: FastAPI ≤0.111 validation error with 204+body).
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _portfolio_headers(request)
    clients = _clients(request)
    resp = await clients.portfolio.delete(
        f"/api/v1/watchlists/{watchlist_id}/members/{entity_id}",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/watchlists/{watchlist_id}/insights")
async def watchlist_insights(watchlist_id: str, request: Request) -> Response:
    """Composite insights for a single watchlist (PLAN-0050 Wave B / T-B-2-01).

    Combines members + live quotes + per-member sectors + 24h news linkage +
    pending alerts in one server-side fan-out, replacing the prior 5-query
    chain in the WatchlistMoversWidget. Returns the shape
    ``{watchlist_id, members_count, movers, weighted_return_1d, sectors,
    biggest_news, alerts_count}``.

    Auth: required — operates over the user's own watchlist members.
    Cache-Control: ``private, max-age=60`` — the watchlist's makeup is
    user-specific (private) and the live quote slice goes stale within ~60s,
    matching the WatchlistMoversWidget's intra-day refetch cadence.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        payload = await get_watchlist_insights(
            _clients(request),
            watchlist_id,
            make_headers=lambda: _auth_headers(request),
        )
    except DownstreamError as e:
        raise HTTPException(status_code=e.status, detail=e.detail) from e

    body = json.dumps(payload).encode()
    # WHY private: the response is user-scoped (their watchlist's members
    # + alert flags). A shared CDN must never serve one user's response to
    # another. WHY max-age=60: matches the underlying widget's quote refresh
    # cadence — anything tighter wastes round-trips, anything wider would
    # show stale gainers/losers during the trading day.
    return Response(
        content=body,
        status_code=200,
        media_type="application/json",
        headers={"Cache-Control": "private, max-age=60"},
    )


# ── Feedback subsystem (PLAN-0052 Wave D) ───────────────────────────────────
# Thin proxy from /v1/feedback/* → S1 portfolio service /api/v1/feedback/*.
# All routes forward the X-Internal-JWT issued by the gateway so backend
# InternalJWTMiddleware can authenticate (and so role / tenant / user_id
# arrive at the portfolio router via request.state).
#
# Public POST /submissions and POST /micro-survey work for unauthenticated
# users (e.g. docs page) — the gateway issues a system JWT for those.


@router.post("/feedback/submissions", status_code=201)
async def feedback_create_submission(request: Request) -> Response:
    """Anonymous-friendly: accepts unauthenticated requests when body has email."""
    body = await request.body()
    # When unauthenticated, attach a system JWT so backend InternalJWTMiddleware
    # admits the request — the route then enforces the email-required rule.
    headers = _portfolio_headers(request) if getattr(request.state, "user", None) else _system_headers(request)
    clients = _clients(request)
    resp = await clients.portfolio.post(
        "/api/v1/feedback/submissions",
        content=body,
        headers={"Content-Type": "application/json", **headers},
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/feedback/submissions")
async def feedback_list_submissions(request: Request) -> Response:
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _portfolio_headers(request)
    clients = _clients(request)
    qs = request.url.query
    target = "/api/v1/feedback/submissions"
    if qs:
        target = f"{target}?{qs}"
    resp = await clients.portfolio.get(target, headers=headers)
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/feedback/submissions/anonymous")
async def feedback_list_anonymous_submissions(request: Request) -> Response:
    """F-Q1-04: admin-only proxy — list submissions made by unauthenticated users.

    Defined BEFORE ``/feedback/submissions/{submission_id}`` so the literal
    "anonymous" segment wins over the UUID parameter.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _portfolio_headers(request)
    clients = _clients(request)
    qs = request.url.query
    target = "/api/v1/feedback/submissions/anonymous"
    if qs:
        target = f"{target}?{qs}"
    resp = await clients.portfolio.get(target, headers=headers)
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/feedback/submissions/{submission_id}")
async def feedback_get_submission(submission_id: str, request: Request) -> Response:
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _portfolio_headers(request)
    clients = _clients(request)
    resp = await clients.portfolio.get(
        f"/api/v1/feedback/submissions/{submission_id}",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.patch("/feedback/submissions/{submission_id}")
async def feedback_update_submission(submission_id: str, request: Request) -> Response:
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    body = await request.body()
    headers = _portfolio_headers(request)
    clients = _clients(request)
    resp = await clients.portfolio.patch(
        f"/api/v1/feedback/submissions/{submission_id}",
        content=body,
        headers={"Content-Type": "application/json", **headers},
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.delete(
    "/feedback/submissions/{submission_id}",
    status_code=204,
    response_class=Response,
    response_model=None,
)
async def feedback_delete_submission(submission_id: str, request: Request) -> Response:
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _portfolio_headers(request)
    clients = _clients(request)
    resp = await clients.portfolio.delete(
        f"/api/v1/feedback/submissions/{submission_id}",
        headers=headers,
    )
    # F-Q1-13: 204 carries no body — omit ``media_type`` so we don't ship
    # a Content-Type header on an empty response. Only attach JSON media
    # type when the backend actually returned a body (e.g. 4xx errors).
    if resp.status_code == 204:
        return Response(status_code=204)
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.post("/feedback/nps", status_code=201)
async def feedback_post_nps(request: Request) -> Response:
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    body = await request.body()
    headers = _portfolio_headers(request)
    clients = _clients(request)
    resp = await clients.portfolio.post(
        "/api/v1/feedback/nps",
        content=body,
        headers={"Content-Type": "application/json", **headers},
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/feedback/nps/aggregate")
async def feedback_nps_aggregate(request: Request) -> Response:
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _portfolio_headers(request)
    clients = _clients(request)
    qs = request.url.query
    target = "/api/v1/feedback/nps/aggregate"
    if qs:
        target = f"{target}?{qs}"
    resp = await clients.portfolio.get(target, headers=headers)
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/feedback/features")
async def feedback_list_features(request: Request) -> Response:
    """Public roadmap — works for unauthenticated viewers (no has_voted)."""
    headers = _portfolio_headers(request) if getattr(request.state, "user", None) else _system_headers(request)
    clients = _clients(request)
    qs = request.url.query
    target = "/api/v1/feedback/features"
    if qs:
        target = f"{target}?{qs}"
    resp = await clients.portfolio.get(target, headers=headers)
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.post("/feedback/features", status_code=201)
async def feedback_create_feature(request: Request) -> Response:
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    body = await request.body()
    headers = _portfolio_headers(request)
    clients = _clients(request)
    resp = await clients.portfolio.post(
        "/api/v1/feedback/features",
        content=body,
        headers={"Content-Type": "application/json", **headers},
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.post("/feedback/features/{feature_request_id}/vote")
async def feedback_vote_feature(feature_request_id: str, request: Request) -> Response:
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _portfolio_headers(request)
    clients = _clients(request)
    resp = await clients.portfolio.post(
        f"/api/v1/feedback/features/{feature_request_id}/vote",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.patch("/feedback/features/{feature_request_id}")
async def feedback_update_feature(feature_request_id: str, request: Request) -> Response:
    """F-Q1-05: admin-only PATCH proxy for feature roadmap status updates.

    Without this proxy, admins could not move a feature through the
    proposed → planned → in_progress → shipped lifecycle from the
    frontend. The portfolio route already existed; only the gateway
    forwarder was missing.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    body = await request.body()
    headers = _portfolio_headers(request)
    clients = _clients(request)
    resp = await clients.portfolio.patch(
        f"/api/v1/feedback/features/{feature_request_id}",
        content=body,
        headers={"Content-Type": "application/json", **headers},
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.post("/feedback/micro-survey", status_code=201)
async def feedback_micro_survey(request: Request) -> Response:
    """Anonymous-friendly — used by the docs feedback widget."""
    body = await request.body()
    headers = _portfolio_headers(request) if getattr(request.state, "user", None) else _system_headers(request)
    clients = _clients(request)
    resp = await clients.portfolio.post(
        "/api/v1/feedback/micro-survey",
        content=body,
        headers={"Content-Type": "application/json", **headers},
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/feedback/beta-program/enrollment")
async def feedback_get_beta_enrollment(request: Request) -> Response:
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _portfolio_headers(request)
    clients = _clients(request)
    resp = await clients.portfolio.get(
        "/api/v1/feedback/beta-program/enrollment",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.patch("/feedback/beta-program/enrollment")
async def feedback_patch_beta_enrollment(request: Request) -> Response:
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    body = await request.body()
    headers = _portfolio_headers(request)
    clients = _clients(request)
    resp = await clients.portfolio.patch(
        "/api/v1/feedback/beta-program/enrollment",
        content=body,
        headers={"Content-Type": "application/json", **headers},
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# ── Notification preferences (W1-BACKEND / MED-022 / CRIT-004) ───────────────
#
# Proxied to S1 Portfolio service at /api/v1/users/me/notification-preferences.
# Both endpoints forward the X-Internal-JWT so S1's InternalJWTMiddleware can
# extract tenant_id from the verified RS256 JWT payload.


@router.get("/users/me/notification-preferences")
async def get_notification_preferences(request: Request) -> Any:
    """Proxy GET /api/v1/users/me/notification-preferences → S1 Portfolio service.

    Returns per-tenant notification toggle preferences. Defaults (all True) are
    returned when no preferences have been written yet — no 404 risk.
    """
    if getattr(request.state, "user", None) is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.portfolio.get(
        "/api/v1/users/me/notification-preferences",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.patch("/users/me/notification-preferences")
async def update_notification_preferences(request: Request) -> Any:
    """Proxy PATCH /api/v1/users/me/notification-preferences → S1 Portfolio service.

    Partial update — only fields included in the JSON body are changed.
    The upsert is idempotent so retrying on 5xx is safe (CRIT-006).
    """
    if getattr(request.state, "user", None) is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    body = await request.body()
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.portfolio.patch(
        "/api/v1/users/me/notification-preferences",
        content=body,
        headers={"Content-Type": "application/json", **headers},
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")
