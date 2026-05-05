"""Add enrichment fields to canonical_entities.

Revision ID: 0022
Revises: 0021
Create Date: 2026-05-05

Changes:
  canonical_entities:
    - ADD COLUMN description TEXT NULL
    - ADD COLUMN data_completeness DOUBLE PRECISION NULL
    - ADD COLUMN enriched_at TIMESTAMPTZ NULL
    - ADD COLUMN enrichment_attempts INTEGER NOT NULL DEFAULT 0
  indexes:
    - CREATE INDEX CONCURRENTLY ix_canonical_entities_enrichment_sweep

WHY:
  PLAN-0073 Worker 13J (StructuredEnrichmentWorker) enriches canonical entities
  via a three-source cascade (S3 DB lookup → EODHD on-demand → LLM). These columns
  store the enrichment output and drive the periodic sweep query:
    WHERE (enriched_at IS NULL OR data_completeness < 0.5)
      AND enrichment_attempts < 3

  The `enrichment_attempts` counter caps permanent failures at 3 retries to
  prevent infinite retry storms against entities that will never have EODHD data.
  It resets to 0 on each successful enrichment.

  Note: `metadata JSONB`, `isin`, `ticker`, and `exchange` columns already exist
  on canonical_entities (from migration 0001). This migration adds only the 4
  new columns above.

FORWARD-COMPATIBILITY (R5):
  All additions are nullable or carry a server-side DEFAULT. No existing rows
  are affected. `enrichment_attempts DEFAULT 0` means all pre-existing entities
  start eligible for the periodic sweep.

BP-126: enrichment_attempts is NOT NULL — server_default="0" required here.
BP-007: CREATE INDEX CONCURRENTLY cannot run inside a transaction — must use
  autocommit_block().
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("canonical_entities", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("canonical_entities", sa.Column("data_completeness", sa.Double(), nullable=True))
    op.add_column(
        "canonical_entities",
        sa.Column("enriched_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.add_column(
        "canonical_entities",
        sa.Column(
            "enrichment_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )

    # CONCURRENTLY cannot run inside a transaction block
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_canonical_entities_enrichment_sweep "
            "ON canonical_entities (enrichment_attempts, enriched_at) "
            "WHERE enrichment_attempts < 3"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX IF EXISTS ix_canonical_entities_enrichment_sweep")
    op.drop_column("canonical_entities", "enrichment_attempts")
    op.drop_column("canonical_entities", "enriched_at")
    op.drop_column("canonical_entities", "data_completeness")
    op.drop_column("canonical_entities", "description")
