"""Add relation_source column to relations (partitioned table).

Revision ID: 0024
Revises: 0023
Create Date: 2026-05-05

Changes:
  relations (+ all 8 hash partitions relations_p0..p7):
    - ADD COLUMN relation_source TEXT NULL

WHY:
  PLAN-0073 Worker 13J seeds structural relations with provenance:
    relation_source = 'structured_enrichment'

  Knowing the origin of each relation edge is essential for quality audits.
  Structured enrichment relations (sector, country, exchange) should be
  distinguishable from NLP-extracted ('llm_extraction') and manually curated
  ('manual') relations for downstream filtering and scoring.

  PostgreSQL 16 propagates ADD COLUMN to all child partitions automatically when
  the column is nullable with no DEFAULT constraint -- no per-partition DDL needed.

FORWARD-COMPATIBILITY (R5):
  Nullable column. All existing relations rows have relation_source = NULL,
  which semantically means "pre-enrichment / unknown origin". No existing
  consumer reads this column so no code changes are required alongside this DDL.

ADR-0073-004: relations is hash-partitioned 8-ways -- nullable ADD COLUMN is
  safe on PG16; MUST NOT add NOT NULL without a default.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL 16 propagates this to all 8 child partitions automatically.
    op.add_column("relations", sa.Column("relation_source", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("relations", "relation_source")
