"""Add processed_events idempotency table for ArticleConsumer.

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-27
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS processed_events (
            event_id     UUID        PRIMARY KEY,
            processed_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_processed_events_processed_at ON processed_events (processed_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS processed_events")
