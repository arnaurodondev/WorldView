"""Brokerage connection use cases (PRD-0022 §6.2, §6.5, §6.7, §4.1)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import UUID

from common.ids import new_uuid  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from observability import get_logger  # type: ignore[import-untyped]
from portfolio.application.ports.brokerage_client import SnapTradeUser
from portfolio.domain.entities.brokerage_connection import BrokerageConnection
from portfolio.domain.enums import ConnectionStatus
from portfolio.domain.errors import (
    BrokerageApiError,
    BrokerageConnectionForbiddenError,
    BrokerageConnectionNotFoundError,
    PortfolioNotFoundError,
    TosNotAcceptedError,
)

if TYPE_CHECKING:
    from portfolio.application.ports.brokerage_client import IBrokerageClient
    from portfolio.application.ports.unit_of_work import ReadOnlyUnitOfWork, UnitOfWork
    from portfolio.domain.entities.brokerage_sync_error import BrokerageTransactionSyncError

logger = get_logger(__name__)  # type: ignore[no-any-return]

# ── Initiate ──────────────────────────────────────────────────────────────────


@dataclass
class InitiateBrokerageConnectionCommand:
    tenant_id: UUID
    user_id: UUID
    portfolio_id: UUID
    snaptrade_tos_accepted: bool  # must be True or TosNotAcceptedError raised


@dataclass
class InitiateBrokerageConnectionResult:
    connection_id: UUID
    redirect_uri: str


class InitiateBrokerageConnectionUseCase:
    """Register a SnapTrade user and create a PENDING brokerage connection.

    Logic (PRD-0022 §6.2, §4.1 F-01..F-05):
    1. Validate ToS accepted — fail fast before any SnapTrade call (BP-038).
    2. Verify portfolio exists and belongs to tenant.
    3. Generate connection_id BEFORE calling SnapTrade so it can be embedded
       in the redirect URI (PRD-0022 §6.7 R-004).
    4. Register SnapTrade user and generate portal URL.
    5. Persist connection (PENDING) — commit AFTER API calls (BP-057).
    """

    async def execute(
        self,
        cmd: InitiateBrokerageConnectionCommand,
        uow: UnitOfWork,
        brokerage_client: IBrokerageClient,
        snaptrade_redirect_uri: str,
    ) -> InitiateBrokerageConnectionResult:
        # 1. ToS guard — use if-check, not assert (BP-038)
        if not cmd.snaptrade_tos_accepted:
            raise TosNotAcceptedError(
                "SnapTrade Terms of Service must be accepted before connecting a brokerage account",
            )

        # 2. Portfolio ownership check
        portfolio = await uow.portfolios.get(cmd.portfolio_id, cmd.tenant_id)
        if portfolio is None:
            raise PortfolioNotFoundError(
                f"Portfolio {cmd.portfolio_id} not found",
                details={"portfolio_id": str(cmd.portfolio_id)},
            )

        # 3. Generate connection ID first so it can be embedded in the redirect URI
        connection_id = new_uuid()
        redirect_uri_with_id = f"{snaptrade_redirect_uri}?connectionId={connection_id}"

        # 4. SnapTrade API calls — before uow.commit() (BP-057)
        # WHY recovery block: SnapTrade is a persistent external service. After a DB
        # wipe (dev) or data loss (prod), the SnapTrade user may already exist but we
        # no longer have their credentials. Two recovery paths:
        #   a) Credentials exist in DB → reuse them (generate a new portal URL).
        #   b) Credentials lost → delete the SnapTrade user, then re-register fresh.
        try:
            snaptrade_user = await brokerage_client.register_user(user_id_hint=str(cmd.user_id))
        except BrokerageApiError as exc:
            if exc.details.get("reason") != "already_exists":
                raise
            # Path a: find stored credentials for any existing connection this user has.
            existing = await uow.brokerage_connections.list_by_user(cmd.user_id, cmd.tenant_id)
            cred_conn = next(
                (c for c in existing if c.status != ConnectionStatus.DISCONNECTED),
                existing[0] if existing else None,
            )
            if cred_conn is not None:
                snaptrade_user = SnapTradeUser(
                    snaptrade_user_id=cred_conn.snaptrade_user_id,
                    snaptrade_user_secret=cred_conn.snaptrade_user_secret,
                )
                logger.info(  # type: ignore[no-any-return]
                    "brokerage_reuse_existing_credentials",
                    user_id=str(cmd.user_id),
                    source_connection_id=str(cred_conn.id),
                )
            else:
                # Path b: credentials are gone — delete SnapTrade user and re-register.
                # Needed after DB wipe in dev or after full data loss in prod.
                await brokerage_client.delete_user(user_id_hint=str(cmd.user_id))
                snaptrade_user = await brokerage_client.register_user(user_id_hint=str(cmd.user_id))
                logger.info(  # type: ignore[no-any-return]
                    "brokerage_snaptrade_user_deleted_and_reregistered",
                    user_id=str(cmd.user_id),
                )

        portal_url = await brokerage_client.generate_portal_url(
            user=snaptrade_user,
            redirect_uri=redirect_uri_with_id,
        )

        # 5. Create entity and persist — commit last
        connection = BrokerageConnection(
            id=connection_id,
            tenant_id=cmd.tenant_id,
            user_id=cmd.user_id,
            portfolio_id=cmd.portfolio_id,
            snaptrade_user_id=snaptrade_user.snaptrade_user_id,
            snaptrade_user_secret=snaptrade_user.snaptrade_user_secret,
            snaptrade_tos_accepted_at=utc_now(),
            status=ConnectionStatus.PENDING,
        )
        await uow.brokerage_connections.save(connection)
        await uow.commit()

        logger.info(  # type: ignore[no-any-return]
            "brokerage_connection_initiated",
            connection_id=str(connection.id),
            tenant_id=str(cmd.tenant_id),
            # snaptrade_user_secret intentionally omitted
        )
        return InitiateBrokerageConnectionResult(
            connection_id=connection.id,
            redirect_uri=portal_url,
        )


# ── Activate ──────────────────────────────────────────────────────────────────


@dataclass
class ActivateBrokerageConnectionCommand:
    connection_id: UUID
    user_id: UUID
    tenant_id: UUID
    snaptrade_user_id: str  # from SnapTrade callback param "userId"
    authorization_id: str  # from SnapTrade callback param "authorizationId"


@dataclass
class ActivateBrokerageConnectionResult:
    connection_id: UUID
    status: str  # "active"


class ActivateBrokerageConnectionUseCase:
    """Transition a PENDING connection to ACTIVE after SnapTrade callback.

    Logic (PRD-0022 §6.2, §6.7):
    1. Load connection (ownership-checked).
    2. Verify snaptrade_user_id matches — prevents callback spoofing.
    3. Transition state via entity method (raises on bad state).
    4. Persist and commit.
    """

    async def execute(
        self,
        cmd: ActivateBrokerageConnectionCommand,
        uow: UnitOfWork,
    ) -> ActivateBrokerageConnectionResult:
        connection = await uow.brokerage_connections.get_by_user(cmd.connection_id, cmd.user_id, cmd.tenant_id)
        if connection is None:
            raise BrokerageConnectionNotFoundError(
                f"Brokerage connection {cmd.connection_id} not found",
                details={"connection_id": str(cmd.connection_id)},
            )

        # Anti-spoofing: validate callback userId matches stored snaptrade_user_id.
        # WHY only when provided: SnapTrade Connection Portal v4 omits userId from
        # the callback redirect. When absent (empty string), JWT-based ownership
        # (get_by_user above) is sufficient — no need for the secondary check.
        if cmd.snaptrade_user_id and cmd.snaptrade_user_id != connection.snaptrade_user_id:
            raise BrokerageConnectionForbiddenError(
                "SnapTrade userId in callback does not match stored connection",
                details={"connection_id": str(cmd.connection_id)},
            )

        # Entity method raises BrokerageConnectionStateError if not PENDING
        connection.activate(authorization_id=cmd.authorization_id)
        await uow.brokerage_connections.save(connection)
        await uow.commit()

        logger.info(  # type: ignore[no-any-return]
            "brokerage_connection_activated",
            connection_id=str(connection.id),
            tenant_id=str(cmd.tenant_id),
        )
        return ActivateBrokerageConnectionResult(
            connection_id=connection.id,
            status="active",
        )


# ── List ──────────────────────────────────────────────────────────────────────


@dataclass
class ListBrokerageConnectionsQuery:
    user_id: UUID
    tenant_id: UUID
    portfolio_id: UUID | None = None


@dataclass
class ListBrokerageConnectionsResult:
    items: list[BrokerageConnection]


class ListBrokerageConnectionsUseCase:
    """Return brokerage connections for a user (read-only, R27).

    Uses ReadUoWDep at the API layer; no write operations.
    """

    async def execute(
        self,
        query: ListBrokerageConnectionsQuery,
        uow: ReadOnlyUnitOfWork,
    ) -> ListBrokerageConnectionsResult:
        items = await uow.brokerage_connections.list_by_user(
            user_id=query.user_id,
            tenant_id=query.tenant_id,
            portfolio_id=query.portfolio_id,
        )
        return ListBrokerageConnectionsResult(items=items)


# ── Disconnect ────────────────────────────────────────────────────────────────


@dataclass
class DisconnectBrokerageConnectionCommand:
    connection_id: UUID
    user_id: UUID
    tenant_id: UUID


@dataclass
class DisconnectBrokerageConnectionResult:
    status: str  # "disconnected"


class DisconnectBrokerageConnectionUseCase:
    """Disconnect a brokerage connection (user-initiated).

    Logic (PRD-0022 §6.2, §4.1 F-07/F-08):
    1. Load connection (ownership-checked).
    2. Best-effort revoke authorization in SnapTrade — log warning on failure
       but continue; user intent is to disconnect regardless (BP-057: API call
       before commit).
    3. Transition entity to DISCONNECTED.
    4. Persist and commit.
    5. Does NOT delete transactions or holdings (F-08).
    """

    async def execute(
        self,
        cmd: DisconnectBrokerageConnectionCommand,
        uow: UnitOfWork,
        brokerage_client: IBrokerageClient,
    ) -> DisconnectBrokerageConnectionResult:
        connection = await uow.brokerage_connections.get_by_user(cmd.connection_id, cmd.user_id, cmd.tenant_id)
        if connection is None:
            raise BrokerageConnectionNotFoundError(
                f"Brokerage connection {cmd.connection_id} not found",
                details={"connection_id": str(cmd.connection_id)},
            )

        # Best-effort revoke — API call BEFORE commit (BP-057)
        if connection.authorization_id is not None:
            from portfolio.application.ports.brokerage_client import SnapTradeUser

            snap_user = SnapTradeUser(
                snaptrade_user_id=connection.snaptrade_user_id,
                snaptrade_user_secret=connection.snaptrade_user_secret,
            )
            try:
                await brokerage_client.revoke_authorization(snap_user, connection.authorization_id)
            except Exception:
                # Best-effort: log and continue — disconnect proceeds regardless
                logger.warning(  # type: ignore[no-any-return]
                    "brokerage_revoke_failed_continuing_disconnect",
                    connection_id=str(connection.id),
                )

        # Raises BrokerageConnectionAlreadyDisconnectedError if already DISCONNECTED
        connection.disconnect()
        await uow.brokerage_connections.save(connection)
        await uow.commit()

        logger.info(  # type: ignore[no-any-return]
            "brokerage_connection_disconnected",
            connection_id=str(connection.id),
            tenant_id=str(cmd.tenant_id),
        )
        return DisconnectBrokerageConnectionResult(status="disconnected")


# ── Get Sync Errors ───────────────────────────────────────────────────────────


@dataclass
class GetSyncErrorsQuery:
    connection_id: UUID
    user_id: UUID
    tenant_id: UUID
    limit: int = 50


@dataclass
class GetSyncErrorsResult:
    items: list[BrokerageTransactionSyncError]


class GetSyncErrorsUseCase:
    """Return sync errors for a brokerage connection (read-only, R27).

    Logic (PRD-0022 §4.2 F-18, §11):
    1. Verify connection ownership (prevents cross-tenant error exposure).
    2. List sync errors ordered by recency.
    Uses ReadUoWDep at the API layer.
    """

    async def execute(
        self,
        query: GetSyncErrorsQuery,
        uow: ReadOnlyUnitOfWork,
    ) -> GetSyncErrorsResult:
        connection = await uow.brokerage_connections.get_by_user(query.connection_id, query.user_id, query.tenant_id)
        if connection is None:
            raise BrokerageConnectionNotFoundError(
                f"Brokerage connection {query.connection_id} not found",
                details={"connection_id": str(query.connection_id)},
            )

        items = await uow.brokerage_sync_errors.list_by_connection(
            connection_id=query.connection_id,
            limit=query.limit,
        )
        return GetSyncErrorsResult(items=items)
