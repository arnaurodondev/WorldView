"""Watchlist API routes."""

# NOTE(Q1): The reverse-index endpoint GET /watchlists/reverse/{entity_id} is intentionally
# omitted. Per gap analysis open question Q1, Option C was selected: the alert service (S10)
# consumes portfolio.watchlist.updated.v1 events directly and maintains its own local
# entity→user_ids index. This avoids exposing cross-user data via HTTP and aligns with the
# event-driven architecture.

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Header, status
from fastapi.responses import Response

from portfolio.api.dependencies import UoWDep, WatchlistCacheDep
from portfolio.api.schemas import (
    WatchlistCreateRequest,
    WatchlistMemberCreateRequest,
    WatchlistMemberResponse,
    WatchlistResponse,
)
from portfolio.application.use_cases.watchlist import (
    AddWatchlistMemberCommand,
    AddWatchlistMemberUseCase,
    CreateWatchlistCommand,
    CreateWatchlistUseCase,
    DeleteWatchlistCommand,
    DeleteWatchlistUseCase,
    GetWatchlistUseCase,
    ListWatchlistsUseCase,
    RemoveWatchlistMemberCommand,
    RemoveWatchlistMemberUseCase,
)

router = APIRouter(tags=["watchlists"])


@router.post("", response_model=WatchlistResponse, status_code=status.HTTP_201_CREATED)
async def create_watchlist(
    body: WatchlistCreateRequest,
    uow: UoWDep,
    x_tenant_id: UUID = Header(..., alias="X-Tenant-ID"),
    x_owner_id: UUID = Header(..., alias="X-Owner-ID"),
) -> WatchlistResponse:
    uc = CreateWatchlistUseCase()
    wl = await uc.execute(
        CreateWatchlistCommand(tenant_id=x_tenant_id, user_id=x_owner_id, name=body.name),
        uow,
    )
    return WatchlistResponse(
        id=wl.id,
        tenant_id=wl.tenant_id,
        user_id=wl.user_id,
        name=wl.name,
        status=str(wl.status),
        created_at=wl.created_at,
    )


@router.get("", response_model=list[WatchlistResponse])
async def list_watchlists(
    uow: UoWDep,
    x_tenant_id: UUID = Header(..., alias="X-Tenant-ID"),
    x_owner_id: UUID = Header(..., alias="X-Owner-ID"),
) -> list[WatchlistResponse]:
    uc = ListWatchlistsUseCase()
    watchlists = await uc.execute(x_owner_id, x_tenant_id, uow)
    return [
        WatchlistResponse(
            id=wl.id,
            tenant_id=wl.tenant_id,
            user_id=wl.user_id,
            name=wl.name,
            status=str(wl.status),
            created_at=wl.created_at,
        )
        for wl in watchlists
    ]


@router.get("/{watchlist_id}", response_model=WatchlistResponse)
async def get_watchlist(
    watchlist_id: UUID,
    uow: UoWDep,
    x_tenant_id: UUID = Header(..., alias="X-Tenant-ID"),
    x_owner_id: UUID = Header(..., alias="X-Owner-ID"),
) -> WatchlistResponse:
    uc = GetWatchlistUseCase()
    wl = await uc.execute(watchlist_id, x_owner_id, x_tenant_id, uow)
    return WatchlistResponse(
        id=wl.id,
        tenant_id=wl.tenant_id,
        user_id=wl.user_id,
        name=wl.name,
        status=str(wl.status),
        created_at=wl.created_at,
    )


@router.delete("/{watchlist_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response, response_model=None)
async def delete_watchlist(
    watchlist_id: UUID,
    uow: UoWDep,
    x_tenant_id: UUID = Header(..., alias="X-Tenant-ID"),
    x_owner_id: UUID = Header(..., alias="X-Owner-ID"),
) -> None:
    uc = DeleteWatchlistUseCase()
    await uc.execute(
        DeleteWatchlistCommand(watchlist_id=watchlist_id, owner_id=x_owner_id, tenant_id=x_tenant_id),
        uow,
    )


@router.post(
    "/{watchlist_id}/members",
    response_model=WatchlistMemberResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_member(
    watchlist_id: UUID,
    body: WatchlistMemberCreateRequest,
    uow: UoWDep,
    cache: WatchlistCacheDep,
    x_tenant_id: UUID = Header(..., alias="X-Tenant-ID"),
    x_owner_id: UUID = Header(..., alias="X-Owner-ID"),
) -> WatchlistMemberResponse:
    uc = AddWatchlistMemberUseCase()
    member = await uc.execute(
        AddWatchlistMemberCommand(
            tenant_id=x_tenant_id,
            watchlist_id=watchlist_id,
            owner_id=x_owner_id,
            entity_id=body.entity_id,
            entity_type=body.entity_type,
        ),
        uow,
        cache,
    )
    return WatchlistMemberResponse(
        id=member.id,
        watchlist_id=member.watchlist_id,
        entity_id=member.entity_id,
        entity_type=member.entity_type,
        added_at=member.added_at,
    )


@router.delete(
    "/{watchlist_id}/members/{entity_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    response_model=None,
)
async def remove_member(
    watchlist_id: UUID,
    entity_id: UUID,
    uow: UoWDep,
    cache: WatchlistCacheDep,
    x_tenant_id: UUID = Header(..., alias="X-Tenant-ID"),
    x_owner_id: UUID = Header(..., alias="X-Owner-ID"),
) -> None:
    uc = RemoveWatchlistMemberUseCase()
    await uc.execute(
        RemoveWatchlistMemberCommand(
            tenant_id=x_tenant_id,
            watchlist_id=watchlist_id,
            owner_id=x_owner_id,
            entity_id=entity_id,
        ),
        uow,
        cache,
    )
