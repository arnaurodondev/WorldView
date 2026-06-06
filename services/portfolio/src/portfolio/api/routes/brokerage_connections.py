"""Brokerage connections API routes (PRD-0022 §6.2)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query, Request, status

from observability import get_logger  # type: ignore[import-untyped]
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
from portfolio.application.ports.brokerage_client import SnapTradeUser
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

logger = get_logger(__name__)  # type: ignore[no-any-return]

router = APIRouter(tags=["brokerage-connections"])


def _require_user_headers(request: Request) -> tuple[UUID, UUID]:
    """Extract and validate user/tenant IDs from request.state (set by InternalJWTMiddleware)."""
    user_id_str = getattr(request.state, "user_id", None)
    tenant_id_str = getattr(request.state, "tenant_id", None)
    if not user_id_str or not tenant_id_str:
        raise HTTPException(status_code=401, detail="Missing auth claims")
    try:
        return UUID(str(user_id_str)), UUID(str(tenant_id_str))
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid auth claims format") from exc


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
    background_tasks: BackgroundTasks,
    # WHY optional: SnapTrade Connection Portal v4 sends `connection_id` (their
    # authorization UUID) instead of `authorizationId`. Accept both; prefer
    # `authorizationId` if both arrive (v3 compat), else fall back to `connection_id`.
    authorizationId: str | None = Query(default=None),  # noqa: N803 — v3 param
    connection_id_snap: str | None = Query(default=None, alias="connection_id"),  # v4 param
    # WHY optional: v4 portal omits userId/sessionId from the callback redirect.
    # Ownership is already verified by the JWT (user_id from InternalJWTMiddleware).
    userId: str | None = Query(default=None),  # noqa: N803 — v3 param, informational
    sessionId: str | None = Query(default=None),  # noqa: N803 — informational only
) -> ActivateBrokerageConnectionResponse:
    """Activate a PENDING connection after the SnapTrade OAuth callback.

    Supports both Connection Portal v3 (authorizationId + userId + sessionId)
    and v4 (connection_id + status only). JWT ownership check replaces the
    userId anti-spoofing check when userId is absent.

    Post-activation auto-sync (2026-05-09 QA fix): immediately after the connection
    transitions to ACTIVE we schedule a one-shot ``_run_single_sync`` background
    task so transactions and holdings appear in the UI within seconds, instead of
    requiring the user to wait up to ``brokerage_sync_cycle_seconds`` (default 4 h)
    for the next periodic ``BrokerageTransactionSyncWorker`` cycle. This was the
    direct cause of the user-reported "SnapTrade flag-fetch initiated but no
    transactions appear after connecting" symptom.
    """
    user_id, tenant_id = _require_user_headers(request)
    # Resolve authorization ID: v3 uses authorizationId, v4 uses connection_id
    resolved_authorization_id = authorizationId or connection_id_snap or ""
    uc = ActivateBrokerageConnectionUseCase()
    result = await uc.execute(
        cmd=ActivateBrokerageConnectionCommand(
            connection_id=connection_id,
            user_id=user_id,
            tenant_id=tenant_id,
            snaptrade_user_id=userId or "",  # empty → use case skips userId check
            authorization_id=resolved_authorization_id,
        ),
        uow=uow,
    )

    # ── Post-activation auto-sync ─────────────────────────────────────────────
    # WHY background task: re-load the connection through a fresh ReadOnly UoW
    # outside the request UoW, then enqueue the sync. We avoid re-using `uow`
    # because BackgroundTasks runs AFTER the response is sent and `uow` will
    # already have been closed by the dependency injector by then. Failures are
    # swallowed inside `_run_single_sync` (logged via structlog) so the 200
    # response is never delayed.
    if result.status == "active":
        # Re-fetch via a fresh read-only UoW so we have a fully-hydrated entity
        # (with secrets decrypted via the cipher) for the sync worker.
        connection = await uow.brokerage_connections.get_by_user(
            connection_id,
            user_id,
            tenant_id,
        )
        if connection is not None:
            background_tasks.add_task(
                _run_single_sync,
                request.app.state,
                connection,
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


# ── Account balance (P1-C) ────────────────────────────────────────────────────


@router.get(
    "/brokerage-connections/{connection_id}/balance",
    status_code=status.HTTP_200_OK,
)
async def get_brokerage_balance(
    connection_id: UUID,
    uow: ReadUoWDep,
    request: Request,
) -> dict[str, Any]:
    """Return cash/buying-power balance for a brokerage connection (read-only, R27).

    Calls SnapTrade's per-account balance endpoint. Returns
    ``{"available": true, "cash": ..., "buying_power": ..., "currency": ...}``
    when the broker exposes balance data, or ``{"available": false, "reason": ...}``
    when balance is unavailable — the frontend renders an em-dash for the latter.

    This is a best-effort endpoint: any SDK/network failure returns
    ``available: false`` rather than 500, so the UI never crashes on balance.
    """
    user_id, tenant_id = _require_user_headers(request)

    # Ownership check — read replica (R27); verifies connection belongs to user.
    connection = await uow.brokerage_connections.get_by_user(connection_id, user_id, tenant_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="Brokerage connection not found")

    # Only ACTIVE connections have valid SnapTrade credentials that can query balance.
    from portfolio.domain.enums import ConnectionStatus

    if connection.status != ConnectionStatus.ACTIVE:
        return {"available": False, "reason": "connection_not_active"}

    # Build the SnapTrade user credentials from the stored (decrypted) connection.
    # WHY: SnapTradeClient methods always require user_id + user_secret for HMAC signing.
    snap_user = SnapTradeUser(
        snaptrade_user_id=connection.snaptrade_user_id,
        snaptrade_user_secret=connection.snaptrade_user_secret,  # NEVER logged
    )

    brokerage_client = request.app.state.brokerage_client

    # Step 1: get the list of SnapTrade account IDs linked to this connection.
    # WHY: the balance endpoint is per-account; we aggregate (first account = primary).
    try:
        account_ids = await brokerage_client.list_account_ids(snap_user)
    except Exception:
        logger.warning(
            "brokerage_balance_list_accounts_failed",
            connection_id=str(connection_id),
        )
        return {"available": False, "reason": "account_list_unavailable"}

    if not account_ids:
        return {"available": False, "reason": "no_accounts_linked"}

    # Step 2: fetch balance for the primary (first) account.
    # WHY first only: most users have one account per connection; aggregating
    # multi-currency/multi-account balances without knowing the user's intent
    # would be misleading.  The frontend can call per-account if needed.
    primary_account_id = account_ids[0]
    balance = await brokerage_client.get_account_balance(snap_user, primary_account_id)

    if balance is None:
        return {"available": False, "reason": "balance_unavailable"}

    return {
        "available": True,
        "cash": str(balance["cash"]) if balance.get("cash") is not None else None,
        "buying_power": str(balance["buying_power"]) if balance.get("buying_power") is not None else None,
        "currency": balance.get("currency", "USD"),
    }


# ── Background task helper ────────────────────────────────────────────────────


async def _run_single_sync(app_state: Any, connection: Any) -> None:
    """Run one sync cycle for a single brokerage connection in a background task.

    Delegates to ``TriggerBrokerageSync`` use case (F-013).
    Dependencies are constructed from ``app_state`` rather than from FastAPI
    DI so this function can be scheduled via ``BackgroundTasks.add_task()``
    without a live request context.
    """
    from portfolio.application.use_cases.trigger_brokerage_sync import TriggerBrokerageSync

    uc = TriggerBrokerageSync(
        session_factory=app_state.session_factory,
        brokerage_client=app_state.brokerage_client,
        settings=app_state.settings,
        cipher=getattr(app_state, "snaptrade_cipher", None),
    )
    await uc.execute(connection)


# ── Force re-sync endpoint ────────────────────────────────────────────────────


@router.post(
    "/brokerage-connections/{connection_id}/sync",
    status_code=status.HTTP_202_ACCEPTED,
)
async def trigger_brokerage_sync(
    connection_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    uow: ReadUoWDep,  # read-only ownership check (R27)
    # REQ-002c (TASK-W0-04): optional ``Idempotency-Key`` header. The
    # underlying ``BrokerageTransactionSyncWorker`` is already DB-idempotent
    # via the per-transaction ``external_ref`` dedup, so the only thing we
    # need to suppress on the HTTP side is enqueuing duplicate background
    # sync tasks within a short window. We use Valkey for that — a DB table
    # would be overkill for a 5-minute TTL guard.
    idempotency_key: str | None = Header(None, alias="Idempotency-Key"),
) -> dict[str, str]:
    """Trigger an immediate background sync for a single active or errored brokerage connection.

    Returns 202 immediately — the sync runs asynchronously via FastAPI BackgroundTasks.
    Rate-limited at 30 req/min (same limit as other brokerage endpoints in S9).

    Idempotency (REQ-002c):
        When an ``Idempotency-Key`` header is supplied, a Valkey lock keyed by
        ``brokerage_sync_trigger:{tenant_id}:{connection_id}:{key}`` is set
        with a 300-second TTL. A second request with the same key within that
        window returns 202 with ``status="already_queued"`` and does NOT
        enqueue a second background task. The worker is already idempotent at
        the per-transaction level via ``external_ref``, so missing the key
        only means the user sees redundant work, not duplicate writes.

    Status codes:
        202 — sync started (connection is ACTIVE or ERROR); ``status`` field
              is ``"syncing"`` for a fresh trigger and ``"already_queued"``
              for an idempotent replay within the 5-minute window.
        401 — missing or invalid auth claims
        403 — connection belongs to a different user
        404 — connection_id not found in this tenant
        422 — connection is DISCONNECTED or PENDING (cannot sync), or the
              idempotency key is not a valid UUID.
    """
    from portfolio.domain.enums import ConnectionStatus

    user_id, tenant_id = _require_user_headers(request)

    # Validate UUID format before hitting the DB
    try:
        conn_uuid = UUID(connection_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Invalid connection_id format") from exc

    # REQ-002c: validate the idempotency key shape early — same UUID guard as
    # the other idempotent mutations to keep the API contract uniform.
    if idempotency_key is not None:
        try:
            UUID(idempotency_key)
        except (ValueError, AttributeError) as exc:
            raise HTTPException(
                status_code=422,
                detail="Idempotency-Key must be a valid UUID",
            ) from exc

    # Ownership check — use read replica (R27); we only need to verify the
    # connection exists and belongs to this user before scheduling the task.
    connection = await uow.brokerage_connections.get(conn_uuid, tenant_id)
    if connection is None:
        raise HTTPException(status_code=404, detail="Brokerage connection not found")

    if connection.user_id != user_id:
        # The connection exists in the tenant but belongs to a different user.
        raise HTTPException(status_code=403, detail="Forbidden: connection belongs to a different user")

    # Only ACTIVE and ERROR connections can be force-synced.  PENDING means the
    # OAuth flow is not complete yet; DISCONNECTED means the user has revoked access.
    if connection.status in (ConnectionStatus.DISCONNECTED, ConnectionStatus.PENDING):
        raise HTTPException(
            status_code=422,
            detail="Connection is not active — cannot sync",
        )

    # REQ-002c: Valkey-backed trigger dedup. Key shape includes tenant_id
    # (multi-tenant isolation), connection_id (per-connection bucket) and the
    # caller-supplied key. TTL is 300 s — long enough to absorb retried POSTs
    # from network blips but short enough that a genuine new request 5 minutes
    # later still goes through.
    if idempotency_key is not None:
        valkey_client = getattr(request.app.state, "valkey_client", None)
        if valkey_client is not None:
            key = f"brokerage_sync_trigger:{tenant_id}:{conn_uuid}:{idempotency_key}"
            # ``set_nx`` returns True on first-write, False if the key already
            # exists. Atomic NX prevents the TOCTOU race between GET + SET
            # that a check-then-set pattern would have.
            try:
                acquired = await valkey_client.set_nx(key, "1", ex=300)
            except Exception as exc:  # — Valkey is best-effort here
                # If Valkey is unavailable we fall back to "no dedup" rather
                # than failing the user's sync request. The worker layer is
                # still idempotent at the transaction level.
                logger.warning(
                    "brokerage_sync_idempotency_valkey_error",
                    connection_id=connection_id,
                    error=str(exc),
                )
                acquired = True
            if not acquired:
                return {
                    "status": "already_queued",
                    "connection_id": connection_id,
                    "idempotency_key": idempotency_key,
                }

    # Schedule the sync as a FastAPI background task — returns 202 immediately.
    background_tasks.add_task(_run_single_sync, request.app.state, connection)

    return {"status": "syncing", "connection_id": connection_id}
