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
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import structlog
from fastapi import APIRouter, HTTPException, Request

from rag_chat.api.schemas import PublicBriefingResponse
from rag_chat.domain.errors import EntityNotFoundError, ProviderUnavailableError, RateLimitExceededError

router = APIRouter(prefix="/api/v1", tags=["briefings"])
log = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# Cache TTL: 24 hours — briefings are expensive (LLM call) and stable within a day.
_CACHE_TTL = 86400


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
        # PLAN-0049 T-A-1-04: pass through structured fields. Both default to
        # None / [] when the use case couldn't parse them — frontend then falls
        # back to MarkdownContent over narrative (graceful degradation).
        # Truncate to max_length=240 to guard against LLM over-generating.
        "headline": (result.get("headline") or "")[:240] or None,
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
        # PLAN-0049 T-A-1-04: structured render fields for the frontend.
        # Truncate to max_length=240 to guard against LLM over-generating.
        "headline": (result.get("headline") or "")[:240] or None,
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
