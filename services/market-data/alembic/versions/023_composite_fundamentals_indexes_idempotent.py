"""Idempotent re-application of the composite (instrument_id, period_end_date)
indexes from migration 019 — defensive no-op for fresh DBs.

Revision ID: 023
Revises: 022
Create Date: 2026-05-27

PLAN-0097 T-W4-02 (P2 item 3, BP-130 pattern).

WHY THIS MIGRATION EXISTS:
  Migration 019 created 18 composite indexes with ``op.create_index``, which
  emits a plain ``CREATE INDEX`` (no IF NOT EXISTS). If 019 failed partway
  through (e.g. a single ``CREATE INDEX`` raised because the index already
  existed from a hot-fix outside Alembic), the migration cannot be re-run:
  the second invocation immediately errors on the first already-present
  index.

  We do NOT amend 019 itself — committed migrations are immutable contracts
  (R5 spirit). Instead, this 023 walks the same 18-table list and issues
  ``CREATE INDEX IF NOT EXISTS`` for each. On a fresh database where 019
  ran to completion, every statement is a no-op. On a partial-failure-and-
  rerun database, this migration rescues the missing indexes without manual
  ops intervention.

WHY DEPENDENT ON 022 (not directly on 019):
  022 is the most recent Alembic head (``VACUUM ANALYZE`` of the same
  fundamentals tables). We chain to 022 so the linear migration history is
  preserved and ``alembic upgrade head`` runs both in the correct order.

DOWNGRADE: no-op. Dropping these indexes here would also drop the indexes
019 created — we intentionally do not own that lifecycle. Operators who
truly want the indexes gone should downgrade past 019.
"""

from __future__ import annotations

from alembic import op

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


# Canonical list copied verbatim from migration 019 (and 022). Each entry is
# a mixin-using fundamentals section table that has the composite
# (instrument_id, period_end_date) index from 019.
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
    """Index name convention: ix_<table>_instrument_period — same as 019."""
    return f"ix_{table}_instrument_period"


def upgrade() -> None:
    """Re-create every composite index with ``IF NOT EXISTS`` so a partial
    failure of 019 can be rescued by simply re-running ``alembic upgrade head``.

    Each statement is a no-op on a healthy DB.
    """
    for table in _TABLES:
        # Static identifiers from a hard-coded whitelist — no user input.
        op.execute(
            f'CREATE INDEX IF NOT EXISTS "{_index_name(table)}" ' f'ON "{table}" (instrument_id, period_end_date ASC)'
        )


def downgrade() -> None:
    """No-op — see module docstring (R5 + immutable-migration rationale)."""
    return
