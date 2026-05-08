"""Narrative history and manual trigger endpoints for the Knowledge Graph service (S7).

  GET  /api/v1/entities/{entity_id}/narratives           — paginated version history
  POST /api/v1/entities/{entity_id}/narratives/generate  — manual generation trigger

Read-only GET uses ReadOnlyDbSessionDep (R27).
POST uses write session for GenerateNarrativeUseCase.

Rate-limit (POST): one manual trigger per entity+tenant+user per hour via Valkey.
BP-200 guard: uses set_nx() — NOT set(..., nx=True).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request

from knowledge_graph.api.dependencies import ReadOnlyDbSessionDep
from knowledge_graph.api.schemas_intelligence import (
    NarrativeGenerateTriggerResponse,
    NarrativeVersionListResponse,
)
from knowledge_graph.application.use_cases.generate_narrative import GenerateNarrativeUseCase
from knowledge_graph.application.use_cases.trigger_narrative_generation import (
    TriggerNarrativeGenerationUseCase,
)
from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]

router = APIRouter(prefix="/api/v1", tags=["narratives"])

_log = get_logger(__name__)  # type: ignore[no-any-return]

_RATE_LIMIT_RETRY_AFTER = 3600  # seconds — matches TriggerNarrativeGenerationUseCase TTL


@router.get(
    "/entities/{entity_id}/narratives",
    response_model=NarrativeVersionListResponse,
    summary="Paginated narrative version history for an entity",
)
async def list_narrative_versions(
    entity_id: UUID,
    session: ReadOnlyDbSessionDep,
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    cursor: str | None = Query(default=None),
) -> NarrativeVersionListResponse:
    """Return the narrative version history for an entity, newest first.

    Cursor-based pagination: supply ``cursor`` from the previous response's
    ``next_cursor`` field.  ``next_cursor=null`` means there are no more pages.

    - 200: list (possibly empty) with optional next_cursor
    - 422: invalid entity_id UUID

    Uses ReadOnlyDbSessionDep (R27 — read-only).
    """
    # Deferred infra import: R25 compliance — never import infra at module level
    from knowledge_graph.application.use_cases.list_narrative_versions import (
        ListNarrativeVersionsUseCase,
    )
    from knowledge_graph.infrastructure.intelligence_db.repositories.narrative_repository import (
        NarrativeRepository,
    )

    narrative_repo = NarrativeRepository(session)
    uc = ListNarrativeVersionsUseCase(narrative_repo)

    # Extract tenant_id from JWT claims (optional)
    tenant_id: UUID | None = None
    jwt_claims = getattr(request.state, "jwt_claims", {}) or {}
    raw_tenant = jwt_claims.get("tenant_id")
    if raw_tenant:
        try:
            tenant_id = UUID(str(raw_tenant))
        except (ValueError, AttributeError):
            tenant_id = None

    return await uc.execute(
        entity_id=entity_id,
        tenant_id=tenant_id,
        limit=limit,
        cursor=cursor,
    )


@router.post(
    "/entities/{entity_id}/narratives/generate",
    status_code=202,
    response_model=NarrativeGenerateTriggerResponse,
    summary="Manually trigger narrative generation for an entity",
)
async def trigger_narrative_generation(
    entity_id: UUID,
    request: Request,
) -> NarrativeGenerateTriggerResponse:
    """Queue a manual narrative generation for an entity.

    Rate-limited to one request per entity+tenant+user per hour.

    - 202: generation queued (fire-and-forget background task)
    - 429: rate limit hit — ``Retry-After: 3600`` header included
    - 422: invalid entity_id UUID

    Uses write session (R27 — write use case).
    """
    # Identify caller for rate-limit key
    jwt_claims = getattr(request.state, "jwt_claims", {}) or {}
    user_id: str = str(jwt_claims.get("sub") or jwt_claims.get("user_id") or "anonymous")
    tenant_id: UUID | None = None
    raw_tenant = jwt_claims.get("tenant_id")
    if raw_tenant:
        try:
            tenant_id = UUID(str(raw_tenant))
        except (ValueError, AttributeError):
            tenant_id = None

    # Build Valkey client from app state
    try:
        valkey_url: str = request.app.state.settings.valkey_url
        valkey: ValkeyClient | None = ValkeyClient(url=valkey_url)
    except Exception as exc:  # pragma: no cover — Valkey unavailable (dev/test)
        _log.warning("narrative_trigger_valkey_unavailable", error=str(exc))
        # Fail open — allow the trigger but skip rate limiting
        valkey = None

    # Build GenerateNarrativeUseCase using the app session factories
    # Use getattr to handle tests where lifespan has not run (factories not set).
    settings = request.app.state.settings
    generate_uc = GenerateNarrativeUseCase(
        write_session_factory=getattr(request.app.state, "write_factory", None),  # type: ignore[arg-type]
        read_session_factory=getattr(request.app.state, "read_factory", None),
        narrative_llm_model_id=getattr(settings, "narrative_llm_model_id", "template-v1"),
    )

    if valkey is not None:
        uc = TriggerNarrativeGenerationUseCase(valkey=valkey, generate_uc=generate_uc)
        allowed = await uc.execute(
            entity_id=entity_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit: one manual generation per hour. Retry after {_RATE_LIMIT_RETRY_AFTER}s.",
                headers={"Retry-After": str(_RATE_LIMIT_RETRY_AFTER)},
            )
    else:
        # Valkey unavailable — fire directly without rate limiting
        import asyncio

        from knowledge_graph.domain.narrative import NarrativeGenerationReason

        asyncio.create_task(  # noqa: RUF006 — intentional fire-and-forget
            generate_uc.execute(
                entity_id=entity_id,
                tenant_id=tenant_id,
                reason=NarrativeGenerationReason.MANUAL_TRIGGER.value,
            )
        )

    return NarrativeGenerateTriggerResponse(
        message="Narrative generation queued",
        entity_id=str(entity_id),
    )
