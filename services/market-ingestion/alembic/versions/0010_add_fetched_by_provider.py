"""Add fetched_by_provider column to ingestion_tasks.

Revision ID: 0010
Revises: 0009
Create Date: 2026-04-26

Tracks which provider actually fetched the data for a given task.
When multi-provider routing is active the fetched_by_provider may differ
from the task's original provider (the "assigned" provider).

Also adds a partial index for the reclaim worker that needs to find
SUCCEEDED tasks with a known fetched_by_provider efficiently.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE ingestion_tasks ADD COLUMN fetched_by_provider VARCHAR(50);")
    op.execute(
        "CREATE INDEX ix_ingestion_tasks_reclaim "
        "ON ingestion_tasks (status, fetched_by_provider) "
        "WHERE status = 'succeeded' AND fetched_by_provider IS NOT NULL;"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_ingestion_tasks_reclaim;")
    op.execute("ALTER TABLE ingestion_tasks DROP COLUMN IF EXISTS fetched_by_provider;")
