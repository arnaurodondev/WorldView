"""BrokerageConnection domain entity."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from common.ids import new_uuid  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from portfolio.domain.enums import ConnectionStatus
from portfolio.domain.errors import BrokerageConnectionAlreadyDisconnectedError, BrokerageConnectionStateError


@dataclass
class BrokerageConnection:
    """A user's read-only brokerage account connection via SnapTrade.

    Unique constraint: (user_id, portfolio_id) — one connection per portfolio.
    Security invariant: snaptrade_user_secret is NEVER exposed in __repr__,
    __str__, or any log field (F-19).
    """

    tenant_id: UUID
    user_id: UUID
    portfolio_id: UUID
    snaptrade_user_id: str
    snaptrade_user_secret: str
    snaptrade_tos_accepted_at: datetime
    id: UUID = field(default_factory=new_uuid)
    status: ConnectionStatus = ConnectionStatus.PENDING
    authorization_id: str | None = None
    brokerage_name: str | None = None
    last_synced_at: datetime | None = None
    last_sync_cursor: str | None = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)

    def __repr__(self) -> str:
        return (
            f"BrokerageConnection("
            f"id={self.id!r}, "
            f"tenant_id={self.tenant_id!r}, "
            f"user_id={self.user_id!r}, "
            f"portfolio_id={self.portfolio_id!r}, "
            f"snaptrade_user_id={self.snaptrade_user_id!r}, "
            f"snaptrade_user_secret='***REDACTED***', "
            f"status={self.status!r}, "
            f"brokerage_name={self.brokerage_name!r}"
            f")"
        )

    def activate(self, authorization_id: str) -> None:
        """Transition PENDING → ACTIVE after SnapTrade callback."""
        if self.status != ConnectionStatus.PENDING:
            raise BrokerageConnectionStateError(
                f"Cannot activate connection with status '{self.status}'; expected 'pending'",
                details={"connection_id": str(self.id), "current_status": str(self.status)},
            )
        self.authorization_id = authorization_id
        self.status = ConnectionStatus.ACTIVE
        self.updated_at = utc_now()

    def mark_error(self) -> None:
        """Transition to ERROR after a failed sync cycle."""
        self.status = ConnectionStatus.ERROR
        self.updated_at = utc_now()

    def disconnect(self) -> None:
        """Transition to DISCONNECTED on user-initiated deletion."""
        if self.status == ConnectionStatus.DISCONNECTED:
            raise BrokerageConnectionAlreadyDisconnectedError(
                "Connection is already disconnected",
                details={"connection_id": str(self.id)},
            )
        self.status = ConnectionStatus.DISCONNECTED
        self.updated_at = utc_now()
