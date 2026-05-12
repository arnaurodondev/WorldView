"""Gateway API routes — composition endpoints for the frontend."""

from __future__ import annotations

import asyncio
import json
import uuid as _uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from api_gateway.clients import (
    DownstreamError,
    ServiceClients,
    get_map_layers,
    get_market_heatmap,
    get_relevant_news,
    get_top_movers,
    get_watchlist_insights,
)
from api_gateway.jwt_utils import issue_public_jwt, issue_user_jwt
from api_gateway.schemas import (
    AlertResponse,
    DashboardSnapshotResponse,
    EarningsCalendarResponse,
    FundamentalsResponse,
    InstrumentSearchResult,
    NewsTopResponse,
    OHLCVResponse,
    PortfolioBundleResponse,
    PortfolioResponse,
    PredictionMarket,
    PredictionMarketsListResponse,
    QuoteResponse,
    WatchlistResponse,
)
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

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
        # F-Q1-02: forward the role claim from the OIDC/dev-login payload
        # into the internal JWT. Without this, every admin endpoint on every
        # backend service returned 403 because the role defaulted to "user".
        role = user.get("role") or "user"
        token = issue_user_jwt(
            user_id=user.get("user_id", ""),
            tenant_id=user.get("tenant_id", ""),
            oidc_sub=user.get("sub", ""),
            private_key=private_key,
            kid=kid,
            role=role,
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


# ── Email preferences ─────────────────────────────────────────────────────────


@router.get("/email/preferences")
async def get_email_preferences(request: Request) -> Any:
    """Proxy GET /api/v1/email/preferences → S10 Alert service.

    Passes X-Tenant-Id and X-User-Id headers derived from the JWT payload
    so S10 can enforce per-user isolation.
    """
    if getattr(request.state, "user", None) is None:
        raise HTTPException(status_code=401, detail="Authentication required")
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
    if getattr(request.state, "user", None) is None:
        raise HTTPException(status_code=401, detail="Authentication required")
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


# ── Entity detail (PRD-0073 Wave D-1) ────────────────────────────────────────


@router.get("/entities/{entity_id}")
async def get_entity_detail(entity_id: UUID, request: Request) -> Any:
    """Proxy GET /api/v1/entities/{entity_id} → S7 Knowledge Graph.

    Returns enrichment fields (description, metadata, data_completeness, enriched_at)
    populated by Worker 13J (PRD-0073).  Returns 404 when the entity does not exist
    or enrichment has not yet run.

    Requires authentication — enrichment data is behind the user JWT boundary.

    F-S04 (PLAN-0073 cleanup): ``entity_id`` is typed as ``UUID`` so FastAPI validates
    the path param at the gateway boundary before we issue any downstream request.
    This blocks path-traversal probes (e.g. ``../../admin``) and arbitrary string
    payloads from reaching S7 — defence-in-depth even though S7 also validates.

    WHY registered before /entities/{entity_id}/graph and /entities/{entity_id}/contradictions:
    The bare /{entity_id} path will NOT shadow the sub-resource paths because those have
    an extra path segment.  FastAPI matches the most specific (longest) path first when
    both are registered; `/entities/UUID/graph` always wins over `/entities/UUID`.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.knowledge_graph.get(
        f"/api/v1/entities/{entity_id}",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


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


# ── Alert endpoints (PRD-0025 T-D-1-10) ──────────────────────────────────────


@router.get("/alerts/pending", response_model=list[AlertResponse], response_model_exclude_none=True)
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


@router.get("/alerts/stream/ws-url")
async def get_alerts_ws_url(request: Request) -> dict[str, str | int]:
    """Issue a short-lived WS token and return the full WebSocket URL.

    Replaces the client-side pattern of calling /v1/auth/ws-token then
    constructing the URL manually.  Returns ws_url ready for new WebSocket().
    Auth: requires Bearer access token.  Token TTL: 30 s (hardcoded in jwt_utils._WS_TTL).
    """
    user = getattr(request.state, "user", None)
    if not user:
        raise HTTPException(status_code=401, detail="authentication_required")

    private_key = getattr(request.app.state, "rsa_private_key", None)
    kid = getattr(request.app.state, "rsa_kid", None)
    if private_key is None or kid is None:
        raise HTTPException(status_code=503, detail="jwt_signing_unavailable")

    user_id = user.get("user_id") or user.get("sub")
    tenant_id = user.get("tenant_id")
    if not user_id or not tenant_id:
        raise HTTPException(status_code=401, detail="incomplete_auth_claims")

    from api_gateway.jwt_utils import issue_ws_jwt

    token = issue_ws_jwt(user_id=user_id, tenant_id=tenant_id, private_key=private_key, kid=kid)
    settings = request.app.state.settings
    ws_url = f"{settings.alert_ws_url}/api/v1/alerts/stream?token={token}"
    return {"ws_url": ws_url, "token": token, "expires_in": 30}


# ── Alert ack/snooze/history proxies (PLAN-0051 T-D-4-02) ────────────────────
#
# Cache-Control: no-store on every response — these are user-specific, mutate
# state (ack/snooze) or expose tenant-scoped lists (history). A shared CDN
# must never cache them.


@router.patch("/alerts/{alert_id}/acknowledge", status_code=200)
async def acknowledge_alert_entity(alert_id: str, request: Request) -> Response:
    """Proxy PATCH /api/v1/alerts/{alert_id}/acknowledge → S10.

    Forwards the (optional) JSON body and X-Internal-JWT. ``Cache-Control:
    no-store`` prevents any intermediary from caching the mutation response.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    body = await request.body()
    headers = {**_auth_headers(request)}
    if body:
        headers["Content-Type"] = "application/json"
    clients = _clients(request)
    resp = await clients.alert.patch(
        f"/api/v1/alerts/{alert_id}/acknowledge",
        content=body,
        headers=headers,
    )
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )


@router.patch("/alerts/{alert_id}/snooze", status_code=200)
async def snooze_alert_entity(alert_id: str, request: Request) -> Response:
    """Proxy PATCH /api/v1/alerts/{alert_id}/snooze → S10."""
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    body = await request.body()
    headers = {"Content-Type": "application/json", **_auth_headers(request)}
    clients = _clients(request)
    resp = await clients.alert.patch(
        f"/api/v1/alerts/{alert_id}/snooze",
        content=body,
        headers=headers,
    )
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/alerts/history")
async def list_alert_history(request: Request) -> Response:
    """Proxy GET /api/v1/alerts/history → S10 with query params forwarded verbatim."""
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.alert.get(
        "/api/v1/alerts/history",
        params=dict(request.query_params),
        headers=headers,
    )
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )


# ── Alert creation proxy (PLAN-0082 Wave B) ──────────────────────────────────


@router.post("/alerts", status_code=201)
async def create_alert(request: Request) -> Response:
    """Proxy POST /api/v1/alerts → S10 Alert service.

    Creates a user-initiated alert rule.  Requires authentication.  Forwards
    the JSON body and X-Internal-JWT so S10's InternalJWTMiddleware can extract
    the user_id and tenant_id from the JWT (PRD-0025 §T-D-1-10).

    Cache-Control: no-store — this is a write mutation, must never be cached.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    body = await request.body()
    headers = {"Content-Type": "application/json", **_auth_headers(request)}
    clients = _clients(request)
    resp = await clients.alert.post(
        "/api/v1/alerts",
        content=body,
        headers=headers,
    )
    return Response(
        content=resp.content,
        status_code=resp.status_code,
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )


# ── Prediction Markets (PRD-0019 Wave C-1) ────────────────────────────────────


@router.get(
    "/signals/prediction-markets",
    response_model=PredictionMarketsListResponse,
    response_model_exclude_none=True,
)
async def list_prediction_markets(
    request: Request,
    # PLAN-0049 T-C-3-03 — declared explicitly (rather than left as a generic
    # ``request.query_params`` pass-through) so the OpenAPI spec advertises
    # it to frontend type-generators.  The ``description`` lists the
    # non-binding suggested values; backend does case-insensitive equality
    # so any future Polymarket tag works without a code change.
    category: str | None = Query(
        default=None,
        max_length=50,
        description=(
            "Optional category filter. Suggested values: macro, politics, "
            "sports, crypto, general (non-binding — backend does case-"
            "insensitive equality, never validates the enum)."
        ),
    ),
) -> Any:
    """Proxy GET /api/v1/prediction-markets → S3 Market Data.

    Requires authentication. Forwards query params (status, limit, offset,
    category) and auth headers derived from the JWT payload.

    WHY response_model=PredictionMarketsListResponse: S3 returns
    {items: [...], total, limit, offset}. PredictionMarketsListResponse
    mirrors that shape exactly (extra=allow passes any new fields through).
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    # F-QAC-09 fix: forward all query params verbatim. The explicit
    # ``category`` parameter declaration above exists purely so OpenAPI
    # documents it for type-generators; FastAPI parses ``category`` from
    # the same query string that backs ``request.query_params``, so the
    # values cannot disagree.
    forwarded: dict[str, Any] = dict(request.query_params)
    resp = await clients.market_data.get(
        "/api/v1/prediction-markets",
        params=forwarded,
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/signals/prediction-markets/categories")
async def get_prediction_market_categories(request: Request) -> Any:
    """Proxy GET /api/v1/prediction-markets/categories → S3 Market Data.

    PLAN-0053 T-C-3-05. Registered BEFORE the ``/{market_id}`` route so the
    literal "categories" path matches first (FastAPI evaluates routes in
    registration order; if /{market_id} were declared first it would shadow
    this and treat "categories" as a market_id).

    Returns ``[{category, count}, ...]`` and a top-level ``total`` for all
    currently-open markets.  Used by PredictionMarketsWidget to render
    filter pill counts and the empty-state explainer.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.market_data.get(
        "/api/v1/prediction-markets/categories",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get(
    "/signals/prediction-markets/{market_id}",
    response_model=PredictionMarket,
    response_model_exclude_none=True,
)
async def get_prediction_market(market_id: str, request: Request) -> Any:
    """Proxy GET /api/v1/prediction-markets/{id} → S3 Market Data.

    Requires authentication. S3 returns 404 if the market_id is unknown.

    WHY response_model=PredictionMarket: S3 PredictionMarketDetailResponse
    is a superset of PredictionMarketSummaryResponse (adds description +
    created_at). PredictionMarket uses extra=allow so those extra fields
    pass through without a validation error.
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


def _portfolio_headers(request: Request) -> dict[str, str]:
    """Auth headers for S1 Portfolio service.

    S1 now reads tenant_id/user_id from the JWT (InternalJWTMiddleware).
    Only X-Internal-JWT is forwarded (F-MAJOR-013 remediation).
    """
    return _auth_headers(request)


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
                # WHY ticker: PeerComparisonPanel needs ticker to look up S3
                # fundamentals (entity_id ≠ instrument_id; resolved by ticker).
                "ticker": center.get("ticker") or "",
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
                "ticker": entity_data.get("ticker") or "",
            }
        )

    # Build edges from S7 relations; skip any relation missing required fields
    # (relation_id / subject / object) rather than emitting a malformed edge.
    # WHY .lower(): canonical_type is stored lowercase in the DB for relations
    # created via the NLP pipeline but some seeded relations used uppercase
    # (e.g., "COMPETES_WITH"). Normalising to lowercase here means frontend
    # code can always filter with a single lowercase comparison.
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
                "label": (rel.get("canonical_type") or "").lower(),
                "weight": float(rel.get("confidence") or 0.5),
                # WHY: S7 returns these from relation_summaries (Worker 13C) and
                # relation_evidence_raw respectively. They are forwarded here so
                # the frontend EntitySidebar can render LLM summaries and evidence
                # snippets in the Top Relations panel without a second API call.
                "relation_summary": rel.get("relation_summary"),  # str | None
                "evidence_snippets": rel.get("evidence_snippets") or [],  # list[str]
            }
        )

    return {"entity_id": entity_id, "nodes": nodes, "edges": edges}


@router.get("/entities/{entity_id}/graph")
async def get_entity_graph(
    entity_id: UUID,  # WHY UUID not str: enforces 422 on malformed values before any downstream call
    request: Request,
    limit: int = Query(default=40, ge=1, le=200),
    depth: int = Query(default=1, ge=1, le=3),
    confidence_breakdown: bool = Query(default=False),
    focus_node: str | None = Query(default=None),
) -> Any:
    """Proxy GET /api/v1/entities/{entity_id}/graph → S7 Knowledge Graph.

    Requires authentication. Forwards query parameters (min_confidence, etc.)
    for entity relationship graph traversal.

    WHY explicit limit param (was pass-through):
    S7's GetEntityGraphUseCase does N+1 DB round-trips — one entity lookup per
    unique entity referenced in the returned relations. With S7's default of
    limit=50 relations and a dense entity graph, this means up to 50 sequential
    entity fetches. By capping at 50 here and defaulting to 40, we bound the
    worst-case DB latency.

    The frontend now sends explicit limits (15 for sidebar depth=1, 40 for
    Intelligence tab depth=2) so the default of 40 is just a safety fallback.

    WHY le=200 (PLAN-0088 P0-8, 2026-05-10 — was le=50): the previous cap of 50
    silently truncated demo entities like AAPL whose entity neighborhood routinely
    exceeds 50 high-confidence relations, and the FE depth slider was unable to
    request more than that no matter what value the analyst dragged it to. Lifting
    the gateway cap to 200 (S7's hard upper bound) lets the slider's "show more"
    extreme actually deliver more edges. Each unit increment in the FE slider now
    bumps `limit` linearly so the slider has visible effect at every step.

    WHY forward depth (ISSUE-5 fix, 2026-05-10 — was silently stripped):
    S7 supports depth=1/2/3 via AGE Cypher multi-hop graph traversal.
    depth=1 uses the standard SQL neighbourhood query (default, fast).
    depth=2/3 require KNOWLEDGE_GRAPH_CYPHER_ENABLED=true in the KG service
    and use AGE Cypher to traverse 2- or 3-hop paths. The previous comment
    claiming "S7 has no depth param" was incorrect — depth is a first-class
    Query param at S7 GET /api/v1/entities/{id}/graph (ge=1, le=3).

    WHY transform instead of raw proxy: S7 returns GraphNeighborhoodResponse
    {center, relations, entities} but the frontend Cytoscape.js renderer
    expects EntityGraph {entity_id, nodes, edges}. _transform_graph_response()
    bridges the mismatch at the BFF layer so neither S7 nor the frontend needs
    to change.

    PLAN-0074 Wave G: ``confidence_breakdown`` and ``focus_node`` are now
    forwarded to S7 (Wave D additions — previously silently ignored).
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)

    # Build params: forward known S7 params explicitly so the intent of each
    # forwarded param is clear and log noise from unknown params is avoided.
    raw_params = dict(request.query_params)
    s7_params: dict[str, str] = {"limit": str(limit)}
    if "min_confidence" in raw_params:
        s7_params["min_confidence"] = raw_params["min_confidence"]
    if "semantic_mode" in raw_params:
        s7_params["semantic_mode"] = raw_params["semantic_mode"]
    # ISSUE-5 (2026-05-10): forward depth to S7 which supports AGE Cypher multi-hop
    # traversal. depth=1 is S7's default (SQL query) so only send when >1 to avoid
    # a redundant param on the common case. depth>1 requires KNOWLEDGE_GRAPH_CYPHER_ENABLED.
    if depth > 1:
        s7_params["depth"] = str(depth)
    # PLAN-0074 Wave G: forward confidence_breakdown and focus_node (Wave D additions).
    if confidence_breakdown:
        s7_params["confidence_breakdown"] = "true"
    if focus_node is not None:
        s7_params["focus_node"] = focus_node

    resp = await clients.knowledge_graph.get(
        f"/api/v1/entities/{entity_id}/graph",
        params=s7_params,
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


@router.post("/search/relations")
async def search_relations(request: Request) -> Any:
    """Proxy POST /api/v1/search/relations → S7 Knowledge Graph.

    ANN search over relation summaries using a query embedding.
    Returns relations ordered by cosine similarity (most similar first).
    Auth required. Forwards X-Internal-JWT to S7.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    body = await request.body()
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.knowledge_graph.post(
        "/api/v1/search/relations",
        content=body,
        headers={"Content-Type": "application/json", **headers},
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.post("/claims/search")
async def search_claims(request: Request) -> Any:
    """Proxy POST /api/v1/claims/search → S7 Knowledge Graph.

    Search analyst claims for a set of entities with optional filters.
    Returns claims ordered by extraction_confidence DESC.
    Auth required. Forwards X-Internal-JWT to S7.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    body = await request.body()
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.knowledge_graph.post(
        "/api/v1/claims/search",
        content=body,
        headers={"Content-Type": "application/json", **headers},
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# ── Entity Intelligence, Narratives, Paths (PLAN-0074 Wave G) ────────────────
#
# All 5 new routes proxy to S7 Knowledge Graph or S8 RAG-Chat.
# Cache keys follow the pattern: <resource>:<tenant_id>:<entity_id>[:<params_hash>]
# BP-200: rate limiting uses set_nx(key, val, ex=N) — NOT set(..., nx=True).
# BP-235: httpx clients are configured with explicit Timeout(N) in app.py lifespan.


@router.get(
    "/entities/{entity_id}/intelligence",
    summary="Entity intelligence aggregate (PLAN-0074 Wave G)",
)
async def get_entity_intelligence(
    entity_id: UUID,
    request: Request,
    confidence_breakdown: bool = Query(default=False),
    focus_node: str | None = Query(default=None),
) -> Any:
    """Proxy GET /api/v1/entities/{entity_id}/intelligence → S7 Knowledge Graph.

    Returns the full entity intelligence aggregate: health score, current
    narrative, confidence breakdown, key metrics, and data completeness.

    Caching strategy:
      - Cache key: ``intel:<tenant_id>:<entity_id>`` (60 s TTL).
      - On hit: return cached JSON directly, skipping the S7 round-trip.
      - On miss: proxy to S7, cache the 200 response, return to caller.
      - Non-2xx responses are never cached (transient errors should not be
        cached; 404 means entity missing — may change soon).
      - Fail-open: Valkey errors are silently swallowed; the request
        proceeds to S7 as if the cache were empty.

    WHY cache at 60 s: intelligence aggregates are computed nightly by the
    KG scheduler; they don't change within a session.  60 s is a safe window
    that avoids thundering-herd on the Intelligence Tab's initial load while
    still refreshing quickly enough for dev/debug cycles.

    Requires authentication.  Forward ``confidence_breakdown`` and
    ``focus_node`` query params to S7 (Wave D additions).
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")

    user = request.state.user
    tenant_id: str = str(user.get("tenant_id", ""))
    cache_key = f"intel:{tenant_id}:{entity_id}"
    valkey = getattr(request.app.state, "valkey", None)

    # ── Cache hit check ─────────────────────────────────────────────────────
    if valkey is not None:
        try:
            cached = await valkey.get(cache_key)
            if cached is not None:
                return Response(content=cached, status_code=200, media_type="application/json")
        except Exception:
            # Fail-open: Valkey error must not block the request.
            logger.warning("intelligence_cache_read_failed", entity_id=str(entity_id))

    # ── Proxy to S7 ─────────────────────────────────────────────────────────
    headers = _auth_headers(request)
    clients = _clients(request)

    # Forward only the known S7 query params; strip unknown ones.
    s7_params: dict[str, str] = {}
    if confidence_breakdown:
        s7_params["confidence_breakdown"] = "true"
    if focus_node is not None:
        s7_params["focus_node"] = focus_node

    resp = await clients.knowledge_graph.get(
        f"/api/v1/entities/{entity_id}/intelligence",
        params=s7_params if s7_params else None,
        headers=headers,
    )

    # ── Cache store (only 2xx) ───────────────────────────────────────────────
    if resp.status_code < 400 and valkey is not None:
        try:
            # WHY ex= (not ttl=): aligns with the ValkeyClient.set() signature.
            await valkey.set(cache_key, resp.content.decode(), ex=60)
        except Exception:
            # Fail-open: caching is best-effort.
            logger.warning("intelligence_cache_write_failed", entity_id=str(entity_id))

    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get(
    "/entities/{entity_id}/narratives",
    summary="Paginated narrative version history (PLAN-0074 Wave G)",
)
async def get_entity_narratives(
    entity_id: UUID,
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> Any:
    """Proxy GET /api/v1/entities/{entity_id}/narratives → S7 Knowledge Graph.

    Returns paginated narrative version history for an entity, newest first.
    Supply ``cursor`` from the previous response's ``next_cursor`` field to
    page forward.  No caching — paginated endpoints change frequently.

    Requires authentication.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")

    headers = _auth_headers(request)
    clients = _clients(request)

    params: dict[str, str | int] = {"limit": limit}
    if cursor is not None:
        params["cursor"] = cursor

    resp = await clients.knowledge_graph.get(
        f"/api/v1/entities/{entity_id}/narratives",
        params=params,
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.post(
    "/entities/{entity_id}/narratives/generate",
    status_code=202,
    summary="Manually trigger narrative generation (PLAN-0074 Wave G)",
)
async def trigger_entity_narrative_generation(
    entity_id: UUID,
    request: Request,
) -> Any:
    """Proxy POST /api/v1/entities/{entity_id}/narratives/generate → S7.

    Rate-limited to one request per entity+tenant+user per hour at the S9
    proxy layer (in addition to the identical rate limit enforced by S7).

    Why rate-limit at S9 too: defence-in-depth.  An unauthenticated attacker
    who somehow reaches S7 directly is blocked there, but authenticated callers
    who hammer the gateway are stopped here before the request even reaches S7.

    Rate-limit key: ``narrative_gen_proxy:<tenant_id>:<entity_id>:<user_id>``
    BP-200: uses set_nx(key, "1", ex=3600) — NOT set(..., nx=True).

    On 429: returns ``Retry-After: 3600`` header.
    On Valkey unavailable: proxy proceeds without rate limiting (fail-open).
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")

    user = request.state.user
    tenant_id: str = str(user.get("tenant_id", ""))
    user_id: str = str(user.get("user_id") or user.get("sub", "anonymous"))

    # ── Proxy-layer rate limit (BP-200) ─────────────────────────────────────
    valkey = getattr(request.app.state, "valkey", None)
    if valkey is not None:
        rl_key = f"narrative_gen_proxy:{tenant_id}:{entity_id}:{user_id}"
        try:
            allowed = await valkey.set_nx(rl_key, "1", ex=3600)
            if not allowed:
                # Key already existed → rate limit hit.
                raise HTTPException(
                    status_code=429,
                    detail="Rate limit: one manual generation per hour.",
                    headers={"Retry-After": "3600"},
                )
        except HTTPException:
            raise
        except Exception:
            # Fail-open: Valkey error → allow the request through.
            logger.warning("narrative_gen_proxy_rl_failed", entity_id=str(entity_id))

    # ── Proxy to S7 ─────────────────────────────────────────────────────────
    headers = _auth_headers(request)
    clients = _clients(request)
    resp = await clients.knowledge_graph.post(
        f"/api/v1/entities/{entity_id}/narratives/generate",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get(
    "/entities/{entity_id}/paths",
    summary="Multi-hop opportunity paths for an entity (PLAN-0074 Wave G)",
)
async def get_entity_paths(
    entity_id: UUID,
    request: Request,
    limit: int = Query(default=10, ge=1, le=50),
    min_score: float = Query(default=0.3, ge=0.0, le=1.0),
    min_hops: int = Query(default=2, ge=2, le=5),
    max_hops: int = Query(default=5, ge=2, le=5),
) -> Any:
    """Proxy GET /api/v1/entities/{entity_id}/paths → S7 Knowledge Graph.

    Returns top-N pre-computed multi-hop opportunity paths originating from
    the entity, ordered by composite_score descending.

    Caching strategy (5-minute TTL):
      - Cache key: ``paths:<tenant_id>:<entity_id>:<limit>:<min_score>:<min_hops>:<max_hops>``
      - Paths are recomputed nightly by the KG scheduler; 5 min is safe.
      - Non-2xx responses are never cached.
      - Fail-open on Valkey errors.

    Query param validation mirrors S7: 422 if min_hops > max_hops.
    Requires authentication.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")

    # Validate hop range here for a clean 422 (S7 also validates).
    if min_hops > max_hops:
        raise HTTPException(
            status_code=422,
            detail=f"min_hops ({min_hops}) must be <= max_hops ({max_hops})",
        )

    user = request.state.user
    tenant_id: str = str(user.get("tenant_id", ""))
    # Build a deterministic cache key from all query params.
    cache_key = f"paths:{tenant_id}:{entity_id}:{limit}:{min_score}:{min_hops}:{max_hops}"
    valkey = getattr(request.app.state, "valkey", None)

    # ── Cache hit ────────────────────────────────────────────────────────────
    if valkey is not None:
        try:
            cached = await valkey.get(cache_key)
            if cached is not None:
                return Response(content=cached, status_code=200, media_type="application/json")
        except Exception:
            logger.warning("paths_cache_read_failed", entity_id=str(entity_id))

    # ── Proxy to S7 ─────────────────────────────────────────────────────────
    headers = _auth_headers(request)
    clients = _clients(request)

    resp = await clients.knowledge_graph.get(
        f"/api/v1/entities/{entity_id}/paths",
        params={
            "limit": limit,
            "min_score": min_score,
            "min_hops": min_hops,
            "max_hops": max_hops,
        },
        headers=headers,
    )

    # ── Cache store (5 min — paths change nightly) ───────────────────────────
    if resp.status_code < 400 and valkey is not None:
        try:
            await valkey.set(cache_key, resp.content.decode(), ex=300)
        except Exception:
            logger.warning("paths_cache_write_failed", entity_id=str(entity_id))

    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


# ── News (PRD-0028 Wave S9-1) ────────────────────────────────────────────────


@router.get("/news/top", response_model=NewsTopResponse, response_model_exclude_none=True)
async def get_news_top(request: Request) -> Any:
    """Proxy GET /api/v1/news/top → S6 NLP Pipeline with cluster_size enrichment.

    No authentication required — public endpoint.  Issues a system JWT so S6's
    InternalJWTMiddleware accepts the request.
    Forwards query parameters (hours, limit, offset, min_display_score, routing_tier) unchanged.

    SA-4 enrichment: after fetching from S6, calls content-store
    POST /api/v1/documents/cluster-sizes in a single batch to add cluster_size
    to each article.  cluster_size=1 means no near-duplicates detected;
    cluster_size=N means N-1 near-duplicate siblings exist.  Enrichment
    failure is non-fatal (cluster_size defaults to null in the response).

    PERF-001 (2026-05-11): this endpoint is on the dashboard critical path (every
    page load + every 5-minute refetch).  Two sequential downstream hops (S6 SQL
    with 3-CTE window pivot + content-store cluster enrichment) caused 3-5 s
    cold latency.  Added a 2-minute Valkey cache keyed on all query params so
    only the first request per 2-minute window pays the full cost; all others
    return in <10 ms.  TTL=120 s is short enough to surface breaking news within
    2 minutes and long enough to amortise the cost across all dashboard tabs.
    Cache is skipped gracefully when Valkey is unavailable (fail-open pattern).
    """
    # ── Valkey cache check ────────────────────────────────────────────────────
    # WHY cache at S9 (not S6): S9 owns the composed response (S6 body +
    # cluster-size enrichment). Caching at S6 would not capture the enrichment.
    # WHY 120 s TTL: news relevance changes slowly within a 2-minute window.
    # This collapses repeated dashboard loads/tab switches to a single S6 call.
    _news_top_cache_ttl = 120
    valkey = getattr(request.app.state, "valkey", None)
    qp = dict(request.query_params)
    # Cache key: sorted params so ?limit=20&hours=24 == ?hours=24&limit=20.
    _cache_key = "news:top:v1:" + ":".join(f"{k}={v}" for k, v in sorted(qp.items()))

    if valkey is not None:
        try:
            cached = await valkey.get(_cache_key)
            if cached:
                raw = cached.decode("utf-8") if isinstance(cached, bytes) else cached
                return Response(content=raw, status_code=200, media_type="application/json")
        except Exception as _e:
            logger.warning("news_top_cache_read_failed", error=str(_e))

    clients = _clients(request)
    sys_headers = _system_headers(request)
    resp = await clients.nlp_pipeline.get(
        "/api/v1/news/top",
        params=qp,
        headers=sys_headers,
    )
    if resp.status_code != 200:
        # Pass through non-200 responses unchanged (e.g. 429, 503 from S6).
        return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")

    # ── Cluster-size enrichment ───────────────────────────────────────────────
    # Parse the S6 response, collect article_ids (= content-store doc_ids),
    # and batch-fetch cluster sizes.  Merge back into each article dict.
    # WHY best-effort (try/except): enrichment is cosmetic — a content-store
    # outage should never break the news feed.
    try:
        body = json.loads(resp.content)
        articles = body.get("articles", [])
        doc_ids = [a["article_id"] for a in articles if a.get("article_id")]
        cluster_size_map: dict[str, int] = {}
        # WHY cluster_id added (P2-F): the "+N sim" chip click opens a drawer
        # that fetches GET /v1/news/cluster/{cluster_id}.  The frontend needs
        # cluster_id on the article to make that call.  cluster_id is None when
        # cluster_size=1 (no near-duplicates) — content-store contract.
        cluster_id_map: dict[str, str | None] = {}
        if doc_ids:
            cs_resp = await clients.content_store.post(
                "/api/v1/documents/cluster-sizes",
                json={"doc_ids": doc_ids},
                headers=sys_headers,
            )
            if cs_resp.status_code == 200:
                cs_body = json.loads(cs_resp.content)
                for entry in cs_body.get("entries", []):
                    aid_str = str(entry["doc_id"])
                    cluster_size_map[aid_str] = entry["cluster_size"]
                    # cluster_id present since P2-F; None for isolated articles.
                    cluster_id_map[aid_str] = entry.get("cluster_id")
        for article in articles:
            aid = str(article.get("article_id", ""))
            # cluster_size=1 means "alone in cluster" (no near-duplicates)
            article["cluster_size"] = cluster_size_map.get(aid, 1)
            article["cluster_id"] = cluster_id_map.get(aid)
        body["articles"] = articles
        final_body = json.dumps(body)

        # ── Write enriched response to Valkey cache ───────────────────────────
        if valkey is not None:
            try:
                await valkey.set(_cache_key, final_body, ex=_news_top_cache_ttl)
            except Exception as _e:
                logger.warning("news_top_cache_write_failed", error=str(_e))

        return Response(
            content=final_body,
            status_code=200,
            media_type="application/json",
        )
    except Exception:
        # Enrichment failed — return the original S6 response unchanged.
        logger.warning("news_top_cluster_size_enrichment_failed", exc_info=True)
        return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/news/cluster/{cluster_id}")
async def get_news_cluster(cluster_id: str, request: Request) -> Any:
    """Proxy GET /v1/news/cluster/{cluster_id} → content-store cluster articles.

    No authentication required — same public-read posture as /v1/news/top.
    Issues a system JWT so content-store's InternalJWTMiddleware accepts the
    request.

    WHY this endpoint (P2-F): the frontend "+N sim" chip click opens a Sheet
    (side panel) showing all articles in the same near-duplicate cluster.
    The frontend passes the cluster_id it received from the enriched news/top
    response to fetch the cluster member list.

    Returns the content-store response unchanged (200 with articles list, or
    404 if the cluster_id is not found).
    """
    clients = _clients(request)
    sys_headers = _system_headers(request)
    resp = await clients.content_store.get(
        f"/api/v1/documents/cluster/{cluster_id}/articles",
        headers=sys_headers,
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


# NOTE: /entities/{entity_id}/articles MUST be registered before /entities/{entity_id}/graph
# to avoid ambiguity with other entity sub-resource paths. FastAPI matches in registration order.
@router.get("/entities/{entity_id}/articles")
async def get_entity_articles(entity_id: str, request: Request) -> Any:
    """Proxy GET /api/v1/entities/{entity_id}/articles → S6 NLP Pipeline.

    Canonical alias for /v1/news/entity/{entity_id} — same S6 endpoint.

    WHY this alias exists: the frontend Instrument page components (InstrumentTopNews,
    FundamentalsTopNews, IntelligenceTab) reference /v1/entities/{id}/articles as the
    canonical path for entity-scoped news.  Maintaining both /v1/news/entity/{id} and
    this path ensures backward compat while giving instrument-page consumers a natural
    resource-oriented URL shape.

    Requires authentication. Forwards query parameters (start_date, end_date,
    order_by, limit, offset) unchanged.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")
    headers = _auth_headers(request)
    clients = _clients(request)
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


# ── Tenant Document Management (PLAN-0086 Wave E-2) ───────────────────────────
#
# These routes proxy tenant document upload/list/get/delete to S4
# (content-ingestion service).  All four require authentication — documents are
# tenant-scoped and must never be accessible to unauthenticated callers.
#
# Header forwarding strategy:
# - X-Internal-JWT: issued by _auth_headers(); carries user_id, tenant_id, role.
# - X-Tenant-ID / X-User-ID: forwarded explicitly for S4's header-based dep
#   extractors (tenant_id_dep / user_id_dep in documents.py).
#
# The upload route uses httpx multipart forwarding: the file bytes are read from
# the incoming request and re-sent as a multipart/form-data body to S4.  httpx
# handles the boundary header automatically when ``files=`` is used.


def _document_headers(request: Request) -> dict[str, str]:
    """Build headers for S4 document requests.

    Extends _auth_headers() with X-Tenant-ID and X-User-ID so S4's
    header-based dependency extractors receive the tenant/user identity
    in addition to the internal JWT payload.

    WHY explicit headers: S4's documents router defines Depends(tenant_id_dep)
    and Depends(user_id_dep) which first try X-Tenant-ID / X-User-ID headers,
    then fall back to request.state (populated by InternalJWTMiddleware).
    Forwarding both is belt-and-suspenders and makes the S4 dep resolution
    independent of whether S4's own middleware ran.
    """
    headers = _auth_headers(request)
    user = getattr(request.state, "user", None) or {}
    if isinstance(user, dict):
        tenant_id = user.get("tenant_id", "")
        user_id = user.get("user_id", "") or user.get("sub", "")
        if tenant_id:
            headers["X-Tenant-ID"] = tenant_id
        if user_id:
            headers["X-User-ID"] = user_id
    return headers


@router.post("/documents/upload", status_code=202)
async def upload_document_proxy(request: Request) -> Response:
    """Proxy POST /v1/documents/upload → S4 POST /api/v1/documents/upload.

    PLAN-0086 Wave E-2: Tenant document upload.

    The multipart file is forwarded by reading the raw body and passing it
    through with the original Content-Type header (which includes the boundary
    parameter).  This avoids parsing and re-encoding the multipart data at the
    gateway layer.

    Requires authentication.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")

    # Read raw multipart body — pass it through verbatim to S4.
    # The Content-Type header (multipart/form-data; boundary=...) MUST be
    # forwarded unchanged so S4 can decode the boundary.
    body = await request.body()
    content_type = request.headers.get("Content-Type", "")
    headers = _document_headers(request)

    clients = _clients(request)
    resp = await clients.content_ingestion.post(
        "/api/v1/documents/upload",
        content=body,
        headers={"Content-Type": content_type, **headers},
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/documents/{doc_id}")
async def get_document_proxy(doc_id: str, request: Request) -> Response:
    """Proxy GET /v1/documents/{doc_id} → S4 GET /api/v1/documents/{doc_id}.

    PLAN-0086 Wave E-2: Fetch a single tenant document status.

    Requires authentication.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")

    headers = _document_headers(request)
    clients = _clients(request)
    resp = await clients.content_ingestion.get(
        f"/api/v1/documents/{doc_id}",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.get("/documents")
async def list_documents_proxy(request: Request) -> Response:
    """Proxy GET /v1/documents → S4 GET /api/v1/documents.

    PLAN-0086 Wave E-2: Paginated list of tenant documents.

    Forwards all query params (status, limit, cursor) to S4 unchanged.
    Requires authentication.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")

    headers = _document_headers(request)
    clients = _clients(request)
    # Forward all query params (status filter, limit, cursor) to S4 as-is.
    resp = await clients.content_ingestion.get(
        "/api/v1/documents",
        params=dict(request.query_params),
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")


@router.delete("/documents/{doc_id}", status_code=200)
async def delete_document_proxy(doc_id: str, request: Request) -> Response:
    """Proxy DELETE /v1/documents/{doc_id} → S4 DELETE /api/v1/documents/{doc_id}.

    PLAN-0086 Wave E-2: Soft-delete a tenant document.

    Returns 200 with body (BP-064: never 204) — S4 returns the same.
    Requires authentication.
    """
    if not getattr(request.state, "user", None):
        raise HTTPException(status_code=401, detail="Authentication required")

    headers = _document_headers(request)
    clients = _clients(request)
    resp = await clients.content_ingestion.delete(
        f"/api/v1/documents/{doc_id}",
        headers=headers,
    )
    return Response(content=resp.content, status_code=resp.status_code, media_type="application/json")
