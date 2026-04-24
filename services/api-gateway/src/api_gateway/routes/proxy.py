"""Gateway API routes — composition endpoints for the frontend."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import StreamingResponse

from api_gateway.clients import (
    DownstreamError,
    ServiceClients,
    get_company_overview,
    get_map_layers,
    get_market_heatmap,
    get_relevant_news,
    get_top_movers,
)
from api_gateway.jwt_utils import issue_public_jwt, issue_user_jwt
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

router = APIRouter(prefix="/v1")
logger = get_logger(__name__)  # type: ignore[no-any-return]


def _clients(request: Request) -> ServiceClients:
    """Shortcut to get ServiceClients from app state."""
    return cast("ServiceClients", request.app.state.clients)


def _auth_headers(request: Request) -> dict[str, str]:
    """Issue a fresh RS256 internal JWT for a single downstream call.

    Called once per downstream request (not shared across parallel calls) so
    that each JWT has a unique JTI — this prevents ``InternalJWTMiddleware``
    on backend services from raising "Token replay detected" when a single
    gateway request fans out to multiple backend calls in parallel.

    Falls back to reading the pre-issued ``X-Internal-JWT`` header if RSA keys
    are not configured (e.g. unit tests that don't run the full lifespan).
    """
    user = getattr(request.state, "user", None)
    private_key = getattr(request.app.state, "rsa_private_key", None)
    kid = getattr(request.app.state, "rsa_kid", None)
    if user is not None and private_key is not None and kid is not None:
        token = issue_user_jwt(
            user_id=user.get("user_id", ""),
            tenant_id=user.get("tenant_id", ""),
            oidc_sub=user.get("sub", ""),
            private_key=private_key,
            kid=kid,
        )
        return {"X-Internal-JWT": token}
    # Fallback: read the pre-issued JWT (tests without RSA keys / system routes)
    internal_jwt = request.headers.get("X-Internal-JWT")
    return {"X-Internal-JWT": internal_jwt} if internal_jwt else {}


def _system_headers(request: Request) -> dict[str, str]:
    """Issue a system-level JWT for public proxy routes.

    Backend services require ``X-Internal-JWT`` on every API request
    (InternalJWTMiddleware).  For public endpoints that don't have a real
    user, the gateway issues a short-lived system JWT (nil-UUID user/tenant,
    role=system) so the backend can authenticate the request.

    Returns an empty dict if RSA keys are not configured (tests without
    lifespan) — the downstream mock will not check for the header.
    """
    private_key = getattr(request.app.state, "rsa_private_key", None)
    kid = getattr(request.app.state, "rsa_kid", None)
    if private_key is None or kid is None:
        return {}
    token = issue_public_jwt(private_key, kid)
    return {"X-Internal-JWT": token}


# ── Company ───────────────────────────────────────────────


@router.get("/companies/{company_id}/overview")
async def company_overview(company_id: str, request: Request) -> dict[str, Any]:
    """Composed endpoint: instrument + quote + OHLCV + (optional) fundamentals.

    Passes a JWT factory so each of the 4 parallel downstream calls gets a fresh
    JWT with a unique JTI, preventing replay detection on market-data.
    """
    try:
        return await get_company_overview(
            _clients(request),
            company_id,
            make_headers=lambda: _auth_headers(request),
        )
    except DownstreamError as e:
        raise HTTPException(status_code=e.status, detail=e.detail) from e


# ── News ──────────────────────────────────────────────────


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


# ── Chat ──────────────────────────────────────────────────


@router.post("/chat")
async def chat(request: Request) -> Any:
    """Proxy synchronous chat request to S8 RAG/Chat service.

    Requires authentication — chat uses user context for personalised responses.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    body = await request.body()
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.rag_chat.post(
        "/api/v1/chat",
        content=body,
        headers={"Content-Type": "application/json", **headers},
    )
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type="application/json",
    )


@router.post("/chat/stream")
async def chat_stream(request: Request) -> Any:
    """Proxy SSE streaming chat to S8 — not buffered (chunked transfer).

    Requires authentication. Forwards the request body to S8 `/api/v1/chat/stream`
    and streams back Server-Sent Events without buffering, preserving the
    `text/event-stream` content type.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    body = await request.body()
    headers = _auth_headers(request)
    clients = _clients(request)

    async def _stream_body() -> AsyncIterator[bytes]:
        async with clients.rag_chat.stream(
            "POST",
            "/api/v1/chat/stream",
            content=body,
            headers={"Content-Type": "application/json", **headers},
        ) as resp:
            async for chunk in resp.aiter_bytes():
                yield chunk

    return StreamingResponse(_stream_body(), media_type="text/event-stream")


# ── Threads ───────────────────────────────────────────────


@router.post("/threads")
async def create_thread(request: Request) -> Any:
    """Create a new conversation thread (proxy to S8)."""
    body = await request.body()
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.rag_chat.post(
        "/api/v1/threads",
        content=body,
        headers={"Content-Type": "application/json", **headers},
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/threads")
async def list_threads(request: Request) -> Any:
    """List conversation threads for the authenticated user (proxy to S8)."""
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.rag_chat.get(
        "/api/v1/threads",
        params=dict(request.query_params),
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/threads/{thread_id}")
async def get_thread(thread_id: str, request: Request) -> Any:
    """Get a single conversation thread (proxy to S8)."""
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.rag_chat.get(
        f"/api/v1/threads/{thread_id}",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.delete("/threads/{thread_id}", status_code=200)
async def delete_thread(thread_id: str, request: Request) -> Any:
    """Delete a conversation thread (proxy to S8)."""
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.rag_chat.delete(
        f"/api/v1/threads/{thread_id}",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# ── Email preferences ─────────────────────────────────────────────────────────


@router.get("/email/preferences")
async def get_email_preferences(request: Request) -> Any:
    """Proxy GET /api/v1/email/preferences → S10 Alert service.

    Passes X-Tenant-Id and X-User-Id headers derived from the JWT payload
    so S10 can enforce per-user isolation.
    """
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.alert.get(
        "/api/v1/email/preferences",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.put("/email/preferences")
async def update_email_preferences(request: Request) -> Any:
    """Proxy PUT /api/v1/email/preferences → S10 Alert service.

    Passes request body unchanged; forwards X-Tenant-Id and X-User-Id headers.
    S10 returns 400 on invalid preference values (e.g., send_day_of_week > 6).
    """
    body = await request.body()
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.alert.put(
        "/api/v1/email/preferences",
        content=body,
        headers={"Content-Type": "application/json", **headers},
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# ── Screener + Timeseries (PRD-0017 Wave C-1) ─────────────────────────────────


@router.post("/fundamentals/screen")
async def screen_instruments(request: Request) -> Any:
    """Proxy POST /api/v1/fundamentals/screen → S3 Market Data.

    Public endpoint — issues a system JWT so the backend's InternalJWTMiddleware
    accepts the request.  S3 returns 400 for no filters, 422 for invalid metric/sort_by.
    """
    body = await request.body()
    clients = _clients(request)
    resp = await clients.market_data.post(
        "/api/v1/fundamentals/screen",
        content=body,
        headers={"Content-Type": "application/json", **_system_headers(request)},
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


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


# ── Similar entities (PRD-0017 Wave C-1) ─────────────────────────────────────


@router.post("/entities/similar")
async def find_similar_entities(request: Request) -> Any:
    """Proxy POST /api/v1/entities/similar → S7 Knowledge Graph.

    Public endpoint — issues a system JWT for backend authentication.
    S7 returns 404 (entity not found), 422 (no embedding), 503 (pgvector unavailable).
    """
    body = await request.body()
    clients = _clients(request)
    resp = await clients.knowledge_graph.post(
        "/api/v1/entities/similar",
        content=body,
        headers={"Content-Type": "application/json", **_system_headers(request)},
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# ── Alert endpoints (PRD-0025 T-D-1-10) ──────────────────────────────────────


@router.get("/alerts/pending")
async def get_pending_alerts(request: Request) -> Any:
    """Proxy GET /api/v1/alerts/pending → S10 Alert service.

    Requires authentication. Forwards X-Internal-JWT so S10's InternalJWTMiddleware
    can extract user_id from the JWT (PRD-0025 §T-D-1-10).
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.alert.get(
        "/api/v1/alerts/pending",
        params=dict(request.query_params),
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.delete("/alerts/{alert_id}/ack", status_code=200)
async def acknowledge_alert(alert_id: str, request: Request) -> Any:
    """Proxy DELETE /api/v1/alerts/{alert_id}/ack → S10 Alert service.

    Requires authentication. Forwards X-Internal-JWT so S10 can verify the user
    owns the alert before acknowledging it (PRD-0025 §T-D-1-10).
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.alert.delete(
        f"/api/v1/alerts/{alert_id}/ack",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# TODO: WebSocket /alerts/stream proxying requires a dedicated WS proxy implementation.
# S9 does not yet support transparent WebSocket proxying — clients must connect
# directly to S10 (alert-delivery:8010) using a short-lived token from S9.


# ── Prediction Markets (PRD-0019 Wave C-1) ────────────────────────────────────


@router.get("/signals/prediction-markets")
async def list_prediction_markets(request: Request) -> Any:
    """Proxy GET /api/v1/prediction-markets → S3 Market Data.

    Requires authentication. Forwards query params (status, limit, offset)
    and auth headers derived from the JWT payload.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.market_data.get(
        "/api/v1/prediction-markets",
        params=dict(request.query_params),
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/signals/prediction-markets/{market_id}")
async def get_prediction_market(market_id: str, request: Request) -> Any:
    """Proxy GET /api/v1/prediction-markets/{id} → S3 Market Data.

    Requires authentication. S3 returns 404 if the market_id is unknown.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.market_data.get(
        f"/api/v1/prediction-markets/{market_id}",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/signals/prediction-markets/{market_id}/history")
async def get_prediction_market_history(market_id: str, request: Request) -> Any:
    """Proxy GET /api/v1/prediction-markets/{id}/history → S3 Market Data.

    Requires authentication. Forwards from/to/limit query params.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.market_data.get(
        f"/api/v1/prediction-markets/{market_id}/history",
        params=dict(request.query_params),
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


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


def _portfolio_headers(request: Request) -> dict[str, str]:
    """Auth headers for S1 Portfolio service.

    S1 now reads tenant_id/user_id from the JWT (InternalJWTMiddleware).
    Only X-Internal-JWT is forwarded (F-MAJOR-013 remediation).
    """
    return _auth_headers(request)


# ── OHLCV + Quotes + Fundamentals (PRD-0028 Wave S9-1) ──────────────────────


@router.get("/ohlcv/{instrument_id}")
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


@router.get("/quotes/{instrument_id}")
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


# ── Manual price refresh (PLAN-0036 W1-11) ────────────────────────────────────

# WHY 300s cooldown: prevents a single user from hammering EODHD via the manual
# refresh button. Each instrument gets a per-instrument 5-minute gate. This is
# independent of the automatic cadence — a user pressing refresh ALSO counts
# against the monthly quota (quota check happens in S2's ExecuteTaskUseCase).
_REFRESH_COOLDOWN_SECONDS = 300


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
        f"/api/v1/instruments/{instrument_id}",
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
        params={"event_type": "economic", **{k: v for k, v in dict(request.query_params).items() if k != "event_type"}},
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/fundamentals/{instrument_id}")
async def get_fundamentals(instrument_id: str, request: Request) -> Any:
    """Proxy GET /api/v1/fundamentals/{instrument_id} → S3 Market Data.

    Requires authentication. Forwards query parameters (fields, etc.) to S3 for
    fundamentals data retrieval. Distinct from the public screener endpoints.
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


# ── Entity Graph + Contradictions (PRD-0028 Wave S9-1) ───────────────────────


def _transform_graph_response(raw: dict[str, Any]) -> dict[str, Any]:
    """Transform S7 GraphNeighborhoodResponse → frontend EntityGraph format.

    S7 returns: {center, relations, entities}
    Frontend expects: {entity_id, nodes, edges}

    WHY transform here (not in S7): S7 owns the domain model; S9 owns the
    presentation contract. This transformation is a BFF (Backend For Frontend)
    concern — S9 is the composition layer whose job is to shape data for the UI.
    Changing S7's response would couple the knowledge-graph domain to a single
    frontend's rendering requirements.

    Resilience: all field accesses use .get() with safe defaults so partial or
    missing fields from S7 never raise KeyError / TypeError in the gateway.
    """
    center = raw.get("center") or {}
    relations = raw.get("relations") or []
    entities = raw.get("entities") or {}

    entity_id = str(center.get("entity_id") or "")

    # Build nodes: center node first (size=2 makes it visually prominent in the
    # Cytoscape.js graph), then all related entities (size=1).
    nodes: list[dict[str, Any]] = []
    if entity_id:
        nodes.append(
            {
                "id": entity_id,
                "label": center.get("canonical_name") or "",
                "type": center.get("entity_type") or "unknown",
                "size": 2,  # Center node rendered larger than neighbors
            }
        )

    for eid, entity_data in entities.items():
        if eid == entity_id:
            # Skip if S7 also includes the center in the entities dict
            continue
        nodes.append(
            {
                "id": str(entity_data.get("entity_id") or eid),
                "label": entity_data.get("canonical_name") or "",
                "type": entity_data.get("entity_type") or "unknown",
                "size": 1,
            }
        )

    # Build edges from S7 relations; skip any relation missing required fields
    # (relation_id / subject / object) rather than emitting a malformed edge.
    edges: list[dict[str, Any]] = []
    for rel in relations:
        rel_id = str(rel.get("relation_id") or "")
        src = str(rel.get("subject_entity_id") or "")
        tgt = str(rel.get("object_entity_id") or "")
        if not rel_id or not src or not tgt:
            continue
        edges.append(
            {
                "id": rel_id,
                "source": src,
                "target": tgt,
                "label": rel.get("canonical_type") or "",
                "weight": float(rel.get("confidence") or 0.5),
            }
        )

    return {"entity_id": entity_id, "nodes": nodes, "edges": edges}


@router.get("/entities/{entity_id}/graph")
async def get_entity_graph(entity_id: str, request: Request) -> Any:
    """Proxy GET /api/v1/entities/{entity_id}/graph → S7 Knowledge Graph.

    Requires authentication. Forwards query parameters (depth, etc.) for
    entity relationship graph traversal.

    WHY transform instead of raw proxy: S7 returns GraphNeighborhoodResponse
    {center, relations, entities} but the frontend Cytoscape.js renderer
    expects EntityGraph {entity_id, nodes, edges}. _transform_graph_response()
    bridges the mismatch at the BFF layer so neither S7 nor the frontend needs
    to change.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.knowledge_graph.get(
        f"/api/v1/entities/{entity_id}/graph",
        params=dict(request.query_params),
        headers=headers,
    )
    # Pass non-2xx responses through unchanged (404 = entity not found, etc.)
    if resp.status_code >= 400:
        return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")
    import json as _json

    raw: dict[str, Any] = resp.json()
    transformed = _transform_graph_response(raw)
    return Response(
        content=_json.dumps(transformed).encode(),
        status_code=resp.status_code,
        media_type="application/json",
    )


@router.get("/entities/{entity_id}/contradictions")
async def get_entity_contradictions(entity_id: str, request: Request) -> Any:
    """Proxy GET /api/v1/entities/{entity_id}/contradictions → S7 Knowledge Graph.

    Requires authentication. Returns detected contradictions for the entity.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.knowledge_graph.get(
        f"/api/v1/entities/{entity_id}/contradictions",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# ── News (PRD-0028 Wave S9-1) ────────────────────────────────────────────────


@router.get("/news/top")
async def get_news_top(request: Request) -> Any:
    """Proxy GET /api/v1/news/top → S6 NLP Pipeline (PRD-0026 §6.7 Flow C).

    No authentication required — public endpoint.  Issues a system JWT so S6's
    InternalJWTMiddleware accepts the request.
    Forwards query parameters (hours, limit, offset, min_display_score, routing_tier) unchanged.
    """
    clients = _clients(request)
    resp = await clients.nlp_pipeline.get(
        "/api/v1/news/top",
        params=dict(request.query_params),
        headers=_system_headers(request),
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/news/entity/{entity_id}")
async def get_news_entity(entity_id: str, request: Request) -> Any:
    """Proxy GET /api/v1/entities/{entity_id}/articles → S6 NLP Pipeline (PRD-0026 §6.7 Flow D).

    Requires authentication. entity_id is a path parameter (not a query param).
    Forwards query parameters (start_date, end_date, order_by, limit, offset) unchanged.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    # entity_id is part of the path, not a query param (BP-026 guard).
    resp = await clients.nlp_pipeline.get(
        f"/api/v1/entities/{entity_id}/articles",
        params=dict(request.query_params),
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# ── Briefings (PRD-0028 Wave S9-1) ───────────────────────────────────────────


@router.get("/briefings/morning")
async def get_morning_briefing(request: Request) -> Any:
    """Proxy GET /api/v1/briefings/morning → S8 RAG/Chat service.

    Requires authentication. Returns the AI-generated morning market briefing.

    Note: S8 does not yet expose this GET endpoint — the proxy route will return
    404/503 from S8 until the briefing endpoints are implemented in S8.
    The proxy is correct and will work automatically once S8 adds the route.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.rag_chat.get(
        "/api/v1/briefings/morning",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/briefings/instrument/{entity_id}")
async def get_instrument_briefing(entity_id: str, request: Request) -> Any:
    """Proxy GET /api/v1/briefings/instrument/{entity_id} → S8 RAG/Chat service.

    Requires authentication. Returns the AI-generated briefing for a specific
    instrument/entity.

    Note: S8 does not yet expose this GET endpoint — the proxy route will return
    404/503 from S8 until the briefing endpoints are implemented in S8.
    The proxy is correct and will work automatically once S8 adds the route.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.rag_chat.get(
        f"/api/v1/briefings/instrument/{entity_id}",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# ── Portfolio + Holdings + Transactions (PRD-0028 Wave S9-2) ─────────────────


@router.get("/portfolios")
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


@router.get("/holdings/{portfolio_id}")
async def get_holdings(portfolio_id: str, request: Request) -> Any:
    """Proxy GET /api/v1/holdings/{portfolio_id} → S1 Portfolio service.

    Requires authentication. Returns all holdings for the specified portfolio.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _portfolio_headers(request)
    clients = _clients(request)
    resp = await clients.portfolio.get(
        f"/api/v1/holdings/{portfolio_id}",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


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


@router.get("/watchlists")
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


# ── Search (PRD-0028 Wave S9-3, OQ-01) ──────────────────────────────────────


@router.get("/search/instruments")
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


# ── Market Heatmap (PRD-0028 Wave S9-3, OQ-02) ──────────────────────────────


@router.get("/market/heatmap")
async def market_heatmap(request: Request) -> dict[str, Any]:
    """Sector heatmap — aggregated daily_return per GICS sector.

    Composed endpoint: makes 11 parallel S3 screener calls (one per sector),
    computes average daily_return, returns HeatCell-ready data.
    Uses asyncio.gather with return_exceptions=True (BP-114).
    Auth required. Forwards X-Internal-JWT to all downstream screener calls.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    try:
        return await get_market_heatmap(_clients(request), make_headers=lambda: _auth_headers(request))
    except DownstreamError as e:
        raise HTTPException(status_code=e.status, detail=e.detail) from e


# ── Top Movers (PRD-0028 Wave S9-3, OQ-03) ──────────────────────────────────


@router.get("/market/top-movers")
async def top_movers(
    request: Request,
    mover_type: str = Query("gainers", alias="type", description="gainers or losers"),
    limit: int = Query(10, ge=1, le=20),
) -> dict[str, Any]:
    """Top gainers or losers — screener sorted by daily_return.

    Composed endpoint: single S3 screener call with sort_by=daily_return.
    Auth required. Forwards X-Internal-JWT to the downstream screener call.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    if mover_type not in ("gainers", "losers"):
        raise HTTPException(status_code=400, detail="type must be 'gainers' or 'losers'")
    try:
        return await get_top_movers(
            _clients(request),
            mover_type=mover_type,
            limit=limit,
            headers=_auth_headers(request),
        )
    except DownstreamError as e:
        raise HTTPException(status_code=e.status, detail=e.detail) from e


# ── AI Signals (PRD-0028 Wave S9-3 → real proxy to S6) ────────────────────


@router.get("/signals/ai")
async def ai_signals(request: Request) -> Any:
    """Proxy GET /api/v1/signals → S6 NLP Pipeline.

    Returns price-impact signals. Forwards query parameters (e.g., min_impact_score).
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
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")
