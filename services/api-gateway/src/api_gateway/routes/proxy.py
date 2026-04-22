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
from api_gateway.jwt_utils import issue_public_jwt

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

router = APIRouter(prefix="/v1")


def _clients(request: Request) -> ServiceClients:
    """Shortcut to get ServiceClients from app state."""
    return cast("ServiceClients", request.app.state.clients)


def _auth_headers(request: Request) -> dict[str, str]:
    """Extract auth headers for downstream services.

    Forwards only ``X-Internal-JWT`` set by ``InternalJWTIssuerMiddleware``.
    Backends extract tenant_id/user_id from the JWT payload via their own
    InternalJWTMiddleware (PRD-0025). Legacy X-Tenant-Id / X-User-Id headers
    are no longer forwarded (F-MAJOR-013 remediation).
    """
    headers: dict[str, str] = {}
    # Forward RS256 internal JWT issued by InternalJWTIssuerMiddleware
    # F-014: Starlette headers are case-insensitive; single lookup suffices
    internal_jwt = request.headers.get("X-Internal-JWT")
    if internal_jwt:
        headers["X-Internal-JWT"] = internal_jwt
    return headers


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
    """Composed endpoint: fundamentals + OHLCV chart + latest news.

    Forwards ``X-Internal-JWT`` to all downstream calls so S3 and S5 can
    authenticate the request via InternalJWTMiddleware.
    """
    try:
        return await get_company_overview(_clients(request), company_id, headers=_auth_headers(request))
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

    Requires authentication. Forwards query parameters (period, from, to, etc.)
    to S3 for OHLCV bar data retrieval.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.market_data.get(
        f"/api/v1/ohlcv/{instrument_id}",
        params=dict(request.query_params),
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/quotes/{instrument_id}")
async def get_quote(instrument_id: str, request: Request) -> Any:
    """Proxy GET /api/v1/quotes/{instrument_id} → S3 Market Data.

    Requires authentication. Returns the latest quote snapshot for the instrument.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.market_data.get(
        f"/api/v1/quotes/{instrument_id}",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.post("/quotes/batch")
async def get_quotes_batch(request: Request) -> Any:
    """Proxy POST /api/v1/quotes/batch → S3 Market Data.

    Requires authentication. Forwards the request body containing a list of
    instrument_ids to S3 for batch quote retrieval.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    body = await request.body()
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.market_data.post(
        "/api/v1/quotes/batch",
        content=body,
        headers={"Content-Type": "application/json", **headers},
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
        # F-010: filter out user-supplied 'type' to enforce economic-only filter
        params={"type": "economic", **{k: v for k, v in dict(request.query_params).items() if k != "type"}},
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


@router.get("/entities/{entity_id}/graph")
async def get_entity_graph(entity_id: str, request: Request) -> Any:
    """Proxy GET /api/v1/entities/{entity_id}/graph → S7 Knowledge Graph.

    Requires authentication. Forwards query parameters (depth, etc.) for
    entity relationship graph traversal.
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
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


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
    """Proxy GET /v1/articles/relevant → S5 Content Store.

    No authentication required — public endpoint.  Issues a system JWT so S5's
    InternalJWTMiddleware accepts the request.
    Forwards query parameters (hours, limit, offset) unchanged.

    TODO(PRD-0026): S5 endpoint path will change once PRD-0026 news intelligence
    APIs are implemented. Update the downstream path when S5 exposes /v1/news/top.
    """
    clients = _clients(request)
    resp = await clients.content_store.get(
        "/v1/articles/relevant",
        params=dict(request.query_params),
        headers=_system_headers(request),
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/news/entity/{entity_id}")
async def get_news_entity(entity_id: str, request: Request) -> Any:
    """Proxy GET /v1/articles → S5 Content Store (filtered by entity_id).

    Requires authentication. Forwards query parameters plus entity_id to S5
    for entity-scoped article retrieval.

    TODO(PRD-0026): S5 endpoint path will change once PRD-0026 news intelligence
    APIs are implemented. Update the downstream path when S5 exposes
    /v1/entities/{entity_id}/articles.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    params = dict(request.query_params)
    params["entity_id"] = entity_id
    resp = await clients.content_store.get(
        "/v1/articles",
        params=params,
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

    Requires authentication. Forwards query parameters (portfolio_id, limit, offset)
    to S1 for transaction listing.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _portfolio_headers(request)
    clients = _clients(request)
    resp = await clients.portfolio.get(
        "/api/v1/transactions",
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
        return await get_market_heatmap(_clients(request), headers=_auth_headers(request))
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
