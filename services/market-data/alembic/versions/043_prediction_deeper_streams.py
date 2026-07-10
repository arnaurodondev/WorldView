"""Prediction deeper-stream tables + prediction_markets.event_id (PLAN-0056 A1).

Revision ID: 043
Revises: 042
Create Date: 2026-07-09

WHY THIS MIGRATION EXISTS (PLAN-0056 Sub-Plan A / Wave A1, PRD-0033 §6.1):

  The existing prediction pipeline stores only per-market metadata
  (``prediction_markets``) and periodic probability snapshots
  (``prediction_market_snapshots``). PRD-0033 activates four DEEPER streams
  fetched from Polymarket's CLOB / Data / Gamma APIs, co-located here in
  ``market_data_db`` next to the existing prediction tables so S3 owns the
  whole prediction domain (no cross-service DB access, R9):

    1. ``prediction_market_prices``  — per-token price history at a fixed
       interval (1h / 1d), a TimescaleDB hypertable partitioned on
       ``window_start_ts`` (mirrors ``ohlcv_bars`` / the snapshots hypertable).
    2. ``prediction_market_trades``  — individual fills, hypertable on ``ts``.
    3. ``prediction_market_oi``       — daily open-interest / 24h volume roll-up.
       NOT a hypertable: one row per (market, day), tiny volume.
    4. ``prediction_events``          — Polymarket "event" groups (a set of
       related markets, e.g. one election with many candidate markets).
       NOT a hypertable.

  It also adds ``prediction_markets.event_id`` (nullable) so each market can be
  linked back to its Polymarket event group (backfilled by the event consumer
  in Wave A3).

BP-007: ``interval`` and ``side`` are VARCHAR (not PG enums) — enums require a
  DDL migration to add a value, whereas VARCHAR lets new Polymarket interval /
  side tokens roll out without a schema change.

BP-019 / BP-032 (hypertable ordering): each hypertable is created AFTER its
  table + indexes exist, and with ``migrate_data => true`` so any rows already
  present are chunked (a no-op on the fresh tables here, but the correct,
  copy-safe pattern mirrored from migration 001's ``ohlcv_bars``).

R11 forward-compat: all new tables; the single ALTER only ADDs a NULLABLE
  column with no default — safe to apply ahead of or behind the code that
  writes it, and cleanly reversible.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "043"
down_revision: str = "042"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── 1. prediction_market_prices (hypertable on window_start_ts) ───────────
    op.create_table(
        "prediction_market_prices",
        sa.Column("id", UUID(as_uuid=False), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("market_id", sa.Text, nullable=False),
        sa.Column("token_id", sa.Text, nullable=False),
        sa.Column("outcome_name", sa.Text, nullable=True),
        # BP-007: VARCHAR, not a PG enum — new interval tokens need no DDL.
        sa.Column("interval", sa.String(4), nullable=False),
        sa.Column("window_start_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("price", sa.Numeric(12, 6), nullable=False),
        sa.Column("source", sa.Text, nullable=False, server_default=sa.text("'polymarket_clob'")),
        sa.Column("is_backfill", sa.Boolean, nullable=False, server_default=sa.text("false")),
        # TimescaleDB requires the partition column (window_start_ts) in the PK.
        sa.PrimaryKeyConstraint("id", "window_start_ts", name="pk_prediction_market_prices"),
    )
    op.create_index(
        "uq_pmp_market_token_interval_window",
        "prediction_market_prices",
        ["market_id", "token_id", "interval", "window_start_ts"],
        unique=True,
    )
    op.create_index(
        "ix_pmp_market_window",
        "prediction_market_prices",
        ["market_id", sa.text("window_start_ts DESC")],
    )
    op.execute(
        "SELECT create_hypertable("
        "  'prediction_market_prices',"
        "  'window_start_ts',"
        "  migrate_data => true,"
        "  chunk_time_interval => INTERVAL '1 month'"
        ")"
    )

    # ── 2. prediction_market_trades (hypertable on ts) ───────────────────────
    op.create_table(
        "prediction_market_trades",
        sa.Column("id", UUID(as_uuid=False), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("market_id", sa.Text, nullable=False),
        sa.Column("trade_id", sa.Text, nullable=False),
        sa.Column("token_id", sa.Text, nullable=False),
        sa.Column("price", sa.Numeric(12, 6), nullable=False),
        sa.Column("size_usd", sa.Numeric(20, 4), nullable=True),
        # BP-007: VARCHAR, not a PG enum.
        sa.Column("side", sa.String(8), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        # TimescaleDB requires the partition column (ts) in the PK.
        sa.PrimaryKeyConstraint("id", "ts", name="pk_prediction_market_trades"),
    )
    # TimescaleDB requires every UNIQUE index on a hypertable to include the
    # partition column (``ts``). ``trade_id`` is globally unique per market and a
    # trade's ``ts`` is immutable, so ``(market_id, trade_id, ts)`` dedups exactly
    # like ``(market_id, trade_id)`` would — a replayed fill carries the same ts.
    op.create_index(
        "uq_pmt_market_trade",
        "prediction_market_trades",
        ["market_id", "trade_id", "ts"],
        unique=True,
    )
    op.create_index(
        "ix_pmt_market_ts",
        "prediction_market_trades",
        ["market_id", sa.text("ts DESC")],
    )
    op.execute(
        "SELECT create_hypertable("
        "  'prediction_market_trades',"
        "  'ts',"
        "  migrate_data => true,"
        "  chunk_time_interval => INTERVAL '1 month'"
        ")"
    )

    # ── 3. prediction_market_oi (daily roll-up — NOT a hypertable) ───────────
    op.create_table(
        "prediction_market_oi",
        sa.Column("id", UUID(as_uuid=False), nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("market_id", sa.Text, nullable=False),
        sa.Column("snapshot_date", sa.Date, nullable=False),
        sa.Column("total_oi_usd", sa.Numeric(20, 4), nullable=True),
        sa.Column("total_volume_24h_usd", sa.Numeric(20, 4), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("market_id", "snapshot_date", name="pk_prediction_market_oi"),
    )

    # ── 4. prediction_events (event groups — NOT a hypertable) ───────────────
    op.create_table(
        "prediction_events",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("event_id", sa.Text, nullable=False),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("category", sa.String(50), nullable=True),
        sa.Column("start_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("end_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("market_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("event_id", name="uq_prediction_events_event_id"),
    )

    # ── 5. prediction_markets.event_id (nullable link to event group) ────────
    op.add_column(
        "prediction_markets",
        sa.Column("event_id", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("prediction_markets", "event_id")

    op.drop_constraint("uq_prediction_events_event_id", "prediction_events", type_="unique")
    op.drop_table("prediction_events")

    op.drop_table("prediction_market_oi")

    op.drop_index("ix_pmt_market_ts", table_name="prediction_market_trades")
    op.drop_index("uq_pmt_market_trade", table_name="prediction_market_trades")
    op.drop_table("prediction_market_trades")

    op.drop_index("ix_pmp_market_window", table_name="prediction_market_prices")
    op.drop_index("uq_pmp_market_token_interval_window", table_name="prediction_market_prices")
    op.drop_table("prediction_market_prices")
