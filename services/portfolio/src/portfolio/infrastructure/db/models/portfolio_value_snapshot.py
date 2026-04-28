"""SQLAlchemy ORM model for ``portfolio_value_snapshots`` (PLAN-0046 Wave 4)."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date as SADate
from sqlalchemy import DateTime, ForeignKey, Index, Numeric, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from portfolio.infrastructure.db.models import Base


class PortfolioValueSnapshotModel(Base):
    __tablename__ = "portfolio_value_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "portfolio_id",
            "snapshot_date",
            name="uq_portfolio_value_snapshots_portfolio_date",
        ),
        # Mirror the (portfolio_id, snapshot_date DESC) index from migration 0012
        # so the ORM model is congruent with the DB schema. ``text("snapshot_date DESC")``
        # is required because SQLAlchemy ``Index`` does not parse "DESC" from a string column name.
        Index(
            "ix_portfolio_value_snapshots_portfolio_date_desc",
            "portfolio_id",
            text("snapshot_date DESC"),
        ),
        Index(
            "ix_portfolio_value_snapshots_tenant_id",
            "tenant_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("portfolios.id"),
        nullable=False,
    )
    snapshot_date: Mapped[date] = mapped_column(SADate, nullable=False)
    total_value: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    total_cost: Mapped[Decimal] = mapped_column(Numeric(20, 8), nullable=False)
    cash_value: Mapped[Decimal] = mapped_column(
        Numeric(20, 8),
        nullable=False,
        server_default="0",
        default=Decimal(0),
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
