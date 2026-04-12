"""Brokerage connections API routes (PRD-0022 §6.2)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, status

from portfolio.api.dependencies import ReadUoWDep, UoWDep
from portfolio.api.schemas import (
    ActivateBrokerageConnectionResponse,
    BrokerageConnectionResponse,
    DisconnectBrokerageConnectionResponse,
    GetSyncErrorsResponse,
    InitiateBrokerageConnectionRequest,
    InitiateBrokerageConnectionResponse,
    ListBrokerageConnectionsResponse,
    SyncErrorResponse,
)
from portfolio.application.use_cases.brokerage_connection import (
    ActivateBrokerageConnectionCommand,
    ActivateBrokerageConnectionUseCase,
    DisconnectBrokerageConnectionCommand,
    DisconnectBrokerageConnectionUseCase,
    GetSyncErrorsQuery,
    GetSyncErrorsUseCase,
    InitiateBrokerageConnectionCommand,
    InitiateBrokerageConnectionUseCase,
    ListBrokerageConnectionsQuery,
    ListBrokerageConnectionsUseCase,
)

router = APIRouter(tags=["brokerage-connections"])


def _require_user_headers(request: Request) -> tuple[UUID, UUID]:
    """Extract and validate X-User-Id / X-Tenant-Id headers (injected by S9)."""
    user_id_str = request.headers.get("X-User-Id")
    tenant_id_str = request.headers.get("X-Tenant-Id")
    if not user_id_str or not tenant_id_str:
        raise HTTPException(status_code=401, detail="Missing auth headers")
    return UUID(user_id_str), UUID(tenant_id_str)


@router.post(
    "/brokerage-connections",
    response_model=InitiateBrokerageConnectionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def initiate_brokerage_connection(
    body: InitiateBrokerageConnectionRequest,
    uow: UoWDep,
    request: Request,
) -> InitiateBrokerageConnectionResponse:
    """Register a SnapTrade user and create a PENDING brokerage connection."""
    user_id, tenant_id = _require_user_headers(request)
    uc = InitiateBrokerageConnectionUseCase()
    result = await uc.execute(
        cmd=InitiateBrokerageConnectionCommand(
            tenant_id=tenant_id,
            user_id=user_id,
            portfolio_id=body.portfolio_id,
            snaptrade_tos_accepted=body.snaptrade_tos_accepted,
        ),
        uow=uow,
        brokerage_client=request.app.state.brokerage_client,
        snaptrade_redirect_uri=request.app.state.settings.snaptrade_redirect_uri,
    )
    return InitiateBrokerageConnectionResponse(
        connection_id=result.connection_id,
        redirect_uri=result.redirect_uri,
    )


@router.get(
    "/brokerage-connections",
    response_model=ListBrokerageConnectionsResponse,
    status_code=status.HTTP_200_OK,
)
async def list_brokerage_connections(
    uow: ReadUoWDep,
    request: Request,
    portfolio_id: UUID | None = Query(default=None),
) -> ListBrokerageConnectionsResponse:
    """List brokerage connections for the authenticated user (read-only, R27)."""
    user_id, tenant_id = _require_user_headers(request)
    uc = ListBrokerageConnectionsUseCase()
    result = await uc.execute(
        query=ListBrokerageConnectionsQuery(
            user_id=user_id,
            tenant_id=tenant_id,
            portfolio_id=portfolio_id,
        ),
        uow=uow,
    )
    return ListBrokerageConnectionsResponse(
        items=[
            BrokerageConnectionResponse(
                connection_id=c.id,
                portfolio_id=c.portfolio_id,
                brokerage_name=c.brokerage_name,
                status=str(c.status.value),
                last_synced_at=c.last_synced_at,
                created_at=c.created_at,
            )
            for c in result.items
        ],
    )


@router.delete(
    "/brokerage-connections/{connection_id}",
    response_model=DisconnectBrokerageConnectionResponse,
    status_code=status.HTTP_200_OK,
)
async def disconnect_brokerage_connection(
    connection_id: UUID,
    uow: UoWDep,
    request: Request,
) -> DisconnectBrokerageConnectionResponse:
    """Disconnect a brokerage connection (user-initiated)."""
    user_id, tenant_id = _require_user_headers(request)
    uc = DisconnectBrokerageConnectionUseCase()
    result = await uc.execute(
        cmd=DisconnectBrokerageConnectionCommand(
            connection_id=connection_id,
            user_id=user_id,
            tenant_id=tenant_id,
        ),
        uow=uow,
        brokerage_client=request.app.state.brokerage_client,
    )
    return DisconnectBrokerageConnectionResponse(status=result.status)


@router.get(
    "/brokerage-connections/{connection_id}/callback",
    response_model=ActivateBrokerageConnectionResponse,
    status_code=status.HTTP_200_OK,
)
async def activate_brokerage_connection(
    connection_id: UUID,
    uow: UoWDep,
    request: Request,
    authorizationId: str = Query(...),  # noqa: N803 — SnapTrade callback param name
    userId: str = Query(...),  # noqa: N803 — SnapTrade callback param name
    sessionId: str = Query(...),  # noqa: N803 — SnapTrade callback param name
) -> ActivateBrokerageConnectionResponse:
    """Activate a PENDING connection after the SnapTrade OAuth callback."""
    user_id, tenant_id = _require_user_headers(request)
    uc = ActivateBrokerageConnectionUseCase()
    result = await uc.execute(
        cmd=ActivateBrokerageConnectionCommand(
            connection_id=connection_id,
            user_id=user_id,
            tenant_id=tenant_id,
            snaptrade_user_id=userId,
            authorization_id=authorizationId,
        ),
        uow=uow,
    )
    return ActivateBrokerageConnectionResponse(
        status=result.status,
        connection_id=result.connection_id,
    )


@router.get(
    "/brokerage-connections/{connection_id}/sync-errors",
    response_model=GetSyncErrorsResponse,
    status_code=status.HTTP_200_OK,
)
async def get_sync_errors(
    connection_id: UUID,
    uow: ReadUoWDep,
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
) -> GetSyncErrorsResponse:
    """Return sync errors for a brokerage connection (read-only, R27)."""
    user_id, tenant_id = _require_user_headers(request)
    uc = GetSyncErrorsUseCase()
    result = await uc.execute(
        query=GetSyncErrorsQuery(
            connection_id=connection_id,
            user_id=user_id,
            tenant_id=tenant_id,
            limit=limit,
        ),
        uow=uow,
    )
    return GetSyncErrorsResponse(
        items=[
            SyncErrorResponse(
                id=e.id,
                connection_id=e.connection_id,
                snaptrade_transaction_id=e.snaptrade_transaction_id,
                error_type=str(e.error_type.value),
                error_detail=e.error_detail,
                created_at=e.created_at,
            )
            for e in result.items
        ],
    )
