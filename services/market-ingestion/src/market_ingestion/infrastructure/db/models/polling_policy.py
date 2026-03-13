"""SQLAlchemy 2.0 ORM model for polling_policies."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from market_ingestion.infrastructure.db.models.base import Base


class PollingPolicyModel(Base):
    """ORM model for the ``polling_policies`` table.

    Policies define scheduling rules for data streams.
    ``symbol=NULL`` acts as a wildcard matching any symbol.
    """

    __tablename__ = "polling_policies"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)

    # Targeting (NULL = wildcard)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    dataset_type: Mapped[str] = mapped_column(String(50), nullable=False)
    dataset_variant: Mapped[str | None] = mapped_column(String(100), nullable=True)
    symbol: Mapped[str | None] = mapped_column(String(50), nullable=True)
    exchange: Mapped[str | None] = mapped_column(String(20), nullable=True)
    timeframe: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # Base scheduling (domain: base_interval_seconds)
    base_interval_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=3600)
    min_interval_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    jitter_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=10)

    # Adaptive scheduling (domain: k / hotness)
    adaptive_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    adaptive_k: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    adaptive_half_life_sec: Mapped[int] = mapped_column(Integer, nullable=False, default=3600)

    # Priority
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Enabled flag (domain: is_enabled)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Backfill configuration (domain: backfill_days / backfill_start_date)
    backfill_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    backfill_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    backfill_chunk_days: Mapped[int | None] = mapped_column(Integer, nullable=True, default=30)

    # Audit
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        # Partial index: only enabled policies (scheduler hot path)
        Index(
            "ix_polling_policies_enabled",
            "enabled",
            postgresql_where="enabled = true",
        ),
        # Policy-matching index (most-specific-wins lookup)
        Index(
            "ix_polling_policies_matching",
            "provider",
            "dataset_type",
            "dataset_variant",
            "symbol",
            "exchange",
            "timeframe",
        ),
        # Priority ordering
        Index("ix_polling_policies_priority", "priority"),
    )
