"""Add next_attempt_at to content_ingestion_tasks for EODHD retry backoff.

Revision ID: 0005_add_next_attempt_at_cit
Revises: 0004
Create Date: 2026-04-24

WHY: EODHD returns 429 responses when rate-limited. Without next_attempt_at,
S4 tasks immediately retry, causing a retry storm. This column stores the
earliest time the task may be retried, respecting the Retry-After header.
"""

import sqlalchemy as sa
from alembic import op

# revision identifiers
revision: str = "0005_add_next_attempt_at_cit"
down_revision: str = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "content_ingestion_tasks",
        sa.Column(
            "next_attempt_at",
            sa.TIMESTAMP(timezone=True),
            nullable=True,
            comment="Earliest time this task may be retried (Retry-After backoff).",
        ),
    )
    # Index for the scheduler query:
    # WHERE status IN ('PENDING','RETRY') AND (next_attempt_at IS NULL OR next_attempt_at <= now())
    op.create_index(
        "ix_cit_next_attempt_at",
        "content_ingestion_tasks",
        ["next_attempt_at"],
        postgresql_where=sa.text("next_attempt_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_cit_next_attempt_at", table_name="content_ingestion_tasks")
    op.drop_column("content_ingestion_tasks", "next_attempt_at")
