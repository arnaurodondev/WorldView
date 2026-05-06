"""Add source fields to relation_type_registry and seed market-data mappings.

Revision ID: 0023
Revises: 0022
Create Date: 2026-05-05

Changes:
  relation_type_registry:
    - ADD COLUMN data_source TEXT NULL
    - ADD COLUMN source_field TEXT NULL
  seed data (idempotent UPDATE):
    - 4 market-data relation type mappings (sector, industry, country, exchange)

WHY:
  PLAN-0073 Worker 13J seeds structural relations from relation_type_registry rows
  whose data_source matches the enrichment payload source. The downstream adapter
  (EntityEnrichmentAdapter.seed_relations) reads metadata produced by S2/S5 enrichment
  whose keys are the *normalized* market-data field names ('sector', 'industry',
  'country', 'exchange') — NOT the EODHD-prefixed paths ('General.Sector', etc.).

CONSOLIDATION (QA report 2026-05-05 finding F-D01 / F-D03 / F-A06):
  Earlier draft of this migration seeded six rows split across data_source='eodhd'
  (UPPERCASE canonical_types like OPERATES_IN_SECTOR — none of which exist in the
  registry) and data_source='market_data' (also UPPERCASE — also missing). The
  registry actually seeds LOWERCASE names (is_in_sector / is_in_industry /
  headquartered_in / listed_on; see migration 0001 §relation_type_registry seed
  and migration 0002 for is_in_sector / is_in_industry). Consolidating to four
  market_data rows with the canonical lowercase types fixes both:
    1. UPDATE matches actual rows (was zero-row UPDATE before)
    2. The adapter's metadata.get(source_field) lookup finds values, because the
       enrichment payloads use the same keys ('sector', 'industry', ...).

  See docs/audits/2026-05-05-qa-plan-0073-report.md F-D01 for the full analysis.

  The seed UPDATE is idempotent: `WHERE canonical_type = :type AND data_source IS NULL`
  — re-running this migration never updates rows that already have a data_source.

FORWARD-COMPATIBILITY (R5):
  Both columns are nullable. Existing registry rows gain NULL data_source/source_field,
  which are ignored by all current consumers. The 4 seeded rows are the only ones
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
#
# Canonical type names MUST be the lowercase forms already present in
# relation_type_registry (seeded by migrations 0001 and 0002). Source_field names
# MUST match the keys used by S2/S5 in the canonical_entities.metadata JSONB —
# i.e. the normalized market-data shape, NOT the raw EODHD path. The adapter's
# `seed_relations` query filters `WHERE data_source = 'market_data'` and looks up
# `metadata.get(source_field)` directly.
_MARKET_DATA_MAPPINGS = [
    ("is_in_sector", "market_data", "sector"),
    ("is_in_industry", "market_data", "industry"),
    ("headquartered_in", "market_data", "country"),
    ("listed_on", "market_data", "exchange"),
]


def upgrade() -> None:
    op.add_column("relation_type_registry", sa.Column("data_source", sa.Text(), nullable=True))
    op.add_column("relation_type_registry", sa.Column("source_field", sa.Text(), nullable=True))

    # Seed market-data mappings — idempotent: only updates rows where data_source IS NULL
    for canonical_type, data_source, source_field in _MARKET_DATA_MAPPINGS:
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
