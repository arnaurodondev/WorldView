"""Add source fields to relation_type_registry and seed EODHD/market-data mappings.

Revision ID: 0023
Revises: 0022
Create Date: 2026-05-05

Changes:
  relation_type_registry:
    - ADD COLUMN data_source TEXT NULL
    - ADD COLUMN source_field TEXT NULL
  seed data (idempotent UPDATE):
    - 6 EODHD/market-data relation type mappings

WHY:
  PLAN-0073 Worker 13J seeds structural relations from relation_type_registry rows
  whose data_source matches the enrichment payload source (eodhd or market_data).
  For example, when EODHD returns sector="Technology", the worker looks up the
  registry row where canonical_type='OPERATES_IN_SECTOR' and data_source='eodhd'
  to find that the source_field is 'General.Sector', then upserts an
  OPERATES_IN_SECTOR relation with relation_source='structured_enrichment'.

  The seed UPDATE is idempotent: `WHERE canonical_type = :type AND data_source IS NULL`
  — re-running this migration never updates rows that already have a data_source.

FORWARD-COMPATIBILITY (R5):
  Both columns are nullable. Existing registry rows gain NULL data_source/source_field,
  which are ignored by all current consumers. The 6 seeded rows are the only ones
  that carry non-NULL values after this migration.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None

# Relation type → (data_source, source_field) mappings for structured enrichment seeding.
# Only OPERATES_IN_SECTOR, OPERATES_IN_INDUSTRY, HEADQUARTERED_IN, and LISTED_ON are
# relevant because Worker 13J extracts these fields from EODHD and market-data responses.
_EODHD_MAPPINGS = [
    ("OPERATES_IN_SECTOR", "eodhd", "General.Sector"),
    ("OPERATES_IN_INDUSTRY", "eodhd", "General.Industry"),
    ("HEADQUARTERED_IN", "eodhd", "General.Country"),
    ("LISTED_ON", "eodhd", "General.Exchange"),
    ("OPERATES_IN_SECTOR", "market_data", "sector"),
    ("HEADQUARTERED_IN", "market_data", "country"),
]


def upgrade() -> None:
    op.add_column("relation_type_registry", sa.Column("data_source", sa.Text(), nullable=True))
    op.add_column("relation_type_registry", sa.Column("source_field", sa.Text(), nullable=True))

    # Seed EODHD/market-data mappings — idempotent: only updates rows where data_source IS NULL
    for canonical_type, data_source, source_field in _EODHD_MAPPINGS:
        op.execute(
            sa.text(
                "UPDATE relation_type_registry "
                "SET data_source = :src, source_field = :field "
                "WHERE canonical_type = :type AND data_source IS NULL"
            ).bindparams(src=data_source, field=source_field, type=canonical_type)
        )


def downgrade() -> None:
    op.drop_column("relation_type_registry", "source_field")
    op.drop_column("relation_type_registry", "data_source")
