"""Wave L-5c: add calendar columns to ``instrument_fundamentals_snapshot``
and seed two ``screen_field_metadata`` rows.

Revision ID: 028
Revises: 024
Create Date: 2026-05-28

PLAN-0089 Wave L-5c (Calendar fields backend) — sibling waves L-3/L-4a/L-4b
hold revisions 025/026/027 on parallel branches; this migration claims the
next free integer **028** and chains directly from 024. The migration
graph is re-linearised on merge by the integrator (a no-op rebase since
each sibling only ALTERs distinct columns and seeds distinct
``screen_field_metadata`` rows). Choosing 028 (rather than 025) avoids
collisions while still giving us a clean, single-file migration to test
in this worktree.

WHAT THIS MIGRATION DOES
========================

1) Adds two nullable DATE columns to ``instrument_fundamentals_snapshot``:

     * ``next_earnings_date DATE NULL`` — the next scheduled earnings
       report (sourced from the ``earnings_calendar`` table by the
       snapshot writer; L-5b worker that populates the calendar table is
       deferred, so values stay NULL in the short term).
     * ``next_dividend_date DATE NULL`` — the next dividend payment date
       (sourced from EODHD ``SplitsDividends.DividendDate`` in the
       fundamentals JSONB payload by the snapshot writer).

   Both are nullable for R11 forward-compatibility and because the
   underlying sources are sparse (ETFs / non-dividend payers /
   non-earnings reporters all stay NULL).

2) Adds two BTREE indexes for range queries ("earnings within N days"):

     * ``ix_ifs_next_earnings_date`` on (``next_earnings_date``)
     * ``ix_ifs_next_dividend_date`` on (``next_dividend_date``)

   PARTIAL indexes (WHERE col IS NOT NULL) keep the index small —
   ~95% of rows will have NULL values until L-5b lands.

3) Idempotent: every column / index DDL uses ``IF NOT EXISTS`` so the
   migration is safe to re-run.

4) Seeds two rows in ``screen_field_metadata`` (mirroring L-2 migration
   024 pattern, ON CONFLICT DO NOTHING). LOCK-STEP with the in-memory
   list at ``services/market-data/src/market_data/app.py
   ::_get_static_screen_fields()`` — divergence would let the 6-hour
   refresh loop overwrite our seeded rows.

   field_type uses ``numeric`` (not ``date``) because the CHECK
   constraint ``ck_screen_field_metadata_field_type`` admits only
   ``numeric`` and ``text``. The UI filter is a number-of-days input
   (``next_earnings_within_days``), so numeric semantics map cleanly.

DOWNGRADE
=========
Drops the two indexes, the two columns, and removes the two
``screen_field_metadata`` rows. Other rows in the table are untouched —
the DELETE is keyed by the two specific ``field_name`` values.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "028"
down_revision = "025"
branch_labels = None
depends_on = None


# Canonical seed list mirrors ``app.py::_get_static_screen_fields()`` Wave
# L-5c block. Each tuple: (field_name, label, field_type, unit, description).
# LOCK-STEP with the in-memory list — divergence will cause the 6-hour
# refresh loop to overwrite this migration's rows on the next tick.
_L5C_FIELDS: tuple[tuple[str, str, str, str | None, str], ...] = (
    (
        "next_earnings_date",
        "NEXT EARN",
        "numeric",
        "date",
        "Next scheduled earnings report date (filter accepts days-from-today)",
    ),
    (
        "next_dividend_date",
        "NEXT DIV",
        "numeric",
        "date",
        "Next scheduled dividend payment date (filter accepts days-from-today)",
    ),
)


def upgrade() -> None:
    """Idempotent column + index DDL + screen_field_metadata seed."""
    # ── 1) Columns ──────────────────────────────────────────────────────────
    op.execute("ALTER TABLE instrument_fundamentals_snapshot " "ADD COLUMN IF NOT EXISTS next_earnings_date DATE NULL")
    op.execute("ALTER TABLE instrument_fundamentals_snapshot " "ADD COLUMN IF NOT EXISTS next_dividend_date DATE NULL")

    # ── 2) Indexes (partial, NULL-excluding for compactness) ────────────────
    # WHY partial: until the L-5b worker lands, ~100% of rows have NULLs in
    # these columns. A full BTREE would index NULLs (PostgreSQL does), wasting
    # space and slowing INSERTs. The partial predicate also makes the planner
    # prefer the index for ``WHERE next_earnings_date BETWEEN ...`` queries.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ifs_next_earnings_date "
        "ON instrument_fundamentals_snapshot (next_earnings_date) "
        "WHERE next_earnings_date IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_ifs_next_dividend_date "
        "ON instrument_fundamentals_snapshot (next_dividend_date) "
        "WHERE next_dividend_date IS NOT NULL"
    )

    # ── 3) screen_field_metadata seed ───────────────────────────────────────
    # Parameter-bound INSERT — no string interpolation of values, and the
    # static field-list (above) means there is no user input anywhere.
    sql = (
        "INSERT INTO screen_field_metadata "
        "(field_name, label, field_type, unit, description, null_fraction) "
        "VALUES (:field_name, :label, :field_type, :unit, :description, 0) "
        "ON CONFLICT (field_name) DO NOTHING"
    )
    for field_name, label, field_type, unit, description in _L5C_FIELDS:
        op.execute(
            sa.text(sql).bindparams(
                field_name=field_name,
                label=label,
                field_type=field_type,
                unit=unit,
                description=description,
            )
        )


def downgrade() -> None:
    """Reverse of upgrade — drop indexes, columns, and seeded rows."""
    # Delete only the rows this migration seeded (keyed by field_name).
    delete_sql = "DELETE FROM screen_field_metadata WHERE field_name = :field_name"
    for field_name, *_ in _L5C_FIELDS:
        op.execute(sa.text(delete_sql).bindparams(field_name=field_name))

    op.execute("DROP INDEX IF EXISTS ix_ifs_next_earnings_date")
    op.execute("DROP INDEX IF EXISTS ix_ifs_next_dividend_date")
    op.execute("ALTER TABLE instrument_fundamentals_snapshot " "DROP COLUMN IF EXISTS next_earnings_date")
    op.execute("ALTER TABLE instrument_fundamentals_snapshot " "DROP COLUMN IF EXISTS next_dividend_date")
