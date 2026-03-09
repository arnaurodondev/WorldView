"""ORM model registry."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all portfolio ORM models."""


from portfolio.infrastructure.db.models.holding import HoldingModel  # noqa: E402
from portfolio.infrastructure.db.models.idempotency import IdempotencyModel  # noqa: E402
from portfolio.infrastructure.db.models.instrument import InstrumentModel  # noqa: E402
from portfolio.infrastructure.db.models.outbox import OutboxEventModel  # noqa: E402
from portfolio.infrastructure.db.models.portfolio import PortfolioModel  # noqa: E402
from portfolio.infrastructure.db.models.tenant import TenantModel  # noqa: E402
from portfolio.infrastructure.db.models.transaction import TransactionModel  # noqa: E402
from portfolio.infrastructure.db.models.user import UserModel  # noqa: E402

__all__ = [
    "Base",
    "HoldingModel",
    "IdempotencyModel",
    "InstrumentModel",
    "OutboxEventModel",
    "PortfolioModel",
    "TenantModel",
    "TransactionModel",
    "UserModel",
]
