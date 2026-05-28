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

import sqlalchemy as sa
from alembic import op

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


# Canonical seed list mirrors ``app.py::_get_static_screen_fields()`` Wave
# L-4a block (added in lock-step by T-WL4A-04). Each tuple is:
#   (field_name, label, field_type, unit, description)
# Keep these aligned with the application's in-memory list — divergence will
# cause the 6-hour ``_screen_fields_refresh_loop`` to overwrite this
# migration's rows with (possibly different) values
# (see ``024_seed_l2_snapshot_screen_fields.py:25-31`` for the same warning).
_L4A_FIELDS: tuple[tuple[str, str, str, str | None, str], ...] = (
    (
        "analyst_target_price",
        "ANALYST TGT",
        "numeric",
        "USD",
        "Analyst consensus 12-month target price (USD)",
    ),
    (
        "analyst_consensus_rating",
        "CONSENSUS",
        "numeric",
        "1-5",
        "Analyst consensus rating on a 1-5 scale (higher = more bullish)",
    ),
    (
        "institutional_ownership_pct",
        "INST OWN%",
        "numeric",
        "%",
        "Institutional ownership as a decimal fraction of shares outstanding",
    ),
    (
        "short_percent",
        "SHORT %",
        "numeric",
        "%",
        "Short interest as a decimal fraction of float",
    ),
)


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

    # ── Seed screen_field_metadata rows (idempotent) ─────────────────────────
    # Matches the L-2 seed pattern in ``024_seed_l2_snapshot_screen_fields.py``.
    # ON CONFLICT DO NOTHING makes re-runs safe; the bootstrap refresh loop
    # in ``app.py`` will subsequently UPSERT these every 6 hours from the
    # canonical in-memory list (kept in lock-step by this same task).
    seed_sql = (
        "INSERT INTO screen_field_metadata "
        "(field_name, label, field_type, unit, description, null_fraction) "
        "VALUES (:field_name, :label, :field_type, :unit, :description, 0) "
        "ON CONFLICT (field_name) DO NOTHING"
    )
    for field_name, label, field_type, unit, description in _L4A_FIELDS:
        op.execute(
            sa.text(seed_sql).bindparams(
                field_name=field_name,
                label=label,
                field_type=field_type,
                unit=unit,
                description=description,
            )
        )


def downgrade() -> None:
    """Drop the 4 columns + delete the 4 seeded rows.

    Column drops use ``IF EXISTS`` for safety. Seed deletes target only the
    four ``field_name`` keys we inserted so operators or other migrations
    that may have inserted under the same key are not affected.
    """
    delete_sql = "DELETE FROM screen_field_metadata WHERE field_name = :field_name"
    for field_name, *_ in _L4A_FIELDS:
        op.execute(sa.text(delete_sql).bindparams(field_name=field_name))

    op.execute("ALTER TABLE instrument_fundamentals_snapshot DROP COLUMN IF EXISTS short_percent")
    op.execute("ALTER TABLE instrument_fundamentals_snapshot DROP COLUMN IF EXISTS institutional_ownership_pct")
    op.execute("ALTER TABLE instrument_fundamentals_snapshot DROP COLUMN IF EXISTS analyst_consensus_rating")
    op.execute("ALTER TABLE instrument_fundamentals_snapshot DROP COLUMN IF EXISTS analyst_target_price")
