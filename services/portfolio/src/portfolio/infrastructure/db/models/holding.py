"""SQLAlchemy ORM model for holdings."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from portfolio.infrastructure.db.models import Base


class HoldingModel(Base):
    __tablename__ = "holdings"
    __table_args__ = (
        UniqueConstraint("portfolio_id", "instrument_id", name="uq_holdings_portfolio_instrument"),
        Index("ix_holdings_portfolio_id", "portfolio_id"),
        Index("ix_holdings_tenant_id", "tenant_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("portfolios.id"))
    instrument_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 8), server_default="0")
    average_cost: Mapped[Decimal] = mapped_column(Numeric(18, 8), server_default="0")
    currency: Mapped[str]
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    cost_basis_per_unit: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True, default=None)
    total_cost_basis: Mapped[Decimal | None] = mapped_column(Numeric(20, 8), nullable=True, default=None)
