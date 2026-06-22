"""Add cost_basis_method column to portfolios table.

Revision ID: 0024
Revises: 0023
Create Date: 2026-06-20

PLAN-0114 W6 / T-W1-02:
Adds ``cost_basis_method VARCHAR(8) NOT NULL DEFAULT 'FIFO'`` to ``portfolios``.

This column drives the per-portfolio cost basis accounting method used by
``ComputeManualHoldingsUseCase`` (FIFO vs AVCO). All existing rows are
backfilled to 'FIFO' via the server_default — no data migration needed.

Safety:
- Additive column with NOT NULL + server_default → zero-downtime safe.
- No foreign keys, no enum constraint (domain enum handles validation).
- Rollback: drop the column (backward-compatible because no NOT NULL without
  default was added to a column callers relied on).

BP-126 compliance: NOT NULL column has both server_default AND ORM-level
  mapped_column default='FIFO' so new INSERTs from the ORM work without
  explicitly setting the field.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # WHY server_default='FIFO': existing rows in production need a valid
    # NOT NULL value backfilled atomically. Using server_default avoids a
    # separate UPDATE statement and ensures the column is always consistent
    # even when the application code hasn't set it yet (safe during a
    # rolling deploy where some instances run old code). BP-126 compliance.
    op.add_column(
        "portfolios",
        sa.Column(
            "cost_basis_method",
            sa.String(length=8),
            nullable=False,
            server_default="FIFO",
        ),
    )


def downgrade() -> None:
    op.drop_column("portfolios", "cost_basis_method")
