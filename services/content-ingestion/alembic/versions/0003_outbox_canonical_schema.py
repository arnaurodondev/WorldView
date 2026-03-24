"""Migrate outbox_events to canonical schema; drop dlq_events table.

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-23

Changes:
- Drop the non-canonical ``dlq_events`` table (dead-letter is now
  ``status='dead_letter'`` in ``outbox_events``)
- Add canonical lease + attempt columns: ``topic``, ``lease_owner``,
  ``leased_until``, ``attempts``, ``max_attempts``
- Drop deprecated columns: ``retry_count``, ``error``
- Add ``topic`` column (required by OutboxRecordProtocol)
- Migrate non-canonical status values:
    dispatched → delivered
    failed     → dead_letter
- Replace old index with canonical claimable partial index
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Drop the non-canonical separate DLQ table
    op.drop_table("dlq_events")

    # 2. Add canonical columns
    op.add_column(
        "outbox_events",
        sa.Column("topic", sa.Text(), nullable=False, server_default="content.article.raw.v1"),
    )
    op.add_column("outbox_events", sa.Column("lease_owner", sa.Text(), nullable=True))
    op.add_column(
        "outbox_events",
        sa.Column("leased_until", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "outbox_events",
        sa.Column("attempts", sa.SmallInteger(), nullable=False, server_default="0"),
    )
    op.add_column(
        "outbox_events",
        sa.Column("max_attempts", sa.SmallInteger(), nullable=False, server_default="5"),
    )

    # 3. Migrate non-canonical status values
    op.execute("UPDATE outbox_events SET status = 'delivered'   WHERE status = 'dispatched'")
    op.execute("UPDATE outbox_events SET status = 'dead_letter' WHERE status = 'failed'")

    # 4. Drop deprecated columns
    op.drop_column("outbox_events", "retry_count")
    op.drop_column("outbox_events", "error")

    # 5. Replace old index with canonical claimable partial index
    op.drop_index("ix_outbox_events_status_created_at", table_name="outbox_events")
    op.execute(
        """
        CREATE INDEX ix_outbox_claimable ON outbox_events (status, leased_until)
        WHERE status IN ('pending', 'processing')
        """
    )


def downgrade() -> None:
    # Downgrade not supported — destructive schema change
    raise NotImplementedError("Downgrade of outbox canonical schema migration is not supported")
