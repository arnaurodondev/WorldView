"""SQLAlchemy 2.0 ORM model for symbol_tiers."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from market_ingestion.infrastructure.db.models.base import Base


class SymbolTierModel(Base):
    """ORM model for the ``symbol_tiers`` table.

    Records the cadence tier assigned to each symbol+exchange pair.
    A UNIQUE constraint on (symbol, exchange) ensures one active tier per stream.
    """

    __tablename__ = "symbol_tiers"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    exchange: Mapped[str] = mapped_column(String(20), nullable=False)
    # Integer maps to TierLevel (0-4); stored as plain int for portability.
    tier: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    tier_source: Mapped[str] = mapped_column(String(32), nullable=False, default="default")
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    last_user_refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("symbol", "exchange", name="uq_symbol_tiers_symbol_exchange"),
        Index("ix_symbol_tiers_tier", "tier"),
    )
