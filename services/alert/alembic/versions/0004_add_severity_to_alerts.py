"""Add severity column to alerts table

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-10

Changes:
- alerts: add severity VARCHAR(10) NOT NULL DEFAULT 'low' (PRD-0021 Wave A-2)
- Create index idx_alerts_severity on (severity, created_at DESC) for filter queries
"""

from alembic import op

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add severity column with server default — zero-downtime safe on Postgres:
    # existing rows receive 'low' via the server default without a table rewrite.
    op.execute("ALTER TABLE alerts ADD COLUMN severity VARCHAR(10) NOT NULL DEFAULT 'low'")
    op.execute("CREATE INDEX idx_alerts_severity ON alerts (severity, created_at DESC)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_alerts_severity")
    op.execute("ALTER TABLE alerts DROP COLUMN severity")
