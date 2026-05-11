"""Add alert enrichment columns (PLAN-0049 T-A-1-01)

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-28

Adds four nullable VARCHAR columns to ``alerts`` and a partial index on
``ticker``. All forward-compatible (BP-007: no NOT NULL without server_default;
BP-019: additive only).

- title         VARCHAR(255)  NULL — pre-composed UI subject
- ticker        VARCHAR(20)   NULL — denormalised ticker for filtering
- entity_name   VARCHAR(500)  NULL — denormalised entity display name
- signal_label  VARCHAR(200)  NULL — derived signal label

The partial index ``idx_alerts_ticker`` only covers rows where ticker IS NOT NULL,
keeping it small (most alerts will have a ticker; older rows have NULL until backfilled).
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Use raw SQL with IF NOT EXISTS so re-running on a partially-applied DB
    # (e.g. local dev volume that has the columns from a prior plan attempt)
    # is a no-op rather than an error.
    op.execute("ALTER TABLE alerts ADD COLUMN IF NOT EXISTS title VARCHAR(255) NULL")
    op.execute("ALTER TABLE alerts ADD COLUMN IF NOT EXISTS ticker VARCHAR(20) NULL")
    op.execute("ALTER TABLE alerts ADD COLUMN IF NOT EXISTS entity_name VARCHAR(500) NULL")
    op.execute("ALTER TABLE alerts ADD COLUMN IF NOT EXISTS signal_label VARCHAR(200) NULL")
    op.execute("CREATE INDEX IF NOT EXISTS idx_alerts_ticker ON alerts (ticker) WHERE ticker IS NOT NULL")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_alerts_ticker")
    op.execute("ALTER TABLE alerts DROP COLUMN IF EXISTS signal_label")
    op.execute("ALTER TABLE alerts DROP COLUMN IF EXISTS entity_name")
    op.execute("ALTER TABLE alerts DROP COLUMN IF EXISTS ticker")
    op.execute("ALTER TABLE alerts DROP COLUMN IF EXISTS title")
