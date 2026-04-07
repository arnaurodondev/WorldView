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
    """Extract tenant/user IDs from JWT payload and return as S8 headers."""
    user: dict[str, Any] | None = getattr(request.state, "user", None)
    if not user:
        return {}
    headers: dict[str, str] = {}
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
