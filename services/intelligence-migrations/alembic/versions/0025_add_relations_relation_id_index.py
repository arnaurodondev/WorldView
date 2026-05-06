"""Add index on relations.relation_id for cross-partition lookups.

Revision ID: 0025
Revises: 0024
Create Date: 2026-05-05

Changes:
  relations (partitioned table):
    - CREATE INDEX idx_relations_relation_id ON relations (relation_id)

WHY:
  Supports get_evidence_snippets_batch CTE (PLAN-0072 T-72-2-01) — avoids
  8-partition fanout when looking up relation_ids from the unpartitioned
  relation_evidence_raw table.

  The `relations` table is HASH-partitioned x8 on subject_entity_id.
  The new get_evidence_snippets_batch query filters:
    WHERE r.relation_id = ANY(:relation_ids)
  Without a standalone index on relation_id, PostgreSQL must perform a
  sequential scan across all 8 partitions for every graph API call that
  requests evidence snippets.

  This creates a partitioned index hierarchy (one child index per partition,
  created atomically by Postgres), satisfying the ANY(:relation_ids) predicate
  efficiently across all 8 partitions.

  NOTE: CREATE INDEX CONCURRENTLY on a partitioned parent table is NOT supported
  in PostgreSQL 16 (timescale/timescaledb:2.17.2-pg16).  A plain transactional
  index is used instead; the index is built inside the Alembic migration
  transaction.

FORWARD-COMPATIBILITY (R5):
  Additive index.  All existing writes remain valid.  No schema changes.

DOWNGRADE:
  Drop the index.
"""

from __future__ import annotations

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "idx_relations_relation_id",
        "relations",
        ["relation_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_relations_relation_id", table_name="relations")
