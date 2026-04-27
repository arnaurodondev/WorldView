"""Add is_partial column to ohlcv_bars.

Revision ID: 008
Revises: 007
Create Date: 2026-04-26

Adds a boolean ``is_partial`` flag to ``ohlcv_bars`` to mark bars whose
period is not yet complete (e.g. the current week/month).  Partial bars
are always derived — directly-ingested bars are never partial.

Forward-compatible: ``server_default='false'`` means all existing rows get
``is_partial=false`` with no data loss (BP-019).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "008"
down_revision = "007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ohlcv_bars",
        sa.Column("is_partial", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("ohlcv_bars", "is_partial")
