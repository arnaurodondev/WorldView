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
    get_relevant_news,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

router = APIRouter(prefix="/v1")


def _clients(request: Request) -> ServiceClients:
    """Shortcut to get ServiceClients from app state."""
    return cast("ServiceClients", request.app.state.clients)


def _auth_headers(request: Request) -> dict[str, str]:
    """Extract auth headers (internal JWT + tenant/user IDs) for downstream services.

    Forwards ``X-Internal-JWT`` set by ``InternalJWTIssuerMiddleware`` and the
    legacy ``X-Tenant-Id``/``X-User-Id`` headers derived from ``request.state.user``.
    """
    user: dict[str, Any] | None = getattr(request.state, "user", None)
    headers: dict[str, str] = {}
    # Forward RS256 internal JWT issued by InternalJWTIssuerMiddleware
    internal_jwt = request.headers.get("X-Internal-JWT") or request.headers.get("x-internal-jwt")
    if internal_jwt:
        headers["X-Internal-JWT"] = internal_jwt
    if not user:
        return headers
    if tenant_id := user.get("tenant_id"):
        headers["X-Tenant-Id"] = str(tenant_id)
    if user_id := user.get("sub") or user.get("user_id"):
        headers["X-User-Id"] = str(user_id)
    return headers


# ── Company ───────────────────────────────────────────────


@router.get("/companies/{company_id}/overview")
async def company_overview(company_id: str, request: Request) -> dict[str, Any]:
    """Composed endpoint: fundamentals + OHLCV chart + latest news."""
    try:
        return await get_company_overview(_clients(request), company_id)
    except DownstreamError as e:
        raise HTTPException(status_code=e.status, detail=e.detail) from e


# ── News ──────────────────────────────────────────────────


@router.get("/news/relevant")
async def relevant_news(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    """Most relevant news articles across all sources."""
    try:
        return await get_relevant_news(_clients(request), limit=limit)
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
    """Proxy synchronous chat request to S8 RAG/Chat service."""
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

    Forwards the request body to S8 `/api/v1/chat/stream` and streams
    back Server-Sent Events without buffering, preserving the
    `text/event-stream` content type.
    """
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

    Public endpoint (no auth headers forwarded).  S3 returns 400 for no filters,
    422 for invalid metric/sort_by.
    """
    body = await request.body()
    clients = _clients(request)
    resp = await clients.market_data.post(
        "/api/v1/fundamentals/screen",
        content=body,
        headers={"Content-Type": "application/json"},
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/fundamentals/screen/fields")
async def get_screen_fields(request: Request) -> Any:
    """Proxy GET /api/v1/fundamentals/screen/fields → S3 Market Data.

    Public endpoint. Returns screener field metadata (Valkey-backed, 6h refresh).
    """
    clients = _clients(request)
    resp = await clients.market_data.get("/api/v1/fundamentals/screen/fields")
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/fundamentals/timeseries")
async def get_fundamentals_timeseries(request: Request) -> Any:
    """Proxy GET /api/v1/fundamentals/timeseries → S3 Market Data.

    Forwards query parameters unchanged.
    """
    clients = _clients(request)
    resp = await clients.market_data.get(
        "/api/v1/fundamentals/timeseries",
        params=dict(request.query_params),
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# ── Similar entities (PRD-0017 Wave C-1) ─────────────────────────────────────


@router.post("/entities/similar")
async def find_similar_entities(request: Request) -> Any:
    """Proxy POST /api/v1/entities/similar → S7 Knowledge Graph.

    Public endpoint. S7 returns 404 (entity not found), 422 (no embedding),
    503 (pgvector unavailable).
    """
    body = await request.body()
    clients = _clients(request)
    resp = await clients.knowledge_graph.post(
        "/api/v1/entities/similar",
        content=body,
        headers={"Content-Type": "application/json"},
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
