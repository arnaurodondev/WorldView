"""Add index on relations.relation_id for cross-partition lookups.

Revision ID: 0025
Revises: 0024
Create Date: 2026-05-05

Changes:
  relations (partitioned table):
    - CREATE INDEX CONCURRENTLY idx_relations_relation_id ON relations (relation_id)

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

  A non-partitioned (global) index on relation_id allows the planner to
  satisfy the ANY(:relation_ids) predicate with a single index scan,
  eliminating the 8-partition fanout.

FORWARD-COMPATIBILITY (R5):
  Additive index.  All existing writes remain valid.  No schema changes.

BP-007: CREATE INDEX CONCURRENTLY cannot run inside a transaction —
  must use autocommit_block().

DOWNGRADE:
  Drop the index with DROP INDEX IF EXISTS.
"""

from __future__ import annotations

from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # CONCURRENTLY cannot run inside a transaction block (BP-007).
    # autocommit_block() instructs Alembic to issue a COMMIT before the
    # statement and re-open a new transaction afterwards.
    with op.get_context().autocommit_block():
        op.execute("CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_relations_relation_id " "ON relations (relation_id)")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX IF EXISTS idx_relations_relation_id")
