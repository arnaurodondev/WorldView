"""Manual entity refresh trigger endpoint for the Knowledge Graph service (S7).

  POST /api/v1/entities/{entity_id}/refresh — REQ-003 / TASK-W0-06

Body::

    {"refresh_type": "description" | "narrative" | "all"}   (default "all")

Rate-limit (BP-200): one trigger per entity+tenant+user per hour via Valkey
``set_nx`` + ``ex=3600`` — same pattern as ``narratives.py:111``.

R25: this router never imports from ``knowledge_graph.infrastructure`` — the
``OutboxRepository`` class is resolved from ``app.state`` at request time
(set by the infrastructure startup layer).

R27: uses both read and write session factories from app.state (write is
needed for the outbox INSERT; read for the entity existence check).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from knowledge_graph.application.use_cases.trigger_entity_refresh import (
    EntityNotFoundError,
    InvalidRefreshTypeError,
    TriggerEntityRefreshUseCase,
)
from messaging.valkey.client import ValkeyClient  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]

router = APIRouter(prefix="/api/v1", tags=["entities", "refresh"])

_log = get_logger(__name__)  # type: ignore[no-any-return]

_RATE_LIMIT_RETRY_AFTER = 3600  # seconds — must equal TriggerEntityRefreshUseCase TTL


class EntityRefreshRequest(BaseModel):
    """Request body for POST /api/v1/entities/{entity_id}/refresh.

    Pydantic validation guarantees ``refresh_type`` is non-empty.  Allowed-set
    validation lives in the use case (``ALLOWED_REFRESH_TYPES``) so the API
    layer never duplicates business validation rules.
    """

    refresh_type: str = Field(default="all", description="description | narrative | all")


class EntityRefreshTriggerResponse(BaseModel):
    """202-response body."""

    job_id: str
    entity_id: str
    refresh_type: str
    message: str = "Entity refresh queued"


@router.post(
    "/entities/{entity_id}/refresh",
    status_code=202,
    response_model=EntityRefreshTriggerResponse,
    summary="Manually trigger entity re-enrichment (description / narrative / all)",
)
async def trigger_entity_refresh(
    entity_id: UUID,
    request: Request,
    body: EntityRefreshRequest | None = None,
) -> EntityRefreshTriggerResponse:
    """Queue a manual entity refresh.

    - 202: refresh queued (outbox event persisted; S6 consumer will process).
    - 404: entity_id does not exist in canonical_entities.
    - 422: invalid refresh_type or malformed UUID.
    - 429: rate limit hit — ``Retry-After: 3600`` header included.

    BP-200 guard: uses ``set_nx()`` in the use case — never ``set(..., nx=True)``.
    """
    # Body is optional — when the client omits it we default to refresh_type=all.
    payload = body or EntityRefreshRequest()

    # Identify caller for rate-limit key (jwt_claims is populated by InternalJWTMiddleware).
    jwt_claims = getattr(request.state, "jwt_claims", {}) or {}
    user_id: str = str(jwt_claims.get("sub") or jwt_claims.get("user_id") or "anonymous")
    tenant_id: UUID | None = None
    raw_tenant = jwt_claims.get("tenant_id")
    if raw_tenant:
        try:
            tenant_id = UUID(str(raw_tenant))
        except (ValueError, AttributeError):
            tenant_id = None

    # Build Valkey client from app state.  Failures here disable rate-limiting
    # (fail-open) — same posture as narratives.py:142 to keep dev/test working
    # when Valkey is unreachable.
    valkey: ValkeyClient | None
    try:
        valkey_url: str = request.app.state.settings.valkey_url
        valkey = ValkeyClient(url=valkey_url)
    except Exception as exc:  # pragma: no cover — Valkey unavailable
        _log.warning("entity_refresh_valkey_unavailable", error=str(exc))
        valkey = None

    # Resolve outbox repo class from app.state (R25).
    outbox_repo_class: Any = getattr(request.app.state, "outbox_repo_class", None)
    write_factory = getattr(request.app.state, "write_factory", None)
    read_factory = getattr(request.app.state, "read_factory", None)

    if outbox_repo_class is None or write_factory is None or read_factory is None:
        # Misconfigured app — fail loud rather than swallow.
        _log.error(
            "entity_refresh_misconfigured",
            has_outbox=outbox_repo_class is not None,
            has_write=write_factory is not None,
            has_read=read_factory is not None,
        )
        raise HTTPException(status_code=500, detail="Service not fully initialised")

    uc = TriggerEntityRefreshUseCase(
        valkey=valkey,
        write_session_factory=write_factory,
        read_session_factory=read_factory,
        outbox_repo_class=outbox_repo_class,
    )

    try:
        result = await uc.execute(
            entity_id=entity_id,
            tenant_id=tenant_id,
            user_id=user_id,
            refresh_type=payload.refresh_type,
        )
    except InvalidRefreshTypeError as exc:
        # 422 — invalid enum value; same response shape as Pydantic validation.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    if result is None:
        # Rate limit hit — match narratives.py response shape (BP-200 pattern).
        raise HTTPException(
            status_code=429,
            detail=("Rate limit: one entity refresh per hour. " f"Retry after {_RATE_LIMIT_RETRY_AFTER}s."),
            headers={"Retry-After": str(_RATE_LIMIT_RETRY_AFTER)},
        )

    return EntityRefreshTriggerResponse(
        job_id=str(result.job_id),
        entity_id=str(result.entity_id),
        refresh_type=result.refresh_type,
    )
