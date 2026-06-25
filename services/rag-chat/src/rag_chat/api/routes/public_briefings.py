"""Public briefing routes — GET /api/v1/briefings/* (PLAN-0029 T-2-01).

Called via S9 proxy. Auth enforced by InternalJWTMiddleware (PRD-0025).
Generates on-demand briefings with Valkey caching (24h TTL).

R25: This route imports only from the application layer (schemas + domain errors).

PLAN-0062-W4 (T-W4-C-01):
- Cache keys bumped to v2 to avoid serving stale pre-W4 cached briefs
  (which lack confidence/lead/BriefBullet citations) to the new frontend.
  Key format: "briefing:morning:v2:{user_id}" and
              "briefing:instrument:v2:{entity_id}:{user_id}".
- confidence and lead from the use case result are propagated into the
  response and logged for observability.

PLAN-0066 Wave B (T-W10-B-03):
- GET /api/v1/briefings/morning/history — paginated brief archive.
  Uses BriefArchiveRepositoryDep (read-only session, R27).
  page_size capped at 50 via Query(le=50) to prevent runaway queries.

PLAN-0066 Wave C (T-W10-C-01, T-W10-C-02):
- GET /api/v1/briefings/morning/diff — text-normalised bullet diff between
  the two most-recent morning briefs. Uses ReadUoWDep (R27).
- POST /api/v1/briefings/feedback/bullet — bullet-level reaction (helpful/unhelpful)
- POST /api/v1/briefings/feedback/brief  - brief-level star rating (1-5)
  Both POST endpoints use UoWDep (write session) and return 201.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from rag_chat.api.dependencies import BriefArchiveRepositoryDep, ReadUoWDep, UoWDep
from rag_chat.api.schemas import PublicBriefingResponse
from rag_chat.application.use_cases.create_thread import CreateThreadUseCase
from rag_chat.domain.errors import (
    BriefNotFoundError,
    EntityNotFoundError,
    ProviderUnavailableError,
    RateLimitExceededError,
)

router = APIRouter(prefix="/api/v1", tags=["briefings"])
log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# Cache TTL: 24 hours — briefings are expensive (LLM call) and stable within a day.
_CACHE_TTL = 86400
# PLAN-0094 W2: last-known-good key TTL — 7 days by default (gives a wide
# enough fallback window that a user away on a long weekend still has a brief
# to read on Monday morning).  Mirrors ``brief_last_good_ttl_days`` setting;
# this constant is the seconds equivalent.
_LASTGOOD_TTL = 7 * 86400

# ── Cache-poisoning guard (2026-06-19 empty-AI-brief investigation) ───────────
# A "low-context refusal" brief is one the generator produced WITHOUT any usable
# upstream context: every section reads "No specific items today" and the
# confidence collapses to 0.0.  This happens on a transient auth/upstream blip
# (e.g. the gateway service-token mint returning 503, or all upstreams 401'ing).
#
# Such a brief MUST NOT overwrite the ``briefing:morning:lastgood:{user_id}``
# key — doing so clobbers the last KNOWN-GOOD brief and leaves the dashboard
# blank until the next successful generation.  The matching pregeneration worker
# already guards its lastgood write (``_looks_empty`` in
# morning_brief_pregeneration_worker.py); the on-demand GET cold-gen path and
# the POST /briefings/morning/generate force-regen path did NOT — so a single
# blip while a user hit "Regenerate" could poison lastgood.  This guard closes
# that gap.
#
# The substring is the deterministic placeholder the use case emits for an empty
# section (see GenerateBriefingUseCase low-context branch).  We keep it here as a
# module constant so the test can assert against the exact text.
_LOW_CONTEXT_PLACEHOLDER = "No specific items today"


def _is_low_context_brief(response: PublicBriefingResponse) -> bool:
    """Return True if ``response`` is a zero-context refusal that must not be
    written to the last-known-good cache key.

    A brief is treated as low-context when BOTH hold:

    1. ``confidence`` is 0.0 (the generator's signal that it had no real data),
       AND
    2. it carries no usable structure — no citations, no real sections (every
       section body is the "No specific items today" placeholder).

    Requiring confidence==0 AND no citations keeps the guard conservative: a
    genuine-but-sparse brief (one real citation, or a real section with a
    positive confidence) still passes through and updates lastgood as normal.
    We never want to REJECT a good brief — only refuse to let a refusal stomp
    a previously-good one.
    """
    # Signal 1: confidence collapsed to zero. ``confidence`` defaults to 1.0 in
    # the schema, so a real brief never accidentally trips this.
    if (response.confidence or 0.0) > 0.0:
        return False

    # Signal 2a: any citation at all means the brief grounded in real data.
    if response.citations:
        return False

    # Signal 2b: any section whose BODY is NOT the empty placeholder means the
    # generator found real content for at least one section.  We inspect only
    # body/content fields — NOT the section title (titles like "Portfolio" /
    # "News" are static labels present even on an empty brief and would falsely
    # pass the guard if scanned).
    body_keys = ("body", "content", "text", "markdown", "summary")
    for section in response.sections or []:
        # Sections are dicts (list[dict] in the schema), but read defensively in
        # case a BriefSection model leaks through on some call path.
        if isinstance(section, dict):
            section_dict = section
        elif hasattr(section, "model_dump"):
            section_dict = section.model_dump()
        else:
            section_dict = {}
        for key in body_keys:
            value = section_dict.get(key)
            if isinstance(value, str):
                stripped = value.strip()
                if stripped and _LOW_CONTEXT_PLACEHOLDER not in stripped:
                    return False
            elif isinstance(value, list):
                # Bullet lists: any non-placeholder bullet string is real content.
                for item in value:
                    if isinstance(item, str):
                        text = item
                    elif isinstance(item, dict):
                        text = str(item.get("text", ""))
                    else:
                        text = ""
                    if text.strip() and _LOW_CONTEXT_PLACEHOLDER not in text:
                        return False

    # confidence==0, no citations, every section empty/placeholder → refusal.
    return True


async def _write_brief_caches(
    valkey: Any,
    *,
    cache_key: str,
    lastgood_key: str,
    response: PublicBriefingResponse,
) -> None:
    """Write the fresh brief to ``cache_key`` and (conditionally) ``lastgood_key``.

    The fresh key is ALWAYS written — the caller asked for this brief and should
    see it immediately, even if it is a low-context refusal (so the frontend can
    render the EmptyState / Regenerate affordance rather than serving an even
    older payload).

    The lastgood key is written ONLY when the brief is NOT a low-context refusal
    (see ``_is_low_context_brief``).  This preserves the previous known-good
    brief across a transient upstream/auth blip — the core cache-poisoning fix.

    WHY model_dump_json (not json.dumps): avoids stringifying nested Pydantic
    models to non-deserialisable reprs (BP-319).
    """
    if valkey is None:
        return
    try:
        payload_json = response.model_dump_json()
        # Fresh key: always — the caller wants this exact result back.
        await valkey.set(cache_key, payload_json, ex=_CACHE_TTL)
        # Lastgood key: only for real briefs, never for a zero-context refusal.
        if _is_low_context_brief(response):
            log.warning(  # type: ignore[no-any-return]
                "briefing_lastgood_write_skipped_low_context",
                key=lastgood_key,
                confidence=response.confidence,
            )
        else:
            await valkey.set(lastgood_key, payload_json, ex=_LASTGOOD_TTL)
    except Exception as exc:  # — cache write is best-effort
        log.warning("briefing_cache_write_failed", error=str(exc), key=cache_key)  # type: ignore[no-any-return]


# ── PLAN-0066 Wave B: history response schemas ────────────────────────────────


class BriefHistoryItem(BaseModel):
    """One entry in the brief history list — a lightweight summary of a past brief.

    WHY id as str (not UUID): the JSON API contract uses string UUIDs; the
    frontend converts to UUID if needed. Keeping str here avoids the Pydantic
    UUID→string serialisation edge-cases in older clients.
    """

    id: str
    generated_at: str  # ISO-8601 string — consistent with existing brief response shapes
    headline: str
    lead: str | None = None
    confidence: float


class BriefHistoryResponse(BaseModel):
    """Paginated response for GET /api/v1/briefings/morning/history.

    WHY include total + page + page_size: callers need all three to implement
    pagination UI (know when last page is reached, display "page N of M").
    Matches the standard worldview pagination contract used by screener + thread list.
    """

    items: list[BriefHistoryItem]
    total: int
    page: int
    page_size: int


def _get_briefing_uc(request: Request) -> Any:
    """Retrieve the GenerateBriefingUseCase from app.state (wired in lifespan)."""
    return request.app.state.briefing_uc


def _get_valkey(request: Request) -> Any:
    """Retrieve the Valkey client from app.state (wired in lifespan)."""
    return request.app.state.valkey


def _extract_user_id(request: Request) -> str:
    """Extract user_id from request.state (set by InternalJWTMiddleware).

    The middleware decodes the ``sub`` claim from X-Internal-JWT and stores it
    as ``request.state.user_id``. Missing user_id means the JWT was invalid or
    absent — return 401.
    """
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Missing user_id in JWT")
    return str(user_id)


def _extract_tenant_id(request: Request) -> str:
    """Extract tenant_id from request.state (set by InternalJWTMiddleware).

    Returns empty string if no tenant_id is present (e.g. system-level tokens).
    """
    return str(getattr(request.state, "tenant_id", "") or "")


def _to_uuid(value: str) -> UUID:
    """Safely convert a string to UUID for the use-case layer.

    GenerateBriefingUseCase.execute() expects UUID-typed user_id/tenant_id.
    The InternalJWTMiddleware stores them as strings from the JWT claims.
    """
    try:
        return UUID(value)
    except (ValueError, AttributeError):
        # Fallback: use a nil UUID rather than crashing the request.
        # This can happen with system-level JWTs that have non-UUID sub claims.
        return UUID("00000000-0000-0000-0000-000000000000")


@router.get("/briefings/morning", response_model=PublicBriefingResponse)
async def get_morning_briefing(request: Request) -> PublicBriefingResponse:
    """Generate or retrieve a cached morning market briefing.

    - Checks Valkey cache (key: ``briefing:morning:v2:{user_id}``, TTL: 24h)
    - If cached: returns immediately with ``cached=True``
    - If not: generates via GenerateBriefingUseCase with default market context
    - On generation failure: returns 503

    Auth: InternalJWTMiddleware enforces X-Internal-JWT (PRD-0025).

    PLAN-0062-W4: cache key bumped to v2 to avoid serving stale pre-W4 cached briefs
    (which have string bullets instead of BriefBullet objects). The old
    "briefing:morning:{user_id}" keys will simply expire naturally.
    """
    user_id = _extract_user_id(request)
    tenant_id = _extract_tenant_id(request)
    valkey = _get_valkey(request)
    # WHY v2: PLAN-0062-W4 changed BriefSection.bullets from list[str] to
    # list[BriefBullet]. Cached pre-W4 responses must not be served to W4+ clients.
    cache_key = f"briefing:morning:v2:{user_id}"
    # PLAN-0094 W2: last-known-good fallback key.  Populated by the brief
    # pre-generation worker AND on every successful on-demand generation, so
    # users always have a brief to fall back to if a future regen fails.
    lastgood_key = f"briefing:morning:lastgood:{user_id}"

    # ── Lookup chain (PLAN-0094 W2) ───────────────────────────────────────────
    # 1. Fresh cache hit → return immediately with is_stale=False.
    # 2. Lastgood hit    → return with is_stale=True, fire-and-forget regen.
    # 3. Cold user       → existing on-demand path (block + 503 on failure).
    if valkey is not None:
        try:
            cached = await valkey.get(cache_key)
            if cached:
                # Valkey returns bytes or str — decode if needed
                raw = cached.decode("utf-8") if isinstance(cached, bytes) else cached
                # WHY model_validate_json: avoids the json.loads + **data pattern that
                # breaks when sections are stored as Python repr strings (BP-319).
                resp = PublicBriefingResponse.model_validate_json(raw)
                resp.cached = True
                resp.is_stale = False
                return resp
        except Exception as e:
            # Cache miss or deserialization failure — proceed to lastgood / generation.
            log.warning("briefing_cache_read_failed", error=str(e), key=cache_key)  # type: ignore[no-any-return]

        # ── Step 2: last-known-good fallback ──────────────────────────────────
        # Read the lastgood key; if present, serve as stale and schedule a
        # best-effort background regeneration so the next request can hit fresh.
        try:
            lastgood = await valkey.get(lastgood_key)
            if lastgood:
                raw_lg = lastgood.decode("utf-8") if isinstance(lastgood, bytes) else lastgood
                stale_resp = PublicBriefingResponse.model_validate_json(raw_lg)
                stale_resp.cached = True
                stale_resp.is_stale = True
                # Observability — count stale serves separately so ops can spot
                # a sustained regen-failure pattern.
                try:
                    from rag_chat.application.metrics.prometheus import rag_brief_served_stale_total

                    rag_brief_served_stale_total.inc()
                except Exception:  # pragma: no cover  # noqa: S110 — metrics import never fails in practice
                    pass
                log.info(  # type: ignore[no-any-return]
                    "brief_served_stale",
                    user_id=user_id,
                    lastgood_generated_at=getattr(stale_resp, "generated_at", None),
                )
                # Fire-and-forget background regen.  We DO NOT await — the user
                # gets the stale response immediately.  ``asyncio.create_task``
                # schedules the coroutine; exceptions inside it are swallowed
                # by the helper below (we don't want a background failure to
                # surface anywhere that could affect the request).
                #
                # F-CR-003 fix (PLAN-0093 iter-9 QA): we MUST NOT call
                # ``set_current_jwt(bg_jwt)`` here in the parent request scope.
                # ``asyncio.create_task`` copies the current Context at task
                # creation time — if we set the ContextVar before creating the
                # task, the background JWT bleeds into anything that touches
                # this Context (other code in this handler, future handler
                # extensions, test isolation, etc.).  Instead we pass ``bg_jwt``
                # as an explicit positional arg to the coroutine and the
                # coroutine sets the ContextVar inside its OWN task context —
                # which is isolated by asyncio task boundaries.
                bg_jwt = request.headers.get("X-Internal-JWT")
                uc_for_bg = _get_briefing_uc(request)

                async def _background_regen(jwt_for_bg: str | None) -> None:
                    """Best-effort regeneration — never raises, just logs.

                    WHY a closure that takes ``jwt_for_bg`` as an explicit arg:
                    F-CR-003 (PLAN-0094 iter-9 QA) — calling
                    ``set_current_jwt`` in the parent handler scope before
                    ``asyncio.create_task`` leaked the JWT into the parent
                    request's context.  Setting the ContextVar INSIDE the task
                    coroutine confines it to the background task's own Context
                    copy.
                    """
                    # Set the ContextVar inside the background task's own
                    # Context — never touch the parent request's Context.
                    from rag_chat.infrastructure.clients.auth_context import (
                        set_current_jwt as _set_jwt_bg,
                    )

                    _set_jwt_bg(jwt_for_bg)
                    try:
                        result = await uc_for_bg.execute_public_morning(
                            user_id=user_id,
                            tenant_id=tenant_id,
                            internal_jwt=jwt_for_bg,
                        )
                        # Re-cache both keys so the next request hits fresh.
                        fresh_payload = PublicBriefingResponse(
                            narrative=result.get("content", ""),
                            risk_summary=result.get("risk_summary", {}),
                            citations=result.get("citations", []),
                            generated_at=result["generated_at"],
                            cached=False,
                            entity_id=None,
                            summary=result.get("summary"),
                            sections=result.get("sections", []),
                            confidence=result.get("confidence", 1.0),
                            lead=result.get("lead"),
                            is_stale=False,
                            # PLAN-0103 W3 (BP-624)
                            summary_paragraph=result.get("summary_paragraph"),
                        ).model_dump_json()
                        await valkey.set(cache_key, fresh_payload, ex=_CACHE_TTL)
                        await valkey.set(lastgood_key, fresh_payload, ex=_LASTGOOD_TTL)
                        log.info(  # type: ignore[no-any-return]
                            "brief_background_regen_succeeded",
                            user_id=user_id,
                        )
                    except Exception as exc:
                        log.warning(  # type: ignore[no-any-return]
                            "brief_background_regen_failed",
                            user_id=user_id,
                            error=str(exc),
                        )

                # asyncio.create_task() requires a running event loop, which we
                # have inside this async handler.  The task is not stored
                # anywhere — best-effort fire-and-forget is the contract.
                import asyncio as _asyncio

                _asyncio.create_task(_background_regen(bg_jwt))  # noqa: RUF006
                return stale_resp
        except Exception as e:
            log.warning(  # type: ignore[no-any-return]
                "briefing_lastgood_read_failed",
                error=str(e),
                key=lastgood_key,
            )

    # ── Generate briefing via use case ────────────────────────────────────────
    # WHY execute_public_morning() not execute(): the morning route must use the
    # portfolio-aware path that invokes BriefingContextGatherer (S1/S3/S5/S6/S7),
    # renders the MORNING_BRIEFING prompt, and returns content/risk_summary/citations.
    # Calling execute() here would use the email brief path with no frontend context.
    #
    # WHY set_current_jwt here: InternalJWTMiddleware sets the ContextVar when it
    # validates the incoming JWT.  However, some code paths (e.g. tests that bypass
    # the middleware, or future background-task execution) do not go through the
    # middleware.  Explicitly setting the ContextVar here before any upstream HTTP
    # call is made guarantees that BaseUpstreamClient._get()/_post() — which read
    # get_current_jwt() — always have a valid token for S6/S7 calls (prevents 401).
    from rag_chat.infrastructure.clients.auth_context import set_current_jwt

    internal_jwt = request.headers.get("X-Internal-JWT")
    set_current_jwt(internal_jwt)
    uc = _get_briefing_uc(request)
    # PLAN-0099 Wave C: flag-gated agentic brief generator (experimental).
    # When RAG_CHAT_BRIEF_AGENTIC_ENABLED=true we drive the iterative tool-use
    # loop instead of the single-turn generator. The agentic path falls back
    # to ``uc.execute_public_morning`` internally on any failure, so the
    # response envelope is always shape-compatible with the route.
    _settings = request.app.state.settings
    try:
        if getattr(_settings, "brief_agentic_enabled", False):
            from rag_chat.application.use_cases.agentic_brief_generator import AgenticBriefGenerator

            _factory = request.app.state.tool_executor_factory
            _tool_executor = _factory.for_request(
                user_id=UUID(user_id) if user_id else None,
                tenant_id=UUID(tenant_id) if tenant_id else None,
                internal_jwt=internal_jwt,
            )
            _agentic = AgenticBriefGenerator(
                llm_chain=request.app.state.llm_chain,
                tool_executor=_tool_executor,
                settings=_settings,
                fallback=uc,
            )
            result = await _agentic.generate(
                user_id=UUID(user_id),
                tenant_id=UUID(tenant_id),
            )
        else:
            result = await uc.execute_public_morning(
                user_id=user_id,
                tenant_id=tenant_id,
                internal_jwt=internal_jwt,
            )
    except RateLimitExceededError as e:
        raise HTTPException(status_code=429, detail=str(e)) from e
    except ProviderUnavailableError as e:
        raise HTTPException(status_code=503, detail="Briefing generation unavailable") from e
    except Exception as e:
        log.error("briefing_generation_failed", error=str(e), user_id=user_id)  # type: ignore[no-any-return]
        raise HTTPException(status_code=503, detail="Briefing generation unavailable") from e

    # PLAN-0062-W4: extract confidence + lead from use case result and propagate.
    confidence = result.get("confidence", 1.0)
    lead = result.get("lead")

    response_data = {
        # execute_public_morning() returns 'content' (not 'narrative') — map to schema field
        "narrative": result.get("content", ""),
        "risk_summary": result.get("risk_summary", {}),
        "citations": result.get("citations", []),
        "generated_at": result["generated_at"],
        "cached": False,
        "entity_id": None,
        # PLAN-0048 Wave A: the use case splits the v2.2 prompt output into a
        # 1-2 sentence ``summary`` and a structured ``narrative``. Passing
        # ``summary`` through here lets the frontend render the compact summary
        # in the collapsed card view and the full narrative when expanded.
        # ``None`` when the LLM didn't emit the two-tier divider (legacy fallback).
        "summary": result.get("summary"),
        # PLAN-0049 T-A-1-04: sections for structured render (falls back to []
        # for pre-W4 cached responses; frontend degrades to MarkdownContent).
        "sections": result.get("sections", []),
        # PLAN-0062-W4: confidence score and lead text
        "confidence": confidence,
        "lead": lead,
        # PLAN-0103 W3 (BP-624): collapsed-view summary paragraph from the v4.2
        # ``## Summary`` block. None when the LLM didn't emit the heading (e.g.
        # cached pre-v4.2 responses) — frontend handles the fallback.
        "summary_paragraph": result.get("summary_paragraph"),
    }

    log.info(  # type: ignore[no-any-return]
        "morning_briefing_route_complete",
        user_id=user_id,
        confidence=confidence,
        lead_present=lead is not None,
    )

    resp = PublicBriefingResponse(**response_data)

    # ── Write to cache ────────────────────────────────────────────────────────
    # PLAN-0094 W2: write the lastgood key so a future regen failure has a
    # known-good payload to fall back on. 2026-06-19: gate the lastgood write on
    # ``_is_low_context_brief`` so a zero-context refusal does not clobber the
    # previous good brief (cache-poisoning guard).
    await _write_brief_caches(
        valkey,
        cache_key=cache_key,
        lastgood_key=lastgood_key,
        response=resp,
    )

    return resp


@router.get("/briefings/instrument/{entity_id}", response_model=PublicBriefingResponse)
async def get_instrument_briefing(entity_id: str, request: Request) -> PublicBriefingResponse:
    """Generate or retrieve a cached instrument-specific briefing.

    - Checks Valkey cache (key: ``briefing:instrument:v2:{entity_id}:{user_id}``, TTL: 24h)
    - If cached: returns immediately with ``cached=True``
    - If not: generates via GenerateBriefingUseCase with entity-focused context
    - On generation failure: returns 503

    Auth: InternalJWTMiddleware enforces X-Internal-JWT (PRD-0025).

    PLAN-0062-W4: cache key bumped to v2 (same rationale as morning briefing).
    """
    user_id = _extract_user_id(request)
    tenant_id = _extract_tenant_id(request)  # noqa: F841 — reserved for future cache-key scope
    valkey = _get_valkey(request)
    # WHY no user_id suffix (T-S8-06 / W5 Δ12): instrument briefs are entity-scoped,
    # not user-scoped — the same brief is valid for all users viewing the same entity.
    # Dropping the user_id suffix means a single Valkey entry serves all concurrent
    # viewers, cutting cache misses by ~N users per entity per day. Stale-user-brief
    # isolation is preserved by the morning briefing (which retains the user_id key).
    cache_key = f"briefing:instrument:v2:{entity_id}"

    # ── AI-brief-flag fix (2026-06-19): mark this instrument as "active" ──────
    # Record the view in the Valkey ``active_instruments`` sorted-set (member =
    # entity_id, score = now) so the InstrumentBriefPregenerationWorker can
    # proactively keep this instrument's persisted entity brief fresh — mirroring
    # how S9 populates ``active_users`` for the morning-brief worker. Best-effort:
    # a failure here must never affect the brief response.
    if valkey is not None:
        try:
            # Lazy import (D-1 / IG-LAYER-002): keep this infrastructure constant
            # off the module-import path so the API layer stays infra-free.
            from rag_chat.infrastructure.clients.active_instruments_reader import (
                ACTIVE_INSTRUMENTS_KEY as _ACTIVE_INSTRUMENTS_KEY,
            )

            await valkey.zadd(_ACTIVE_INSTRUMENTS_KEY, {entity_id: int(time.time())})
        except Exception as e:  # pragma: no cover — defensive
            log.warning("active_instruments_mark_failed", error=str(e), entity_id=entity_id)  # type: ignore[no-any-return]

    # ── Check Valkey cache ────────────────────────────────────────────────────
    if valkey is not None:
        try:
            cached = await valkey.get(cache_key)
            if cached:
                raw = cached.decode("utf-8") if isinstance(cached, bytes) else cached
                resp = PublicBriefingResponse.model_validate_json(raw)
                resp.cached = True
                return resp
        except Exception as e:
            log.warning("briefing_cache_read_failed", error=str(e), key=cache_key)  # type: ignore[no-any-return]

    # ── Generate briefing via use case ────────────────────────────────────────
    # WHY execute_public_instrument() not execute(): the instrument brief route
    # must use the entity-focused path that invokes BriefingContextGatherer,
    # assembles S7 graph + S3 fundamentals + S6 news, and renders the v3.0
    # INSTRUMENT_BRIEFING prompt.  Calling execute() here would use the
    # portfolio/email brief path with no entity context (PRD-0030 bug fix).
    #
    # WHY set_current_jwt here: same rationale as get_morning_briefing — ensures
    # BaseUpstreamClient._get()/_post() calls to S6/S7 always carry the JWT even
    # when code paths bypass InternalJWTMiddleware (e.g. tests, background tasks).
    from rag_chat.infrastructure.clients.auth_context import set_current_jwt

    set_current_jwt(request.headers.get("X-Internal-JWT"))
    uc = _get_briefing_uc(request)
    try:
        result = await uc.execute_public_instrument(entity_id=entity_id)
    except RateLimitExceededError as e:
        raise HTTPException(status_code=429, detail=str(e)) from e
    except ProviderUnavailableError as e:
        raise HTTPException(status_code=503, detail="Briefing generation unavailable") from e
    except EntityNotFoundError as e:
        # Entity does not exist in the knowledge graph — return 404 (not 503).
        # This happens when a market-data instrument_id is passed instead of a KG entity_id,
        # or when the entity has not yet been ingested into the KG.
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        # Malformed entity_id (e.g. invalid UUID string) — return 404 instead of 503.
        # UUID("bad-string") raises ValueError; treating as "entity not found" is correct
        # because a well-formed entity_id is a prerequisite for any lookup.
        log.warning(  # type: ignore[no-any-return]
            "briefing_invalid_entity_id",
            error=str(e),
            entity_id=entity_id,
        )
        raise HTTPException(status_code=404, detail=f"Invalid entity_id: {entity_id}") from e
    except Exception as e:
        log.error(  # type: ignore[no-any-return]
            "briefing_generation_failed",
            error=str(e),
            user_id=user_id,
            entity_id=entity_id,
        )
        raise HTTPException(status_code=503, detail="Briefing generation unavailable") from e

    # PLAN-0062-W4: extract confidence + lead from use case result.
    instrument_confidence = result.get("confidence", 1.0)
    instrument_lead = result.get("lead")

    response_data = {
        # execute_public_instrument() returns 'content' (not 'narrative') — map to schema field
        "narrative": result.get("content", result.get("narrative", "")),
        "risk_summary": result.get("risk_summary") or {},
        "citations": result.get("citations", []),
        "generated_at": result["generated_at"],
        "cached": False,
        "entity_id": entity_id,
        "sections": result.get("sections", []),
        # PLAN-0062-W4: confidence score and lead text
        "confidence": instrument_confidence,
        "lead": instrument_lead,
    }

    log.info(  # type: ignore[no-any-return]
        "instrument_briefing_route_complete",
        entity_id=entity_id,
        user_id=user_id,
        confidence=instrument_confidence,
        lead_present=instrument_lead is not None,
    )

    instr_resp = PublicBriefingResponse(**response_data)

    # ── Write to cache ────────────────────────────────────────────────────────
    if valkey is not None:
        try:
            await valkey.set(cache_key, instr_resp.model_dump_json(), ex=_CACHE_TTL)
        except Exception as e:
            log.warning("briefing_cache_write_failed", error=str(e), key=cache_key)  # type: ignore[no-any-return]

    return instr_resp


# ── W5 T-S8-05: lazy-generate endpoint ───────────────────────────────────────


class GenerateBriefResponse(BaseModel):
    """Response for POST /api/v1/briefings/instrument/{entity_id}/generate.

    status:
      "cached"  — a valid brief is already in Valkey; returned immediately (HTTP 200).
      "queued"  — no cached brief; generation was started (HTTP 202).

    WHY brief_id optional: when status="queued", no brief exists yet.
    The caller should poll GET /v1/briefings/instrument/{entity_id} until the brief
    appears (Δ27 lazy-generate contract).
    """

    status: Literal["cached", "queued"]
    brief_id: str | None = None
    entity_id: str


@router.post("/briefings/instrument/{entity_id}/generate", status_code=200)
async def generate_instrument_brief(
    entity_id: str,
    request: Request,
) -> Any:
    """Idempotent lazy-generate endpoint (W5-T-S8-05, Δ27).

    Flow:
      1. Check Valkey for a cached brief (key: briefing:instrument:v2:{entity_id}).
         If found → return 200 + status="cached" + brief_id (avoids re-generation).
      2. Rate-limit: 60 POST calls per user per clock hour via Valkey INCR counter.
         On excess → 429 + Retry-After header with seconds until next hour.
      3. Enqueue generation via GenerateBriefingUseCase.execute_public_instrument().
         If generation fails (503) → propagate. If entity not found (404) → propagate.
      4. Cache the result (briefing:instrument:v2:{entity_id}) for 24h.
      5. Return 202 + status="queued" if the brief was newly generated.

    WHY idempotent: multiple simultaneous page loads should not trigger parallel
    LLM calls for the same entity. The Valkey cache acts as a natural dedup gate.

    WHY 200 (not 201) when cached: the brief was NOT created by this request.
    FastAPI is configured with status_code=200; cached path returns 200 via Response,
    queued path returns 202 by raising a response override.

    Auth: InternalJWTMiddleware enforces X-Internal-JWT (PRD-0025).
    """
    import math

    user_id = _extract_user_id(request)
    valkey = _get_valkey(request)
    cache_key = f"briefing:instrument:v2:{entity_id}"

    # ── Step 1: Cache hit (return 200 immediately) ────────────────────────────
    if valkey is not None:
        try:
            cached = await valkey.get(cache_key)
            if cached:
                raw = cached.decode("utf-8") if isinstance(cached, bytes) else cached
                cached_resp = PublicBriefingResponse.model_validate_json(raw)
                return GenerateBriefResponse(
                    status="cached",
                    brief_id=getattr(cached_resp, "id", None) and str(cached_resp.id),  # type: ignore[attr-defined]
                    entity_id=entity_id,
                )
        except Exception as exc:
            log.warning("generate_brief_cache_read_failed", entity_id=entity_id, error=str(exc))  # type: ignore[no-any-return]

    # ── Step 2: Rate limit (60 calls per user per clock hour) ────────────────
    # WHY clock-hour (not rolling window): simpler implementation; acceptable
    # granularity for a 60/hr quota that resets predictably on the hour.
    if valkey is not None:
        now_utc = datetime.now(tz=UTC)
        hour_bucket = now_utc.strftime("%Y%m%d%H")
        rate_key = f"brief_gen_rate:{user_id}:{hour_bucket}"
        try:
            count = await valkey.incr(rate_key)
            # WHY EXPIRE only on first increment: avoids resetting TTL on every call.
            if count == 1:
                await valkey.expire(rate_key, 3600)
            if count > 60:
                # Compute seconds until next full hour boundary.
                next_hour = now_utc.replace(minute=0, second=0, microsecond=0, tzinfo=UTC) + timedelta(hours=1)
                retry_after = math.ceil((next_hour - now_utc).total_seconds())
                raise HTTPException(
                    status_code=429,
                    detail=f"Brief generation quota exceeded (60/hour). Retry after {retry_after}s.",
                    headers={"Retry-After": str(retry_after)},
                )
        except HTTPException:
            raise
        except Exception as exc:
            # Fail-open: if Valkey is down, allow generation (prefer availability over strict throttling).
            log.warning("generate_brief_rate_check_failed", user_id=user_id, error=str(exc))  # type: ignore[no-any-return]

    # ── Step 3: Generate briefing ─────────────────────────────────────────────
    uc = _get_briefing_uc(request)
    try:
        result = await uc.execute_public_instrument(entity_id=entity_id)
    except RateLimitExceededError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except ProviderUnavailableError as exc:
        raise HTTPException(status_code=503, detail="Briefing generation unavailable") from exc
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=f"Invalid entity_id: {entity_id}") from exc
    except Exception as exc:
        log.error("generate_brief_failed", entity_id=entity_id, error=str(exc))  # type: ignore[no-any-return]
        raise HTTPException(status_code=503, detail="Briefing generation unavailable") from exc

    # ── Step 4: Cache the newly generated brief ───────────────────────────────
    response_data = {
        "narrative": result.get("content", result.get("narrative", "")),
        "risk_summary": result.get("risk_summary") or {},
        "citations": result.get("citations", []),
        "generated_at": result["generated_at"],
        "cached": False,
        "entity_id": entity_id,
        "sections": result.get("sections", []),
        "confidence": result.get("confidence", 1.0),
        "lead": result.get("lead"),
    }
    new_resp = PublicBriefingResponse(**response_data)
    if valkey is not None:
        try:
            await valkey.set(cache_key, new_resp.model_dump_json(), ex=_CACHE_TTL)
        except Exception as exc:
            log.warning("generate_brief_cache_write_failed", entity_id=entity_id, error=str(exc))  # type: ignore[no-any-return]

    log.info("generate_instrument_brief_queued", entity_id=entity_id, user_id=user_id)  # type: ignore[no-any-return]

    # ── Step 5: Return 202 (newly generated) ─────────────────────────────────
    # WHY 202 via raise: FastAPI's status_code=200 is set at the route level.
    # To return 202 for the queued case we need a Response object. We use
    # JSONResponse here to bypass the default Pydantic serialisation.
    from fastapi.responses import JSONResponse as _JSONResp

    return _JSONResp(  # type: ignore[return-value]
        status_code=202,
        content=GenerateBriefResponse(
            status="queued",
            brief_id=None,
            entity_id=entity_id,
        ).model_dump(),
    )


# ── Morning brief force-regenerate endpoint ───────────────────────────────────


class MorningGenerateResponse(BaseModel):
    """Response for POST /api/v1/briefings/morning/generate.

    status is always "queued" — unlike the instrument lazy-generate endpoint
    there is no "cached" short-circuit because the WHOLE POINT of this
    endpoint is to bypass the cache (dashboard "Regenerate" button).

    generated_at lets the caller confirm the brief is fresh without an extra
    round-trip; the canonical payload is still fetched via
    GET /v1/briefings/morning (which now hits the just-written cache).
    """

    status: Literal["queued"]
    generated_at: str | None = None


@router.post("/briefings/morning/generate", status_code=202)
async def generate_morning_brief(request: Request) -> Any:
    """Force-regenerate the authenticated user's morning brief.

    Unlike GET /briefings/morning (which serves cached/lastgood briefs and
    only generates cold), this endpoint ALWAYS regenerates — it bypasses the
    staleness/cache check entirely. Job semantics mirror the instrument
    lazy-generate endpoint (202 + status="queued"); generation itself runs
    synchronously within the request (same as the instrument endpoint) and
    the fresh brief is written to BOTH cache keys (fresh + lastgood) so the
    follow-up GET returns the new brief immediately.

    Flow:
      1. Rate-limit: shares the brief_gen_rate:{user_id}:{hour} Valkey
         counter with the instrument endpoint (60 generations/user/hour
         across both — a brief regen costs the same LLM tokens either way).
      2. Generate via execute_public_morning (or the agentic generator when
         RAG_CHAT_BRIEF_AGENTIC_ENABLED — same branch as the GET route).
      3. Write briefing:morning:v2:{user_id} + lastgood keys.
      4. Return 202 + {"status": "queued", "generated_at": ...}.

    Auth: InternalJWTMiddleware enforces X-Internal-JWT (PRD-0025).
    """
    import math

    user_id = _extract_user_id(request)
    tenant_id = _extract_tenant_id(request)
    valkey = _get_valkey(request)
    cache_key = f"briefing:morning:v2:{user_id}"
    lastgood_key = f"briefing:morning:lastgood:{user_id}"

    # ── Step 1: Rate limit (shared 60/user/hour bucket) ───────────────────────
    # WHY shared with the instrument endpoint: both trigger a full LLM
    # generation; a per-endpoint bucket would double the effective quota.
    if valkey is not None:
        now_utc = datetime.now(tz=UTC)
        hour_bucket = now_utc.strftime("%Y%m%d%H")
        rate_key = f"brief_gen_rate:{user_id}:{hour_bucket}"
        try:
            count = await valkey.incr(rate_key)
            if count == 1:
                await valkey.expire(rate_key, 3600)
            if count > 60:
                next_hour = now_utc.replace(minute=0, second=0, microsecond=0, tzinfo=UTC) + timedelta(hours=1)
                retry_after = math.ceil((next_hour - now_utc).total_seconds())
                raise HTTPException(
                    status_code=429,
                    detail=f"Brief generation quota exceeded (60/hour). Retry after {retry_after}s.",
                    headers={"Retry-After": str(retry_after)},
                )
        except HTTPException:
            raise
        except Exception as exc:
            # Fail-open: Valkey down → allow generation (availability > strict throttling).
            log.warning("generate_brief_rate_check_failed", user_id=user_id, error=str(exc))  # type: ignore[no-any-return]

    # ── Step 2: Generate (bypasses cache by design) ───────────────────────────
    # WHY set_current_jwt: same rationale as GET /briefings/morning — the
    # gatherer's S1/S3/S6/S7 calls read the JWT from the ContextVar.
    from rag_chat.infrastructure.clients.auth_context import set_current_jwt

    internal_jwt = request.headers.get("X-Internal-JWT")
    set_current_jwt(internal_jwt)
    uc = _get_briefing_uc(request)
    _settings = request.app.state.settings
    try:
        if getattr(_settings, "brief_agentic_enabled", False):
            from rag_chat.application.use_cases.agentic_brief_generator import AgenticBriefGenerator

            _factory = request.app.state.tool_executor_factory
            _tool_executor = _factory.for_request(
                user_id=UUID(user_id) if user_id else None,
                tenant_id=UUID(tenant_id) if tenant_id else None,
                internal_jwt=internal_jwt,
            )
            _agentic = AgenticBriefGenerator(
                llm_chain=request.app.state.llm_chain,
                tool_executor=_tool_executor,
                settings=_settings,
                fallback=uc,
            )
            result = await _agentic.generate(
                user_id=UUID(user_id),
                tenant_id=UUID(tenant_id),
            )
        else:
            result = await uc.execute_public_morning(
                user_id=user_id,
                tenant_id=tenant_id,
                internal_jwt=internal_jwt,
            )
    except RateLimitExceededError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except ProviderUnavailableError as exc:
        raise HTTPException(status_code=503, detail="Briefing generation unavailable") from exc
    except Exception as exc:
        log.error("generate_morning_brief_failed", user_id=user_id, error=str(exc))  # type: ignore[no-any-return]
        raise HTTPException(status_code=503, detail="Briefing generation unavailable") from exc

    # ── Step 3: Write BOTH cache keys so the follow-up GET serves fresh ───────
    fresh_resp = PublicBriefingResponse(
        narrative=result.get("content", ""),
        risk_summary=result.get("risk_summary", {}),
        citations=result.get("citations", []),
        generated_at=result["generated_at"],
        cached=False,
        entity_id=None,
        summary=result.get("summary"),
        sections=result.get("sections", []),
        confidence=result.get("confidence", 1.0),
        lead=result.get("lead"),
        is_stale=False,
        summary_paragraph=result.get("summary_paragraph"),
    )
    # 2026-06-19 cache-poisoning guard: a force-regen that lands a zero-context
    # refusal (e.g. a transient gateway/upstream auth blip) must NOT overwrite
    # the user's last-known-good brief. ``_write_brief_caches`` always writes the
    # fresh key (so the follow-up GET serves this result) but skips lastgood for
    # a low-context refusal.
    await _write_brief_caches(
        valkey,
        cache_key=cache_key,
        lastgood_key=lastgood_key,
        response=fresh_resp,
    )

    log.info(  # type: ignore[no-any-return]
        "generate_morning_brief_queued",
        user_id=user_id,
        generated_at=str(result.get("generated_at")),
    )

    # ── Step 4: 202 Accepted (route-level status_code) ────────────────────────
    return MorningGenerateResponse(
        status="queued",
        generated_at=str(result["generated_at"]) if result.get("generated_at") is not None else None,
    )


# ── PLAN-0066 Wave B: brief history endpoint ──────────────────────────────────


@router.get("/briefings/morning/history", response_model=BriefHistoryResponse)
async def get_morning_brief_history(
    request: Request,
    archive: BriefArchiveRepositoryDep,
    page: Annotated[int, Query(ge=0)] = 0,
    page_size: Annotated[int, Query(ge=1, le=50)] = 10,
) -> BriefHistoryResponse:
    """Return paginated history of past morning briefs for the authenticated user.

    WHY ReadUoWDep (read-only): this endpoint never writes — R27 mandates that
    read-only routes use the read replica session factory. BriefArchiveRepositoryDep
    is already wired to read_factory (see api/dependencies.py).

    WHY page_size capped at 50: prevents runaway queries; the frontend history
    panel shows at most 30 items, so 50 is a safe upper bound with room for
    future page-size expansion.

    Auth: InternalJWTMiddleware enforces X-Internal-JWT (PRD-0025). Missing
    user_id in request.state → 401 (same guard as other briefing routes).
    """
    user_id_str = _extract_user_id(request)
    tenant_id_str = _extract_tenant_id(request)
    user_id = _to_uuid(user_id_str)
    tenant_id = _to_uuid(tenant_id_str)

    records, total = await archive.get_history(
        user_id=user_id,
        tenant_id=tenant_id,
        brief_type="morning",
        page=page,
        page_size=page_size,
    )

    items = [
        BriefHistoryItem(
            id=str(r.id),
            # WHY isoformat(): generated_at is a UTC-aware datetime (R11);
            # isoformat() produces a stable string like "2026-05-08T12:00:00+00:00"
            # that the frontend can parse with new Date().
            generated_at=r.generated_at.isoformat(),
            headline=r.headline,
            lead=r.lead,
            confidence=r.confidence,
        )
        for r in records
    ]

    log.info(  # type: ignore[no-any-return]
        "morning_brief_history_fetched",
        user_id=user_id_str,
        page=page,
        page_size=page_size,
        total=total,
        returned=len(items),
    )

    return BriefHistoryResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


# ── PLAN-0066 Wave C: brief diff endpoint ─────────────────────────────────────


class DiffBulletSchema(BaseModel):
    """One bullet that appeared or disappeared between two consecutive briefs.

    WHY separate schema (not reuse DiffBullet dataclass): Pydantic models belong
    in the API layer (PLAN-0083). The DiffBullet dataclass lives in the use case
    layer and must not be serialised directly by FastAPI — that would bleed
    infrastructure knowledge into the application layer.
    """

    section_title: str
    text: str
    citations: list[dict] = []  # — Pydantic field default, not ClassVar


class BriefDiffResponse(BaseModel):
    """Response shape for GET /api/v1/briefings/morning/diff.

    status:
      "diff_available"    — two briefs found; new/removed bullets populated
      "no_diff_available" — fewer than 2 briefs; no diff can be computed

    delta_summary: human-readable one-liner for the frontend
      e.g. "3 new bullets, 1 removed since 2026-05-07"
    """

    status: str  # Literal["diff_available", "no_diff_available"] enforced by use case
    today_generated_at: str | None
    yesterday_generated_at: str | None
    new_bullets: list[DiffBulletSchema]
    removed_bullets: list[DiffBulletSchema]
    changed_sections: list[str]
    delta_summary: str


@router.get("/briefings/morning/diff", response_model=BriefDiffResponse)
async def get_morning_brief_diff(
    request: Request,
    archive: BriefArchiveRepositoryDep,
    uow: ReadUoWDep,  # — R27: read-only UoW; session lifecycle managed by DI
) -> BriefDiffResponse:
    """Return a text-normalised bullet diff between today's and yesterday's morning brief.

    - Fetches the 2 most-recent morning briefs for the authenticated user
    - Compares bullets section-by-section using lowercase+strip normalisation
    - Returns new_bullets, removed_bullets, changed_sections, and delta_summary

    WHY ReadUoWDep: this endpoint only reads (via BriefArchiveRepositoryDep which
    already uses read_factory). R27 mandates ReadUoWDep for read-only routes. The
    uow argument ensures the read session is properly lifecycle-managed even though
    the archive dep has its own session — consistent with the history endpoint pattern.

    Auth: InternalJWTMiddleware enforces X-Internal-JWT (PRD-0025). Missing
    user_id in request.state → 401.
    """
    from rag_chat.application.use_cases.brief_diff import BriefDiffUseCase

    user_id_str = _extract_user_id(request)
    tenant_id_str = _extract_tenant_id(request)
    user_id = _to_uuid(user_id_str)
    tenant_id = _to_uuid(tenant_id_str)

    # WHY instantiate use case here (not DI): BriefDiffUseCase is stateless and
    # only needs the archive port. Constructing it in the route keeps the DI wiring
    # simple — no new Depends() factory needed, consistent with how GenerateBriefingUseCase
    # is retrieved from app.state in the morning briefing route.
    uc = BriefDiffUseCase(archive=archive)
    result = await uc.execute(user_id=user_id, tenant_id=tenant_id)

    log.info(  # type: ignore[no-any-return]
        "morning_brief_diff_fetched",
        user_id=user_id_str,
        status=result.status,
        new_count=len(result.new_bullets),
        removed_count=len(result.removed_bullets),
    )

    return BriefDiffResponse(
        status=result.status,
        today_generated_at=result.today_generated_at,
        yesterday_generated_at=result.yesterday_generated_at,
        new_bullets=[
            DiffBulletSchema(
                section_title=b.section_title,
                text=b.text,
                citations=b.citations,
            )
            for b in result.new_bullets
        ],
        removed_bullets=[
            DiffBulletSchema(
                section_title=b.section_title,
                text=b.text,
                # WHY no citations on removed_bullets: removed bullets belonged to
                # yesterday's brief; their source citations are historical and may
                # no longer be relevant. The use case already strips them.
            )
            for b in result.removed_bullets
        ],
        changed_sections=result.changed_sections,
        delta_summary=result.delta_summary,
    )


# ── PLAN-0066 Wave C: brief feedback endpoints ────────────────────────────────


class BulletFeedbackRequest(BaseModel):
    """Request body for POST /api/v1/briefings/feedback/bullet.

    WHY Literal reaction: enforces the allowed set at schema validation time
    (FastAPI returns 422 automatically for any other value). This is cheaper
    than a runtime check in the use case and produces a clear error message.
    """

    brief_id: UUID
    section_idx: int = Field(ge=0, description="0-based section index")
    bullet_idx: int = Field(ge=0, description="0-based bullet index within the section")
    reaction: Literal["helpful", "unhelpful"]


class BriefFeedbackRequest(BaseModel):
    """Request body for POST /api/v1/briefings/feedback/brief.

    reaction is a star rating string "1"-"5" (not int) so the frontend can
    submit it as a JSON string without integer/string mismatch errors.
    Literal enforces the allowed values; FastAPI returns 422 for anything else.
    """

    brief_id: UUID
    reaction: Literal["1", "2", "3", "4", "5"]


class FeedbackResponse(BaseModel):
    """Response for both feedback POST endpoints.

    id         — UUIDv7 of the newly created feedback row
    created_at — ISO-8601 UTC timestamp of insertion
    """

    id: str
    created_at: str


@router.post("/briefings/feedback/bullet", status_code=201, response_model=FeedbackResponse)
async def submit_bullet_feedback(
    body: BulletFeedbackRequest,
    request: Request,
    uow: UoWDep,
) -> FeedbackResponse:
    """Record a user's helpful/unhelpful reaction to a specific morning brief bullet.

    - Validates that brief_id belongs to the authenticated user (IDOR protection)
    - Inserts a BriefFeedbackModel row with scope='bullet'
    - Returns the new feedback row's id and created_at

    WHY UoWDep (write): this is a POST endpoint that inserts a row — R27 mandates
    the write session factory. The UoW commits after the route handler returns.

    Auth: InternalJWTMiddleware enforces X-Internal-JWT (PRD-0025).
    """
    from rag_chat.application.use_cases.brief_feedback import BriefFeedbackUseCase
    from rag_chat.infrastructure.db.repositories.brief_feedback_repository import BriefFeedbackRepository

    user_id_str = _extract_user_id(request)
    user_id = _to_uuid(user_id_str)

    uc = BriefFeedbackUseCase(feedback=BriefFeedbackRepository(session=uow.session))
    try:
        fb_id, created_at = await uc.submit_bullet_feedback(
            brief_id=body.brief_id,
            user_id=user_id,
            section_idx=body.section_idx,
            bullet_idx=body.bullet_idx,
            reaction=body.reaction,
        )
    except BriefNotFoundError as exc:
        # WHY 404 (not 403): we intentionally do not distinguish "brief not found"
        # from "brief found but owned by another user" — both surface as 404 to
        # prevent IDOR enumeration attacks.
        raise HTTPException(status_code=404, detail="Brief not found") from exc

    await uow.commit()

    return FeedbackResponse(
        id=str(fb_id),
        created_at=created_at.isoformat(),
    )


@router.post("/briefings/feedback/brief", status_code=201, response_model=FeedbackResponse)
async def submit_brief_feedback(
    body: BriefFeedbackRequest,
    request: Request,
    uow: UoWDep,
) -> FeedbackResponse:
    """Record a user's star rating (1-5) for a whole morning brief.

    - Validates that brief_id belongs to the authenticated user (IDOR protection)
    - Inserts a BriefFeedbackModel row with scope='brief'
    - Returns the new feedback row's id and created_at

    WHY UoWDep (write): POST endpoint — R27 mandates write session factory.

    Auth: InternalJWTMiddleware enforces X-Internal-JWT (PRD-0025).
    """
    from rag_chat.application.use_cases.brief_feedback import BriefFeedbackUseCase
    from rag_chat.infrastructure.db.repositories.brief_feedback_repository import BriefFeedbackRepository

    user_id_str = _extract_user_id(request)
    user_id = _to_uuid(user_id_str)

    uc = BriefFeedbackUseCase(feedback=BriefFeedbackRepository(session=uow.session))
    try:
        fb_id, created_at = await uc.submit_brief_feedback(
            brief_id=body.brief_id,
            user_id=user_id,
            reaction=body.reaction,
        )
    except BriefNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Brief not found") from exc

    await uow.commit()

    return FeedbackResponse(
        id=str(fb_id),
        created_at=created_at.isoformat(),
    )


# ── PLAN-0066 Wave D: "Discuss in chat" endpoint ──────────────────────────────


class DiscussBriefRequest(BaseModel):
    """Request body for POST /api/v1/briefings/chat/discuss.

    WHY brief_type with default "morning": the endpoint currently only supports the
    morning brief (the only persisted brief type). The field is included so the
    API contract is extensible to entity-level briefs (PRD-0030) without a
    breaking schema change.
    """

    brief_type: str = "morning"


class DiscussBriefResponse(BaseModel):
    """Response for POST /api/v1/briefings/chat/discuss.

    WHY both thread_id and seeded_with_brief_id as str: the JSON API contract
    uses string UUIDs consistently (matching BriefHistoryItem.id). The frontend
    can display "Started from [brief headline]" by using seeded_with_brief_id
    to fetch the brief details from GET /api/v1/briefings/morning/history.
    """

    thread_id: str
    seeded_with_brief_id: str


@router.post("/briefings/chat/discuss", response_model=DiscussBriefResponse, status_code=201)
async def discuss_brief_in_chat(
    body: DiscussBriefRequest,
    request: Request,
    archive: BriefArchiveRepositoryDep,
    uow: UoWDep,
) -> DiscussBriefResponse:
    """Create a new chat thread pre-seeded with the user's latest brief.

    Flow:
      1. Fetch the latest brief for this user/tenant/brief_type via archive (R27: read-only).
      2. If no brief exists → 422 (caller must generate a brief first).
      3. Create a thread with seed_brief_id set → returns thread_id + brief_id.

    WHY 422 (not 404): the resource class (briefs) exists — the user simply has
    not yet generated one. 422 signals "your request is valid but pre-conditions
    are not met" which is more accurate than 404 ("resource not found").

    WHY UoWDep (write): creating a thread is a write operation (R27). The archive
    read uses BriefArchiveRepositoryDep which internally uses read_factory (R27
    compliant).

    Auth: InternalJWTMiddleware enforces X-Internal-JWT (PRD-0025). Missing
    user_id in request.state → 401 (same guard as other briefing routes).
    """
    user_id_str = _extract_user_id(request)
    tenant_id_str = _extract_tenant_id(request)
    user_id = _to_uuid(user_id_str)
    tenant_id = _to_uuid(tenant_id_str)

    # Fetch the single most-recent brief for this user+tenant+brief_type.
    # limit=1: we only need the latest; no point fetching more.
    briefs = await archive.get_latest(
        user_id=user_id,
        tenant_id=tenant_id,
        brief_type=body.brief_type,
        limit=1,
    )
    if not briefs:
        log.warning(  # type: ignore[no-any-return]
            "discuss_brief_no_brief_available",
            user_id=user_id_str,
            brief_type=body.brief_type,
        )
        raise HTTPException(
            status_code=422,
            detail=f"No {body.brief_type!r} brief available to seed chat — generate a brief first.",
        )

    brief = briefs[0]

    # Create thread seeded with this brief. title=None → the thread list shows
    # the first assistant message as the title (existing frontend behaviour).
    uc = CreateThreadUseCase()
    thread = await uc.execute(
        uow,
        user_id=user_id,
        tenant_id=tenant_id,
        title=None,
        entity_ids=[],
        seed_brief_id=brief.id,
    )

    log.info(  # type: ignore[no-any-return]
        "discuss_brief_thread_created",
        user_id=user_id_str,
        brief_id=str(brief.id),
        thread_id=str(thread.thread_id),
        brief_type=body.brief_type,
    )

    return DiscussBriefResponse(
        thread_id=str(thread.thread_id),
        seeded_with_brief_id=str(brief.id),
    )


# ── PLAN-0066 Wave F: alert pre-fill endpoint ─────────────────────────────────


class CreateAlertPrefillRequest(BaseModel):
    """Request body for POST /api/v1/briefings/{brief_id}/create-alert.

    WHY section_idx + bullet_idx (not bullet_id): BriefBullet objects do not have
    stable IDs — they are position-keyed within sections_json. This matches the
    same convention used by POST /api/v1/briefings/feedback/bullet (Wave C).

    WHY entity_id optional: the frontend may already know the entity_id from the
    BriefCitation, or may pass None and let the backend extract it from the citation
    embedded in the bullet's sections_json.
    """

    section_idx: int = Field(ge=0, description="0-based section index in sections_json")
    bullet_idx: int = Field(ge=0, description="0-based bullet index within the section")
    entity_id: str | None = None


class CreateAlertPrefillResponse(BaseModel):
    """Response for POST /api/v1/briefings/{brief_id}/create-alert.

    Provides pre-filled context for opening the AlertCreateDrawer on the frontend.

    WHY context_snippet (not full bullet text): 200 characters is enough to show
    the trader which bullet triggered the alert creation, without sending the full
    brief over the wire again.

    WHY suggested_alert_type = "NEWS": the morning brief is news-driven; the most
    natural alert for a brief entity is a NEWS alert (notify on new articles). Future
    waves can inspect bullet content and suggest EARNINGS or PRICE alerts contextually.
    """

    entity_id: str | None
    entity_name: str | None
    suggested_alert_type: str
    context_snippet: str


@router.post("/briefings/{brief_id}/create-alert", response_model=CreateAlertPrefillResponse)
async def get_alert_prefill(
    brief_id: UUID,
    body: CreateAlertPrefillRequest,
    request: Request,
    archive: BriefArchiveRepositoryDep,
) -> CreateAlertPrefillResponse:
    """Return pre-filled alert context from a specific brief bullet.

    Flow:
      1. Fetch the brief by ID from the archive.
      2. Verify the brief belongs to the authenticated user (IDOR guard).
      3. Index into sections_json[section_idx].bullets[bullet_idx] to get the bullet.
      4. Extract entity_id + entity_name from the bullet's citations if not provided.
      5. Return pre-filled context for the AlertCreateDrawer.

    WHY ReadUoWDep not needed: BriefArchiveRepositoryDep already wraps a read-only
    session (R27). The archive.get_by_id() call is the only DB operation — no write.

    WHY 404 on ownership mismatch (not 403): intentional IDOR defence — we do not
    distinguish "not found" from "found but not yours" (see submit_bullet_feedback
    for the same pattern and rationale).

    Auth: InternalJWTMiddleware enforces X-Internal-JWT (PRD-0025).
    """
    user_id_str = _extract_user_id(request)
    user_id = _to_uuid(user_id_str)

    brief = await archive.get_by_id(brief_id)
    if brief is None or brief.user_id != user_id:
        raise HTTPException(status_code=404, detail="Brief not found")

    # ── Extract bullet context from sections_json ─────────────────────────────
    # sections_json is a list[dict] stored as JSONB in the DB. Each dict has the
    # shape: {"title": str, "bullets": [{"text": str, "citations": [...]}]}.
    # IndexError / KeyError → bad section_idx/bullet_idx → 404.
    try:
        section = brief.sections_json[body.section_idx]
        bullets: list[dict] = section.get("bullets", [])
        bullet: dict = bullets[body.bullet_idx]
        # WHY [:200]: context_snippet is a preview — truncate to 200 chars to keep
        # the response small and avoid sending a full paragraph as "context".
        context_snippet: str = bullet.get("text", "")[:200]
        citations: list[dict] = bullet.get("citations", [])
    except (IndexError, KeyError, TypeError) as exc:
        # WHY 404 (not 422): if section_idx/bullet_idx are out of range, the brief
        # bullet the user referenced no longer matches what is stored — treat as
        # "resource not found" rather than "invalid request body".
        raise HTTPException(
            status_code=404,
            detail=f"Bullet at section_idx={body.section_idx}, bullet_idx={body.bullet_idx} not found in brief",
        ) from exc

    # ── Resolve entity_id + entity_name from citations if not provided ────────
    # WHY prefer body.entity_id: the frontend may pass the entity_id it already
    # knows from the BriefCitation object; use it directly if present.
    # WHY fall back to citations[0]: the first citation in the bullet is the most
    # relevant source document — its document_id is the best entity proxy available.
    resolved_entity_id: str | None = body.entity_id
    resolved_entity_name: str | None = None

    if not resolved_entity_id and citations:
        first_citation = citations[0]
        resolved_entity_id = first_citation.get("document_id")
        # WHY title as entity_name: the citation title is the article/event name,
        # not the entity name. This is a best-effort approximation until the brief
        # schema surfaces entity names explicitly in a future wave.
        resolved_entity_name = first_citation.get("title")

    log.info(  # type: ignore[no-any-return]
        "alert_prefill_fetched",
        user_id=user_id_str,
        brief_id=str(brief_id),
        section_idx=body.section_idx,
        bullet_idx=body.bullet_idx,
        entity_id=resolved_entity_id,
    )

    return CreateAlertPrefillResponse(
        entity_id=resolved_entity_id,
        entity_name=resolved_entity_name,
        suggested_alert_type="NEWS",
        context_snippet=context_snippet,
    )
