"""Add Wave L-4a snapshot columns to ``instrument_fundamentals_snapshot``.

Revision ID: 025
Revises: 024
Create Date: 2026-05-28

PLAN-0089 Wave L-4a (T-WL4A-01 / T-WL4A-04).

WHY THIS MIGRATION EXISTS:
  Wave L-4a surfaces four screener-relevant fields that are already ingested
  as JSONB (``analyst_consensus`` and ``share_statistics`` sections from the
  EODHD ``/fundamentals`` payload) but never projected into a screenable
  numeric column. The audit at
  ``docs/audits/2026-05-28-wave-l4-scope-investigation.md`` confirms the
  source data is present; only the extraction/projection is missing.

  The four new columns are:
    * ``analyst_target_price``       — USD (NUMERIC 18,4)
    * ``analyst_consensus_rating``   — 1-5 scale, higher = more bullish (NUMERIC 4,2)
    * ``institutional_ownership_pct``— decimal fraction, e.g. 0.743 (NUMERIC 8,6)
    * ``short_percent``              — decimal fraction, e.g. 0.034 (NUMERIC 8,6)

  Unit normalisation (consistent with fcf_margin from L-2): both percent
  fields are stored as fractions (0.0-1.0+), not as percent values. See
  ``InstrumentFundamentalsSnapshotModel`` docstrings and the metric
  extractor for the per-field source-→ target conversion.

  The migration is intentionally idempotent (``ADD COLUMN IF NOT EXISTS``)
  so it is safe to re-run against partially-upgraded databases.

  T-WL4A-04 extends this migration with idempotent seed inserts into
  ``screen_field_metadata`` — keep those rows in lock-step with
  ``app.py::_get_static_screen_fields()`` (the 6-hour refresh loop will
  otherwise overwrite the seeded values).

FORWARD-COMPAT (R11): all new columns are NULLABLE; no renames or drops.
"""

from __future__ import annotations

from alembic import op

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the 4 new L-4a columns to ``instrument_fundamentals_snapshot``.

    Uses ``ADD COLUMN IF NOT EXISTS`` so the migration is idempotent — safe
    to re-run against environments where part of the column set has already
    been added (e.g. by a hot-fix or by a previous failed migration attempt
    that committed partial DDL).
    """
    op.execute(
        "ALTER TABLE instrument_fundamentals_snapshot "
        "ADD COLUMN IF NOT EXISTS analyst_target_price NUMERIC(18, 4) NULL"
    )
    op.execute(
        "ALTER TABLE instrument_fundamentals_snapshot "
        "ADD COLUMN IF NOT EXISTS analyst_consensus_rating NUMERIC(4, 2) NULL"
    )
    op.execute(
        "ALTER TABLE instrument_fundamentals_snapshot "
        "ADD COLUMN IF NOT EXISTS institutional_ownership_pct NUMERIC(8, 6) NULL"
    )
    op.execute(
        "ALTER TABLE instrument_fundamentals_snapshot " "ADD COLUMN IF NOT EXISTS short_percent NUMERIC(8, 6) NULL"
    )


def downgrade() -> None:
    """Drop the 4 columns added in :func:`upgrade`.

    ``DROP COLUMN IF EXISTS`` keeps the downgrade safe against environments
    where the column was already removed manually.
    """
    op.execute("ALTER TABLE instrument_fundamentals_snapshot DROP COLUMN IF EXISTS short_percent")
    op.execute("ALTER TABLE instrument_fundamentals_snapshot DROP COLUMN IF EXISTS institutional_ownership_pct")
    op.execute("ALTER TABLE instrument_fundamentals_snapshot DROP COLUMN IF EXISTS analyst_consensus_rating")
    op.execute("ALTER TABLE instrument_fundamentals_snapshot DROP COLUMN IF EXISTS analyst_target_price")
