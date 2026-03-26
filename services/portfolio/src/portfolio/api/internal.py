"""Internal API endpoints for service-to-service communication (S10 -> S1).

These endpoints are NOT exposed through S9 API Gateway.
Auth: X-Internal-Token header validated against INTERNAL_SERVICE_TOKEN env var.
PRD reference: §6.2.7.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException

from portfolio.api.dependencies import InternalAuthDep, UoWDep
from portfolio.api.schemas import (
    BatchEntityLookupRequest,
    BatchEntityLookupResponse,
    WatcherInfo,
    WatchersByEntityResponse,
    WatchlistEntitiesResponse,
)

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
