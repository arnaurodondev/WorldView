"""Add ``eps_ttm_source`` and ``beta_source`` to ``instrument_fundamentals_snapshot``.

PLAN-0053 T-C-3-02 — Alpha Vantage fundamentals fallback.

WHY THIS MIGRATION:
  The fundamentals backfill script (services/market-ingestion/scripts/
  backfill_fundamentals.py) now falls back to Alpha Vantage's OVERVIEW
  endpoint when EODHD returns NULL for ``eps_ttm`` or ``beta``.  To keep an
  honest audit trail per field we add two TEXT columns recording the
  source.  Possible values (free-form, not enum-constrained on purpose):

      - "eodhd"          → value came from EODHD highlights/technicals
      - "alpha_vantage"  → fallback path filled the value
      - "none"           → neither provider had data
      - NULL             → row predates this migration / source unknown

  Forward-compatibility: both columns are nullable with no server_default,
  so existing rows surface as NULL until the next backfill run reseeds the
  source column.  R5 — adding nullable columns is forward-compatible.

  IDEMPOTENT: uses ``IF NOT EXISTS`` so re-runs are no-ops; the rollback
  uses ``IF EXISTS`` so dropping is safe even if upgrade was partially
  applied.
"""

from __future__ import annotations

from alembic import op

# Revision identifiers — chains after migration 012 to keep linear ordering.
revision = "013"
down_revision = "012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # WHY raw SQL (vs op.add_column): IF NOT EXISTS keeps the migration safely
    # idempotent across local dev DBs that may be at different states.
    op.execute(
        """
        ALTER TABLE instrument_fundamentals_snapshot
        ADD COLUMN IF NOT EXISTS eps_ttm_source TEXT
        """
    )
    op.execute(
        """
        ALTER TABLE instrument_fundamentals_snapshot
        ADD COLUMN IF NOT EXISTS beta_source TEXT
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE instrument_fundamentals_snapshot
        DROP COLUMN IF EXISTS beta_source
        """
    )
    op.execute(
        """
        ALTER TABLE instrument_fundamentals_snapshot
        DROP COLUMN IF EXISTS eps_ttm_source
        """
    )
