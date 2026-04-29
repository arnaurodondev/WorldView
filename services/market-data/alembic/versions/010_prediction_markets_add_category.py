"""add category to prediction_markets

Revision ID: 010
Revises: 009
Create Date: 2026-04-29

PLAN-0049 T-C-3-03 / PLAN-0050 F-D-005.

WHY: PLAN-0050 wants the dashboard prediction-markets widget to filter by
high-level category (``macro``, ``politics``, ``sports``, ``crypto``,
``general``).  The Polymarket Gamma API exposes such a tag on each event
but our Avro pipeline does not yet carry it; this migration lays the
schema groundwork so the API can accept the query param today and the
adapter can start populating the column in a later wave without another
migration round.

Forward-compat / BP-126: column is NULLABLE with NO server_default, which
makes the ALTER a metadata-only catalogue change (no full-table rewrite).
NULL means "category not yet known" — the LIST query treats it as
"matches no category filter", which is the desired behaviour.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "010"
down_revision = "009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Use IF NOT EXISTS so re-running on a partially-applied dev volume is
    # a no-op (common when iterating on local migrations).  String length
    # capped at 50 — Polymarket's published taxonomy fits comfortably and
    # we'd rather error loudly than silently truncate a future tag.
    op.execute(
        "ALTER TABLE prediction_markets ADD COLUMN IF NOT EXISTS category VARCHAR(50) NULL",
    )
    # Partial index — only rows that have a category benefit from the
    # index, which keeps it small (most rows will be NULL for now).
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_prediction_markets_category "
        "ON prediction_markets (category) WHERE category IS NOT NULL",
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_prediction_markets_category")
    op.execute("ALTER TABLE prediction_markets DROP COLUMN IF EXISTS category")
