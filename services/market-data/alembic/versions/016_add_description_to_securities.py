"""Add description column to securities.

Revision ID: 016
Revises: 015
Create Date: 2026-05-05

Changes:
  securities:
    - ADD COLUMN description TEXT NULL

WHY:
  PLAN-0073 Sub-Plan B (Wave B-0) — Worker 13J (StructuredEnrichmentWorker) calls
  the new GET /api/v1/instruments/on-demand-profile endpoint which fetches
  EODHD General.Description and persists it to this column.

  Having description on securities (rather than instruments) keeps it at the
  security level — all exchange listings of the same company share one description.

FORWARD-COMPATIBILITY (R5):
  Nullable column with no DEFAULT. Existing rows have description = NULL.
  No existing consumer reads this column so no code changes are required
  alongside this DDL.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "016"
down_revision = "015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("securities", sa.Column("description", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("securities", "description")
