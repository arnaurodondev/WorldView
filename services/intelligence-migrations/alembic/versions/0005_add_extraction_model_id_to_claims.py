"""Add extraction_model_id to claims (PLAN-0031 B-2).

Revision ID: 0005
Revises: d4e5f6a1b2c3
Create Date: 2026-04-20

Tracks which Qwen/LLM model produced each claim row.  Nullable with
server_default='unknown' so existing rows are backfilled automatically.

Downtime: zero — additive column with server_default.
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "d4e5f6a1b2c3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "claims",
        sa.Column("extraction_model_id", sa.String(100), nullable=True, server_default="unknown"),
    )


def downgrade() -> None:
    op.drop_column("claims", "extraction_model_id")
