"""ORM models for prediction market tables (PRD-0019 §7.2, PRD-0033 §6.1).

* ``PredictionMarketModel`` — one row per Polymarket market; upserted on
  every poll cycle.
* ``PredictionMarketSnapshotModel`` — TimescaleDB hypertable; one row per
  (market_id, snapshot_at) pair storing per-outcome prices.
* ``PredictionMarketPriceModel`` — TimescaleDB hypertable; per-token interval
  price history (PLAN-0056 A1).
* ``PredictionMarketTradeModel`` — TimescaleDB hypertable; individual trades.
* ``PredictionMarketOIModel`` — daily open-interest / 24h-volume roll-up
  (not a hypertable).
* ``PredictionEventModel`` — Polymarket "event" groups (not a hypertable).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
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
    # D-01: tracks the timestamp of the most recent snapshot for this market.
    # Updated by PgPredictionMarketSnapshotRepository on each snapshot write
    # (insert_if_not_exists / bulk_insert_if_not_exists), guarded by
    # monotonicity so an out-of-order/late snapshot never regresses it.
    last_snapshot_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # migration 048 — denormalized latest-snapshot volume_24h, kept in sync by
    # the same snapshot-repo write path as last_snapshot_at above. Lets
    # list_markets() sort/read "recent volume" from a plain column instead of
    # a per-market LEFT JOIN LATERAL against the prediction_market_snapshots
    # hypertable (that per-row join was the root cause of intermittent
    # statement_timeout 500s under load — see migration 048 docstring).
    latest_volume_24h: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    # WHY nullable: existing rows have no slug; backfilled on next consumer poll (migration 009).
    market_slug: Mapped[str | None] = mapped_column(Text, nullable=True)
    # PLAN-0049 T-C-3-03 / migration 010 — high-level category tag
    # (``macro`` | ``politics`` | ``sports`` | ``crypto`` | ``general``).
    # Backfilled by the polymarket adapter when it learns the field; until
    # then NULL means "uncategorised" and is excluded by category filters.
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # PLAN-0056 A1 / migration 043 — links this market to its Polymarket
    # "event" group (see ``PredictionEventModel.event_id``). Nullable: existing
    # rows have no event_id; backfilled by the event consumer (Wave A3).
    event_id: Mapped[str | None] = mapped_column(Text, nullable=True)


class PredictionMarketSnapshotModel(Base):
    """One row per (market_id, snapshot_at) pair — TimescaleDB hypertable.

    No ``TimestampMixin`` because hypertables use ``snapshot_at`` as the
    time dimension rather than a separate ``updated_at`` column.
    ``id`` is a PostgreSQL-generated UUID (gen_random_uuid).

    D-01: composite PRIMARY KEY (id, snapshot_at) — TimescaleDB requires the
    partition column (snapshot_at) to be part of the PK.
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
    snapshot_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, primary_key=True)
    outcomes_prices: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default=text("'{}'::jsonb"))
    volume_24h: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    liquidity: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    source_event_id: Mapped[str] = mapped_column(Text, nullable=False)


class PredictionMarketPriceModel(Base):
    """Per-token interval price history — TimescaleDB hypertable (PLAN-0056 A1).

    One row per ``(market_id, token_id, interval, window_start_ts)``. Mirrors
    ``PredictionMarketSnapshotModel``: no ``TimestampMixin`` because the
    hypertable uses ``window_start_ts`` as the time dimension, and the
    composite PRIMARY KEY ``(id, window_start_ts)`` includes the partition
    column (TimescaleDB requirement).

    BP-007: ``interval`` is VARCHAR, not a PG enum.
    """

    __tablename__ = "prediction_market_prices"
    __table_args__ = (
        UniqueConstraint(
            "market_id",
            "token_id",
            "interval",
            "window_start_ts",
            name="uq_pmp_market_token_interval_window",
        ),
        Index("ix_pmp_market_window", "market_id", text("window_start_ts DESC")),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    market_id: Mapped[str] = mapped_column(Text, nullable=False)
    token_id: Mapped[str] = mapped_column(Text, nullable=False)
    outcome_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    interval: Mapped[str] = mapped_column(String(4), nullable=False)
    window_start_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, primary_key=True)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    source: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'polymarket_clob'"))
    is_backfill: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))


class PredictionMarketTradeModel(Base):
    """Individual fills — TimescaleDB hypertable partitioned on ``ts`` (PLAN-0056 A1).

    Composite PRIMARY KEY ``(id, ts)`` includes the partition column.
    BP-007: ``side`` is VARCHAR, not a PG enum.
    """

    __tablename__ = "prediction_market_trades"
    # TimescaleDB requires every UNIQUE index on a hypertable to include the
    # partition column (``ts``). ``trade_id`` is unique per market and a trade's
    # ``ts`` is immutable, so ``(market_id, trade_id, ts)`` dedups exactly like
    # ``(market_id, trade_id)`` — a replayed fill carries the same ts.
    __table_args__ = (
        UniqueConstraint("market_id", "trade_id", "ts", name="uq_pmt_market_trade"),
        Index("ix_pmt_market_ts", "market_id", text("ts DESC")),
    )

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    market_id: Mapped[str] = mapped_column(Text, nullable=False)
    trade_id: Mapped[str] = mapped_column(Text, nullable=False)
    token_id: Mapped[str] = mapped_column(Text, nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False)
    size_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, primary_key=True)


class PredictionMarketOIModel(TimestampMixin, Base):
    """Daily open-interest / 24h-volume roll-up (PLAN-0056 A1).

    NOT a hypertable — one row per ``(market_id, snapshot_date)``, low volume.
    ``created_at`` / ``updated_at`` come from :class:`TimestampMixin`.
    """

    __tablename__ = "prediction_market_oi"

    market_id: Mapped[str] = mapped_column(Text, primary_key=True)
    snapshot_date: Mapped[date] = mapped_column(Date, primary_key=True)
    total_oi_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)
    total_volume_24h_usd: Mapped[Decimal | None] = mapped_column(Numeric(20, 4), nullable=True)


class PredictionEventModel(TimestampMixin, Base):
    """Polymarket "event" group — a set of related markets (PLAN-0056 A1).

    NOT a hypertable. ``event_id`` is the Polymarket group id (unique).
    ``created_at`` / ``updated_at`` come from :class:`TimestampMixin`.
    """

    __tablename__ = "prediction_events"
    __table_args__ = (UniqueConstraint("event_id", name="uq_prediction_events_event_id"),)

    id: Mapped[str] = mapped_column(
        UUID(as_uuid=False),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    event_id: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(String(50), nullable=True)
    start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    market_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
