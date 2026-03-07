"""Gateway API routes — composition endpoints for the frontend."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from api_gateway.clients import (
    DownstreamError,
    get_company_overview,
    get_map_layers,
    get_relevant_news,
)

router = APIRouter(prefix="/v1")


def _clients(request: Request):
    """Shortcut to get ServiceClients from app state."""
    return request.app.state.clients


# ── Company ───────────────────────────────────────────────


@router.get("/companies/{company_id}/overview")
async def company_overview(company_id: str, request: Request) -> dict[str, Any]:
    """Composed endpoint: fundamentals + OHLCV chart + latest news."""
    try:
        return await get_company_overview(_clients(request), company_id)
    except DownstreamError as e:
        raise HTTPException(status_code=e.status, detail=e.detail)


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
        raise HTTPException(status_code=e.status, detail=e.detail)


# ── Map ───────────────────────────────────────────────────


@router.get("/map/layers")
async def map_layers(request: Request) -> dict[str, Any]:
    """Available map overlay layers."""
    return await get_map_layers(_clients(request))


# ── Chat ──────────────────────────────────────────────────


@router.post("/chat/stream")
async def chat_stream(request: Request) -> Any:
    """Proxy chat request to RAG/Chat service as SSE stream.

    Reads the JSON body and forwards it to S8, streaming back the
    response as Server-Sent Events.
    """
    from sse_starlette.sse import EventSourceResponse

    body = await request.json()
    clients = _clients(request)

    async def event_generator():
        async with clients.rag_chat.stream(
            "POST", "/v1/chat", json=body
        ) as resp:
            async for line in resp.aiter_lines():
                if line.strip():
                    yield {"data": line}

    return EventSourceResponse(event_generator())
