"""Chat, briefing, and thread routes for the API Gateway.

Handles /v1/chat/*, /v1/threads/*, /v1/briefings/* — proxies to S8 RAG-Chat service.
Split from proxy.py (PLAN-0089 B-3).
"""

from __future__ import annotations

import uuid as _uuid
from typing import TYPE_CHECKING, Any

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from api_gateway.routes.helpers import _auth_headers, _clients

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

router = APIRouter(prefix="/v1")


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


@router.post("/chat/entity-context", summary="Entity-context chat (PLAN-0074 Wave G)")
async def chat_entity_context(request: Request) -> Any:
    """Proxy POST /v1/chat/entity-context → S8 RAG-Chat (synchronous).

    Loads entity intelligence from S7 inside S8, prepends a grounding system
    prompt, and returns the full answer once the LLM completes.

    Pre-proxy validations at S9 (before the S8 round-trip):
      - entity_id must be a valid UUID — 422 if not.
      - question must be non-empty — 400 if blank.

    Rate limit: 30 req/min/user via the shared RateLimitMiddleware (standard
    authenticated bucket).  No additional per-route rate limit is applied here
    because entity-context calls are more expensive (invoke LLM) and the
    standard 300/min global bucket is already sufficient to prevent abuse.

    No caching: each answer is dynamic (entity intelligence + user question).

    WHY forward raw body to S8: S8 applies its own Pydantic validation
    (including bleach HTML-strip on question).  Double-parsing at S9 would
    require importing S8 schemas (violates R14) and would be redundant.  We
    do a lightweight check on entity_id and question here, then pass bytes.

    Error pass-through: 429 / 400 / 404 / 422 / 503 from S8 are forwarded
    unchanged so the frontend sees the correct error semantics.

    Requires authentication.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")

    # Read body once — httpx needs raw bytes; we also inspect for validation.
    import json as _json

    body = await request.body()

    # ── Lightweight pre-proxy validation ─────────────────────────────────────
    # WHY parse here: we need to inspect entity_id (UUID validation) and
    # question (non-empty check) before sending a network request to S8.
    # A bad entity_id would cause S8 to return 422 after a round-trip; we
    # catch it early to give a faster, cheaper response.
    try:
        payload = _json.loads(body)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="Invalid JSON body")  # noqa: B904

    # Validate entity_id is a UUID.
    entity_id_raw = payload.get("entity_id")
    if entity_id_raw is None:
        raise HTTPException(status_code=422, detail="entity_id is required")
    try:
        _uuid.UUID(str(entity_id_raw))
    except (ValueError, AttributeError):
        raise HTTPException(status_code=422, detail="entity_id must be a valid UUID")  # noqa: B904

    # Validate question is non-empty.
    question_raw = payload.get("question", "")
    if not str(question_raw).strip():
        raise HTTPException(status_code=400, detail="question cannot be empty")

    # ── Proxy to S8 ─────────────────────────────────────────────────────────
    headers = _auth_headers(request)
    clients = _clients(request)

    resp = await clients.rag_chat.post(
        "/api/v1/chat/entity-context",
        content=body,
        headers={"Content-Type": "application/json", **headers},
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.post("/chat/entity-context/stream", summary="SSE entity-context chat (PLAN-0074 Wave G)")
async def chat_entity_context_stream(request: Request) -> Any:
    """Proxy POST /v1/chat/entity-context/stream → S8 RAG-Chat (SSE streaming).

    Same pre-proxy validation as /chat/entity-context (entity_id UUID check,
    non-empty question), then streams S8 SSE chunks back without buffering.

    WHY separate streaming endpoint: SSE requires chunked-transfer encoding;
    the synchronous endpoint buffers the full response.  The frontend chooses
    between the two based on whether it wants progressive rendering.

    Requires authentication.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")

    import json as _json

    body = await request.body()

    # Lightweight pre-proxy validation (mirrors non-streaming endpoint).
    try:
        payload = _json.loads(body)
    except (ValueError, TypeError):
        raise HTTPException(status_code=422, detail="Invalid JSON body")  # noqa: B904

    entity_id_raw = payload.get("entity_id")
    if entity_id_raw is None:
        raise HTTPException(status_code=422, detail="entity_id is required")
    try:
        _uuid.UUID(str(entity_id_raw))
    except (ValueError, AttributeError):
        raise HTTPException(status_code=422, detail="entity_id must be a valid UUID")  # noqa: B904

    question_raw = payload.get("question", "")
    if not str(question_raw).strip():
        raise HTTPException(status_code=400, detail="question cannot be empty")

    headers = _auth_headers(request)
    clients = _clients(request)

    async def _stream_body() -> AsyncIterator[bytes]:
        async with clients.rag_chat.stream(
            "POST",
            "/api/v1/chat/entity-context/stream",
            content=body,
            headers={"Content-Type": "application/json", **headers},
        ) as resp:
            async for chunk in resp.aiter_bytes():
                yield chunk

    return StreamingResponse(_stream_body(), media_type="text/event-stream")


# ── Proposal confirmation (PLAN-0082 Wave B) ─────────────────────────────────


@router.post("/chat/proposals/{proposal_id}/confirm")
async def confirm_proposal(proposal_id: str, request: Request) -> Any:
    """Proxy POST /v1/chat/proposals/{id}/confirm → S8 (SSE streaming).

    Requires authentication. The frontend calls this after the user confirms
    a write-action in the ActionConfirmModal.  Forwards the JSON body and
    X-Internal-JWT to S8 which executes the action (e.g. creates an alert
    via S10) and streams ``action_executed`` or ``action_rejected`` SSE events.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    body = await request.body()
    headers = _auth_headers(request)
    clients = _clients(request)

    async def _stream_body() -> AsyncIterator[bytes]:
        async with clients.rag_chat.stream(
            "POST",
            f"/api/v1/chat/proposals/{proposal_id}/confirm",
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
    if getattr(request.state, "user", None) is None:
        raise HTTPException(status_code=401, detail="Authentication required")
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
    if getattr(request.state, "user", None) is None:
        raise HTTPException(status_code=401, detail="Authentication required")
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
    if getattr(request.state, "user", None) is None:
        raise HTTPException(status_code=401, detail="Authentication required")
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
    if getattr(request.state, "user", None) is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.rag_chat.delete(
        f"/api/v1/threads/{thread_id}",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.patch("/threads/{thread_id}")
async def update_thread(thread_id: str, request: Request) -> Any:
    """Proxy PATCH /v1/threads/{thread_id} → S8 PATCH /api/v1/threads/{thread_id}.

    PLAN-0051 Wave E / T-E-5-06.

    Used by the chat UI to rename a thread inline (double-click on the
    sidebar title). Body is forwarded unchanged so future patchable fields
    don't require a gateway change.
    """
    if getattr(request.state, "user", None) is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    body = await request.body()
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.rag_chat.patch(
        f"/api/v1/threads/{thread_id}",
        content=body,
        headers={"Content-Type": "application/json", **headers},
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# ── Briefings (PRD-0028 Wave S9-1) ───────────────────────────────────────────


@router.get("/briefings/morning")
async def get_morning_briefing(request: Request) -> Any:
    """Proxy GET /api/v1/briefings/morning → S8 RAG/Chat service.

    Requires authentication. Returns the AI-generated morning market briefing.
    The rag-chat client has a 120 s timeout (app.py lifespan). On timeout we
    return 503 (not 500) so the frontend can show a friendly retry message.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    try:
        resp = await clients.rag_chat.get(
            "/api/v1/briefings/morning",
            headers=headers,
        )
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise HTTPException(status_code=503, detail="Briefing generation timed out") from exc
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/briefings/instrument/{entity_id}")
async def get_instrument_briefing(entity_id: str, request: Request) -> Any:
    """Proxy GET /api/v1/briefings/instrument/{entity_id} → S8 RAG/Chat service.

    Requires authentication. Returns the AI-generated briefing for a specific
    instrument/entity. Returns 503 (not 500) on httpx.TimeoutException so the
    frontend IntelligenceTab can show a "try again" message instead of an error.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    try:
        resp = await clients.rag_chat.get(
            f"/api/v1/briefings/instrument/{entity_id}",
            headers=headers,
        )
    except (httpx.TimeoutException, httpx.NetworkError) as exc:
        raise HTTPException(status_code=503, detail="Briefing generation timed out") from exc
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/briefings/morning/history")
async def get_morning_brief_history(request: Request) -> Any:
    """Proxy GET /api/v1/briefings/morning/history → S8 RAG/Chat service (PLAN-0066 Wave B).

    Requires authentication. Returns paginated history of past morning briefs for
    the authenticated user. Passes query params (page, page_size) through to S8.

    WHY no timeout guard: history queries are fast DB reads (no LLM call).
    Network errors still propagate as 5xx FastAPI defaults.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.rag_chat.get(
        "/api/v1/briefings/morning/history",
        # WHY pass query params: page + page_size are forwarded unchanged so S8
        # applies its own Query constraints (page_size capped at 50).
        params=dict(request.query_params),
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# ── PLAN-0066 Wave C: brief diff + feedback proxies ───────────────────────────


@router.get("/briefings/morning/diff")
async def get_morning_brief_diff(request: Request) -> Any:
    """Proxy GET /api/v1/briefings/morning/diff → S8 RAG/Chat service (PLAN-0066 Wave C).

    Requires authentication. Returns a text-normalised bullet diff between the
    two most-recent morning briefs for the authenticated user.

    WHY no timeout guard: diff is a pure read (2-row DB fetch + in-memory compare).
    Network errors still propagate as 5xx FastAPI defaults.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.rag_chat.get(
        "/api/v1/briefings/morning/diff",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.post("/briefings/feedback/bullet", status_code=201)
async def submit_bullet_feedback(request: Request) -> Any:
    """Proxy POST /api/v1/briefings/feedback/bullet → S8 RAG/Chat service (PLAN-0066 Wave C).

    Requires authentication. Records a helpful/unhelpful reaction to a specific
    bullet in the authenticated user's morning brief.

    WHY forward raw body: the request body contains brief_id, section_idx,
    bullet_idx, and reaction. S8 validates these via Pydantic; forwarding the raw
    bytes avoids double-deserialisation and keeps S9 as a thin proxy.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    body = await request.body()
    resp = await clients.rag_chat.post(
        "/api/v1/briefings/feedback/bullet",
        content=body,
        headers={**headers, "Content-Type": "application/json"},
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.post("/briefings/feedback/brief", status_code=201)
async def submit_brief_feedback(request: Request) -> Any:
    """Proxy POST /api/v1/briefings/feedback/brief → S8 RAG/Chat service (PLAN-0066 Wave C).

    Requires authentication. Records a star rating (1-5) for the authenticated
    user's morning brief.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    body = await request.body()
    resp = await clients.rag_chat.post(
        "/api/v1/briefings/feedback/brief",
        content=body,
        headers={**headers, "Content-Type": "application/json"},
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# ── PLAN-0066 Wave D: chat/discuss + Wave E: create-alert placeholder ─────────


@router.post("/briefings/chat/discuss")
async def discuss_brief(request: Request) -> Any:
    """Proxy POST /api/v1/briefings/chat/discuss → S8 RAG/Chat service (PLAN-0066 Wave D).

    Requires authentication. Sends a follow-up question about the morning brief
    to the S8 chat endpoint and streams the LLM response back to the caller.

    WHY forward raw body: the request body contains brief_id and message.  S8
    validates these via Pydantic; forwarding raw bytes avoids double-deserialisation
    and keeps S9 as a thin proxy.

    WHY no timeout guard here: the chat route on S8 may stream; httpx will raise
    TimeoutException if the first chunk does not arrive within the client timeout
    configured in app.py lifespan (120 s).  FastAPI's default exception handling
    converts that to a 5xx which is acceptable for a streaming endpoint.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    body = await request.body()
    resp = await clients.rag_chat.post(
        "/api/v1/briefings/chat/discuss",
        content=body,
        headers={**headers, "Content-Type": "application/json"},
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.post("/briefings/{brief_id}/create-alert", status_code=201)
async def create_brief_alert(brief_id: str, request: Request) -> Any:
    """Proxy POST /api/v1/briefings/{brief_id}/create-alert → S8 (PLAN-0066 Wave E placeholder).

    Requires authentication. Placeholder route that will be wired to the real S8
    create-alert endpoint once Wave F ships the S8 side.  Until then, S8 returns
    404 for this path and we pass that response through unchanged.

    WHY placeholder now: the S9 route must be registered before the frontend
    ships so that the API surface is stable (no 404 at the gateway level).
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    body = await request.body()
    resp = await clients.rag_chat.post(
        f"/api/v1/briefings/{brief_id}/create-alert",
        content=body,
        headers={**headers, "Content-Type": "application/json"},
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")
