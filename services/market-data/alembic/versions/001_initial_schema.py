"""Consolidated schema — all tables for the market-data service.

Revision ID: 001
Revises: (none)
Create Date: 2026-03-12

Consolidates migrations 001-007 into a single authoritative schema.
Always run from scratch (tmpfs in test, clean DB in dev), so no incremental
upgrade path is needed.

Tables (dependency order):
  Core:           securities → instruments
  Market data:    ohlcv_bars (TimescaleDB hypertable), quotes
  Fundamentals:   income_statements, balance_sheets, cash_flow_statements,
                  valuation_ratios, technicals_snapshots, share_statistics,
                  splits_dividends, analyst_consensus, earnings_history,
                  earnings_trends, earnings_annual_trends, dividend_history,
                  outstanding_shares, company_profiles, highlights,
                  institutional_holders, fund_holders,
                  insider_transactions_snapshot
  Extended data:  earnings_calendar, economic_events, macro_indicators,
                  daily_sentiments, insider_transactions, yield_curve,
                  market_cap_history
  Infrastructure: ingestion_events, failed_tasks, outbox_events
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

# revision identifiers, used by Alembic.
revision = "001"
down_revision = None
branch_labels = None
depends_on = None


# ── Shared helper for standard fundamentals tables ────────────────────────────


def _create_fundamentals_table(table_name: str) -> None:
    """Create a standard fundamentals table with the common column set and unique constraint."""
    op.create_table(
        table_name,
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "instrument_id", UUID(as_uuid=False), sa.ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("period_type", sa.String(20), nullable=False),
        sa.Column("period_end_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("data", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(f"ix_{table_name}_instrument_id", table_name, ["instrument_id"])
    op.create_unique_constraint(
        f"uq_{table_name}_instrument_period",
        table_name,
        ["instrument_id", "period_type", "period_end_date"],
    )


def _drop_fundamentals_table(table_name: str) -> None:
    op.drop_constraint(f"uq_{table_name}_instrument_period", table_name, type_="unique")
    op.drop_index(f"ix_{table_name}_instrument_id", table_name=table_name)
    op.drop_table(table_name)


# ── upgrade ────────────────────────────────────────────────────────────────────


def upgrade() -> None:
    # Enable TimescaleDB (required before hypertable creation)
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE")

    # ── Core entities ──────────────────────────────────────────────────────────
    op.create_table(
        "securities",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("figi", sa.String(12), unique=True, nullable=True),
        sa.Column("isin", sa.String(12), nullable=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("sector", sa.String(100), nullable=True),
        sa.Column("industry", sa.String(100), nullable=True),
        sa.Column("country", sa.String(3), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "instruments",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "security_id", UUID(as_uuid=False), sa.ForeignKey("securities.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("exchange", sa.String(10), nullable=False),
        sa.Column("has_ohlcv", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("has_quotes", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("has_fundamentals", sa.Boolean, nullable=False, server_default="false"),
        # Metadata columns (added in former migration 005)
        sa.Column("name", sa.String(255), nullable=True),
        sa.Column("isin", sa.String(12), nullable=True),
        sa.Column("sector", sa.String(100), nullable=True),
        sa.Column("industry", sa.String(100), nullable=True),
        sa.Column("country", sa.String(3), nullable=True),
        sa.Column("currency_code", sa.String(3), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.UniqueConstraint("symbol", "exchange", name="uq_instruments_symbol_exchange"),
    )

    # ── Market data ────────────────────────────────────────────────────────────
    op.create_table(
        "ohlcv_bars",
        sa.Column(
            "instrument_id", UUID(as_uuid=False), sa.ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("timeframe", sa.String(5), nullable=False),
        sa.Column("bar_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("open", sa.Numeric(18, 8), nullable=False),
        sa.Column("high", sa.Numeric(18, 8), nullable=False),
        sa.Column("low", sa.Numeric(18, 8), nullable=False),
        sa.Column("close", sa.Numeric(18, 8), nullable=False),
        sa.Column("volume", sa.Numeric(24, 8), nullable=False, server_default="0"),
        sa.Column("adjusted_close", sa.Numeric(18, 8), nullable=True),
        sa.Column("source", sa.String(50), nullable=True),
        sa.Column("provider_priority", sa.SmallInteger, nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("instrument_id", "timeframe", "bar_date"),
    )
    op.create_index("ix_ohlcv_bars_instrument_bar_date", "ohlcv_bars", ["instrument_id", "bar_date"])
    # Convert to TimescaleDB hypertable partitioned on bar_date (1-month chunks)
    op.execute(
        "SELECT create_hypertable("
        "  'ohlcv_bars',"
        "  'bar_date',"
        "  migrate_data => true,"
        "  chunk_time_interval => INTERVAL '1 month'"
        ")"
    )

    op.create_table(
        "quotes",
        sa.Column(
            "instrument_id", UUID(as_uuid=False), sa.ForeignKey("instruments.id", ondelete="CASCADE"), primary_key=True
        ),
        sa.Column("bid", sa.Numeric(18, 8), nullable=True),
        sa.Column("ask", sa.Numeric(18, 8), nullable=True),
        sa.Column("last", sa.Numeric(18, 8), nullable=True),
        sa.Column("volume", sa.Numeric(24, 8), nullable=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── Standard fundamentals tables ───────────────────────────────────────────
    for tbl in (
        "income_statements",
        "balance_sheets",
        "cash_flow_statements",
        "valuation_ratios",
        "technicals_snapshots",
        "share_statistics",
        "splits_dividends",
        "analyst_consensus",
        "earnings_history",
        "earnings_trends",
        "earnings_annual_trends",
        "dividend_history",
        "outstanding_shares",
    ):
        _create_fundamentals_table(tbl)

    # ── Extended fundamentals tables ───────────────────────────────────────────
    for tbl in ("highlights", "institutional_holders", "fund_holders", "insider_transactions_snapshot"):
        _create_fundamentals_table(tbl)

    # ── company_profiles (unique on instrument_id alone) ──────────────────────
    op.create_table(
        "company_profiles",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "instrument_id", UUID(as_uuid=False), sa.ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("full_time_employees", sa.Integer, nullable=True),
        sa.Column("ipo_date", sa.Date, nullable=True),
        sa.Column("fiscal_year_end", sa.String(20), nullable=True),
        sa.Column("cik", sa.String(30), nullable=True),
        sa.Column("cusip", sa.String(20), nullable=True),
        sa.Column("lei", sa.String(30), nullable=True),
        sa.Column("open_figi", sa.String(30), nullable=True),
        sa.Column("is_delisted", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("officers", JSONB, nullable=True),
        sa.Column("listings", JSONB, nullable=True),
        sa.Column("data", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_unique_constraint("uq_company_profiles_instrument", "company_profiles", ["instrument_id"])
    op.create_index("ix_company_profiles_instrument", "company_profiles", ["instrument_id"])

    # ── Extended dataset tables ────────────────────────────────────────────────
    op.create_table(
        "earnings_calendar",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "instrument_id", UUID(as_uuid=False), sa.ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("report_date", sa.Date, nullable=False),
        sa.Column("fiscal_date", sa.Date, nullable=True),
        sa.Column("eps_estimate", sa.Numeric(18, 4), nullable=True),
        sa.Column("eps_actual", sa.Numeric(18, 4), nullable=True),
        sa.Column("before_after", sa.String(20), nullable=True),
        sa.Column("currency", sa.String(10), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_unique_constraint("uq_earnings_calendar", "earnings_calendar", ["instrument_id", "report_date"])
    op.create_index("ix_earnings_calendar_report_date", "earnings_calendar", ["report_date"])
    op.create_index("ix_earnings_calendar_instrument", "earnings_calendar", ["instrument_id"])

    op.create_table(
        "economic_events",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("event_type", sa.String(200), nullable=False),
        sa.Column("country", sa.String(10), nullable=False),
        sa.Column("event_date", sa.Date, nullable=False),
        sa.Column("actual", sa.Numeric(18, 6), nullable=True),
        sa.Column("estimate", sa.Numeric(18, 6), nullable=True),
        sa.Column("previous", sa.Numeric(18, 6), nullable=True),
        sa.Column("change_value", sa.Numeric(18, 6), nullable=True),
        sa.Column("change_pct", sa.Numeric(10, 6), nullable=True),
        sa.Column("impact", sa.String(20), nullable=True),
        sa.Column("unit", sa.String(50), nullable=True),
        sa.Column("currency", sa.String(10), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_unique_constraint("uq_economic_events", "economic_events", ["event_type", "country", "event_date"])
    op.create_index("ix_economic_events_date", "economic_events", ["event_date"])
    op.create_index("ix_economic_events_country", "economic_events", ["country", "event_date"])

    op.create_table(
        "macro_indicators",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("country", sa.String(10), nullable=False),
        sa.Column("indicator", sa.String(100), nullable=False),
        sa.Column("period_date", sa.Date, nullable=False),
        sa.Column("value", sa.Numeric(24, 8), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_unique_constraint("uq_macro_indicators", "macro_indicators", ["country", "indicator", "period_date"])
    op.create_index(
        "ix_macro_indicators_country_indicator",
        "macro_indicators",
        ["country", "indicator", sa.text("period_date DESC")],
    )

    op.create_table(
        "daily_sentiments",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "instrument_id", UUID(as_uuid=False), sa.ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("polarity_mean", sa.Numeric(6, 4), nullable=True),
        sa.Column("pos_mean", sa.Numeric(6, 4), nullable=True),
        sa.Column("neu_mean", sa.Numeric(6, 4), nullable=True),
        sa.Column("neg_mean", sa.Numeric(6, 4), nullable=True),
        sa.Column("article_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_unique_constraint("uq_daily_sentiments", "daily_sentiments", ["instrument_id", "date"])
    op.create_index("ix_daily_sentiments_instrument_date", "daily_sentiments", ["instrument_id", sa.text("date DESC")])

    op.create_table(
        "insider_transactions",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "instrument_id", UUID(as_uuid=False), sa.ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("owner_name", sa.String(300), nullable=False),
        sa.Column("owner_title", sa.String(300), nullable=True),
        sa.Column("transaction_date", sa.Date, nullable=False),
        sa.Column("transaction_code", sa.String(5), nullable=True),
        sa.Column("shares", sa.Numeric(18, 2), nullable=True),
        sa.Column("price_per_share", sa.Numeric(18, 4), nullable=True),
        sa.Column("acquired_disposed", sa.String(1), nullable=True),
        sa.Column("total_shares_owned", sa.Numeric(18, 2), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_unique_constraint(
        "uq_insider_transactions",
        "insider_transactions",
        ["instrument_id", "owner_name", "transaction_date", "transaction_code", "shares"],
    )
    op.create_index(
        "ix_insider_tx_instrument_date", "insider_transactions", ["instrument_id", sa.text("transaction_date DESC")]
    )

    op.create_table(
        "yield_curve",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("series", sa.String(20), nullable=False),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("maturity", sa.String(15), nullable=False),
        sa.Column("rate", sa.Numeric(8, 4), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_unique_constraint("uq_yield_curve", "yield_curve", ["series", "date", "maturity"])
    op.create_index("ix_yield_curve_date", "yield_curve", [sa.text("date DESC")])
    op.create_index("ix_yield_curve_series", "yield_curve", ["series", "maturity", sa.text("date DESC")])

    op.create_table(
        "market_cap_history",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column(
            "instrument_id", UUID(as_uuid=False), sa.ForeignKey("instruments.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("value_usd", sa.Numeric(24, 2), nullable=True),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_unique_constraint("uq_market_cap_history", "market_cap_history", ["instrument_id", "date"])
    op.create_index(
        "ix_market_cap_history_instrument_date", "market_cap_history", ["instrument_id", sa.text("date DESC")]
    )

    # ── Infrastructure ─────────────────────────────────────────────────────────
    # event_id and id use String(128) to support both UUID and ULID formats
    op.create_table(
        "ingestion_events",
        sa.Column("id", sa.String(128), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("event_id", sa.String(128), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("content_sha256", sa.String(64), nullable=True),
        sa.UniqueConstraint("event_id", name="uq_ingestion_events_event_id"),
    )
    op.create_index(
        "ix_ingestion_events_content_sha256",
        "ingestion_events",
        ["content_sha256", "event_type"],
        postgresql_where=sa.text("content_sha256 IS NOT NULL"),
    )

    op.create_table(
        "failed_tasks",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("task_type", sa.String(100), nullable=False),
        sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("attempts", sa.SmallInteger, nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.SmallInteger, nullable=False, server_default="5"),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="'PENDING'"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    op.create_table(
        "outbox_events",
        sa.Column("id", UUID(as_uuid=False), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("topic", sa.String(255), nullable=False),
        sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(20), nullable=False, server_default="'PENDING'"),
        sa.Column("claimed_by", sa.String(255), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.SmallInteger, nullable=False, server_default="0"),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_outbox_events_status_created", "outbox_events", ["status", "created_at"])


# ── downgrade ──────────────────────────────────────────────────────────────────


def downgrade() -> None:
    op.drop_index("ix_outbox_events_status_created", table_name="outbox_events")
    op.drop_table("outbox_events")
    op.drop_table("failed_tasks")
    op.drop_index("ix_ingestion_events_content_sha256", table_name="ingestion_events")
    op.drop_table("ingestion_events")

    for tbl in (
        "market_cap_history",
        "yield_curve",
        "insider_transactions",
        "daily_sentiments",
        "macro_indicators",
        "economic_events",
        "earnings_calendar",
    ):
        op.drop_table(tbl)

    op.drop_index("ix_company_profiles_instrument", table_name="company_profiles")
    op.drop_constraint("uq_company_profiles_instrument", "company_profiles", type_="unique")
    op.drop_table("company_profiles")

    for tbl in reversed(("highlights", "institutional_holders", "fund_holders", "insider_transactions_snapshot")):
        _drop_fundamentals_table(tbl)

    for tbl in reversed(
        (
            "income_statements",
            "balance_sheets",
            "cash_flow_statements",
            "valuation_ratios",
            "technicals_snapshots",
            "share_statistics",
            "splits_dividends",
            "analyst_consensus",
            "earnings_history",
            "earnings_trends",
            "earnings_annual_trends",
            "dividend_history",
            "outstanding_shares",
        )
    ):
        _drop_fundamentals_table(tbl)

    op.drop_table("quotes")
    op.drop_index("ix_ohlcv_bars_instrument_bar_date", table_name="ohlcv_bars")
    op.drop_table("ohlcv_bars")
    op.drop_table("instruments")
    op.drop_table("securities")
