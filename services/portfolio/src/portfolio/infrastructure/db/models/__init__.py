"""ORM model registry."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all portfolio ORM models."""


from portfolio.infrastructure.db.models.alert_preference import AlertPreferenceModel  # noqa: E402
from portfolio.infrastructure.db.models.auth_audit_log import AuthAuditLogModel  # noqa: E402
from portfolio.infrastructure.db.models.brokerage_connection import BrokerageConnectionModel  # noqa: E402
from portfolio.infrastructure.db.models.brokerage_sync_error import BrokerageTransactionSyncErrorModel  # noqa: E402
from portfolio.infrastructure.db.models.entity_suppression import EntitySuppressionModel  # noqa: E402
from portfolio.infrastructure.db.models.holding import HoldingModel  # noqa: E402
from portfolio.infrastructure.db.models.idempotency import IdempotencyModel  # noqa: E402
from portfolio.infrastructure.db.models.instrument import InstrumentModel  # noqa: E402
from portfolio.infrastructure.db.models.invitation import InvitationModel  # noqa: E402
from portfolio.infrastructure.db.models.outbox import OutboxEventModel  # noqa: E402
from portfolio.infrastructure.db.models.portfolio import PortfolioModel  # noqa: E402
from portfolio.infrastructure.db.models.portfolio_value_snapshot import PortfolioValueSnapshotModel  # noqa: E402
from portfolio.infrastructure.db.models.tenant import TenantModel  # noqa: E402
from portfolio.infrastructure.db.models.transaction import TransactionModel  # noqa: E402
from portfolio.infrastructure.db.models.user import UserModel  # noqa: E402
from portfolio.infrastructure.db.models.watchlist import WatchlistModel  # noqa: E402
from portfolio.infrastructure.db.models.watchlist_member import WatchlistMemberModel  # noqa: E402

__all__ = [
    "AlertPreferenceModel",
    "AuthAuditLogModel",
    "Base",
    "BrokerageConnectionModel",
    "BrokerageTransactionSyncErrorModel",
    "EntitySuppressionModel",
    "HoldingModel",
    "IdempotencyModel",
    "InstrumentModel",
    "InvitationModel",
    "OutboxEventModel",
    "PortfolioModel",
    "PortfolioValueSnapshotModel",
    "TenantModel",
    "TransactionModel",
    "UserModel",
    "WatchlistMemberModel",
    "WatchlistModel",
]
