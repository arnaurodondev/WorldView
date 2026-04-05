"""Internal API endpoints for service-to-service communication (S10 -> S1).

These endpoints are NOT exposed through S9 API Gateway.
Auth: X-Internal-Token header validated against INTERNAL_SERVICE_TOKEN env var.
PRD reference: §6.2.7.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header, HTTPException

from portfolio.api.dependencies import InternalAuthDep, ReadUoWDep, UoWDep
from portfolio.api.schemas import (
    BatchEntityLookupRequest,
    BatchEntityLookupResponse,
    HoldingContextItem,
    PortfolioContextResponse,
    WatcherInfo,
    WatchersByEntityResponse,
    WatchlistContextItem,
    WatchlistEntitiesResponse,
)
from portfolio.application.use_cases.portfolio_context import PortfolioContextUseCase
from portfolio.domain.errors import UserNotFoundError

internal_router = APIRouter(prefix="/internal/v1", tags=["internal"])


@internal_router.get("/health")
async def internal_health() -> dict[str, str]:
    """Health check for internal service readiness verification (no auth)."""
    return {"status": "healthy"}


@internal_router.get("/watchlists/by-entity/{entity_id}")
async def get_watchers_by_entity(
    entity_id: UUID,
    _auth: InternalAuthDep,
    uow: UoWDep,
) -> WatchersByEntityResponse:
    """Return all users watching a specific entity."""
    dtos = await uow.watchlist_members.get_watchers_by_entity(entity_id)
    watchers = [WatcherInfo(user_id=d.user_id, watchlist_id=d.watchlist_id) for d in dtos]
    return WatchersByEntityResponse(entity_id=entity_id, watchers=watchers)


@internal_router.post("/watchlists/by-entities")
async def get_watchers_by_entities(
    body: BatchEntityLookupRequest,
    _auth: InternalAuthDep,
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
    _auth: InternalAuthDep,
    uow: UoWDep,
) -> WatchlistEntitiesResponse:
    """List all entity_ids in a specific watchlist."""
    members = await uow.watchlist_members.list_by_watchlist(watchlist_id)
    entity_ids = [m.entity_id for m in members]
    return WatchlistEntitiesResponse(watchlist_id=watchlist_id, entity_ids=entity_ids)


@internal_router.get("/users/{user_id}/portfolio/context", response_model=PortfolioContextResponse)
async def get_portfolio_context(
    user_id: UUID,
    _auth: InternalAuthDep,
    uow: ReadUoWDep,
    tenant_id: UUID,
    x_user_id: UUID | None = Header(None),
) -> PortfolioContextResponse:
    """Return portfolio context (holdings + watchlist) for S8 PORTFOLIO-intent queries.

    Auth: X-Internal-Token (service-to-service).
    Ownership: X-User-Id header must match the path user_id.
    """
    if x_user_id is None or x_user_id != user_id:
        raise HTTPException(status_code=403, detail="X-User-Id must match path user_id")

    uc = PortfolioContextUseCase()
    try:
        dto = await uc.execute(user_id, tenant_id, uow)
    except UserNotFoundError as exc:
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
