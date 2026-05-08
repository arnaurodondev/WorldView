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

    # ── Check Valkey cache ────────────────────────────────────────────────────
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
                return resp
        except Exception as e:
            # Cache miss or deserialization failure — proceed to generation.
            log.warning("briefing_cache_read_failed", error=str(e), key=cache_key)  # type: ignore[no-any-return]

    # ── Generate briefing via use case ────────────────────────────────────────
    # WHY execute_public_morning() not execute(): the morning route must use the
    # portfolio-aware path that invokes BriefingContextGatherer (S1/S3/S5/S6/S7),
    # renders the MORNING_BRIEFING prompt, and returns content/risk_summary/citations.
    # Calling execute() here would use the email brief path with no frontend context.
    uc = _get_briefing_uc(request)
    try:
        result = await uc.execute_public_morning(
            user_id=user_id,
            tenant_id=tenant_id,
            internal_jwt=request.headers.get("X-Internal-JWT"),
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
    }

    log.info(  # type: ignore[no-any-return]
        "morning_briefing_route_complete",
        user_id=user_id,
        confidence=confidence,
        lead_present=lead is not None,
    )

    resp = PublicBriefingResponse(**response_data)

    # ── Write to cache ────────────────────────────────────────────────────────
    # WHY model_dump_json: avoids json.dumps(..., default=str) which stringifies
    # Pydantic models (BriefSection, BriefBullet) to repr strings that cannot be
    # re-deserialized on cache read (BP-319).
    if valkey is not None:
        try:
            await valkey.set(cache_key, resp.model_dump_json(), ex=_CACHE_TTL)
        except Exception as e:
            log.warning("briefing_cache_write_failed", error=str(e), key=cache_key)  # type: ignore[no-any-return]

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
    # WHY v2: PLAN-0062-W4 cache key bump — see morning briefing comment above.
    cache_key = f"briefing:instrument:v2:{entity_id}:{user_id}"

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

    user_id_str = _extract_user_id(request)
    user_id = _to_uuid(user_id_str)

    uc = BriefFeedbackUseCase(session=uow.session)
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

    user_id_str = _extract_user_id(request)
    user_id = _to_uuid(user_id_str)

    uc = BriefFeedbackUseCase(session=uow.session)
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
