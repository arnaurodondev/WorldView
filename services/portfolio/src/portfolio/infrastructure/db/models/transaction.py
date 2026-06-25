"""SQLAlchemy ORM model for transactions."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from portfolio.infrastructure.db.models import Base


class TransactionModel(Base):
    __tablename__ = "transactions"
    __table_args__ = (
        UniqueConstraint("portfolio_id", "external_ref", name="uq_transactions_portfolio_external_ref"),
        Index("ix_transactions_tenant_id", "tenant_id"),
        Index("ix_transactions_portfolio_id", "portfolio_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("tenants.id"))
    portfolio_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("portfolios.id"))
    instrument_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True))
    transaction_type: Mapped[str]
    direction: Mapped[str]
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    price: Mapped[Decimal] = mapped_column(Numeric(18, 8))
    fees: Mapped[Decimal] = mapped_column(Numeric(18, 8), server_default="0")
    # ``amount`` is broker-reported cash flow, populated by SnapTrade ingest only.
    # NULLABLE because historical rows pre-date the column (Alembic 0009 added it
    # without a backfill — see PLAN-0046 T-46-1-01 / BP-263). For DIVIDEND rows
    # this carries the cash amount paid; for BUY/SELL it is informational and
    # may be NULL even on new rows when SnapTrade omits the field.
    amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 8), nullable=True, default=None)
    currency: Mapped[str]
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    external_ref: Mapped[str | None] = mapped_column(default=None)
    # P2-E: broker-supplied human-readable description (e.g. "Dividend Payment - AAPL").
    # Nullable — not all brokers or activity types populate this. None when SnapTrade omits it.
    # Column added Alembic 0020; historical rows are NULL (nullable, no server_default).
    description: Mapped[str | None] = mapped_column(Text, nullable=True, default=None)
    # PLAN-0108: BUY or SELL side for TRADE-type transactions; NULL for all other types.
    # VARCHAR(4) is sufficient for "BUY" (3 chars) and "SELL" (4 chars).
    # A CHECK constraint in Alembic 0021 enforces the allowed values at the DB level.
    trade_side: Mapped[str | None] = mapped_column(
        String(4),
        nullable=True,
        default=None,
        comment="BUY or SELL for TRADE-type rows; NULL for all others",
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
