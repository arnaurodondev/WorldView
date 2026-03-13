"""SQLAlchemy 2.0 ORM model for provider_budgets."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from market_ingestion.infrastructure.db.models.base import Base


class ProviderBudgetModel(Base):
    """ORM model for the ``provider_budgets`` table.

    Token-bucket rate limiting at the scheduler level.
    One row per provider; unique constraint on ``provider``.
    """

    __tablename__ = "provider_budgets"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)

    # Provider identifier (unique — one budget per provider)
    provider: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)

    # Token-bucket parameters (domain: burst_capacity / tokens / refill_rate)
    max_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=1000)
    current_tokens: Mapped[float] = mapped_column(Float, nullable=False, default=1000.0)
    refill_rate_per_second: Mapped[float] = mapped_column(Float, nullable=False, default=10.0)

    # Last refill timestamp
    last_refill_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # Audit
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (Index("ix_provider_budgets_provider", "provider"),)
