"""SQLAlchemy 2.0 ORM model for ingestion_watermarks."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column

from market_ingestion.infrastructure.db.models.base import Base


class WatermarkModel(Base):
    """ORM model for the ``ingestion_watermarks`` table.

    Natural key (6-tuple): (provider, dataset_type, dataset_variant, symbol, exchange, timeframe).
    """

    __tablename__ = "ingestion_watermarks"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)

    # Natural key components
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    dataset_type: Mapped[str] = mapped_column(String(50), nullable=False)
    dataset_variant: Mapped[str | None] = mapped_column(String(100), nullable=True)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    exchange: Mapped[str | None] = mapped_column(String(20), nullable=True)
    timeframe: Mapped[str | None] = mapped_column(String(10), nullable=True)

    # Watermark values (domain: current_bar_ts / content_hash)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_bar_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_success_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Backfill tracking (domain: backfill_status)
    backfill_phase: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    backfill_until_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    current_backfill_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Audit
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (
        # Natural-key uniqueness
        Index(
            "uq_ingestion_watermarks_natural_key",
            "provider",
            "dataset_type",
            "dataset_variant",
            "symbol",
            "exchange",
            "timeframe",
            unique=True,
        ),
        # Scheduler: list by provider
        Index("ix_ingestion_watermarks_provider", "provider"),
        # Scheduler: list by provider + dataset_type
        Index(
            "ix_ingestion_watermarks_provider_dataset_type",
            "provider",
            "dataset_type",
        ),
        # Symbol lookups
        Index("ix_ingestion_watermarks_symbol", "symbol"),
    )
