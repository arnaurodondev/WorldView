"""Add functional index on transactions(portfolio_id, (executed_at AT TIME ZONE 'UTC')::date).

Revision ID: 0027
Revises: 0026
Create Date: 2026-06-21

DP-003 fix: the existing composite index ix_transactions_portfolio_executed_instrument
covers (portfolio_id, executed_at, instrument_id) using the raw TIMESTAMPTZ column.
However, _build_filter_clauses() applies a date-cast predicate for the from_date /
to_date filter parameters (BP-180 guard: asyncpg rejects bare datetime comparisons
with date parameters).  PostgreSQL's query planner may not use the existing index for
a date-cast expression on the executed_at column, falling back to a partial scan for
date-range queries that include a portfolio_id but use the date cast.

This migration adds a dedicated functional index on
``(portfolio_id, (executed_at AT TIME ZONE 'UTC')::date)`` so date-range filter queries
(used by ListTransactionsUseCase and ExportTransactionsUseCase) can be satisfied
without a full-table scan on large portfolios.

WHY ``AT TIME ZONE 'UTC'`` AND NOT A BARE ``CAST(... AS DATE)`` (the original bug):
  PostgreSQL refuses to index ``CAST(timestamptz AS date)`` because that cast depends
  on the session ``TimeZone`` GUC and is therefore NOT IMMUTABLE
  ("functions in index expression must be marked IMMUTABLE").  Pinning the conversion
  to a fixed zone — ``(executed_at AT TIME ZONE 'UTC')::date`` — is immutable and
  indexable.  ``_build_filter_clauses()`` is updated in lockstep to emit the same
  expression so the planner actually uses this index (all stored timestamps are UTC,
  so the date boundary is unchanged).

WHY CONCURRENTLY: the transactions table can be large in production; a plain
CREATE INDEX would take a full ACCESS SHARE lock during the build.  CONCURRENTLY
allows concurrent reads and writes at the cost of slightly longer build time.

Rollback:
  DROP INDEX CONCURRENTLY IF EXISTS is safe — queries fall back to seq-scan.
  The ORM query in _build_filter_clauses() continues to work correctly, just slower.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None

# WHY string literal for the index name: it must match what we DROP in downgrade().
_INDEX_NAME = "ix_transactions_portfolio_executed_date"


def upgrade() -> None:
    """Add functional index on transactions(portfolio_id, CAST(executed_at AS DATE)).

    Uses CREATE INDEX CONCURRENTLY (no table lock) in production.  Falls back to
    a plain CREATE INDEX inside the existing transaction for test/CI environments
    where AUTOCOMMIT isolation_level changes are rejected by the transaction wrapper.
    """
    conn = op.get_bind()
    try:
        # Production path: AUTOCOMMIT required for CONCURRENTLY.
        conn.execution_options(isolation_level="AUTOCOMMIT").execute(
            sa.text(
                f"""
                CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX_NAME}
                    ON transactions (portfolio_id, ((executed_at AT TIME ZONE 'UTC')::date))
                """  # -- not user input, safe literal
            ),
        )
    except Exception:
        # Test/CI path: plain index inside the existing transaction.
        conn.execute(
            sa.text(
                f"""
                CREATE INDEX IF NOT EXISTS {_INDEX_NAME}
                    ON transactions (portfolio_id, ((executed_at AT TIME ZONE 'UTC')::date))
                """  # -- not user input, safe literal
            ),
        )


def downgrade() -> None:
    """Drop the functional date filter index."""
    conn = op.get_bind()
    try:
        conn.execution_options(isolation_level="AUTOCOMMIT").execute(
            sa.text(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX_NAME}"),
        )
    except Exception:
        conn.execute(sa.text(f"DROP INDEX IF EXISTS {_INDEX_NAME}"))
