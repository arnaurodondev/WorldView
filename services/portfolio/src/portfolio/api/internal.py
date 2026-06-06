"""Internal API endpoints for service-to-service communication (S10 -> S1).

These endpoints are NOT exposed through S9 API Gateway.
Auth: InternalJWTMiddleware validates X-Internal-JWT (RS256) on every request.
PRD reference: §6.2.7; auth updated by PRD-0025 Wave C.

F-CRIT-002: tenant_id and user_id are now read from request.state set by
InternalJWTMiddleware, not from query strings or headers.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request

from observability.logging import get_logger  # type: ignore[import-untyped]  # type: ignore[import-untyped]
from portfolio.api.dependencies import ReadUoWDep, UoWDep
from portfolio.api.schemas import (
    BatchEntityLookupRequest,
    BatchEntityLookupResponse,
    HoldingContextItem,
    PortfolioContextResponse,
    UserInternalResponse,
    WatcherInfo,
    WatchersByEntityResponse,
    WatchlistContextItem,
    WatchlistEntitiesResponse,
)
from portfolio.application.use_cases.portfolio_context import PortfolioContextUseCase
from portfolio.application.use_cases.user import GetUserUseCase
from portfolio.domain.errors import EntityNotFoundError

logger = get_logger(__name__)

# PLAN-0094 follow-up: allow-list of service-token callers that may read any
# user's portfolio context. Each entry corresponds to a ``service_name`` minted
# by S9's POST /internal/v1/service-token (matched in S9's _ALLOWED_SERVICE_NAMES).
# Defence-in-depth: keep this list short and explicit; an attacker who obtains
# a service-token still cannot read user data unless the calling service_name
# is on this list.
_SERVICE_BRIEF_ALLOWED: frozenset[str] = frozenset(
    {
        "rag-chat-brief-scheduler",
    },
)

internal_router = APIRouter(prefix="/internal/v1", tags=["internal"])


@internal_router.get("/health")
async def internal_health() -> dict[str, str]:
    """Health check for internal service readiness verification (no auth)."""
    return {"status": "healthy"}


@internal_router.get("/watchlists/by-entity/{entity_id}")
async def get_watchers_by_entity(
    entity_id: UUID,
    uow: UoWDep,
) -> WatchersByEntityResponse:
    """Return all users watching a specific entity."""
    dtos = await uow.watchlist_members.get_watchers_by_entity(entity_id)
    watchers = [WatcherInfo(user_id=d.user_id, watchlist_id=d.watchlist_id) for d in dtos]
    return WatchersByEntityResponse(entity_id=entity_id, watchers=watchers)


@internal_router.post("/watchlists/by-entities")
async def get_watchers_by_entities(
    body: BatchEntityLookupRequest,
    uow: UoWDep,
) -> BatchEntityLookupResponse:
    """Batch lookup: given entity_ids, return watcher map."""
    if len(body.entity_ids) > 100:
        raise HTTPException(status_code=400, detail="Maximum 100 entity_ids per request")
    if not body.entity_ids:
        raise HTTPException(status_code=400, detail="entity_ids must not be empty")

    dto_map = await uow.watchlist_members.get_watchers_by_entities(body.entity_ids)
    results: dict[str, list[WatcherInfo]] = {}
    for eid in body.entity_ids:
        dtos = dto_map.get(eid, [])
        results[str(eid)] = [WatcherInfo(user_id=d.user_id, watchlist_id=d.watchlist_id) for d in dtos]
    return BatchEntityLookupResponse(results=results)


@internal_router.get("/watchlists/{watchlist_id}/entities")
async def get_watchlist_entities(
    watchlist_id: UUID,
    uow: UoWDep,
) -> WatchlistEntitiesResponse:
    """List all entity_ids in a specific watchlist."""
    members = await uow.watchlist_members.list_by_watchlist(watchlist_id)
    entity_ids = [m.entity_id for m in members]
    return WatchlistEntitiesResponse(watchlist_id=watchlist_id, entity_ids=entity_ids)


@internal_router.get("/users/{user_id}/portfolio/context", response_model=PortfolioContextResponse)
async def get_portfolio_context(
    user_id: UUID,
    uow: ReadUoWDep,
    request: Request,
) -> PortfolioContextResponse:
    """Return portfolio context (holdings + watchlist) for S8 PORTFOLIO-intent queries.

    Auth: InternalJWTMiddleware (RS256) sets request.state.user_id / tenant_id.
    Ownership: JWT user_id must match the path user_id (F-CRIT-002).
    """
    jwt_user_id = getattr(request.state, "user_id", None)
    jwt_tenant_id = getattr(request.state, "tenant_id", None)
    jwt_role = getattr(request.state, "role", "") or ""
    jwt_service_name = getattr(request.state, "service_name", "") or ""

    # PLAN-0094 follow-up: service-token callers from the allow-list bypass the
    # user-match check and look up the real tenant_id by user_id, because the
    # service token carries a nil tenant_id claim.
    is_system_caller = jwt_role == "system" and jwt_service_name in _SERVICE_BRIEF_ALLOWED

    if not is_system_caller:
        # Existing user-token path: enforce sub == path.user_id and JWT tenant.
        if jwt_user_id is None or str(jwt_user_id) != str(user_id):
            raise HTTPException(status_code=403, detail="JWT user_id must match path user_id")
        if not jwt_tenant_id:
            raise HTTPException(status_code=401, detail="Missing tenant_id in JWT")
        tenant_id = UUID(str(jwt_tenant_id))
    else:
        # System-caller path: look up the real tenant_id for this user. The
        # service token has no real tenant claim (nil UUID), so we read the
        # user's tenant from the users table. If the user doesn't exist we 404,
        # matching the user-token behaviour for an unknown user_id.
        user_entity = await uow.users.find_by_id_any_tenant(user_id)
        if user_entity is None:
            raise HTTPException(status_code=404, detail="User not found")
        tenant_id = user_entity.tenant_id
        # Audit log so ops can spot unexpected service-caller access.
        logger.info(
            "portfolio_context_service_caller",
            service_name=jwt_service_name,
            path_user_id=str(user_id),
            resolved_tenant_id=str(tenant_id),
        )

    uc = PortfolioContextUseCase()
    try:
        dto = await uc.execute(user_id, tenant_id, uow)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return PortfolioContextResponse(
        user_id=dto.user_id,
        tenant_id=dto.tenant_id,
        holdings=[
            HoldingContextItem(
                ticker=h.ticker,
                entity_id=h.entity_id,
                canonical_name=h.canonical_name,
                quantity=h.quantity,
                current_weight=h.current_weight,
            )
            for h in dto.holdings
        ],
        watchlist=[
            WatchlistContextItem(
                ticker=w.ticker,
                entity_id=w.entity_id,
                canonical_name=w.canonical_name,
            )
            for w in dto.watchlist
        ],
        total_positions=dto.total_positions,
    )


@internal_router.get("/users/{user_id}", response_model=UserInternalResponse)
async def get_user_for_digest(
    user_id: UUID,
    uow: ReadUoWDep,
    request: Request,
) -> UserInternalResponse:
    """Return user email for S10 email digest delivery (PRD-0016 §6.2).

    Used by S10 EmailScheduler when ``email_preferences.email_address`` is null.
    Auth: InternalJWTMiddleware (RS256) sets request.state.tenant_id (F-CRIT-002).
    Returns 404 if the user is not found in the tenant.
    """
    raw_tenant_id = getattr(request.state, "tenant_id", None)
    if not raw_tenant_id:
        raise HTTPException(status_code=401, detail="Missing tenant_id in JWT")
    tenant_id = UUID(str(raw_tenant_id))

    uc = GetUserUseCase()
    try:
        user = await uc.execute(user_id, tenant_id, uow)
    except EntityNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return UserInternalResponse(
        user_id=user.id,
        tenant_id=user.tenant_id,
        email_address=user.email,
        username=user.email,  # S1 uses email as username; extend when username field added
        created_at=user.created_at,
    )
