"""Add partial composite index on ohlcv_bars(instrument_id, bar_date DESC) WHERE timeframe='daily'.

Revision ID: 033
Revises: 032
Create Date: 2026-06-06

WHY THIS MIGRATION EXISTS:

The three computed S9 endpoints (multi-period-returns, price-levels,
intraday-stats) all query ``ohlcv_bars`` with a filter of
``timeframe = '1d'`` and a date-range bound on ``bar_date``.

The existing ``ix_ohlcv_bars_instrument_bar_date`` index covers
``(instrument_id, bar_date)`` but does NOT include ``timeframe`` in the
predicate, so the planner must apply the ``timeframe = '1d'`` filter as
a heap re-check after the index scan.

The primary key ``(instrument_id, timeframe, bar_date)`` is a valid
alternative but its leading ``timeframe`` column cannot be used as a
prefix when the query binds ``instrument_id`` first.

A partial index ``WHERE timeframe = 'daily'`` lets the planner:
  1. Eliminate all non-daily rows from the index structure entirely.
  2. Satisfy the ``instrument_id`` + ``bar_date`` range scan with no
     extra heap re-check step.
  3. Order DESC naturally for the LIMIT-pushdown path introduced in
     the companion repository change (find_by_instrument_timeframe_range
     with limit= now uses ORDER BY bar_date DESC LIMIT N).

NOTE: ``CONCURRENTLY`` is NOT supported on TimescaleDB hypertables.
The ``ohlcv_bars`` table is a hypertable (migration 002 converts it).
Therefore we use a plain ``CREATE INDEX IF NOT EXISTS`` which runs inside
the Alembic transaction normally.  This momentarily locks the parent
table during index creation; in practice the lock is brief because
TimescaleDB creates the index on each chunk individually and the overall
DDL completes fast.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "033"
down_revision: str = "032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # WHY partial index: the three computed S9 endpoints (multi-period-returns,
    # price-levels, intraday-stats) always filter timeframe='1d'.  A partial
    # index on daily bars only avoids scanning intraday chunks and lets the
    # planner satisfy ORDER BY bar_date DESC LIMIT N via an index-only scan.
    # WHY NOT CONCURRENTLY: TimescaleDB hypertables do not support concurrent
    # index creation (ERROR: hypertables do not support concurrent index creation).
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ohlcv_bars_instr_bar_date "
        "ON ohlcv_bars(instrument_id, bar_date DESC) "
        "WHERE timeframe = '1d'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_ohlcv_bars_instr_bar_date")
