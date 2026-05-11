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

from fastapi import APIRouter, HTTPException, Query, Request, status
from fastapi.responses import Response

from portfolio.api.dependencies import ReadUoWDep, UoWDep, WatchlistCacheDep
from portfolio.api.schemas import (
    WatchlistCreateRequest,
    WatchlistMemberCreateRequest,
    WatchlistMemberListItem,
    WatchlistMemberListResponse,
    WatchlistMemberResponse,
    WatchlistRenameRequest,
    WatchlistResponse,
)
from portfolio.application.use_cases.list_watchlist_members import (
    ListWatchlistMembersQuery,
    ListWatchlistMembersUseCase,
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
    uow: ReadUoWDep,
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
    uow: ReadUoWDep,
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


@router.get(
    "/{watchlist_id}/members",
    response_model=WatchlistMemberListResponse,
)
async def list_members(
    watchlist_id: UUID,
    uow: ReadUoWDep,
    request: Request,
    # WHY Query() with bounds: standard ``limit``/``offset`` pagination shared
    # with other portfolio list endpoints. ``le=500`` caps the worst case so a
    # single request can't blow up the response payload — watchlists are
    # typically <50 members so 100 is a safe default and 500 is generous.
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> WatchlistMemberListResponse:
    """List members of a watchlist (PLAN-0046 / T-46-2-02).

    Returns 404 (via ``WatchlistNotFoundError`` from the use case) when the
    watchlist either doesn't exist or belongs to a different owner — we don't
    expose ownership information.
    """
    x_tenant_id = _extract_tenant_id(request)
    x_owner_id = _extract_owner_id(request)
    uc = ListWatchlistMembersUseCase()
    result = await uc.execute(
        ListWatchlistMembersQuery(
            watchlist_id=watchlist_id,
            owner_id=x_owner_id,
            tenant_id=x_tenant_id,
            limit=limit,
            offset=offset,
        ),
        uow,
    )
    # F-010: derive ``resolution`` from whether the denorm fields were
    # populated at add-time. NULL ticker → "pending"; the frontend renders
    # a small "resolving…" badge so the user understands the row will
    # auto-fill once the local instruments cache picks up the entity.
    return WatchlistMemberListResponse(
        members=[
            WatchlistMemberListItem(
                entity_id=m.entity_id,
                entity_type=m.entity_type,
                ticker=m.ticker,
                name=m.name,
                instrument_id=m.instrument_id,
                added_at=m.added_at,
                resolution="resolved" if m.ticker is not None else "pending",
            )
            for m in result.members
        ],
        total=result.total,
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
    # F-206 (QA iter-2): mirror the GET-list item shape so the optimistic UI
    # can render the resolution status without a follow-up fetch. ``member``
    # is the domain entity returned from the use case which already carries
    # ticker / name / instrument_id resolved at add-time (or None on cache miss).
    return WatchlistMemberResponse(
        id=member.id,
        watchlist_id=member.watchlist_id,
        entity_id=member.entity_id,
        entity_type=member.entity_type,
        added_at=member.added_at,
        ticker=member.ticker,
        name=member.name,
        instrument_id=member.instrument_id,
        # Same derivation as the GET-list endpoint — keep it server-side so
        # the contract is consistent across both routes.
        resolution="resolved" if member.ticker is not None else "pending",
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
