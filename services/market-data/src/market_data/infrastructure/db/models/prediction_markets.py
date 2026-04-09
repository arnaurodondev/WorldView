"""ORM models for prediction market tables (PRD-0019 §7.2).

* ``PredictionMarketModel`` — one row per Polymarket market; upserted on
  every poll cycle.
* ``PredictionMarketSnapshotModel`` — TimescaleDB hypertable; one row per
  (market_id, snapshot_at) pair storing per-outcome prices.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Index, Numeric, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from market_data.infrastructure.db.base import Base, TimestampMixin


class PredictionMarketModel(TimestampMixin, Base):
    """One row per Polymarket market.

    ``created_at`` / ``updated_at`` come from :class:`TimestampMixin`.
    ``id`` is a PostgreSQL-generated UUID (gen_random_uuid).
    """

    __tablename__ = "prediction_markets"
    __table_args__ = (
        UniqueConstraint("market_id", name="uq_prediction_markets_market_id"),
        Index("ix_pm_status_updated", "resolution_status", text("updated_at DESC")),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    market_id: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'polymarket'"))
    question: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcomes: Mapped[list] = mapped_column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    close_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution_status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'open'"))
    resolved_answer: Mapped[str | None] = mapped_column(Text, nullable=True)


class PredictionMarketSnapshotModel(Base):
    """One row per (market_id, snapshot_at) pair — TimescaleDB hypertable.

    No ``TimestampMixin`` because hypertables use ``snapshot_at`` as the
    time dimension rather than a separate ``updated_at`` column.
    ``id`` is a PostgreSQL-generated UUID (gen_random_uuid).
    """

    __tablename__ = "prediction_market_snapshots"
    __table_args__ = (
        UniqueConstraint("market_id", "snapshot_at", name="uq_pms_market_snapshot"),
        Index("ix_pms_market_time", "market_id", text("snapshot_at DESC")),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    market_id: Mapped[str] = mapped_column(Text, nullable=False)
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    outcomes_prices: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    volume_24h: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    liquidity: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    source_event_id: Mapped[str] = mapped_column(Text, nullable=False)
