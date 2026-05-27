"""ANALYZE the 18 fundamentals section tables post-019 composite indexes.

Revision ID: 022
Revises: 021
Create Date: 2026-05-27

PLAN-0097 T-W3-01 (latency P1, audit `2026-05-27-plan-0097-latency-investigation.md`).

WHY THIS MIGRATION EXISTS:
  Migration 019 created composite ``(instrument_id, period_end_date)`` indexes
  on 18 fundamentals section tables — a textbook 30-100x speedup for the
  ``WHERE instrument_id = :iid ORDER BY period_end_date`` access pattern that
  dominates rag-chat fundamentals latency. But the indexes are *not used* on a
  freshly-migrated DB: the planner relies on ``pg_statistic`` row-count and
  selectivity estimates, and those statistics are only refreshed by autovacuum
  (lazily, hours later) or by an explicit ``ANALYZE``. Until then the planner
  may fall back to the older single-column ``ix_<table>_instrument_id`` btree
  plus an in-memory sort — exactly the slow path 019 was meant to replace.

  The latency investigation (§3 lines 102-118) confirmed that on the live DB,
  ``EXPLAIN`` on the section repository queries was still showing the
  single-column index + Sort node even hours after 019 ran. Forcing ``ANALYZE``
  immediately after creating the indexes guarantees the planner picks the new
  composite on the very next query.

  This is BP-577 (added with this migration): *whenever a migration adds an
  index intended to change a hot query plan, ship a paired ``ANALYZE`` so the
  speedup is realised on first traffic, not eventually*.

WHAT THIS MIGRATION DOES:
  Runs ``ANALYZE <table>`` for each of the 18 mixin-using fundamentals tables
  listed in migration 019. ANALYZE is idempotent and safe to re-run; the cost
  on a freshly-migrated dev/staging DB is sub-second per table because the
  tables are small.

WHY ``autocommit_block()``:
  ``ANALYZE`` cannot run inside an explicit transaction block — PostgreSQL
  rejects it with ``ANALYZE cannot run inside a transaction block`` (similar
  family to CREATE INDEX CONCURRENTLY per BP-393). The Alembic migration
  runner wraps every revision in a transaction by default; ``with
  op.get_context().autocommit_block()`` temporarily exits the transaction so
  ANALYZE can execute, then re-enters for the rest of the upgrade. We issue
  one ANALYZE per ``op.execute`` call (rather than concatenating with ``;``)
  because the autocommit block already gives us per-statement isolation and
  keeping them separate makes the operator log easier to read.

DOWNGRADE:
  No-op. ``ANALYZE`` updates statistics in place — there is nothing to undo,
  and re-running ANALYZE later (via autovacuum or manually) would re-derive
  fresh statistics anyway.
"""

from __future__ import annotations

from alembic import op

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


# Canonical list copied verbatim from migration 019. Keeping the duplicate
# (rather than importing 019's tuple) avoids a runtime dependency between
# migrations — Alembic revisions should be self-contained so a partial
# upgrade can be reasoned about in isolation.
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


def upgrade() -> None:
    """Force the planner to refresh statistics on every 019-indexed table."""
    # autocommit_block exits the migration's wrapping transaction so each
    # ANALYZE can execute (ANALYZE refuses to run inside a transaction block).
    with op.get_context().autocommit_block():
        for table in _TABLES:
            # Identifier is hardcoded above — not user input — so f-string
            # interpolation here is safe. ANALYZE takes only a table name, no
            # parameters, so we cannot bind it via :param syntax anyway.
            op.execute(f"ANALYZE {table}")


def downgrade() -> None:
    """No-op — ANALYZE updates statistics in place; there is nothing to revert."""
    # Intentional pass: a downgrade does not need to "un-analyze" because the
    # stats reflect actual row content, not migration state. Future autovacuum
    # cycles will continue to refresh stats normally.
