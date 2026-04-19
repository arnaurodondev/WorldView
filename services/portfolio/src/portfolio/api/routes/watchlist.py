"""Watchlist API routes.

Auth: InternalJWTMiddleware sets request.state.tenant_id / user_id from the
verified RS256 JWT. Routes read these values from request.state, never from
raw headers (PRD-0025, F-CRIT-001 remediation).
"""

# NOTE(Q1): The reverse-index endpoint GET /watchlists/reverse/{entity_id} is intentionally
# omitted. Per gap analysis open question Q1, Option C was selected: the alert service (S10)
# consumes portfolio.watchlist.updated.v1 events directly and maintains its own local
# entity→user_ids index. This avoids exposing cross-user data via HTTP and aligns with the
# event-driven architecture.

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import Response

from portfolio.api.dependencies import UoWDep, WatchlistCacheDep
from portfolio.api.schemas import (
    WatchlistCreateRequest,
    WatchlistMemberCreateRequest,
    WatchlistMemberResponse,
    WatchlistRenameRequest,
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
    RenameWatchlistCommand,
    RenameWatchlistUseCase,
)

router = APIRouter(tags=["watchlists"])


def _extract_tenant_id(request: Request) -> UUID:
    """Read tenant_id from request.state set by InternalJWTMiddleware."""
    raw = getattr(request.state, "tenant_id", None)
    if not raw:
        raise HTTPException(status_code=401, detail="Missing tenant_id in JWT")
    return UUID(str(raw))


def _extract_owner_id(request: Request) -> UUID:
    """Read user_id (owner) from request.state set by InternalJWTMiddleware."""
    raw = getattr(request.state, "user_id", None)
    if not raw:
        raise HTTPException(status_code=401, detail="Missing user_id in JWT")
    return UUID(str(raw))


@router.post("", response_model=WatchlistResponse, status_code=status.HTTP_201_CREATED)
async def create_watchlist(
    body: WatchlistCreateRequest,
    uow: UoWDep,
    request: Request,
) -> WatchlistResponse:
    x_tenant_id = _extract_tenant_id(request)
    x_owner_id = _extract_owner_id(request)
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
    request: Request,
) -> list[WatchlistResponse]:
    x_tenant_id = _extract_tenant_id(request)
    x_owner_id = _extract_owner_id(request)
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
    request: Request,
) -> WatchlistResponse:
    x_tenant_id = _extract_tenant_id(request)
    x_owner_id = _extract_owner_id(request)
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
    request: Request,
) -> None:
    x_tenant_id = _extract_tenant_id(request)
    x_owner_id = _extract_owner_id(request)
    uc = DeleteWatchlistUseCase()
    await uc.execute(
        DeleteWatchlistCommand(watchlist_id=watchlist_id, owner_id=x_owner_id, tenant_id=x_tenant_id),
        uow,
    )


@router.patch("/{watchlist_id}", response_model=WatchlistResponse)
async def rename_watchlist(
    watchlist_id: UUID,
    body: WatchlistRenameRequest,
    uow: UoWDep,
    request: Request,
) -> WatchlistResponse:
    x_tenant_id = _extract_tenant_id(request)
    x_owner_id = _extract_owner_id(request)
    uc = RenameWatchlistUseCase()
    wl = await uc.execute(
        RenameWatchlistCommand(
            watchlist_id=watchlist_id,
            owner_id=x_owner_id,
            tenant_id=x_tenant_id,
            new_name=body.name,
        ),
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
    request: Request,
) -> WatchlistMemberResponse:
    x_tenant_id = _extract_tenant_id(request)
    x_owner_id = _extract_owner_id(request)
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
    request: Request,
) -> None:
    x_tenant_id = _extract_tenant_id(request)
    x_owner_id = _extract_owner_id(request)
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
