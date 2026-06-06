"""Composite (instrument_id, period_end_date) indexes on fundamentals tables.

Revision ID: 019
Revises: 018
Create Date: 2026-05-26

PLAN-0095 T-W1-03 (ITER-9 audit §2).

WHY THIS MIGRATION EXISTS:
  All 18 mixin-based fundamentals section tables currently have a single-column
  ``ix_<table>_instrument_id`` btree (created in 001_initial_schema). The
  dominant read query — ``WHERE instrument_id = :iid ORDER BY period_end_date``
  emitted by ``query_fundamentals`` — must therefore use the
  instrument_id-only index, fetch every row for the instrument, then sort in
  memory. On a populated DB this manifests as 15-22 s wall-clock for
  ``GET /v1/instruments/<ticker>/fundamentals/history`` (the fundamentals tool
  call that dominates rag-chat p99 latency, audit §2 lines 50-59).

  Adding a composite ``(instrument_id, period_end_date ASC)`` index lets
  Postgres satisfy both the filter and the ORDER BY from one index scan, no
  sort node. Audit-projected speedup: 30-100x.

WHAT THIS MIGRATION DOES:
  Creates 18 composite indexes, one per mixin-using fundamentals table:

    ix_analyst_consensus_instrument_period
    ix_balance_sheets_instrument_period
    ix_cash_flow_statements_instrument_period
    ix_dividend_history_instrument_period
    ix_dividend_summary_instrument_period
    ix_earnings_annual_trends_instrument_period
    ix_earnings_history_instrument_period
    ix_earnings_trends_instrument_period
    ix_fund_holders_instrument_period
    ix_highlights_instrument_period
    ix_income_statements_instrument_period
    ix_insider_transactions_snapshot_instrument_period
    ix_institutional_holders_instrument_period
    ix_outstanding_shares_instrument_period
    ix_share_statistics_instrument_period
    ix_splits_dividends_instrument_period
    ix_technicals_snapshots_instrument_period
    ix_valuation_ratios_instrument_period

WHY PLAIN CREATE INDEX (NOT CONCURRENTLY): BP-393. The Alembic migration
runner wraps each revision in a transaction; ``CREATE INDEX CONCURRENTLY``
cannot run inside a transaction block and the runner aborts.
``CREATE INDEX`` is fine for single-tenant dev/staging; in prod a future
migration could rewrite to CONCURRENTLY with ``--no-transaction``.

WHY KEEP EXISTING SINGLE-COLUMN ix_<table>_instrument_id: PLAN-0095 T-W1-05
defers cleanup. The single-column index is a prefix of the composite so it
is technically redundant, but Postgres may still pick it for very small
tables; safer to leave it for one cycle and drop in a follow-up after
observing query plans in prod.

DOWNGRADE: drops all 18 composite indexes. Existing single-column indexes
are untouched so query plans simply revert to the pre-019 behaviour.
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import inspect

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


# All 18 mixin-using fundamentals section tables. (CompanyProfileModel is the
# one fundamentals model that does NOT use the mixin — no period_end_date —
# and therefore is intentionally excluded.) Listed alphabetically for easy
# audit against ``grep FundamentalsModelMixin``.
_TABLES: tuple[str, ...] = (
    "analyst_consensus",
    "balance_sheets",
    "cash_flow_statements",
    "dividend_history",
    "dividend_summary",
    "earnings_annual_trends",
    "earnings_history",
    "earnings_trends",
    "fund_holders",
    "highlights",
    "income_statements",
    "insider_transactions_snapshot",
    "institutional_holders",
    "outstanding_shares",
    "share_statistics",
    "splits_dividends",
    "technicals_snapshots",
    "valuation_ratios",
)


def _index_name(table: str) -> str:
    """Index name convention: ix_<table>_instrument_period."""
    return f"ix_{table}_instrument_period"


def upgrade() -> None:
    """Create the composite (instrument_id, period_end_date ASC) index on every existing table.

    Skips tables that don't exist in the target DB (defensive: ``dividend_summary``
    has an ORM model but no DDL in 001_initial_schema; will be created by a
    future migration when it ships as a real read table).
    """
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    for table in _TABLES:
        if table not in existing:
            continue
        op.create_index(
            _index_name(table),
            table,
            ["instrument_id", "period_end_date"],
            unique=False,
        )


def downgrade() -> None:
    """Drop the composite indexes; existing single-column indexes remain.

    Defensively skips tables that don't exist (mirrors upgrade()).
    """
    bind = op.get_bind()
    existing = set(inspect(bind).get_table_names())
    for table in _TABLES:
        if table not in existing:
            continue
        op.drop_index(_index_name(table), table_name=table)
