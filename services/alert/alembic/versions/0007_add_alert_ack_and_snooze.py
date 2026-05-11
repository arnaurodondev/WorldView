"""Add alert acknowledgement + snooze columns (PLAN-0051 T-D-4-01).

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-29

Adds three nullable columns to ``alerts`` and a partial index optimised for the
"active alerts" query pattern (``acknowledged_at IS NULL AND
(snooze_until IS NULL OR snooze_until < NOW())``).

All columns are nullable with no server_default — forward-compatible (BP-007:
NOT NULL columns require server_default; we sidestep by staying nullable).
Existing rows will simply read NULL for these new columns.

- acknowledged_at         TIMESTAMPTZ  NULL — when the user acknowledged the alert
- acknowledged_by_user_id UUID         NULL — which user acknowledged it
- snooze_until            TIMESTAMPTZ  NULL — alert hidden from active list until this time

The partial index ``idx_alerts_unack_unsnoozed`` covers ``(severity,
created_at DESC)`` for rows where ``acknowledged_at IS NULL`` so that the
"active alerts" filter in ``GET /v1/alerts/history?status=active`` is fast.
NOTE: NOW() is not IMMUTABLE so it cannot appear in a partial-index predicate;
we therefore index by ``acknowledged_at IS NULL`` only and let the planner
prune snoozed rows from the smaller subset at query time.
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Use IF NOT EXISTS for idempotency on partially-applied dev DBs (mirrors 0006).
    op.execute("ALTER TABLE alerts ADD COLUMN IF NOT EXISTS acknowledged_at TIMESTAMPTZ NULL")
    op.execute("ALTER TABLE alerts ADD COLUMN IF NOT EXISTS acknowledged_by_user_id UUID NULL")
    op.execute("ALTER TABLE alerts ADD COLUMN IF NOT EXISTS snooze_until TIMESTAMPTZ NULL")
    # Partial index — only WHERE acknowledged_at IS NULL because NOW() is not IMMUTABLE
    # and cannot appear in a partial-index predicate. The planner can still scan a
    # narrow subset (un-acked rows) and filter by snooze_until at query time.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_alerts_unack_unsnoozed "
        "ON alerts (severity, created_at DESC) "
        "WHERE acknowledged_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_alerts_unack_unsnoozed")
    op.execute("ALTER TABLE alerts DROP COLUMN IF EXISTS snooze_until")
    op.execute("ALTER TABLE alerts DROP COLUMN IF EXISTS acknowledged_by_user_id")
    op.execute("ALTER TABLE alerts DROP COLUMN IF EXISTS acknowledged_at")
