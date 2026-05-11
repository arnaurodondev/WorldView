"""Activate unused ``relations`` columns via indexes and CHECK constraint.

Revision ID: 0033
Revises: 0032
Create Date: 2026-05-08

WHY (T-A-03 — PRD-0074 §8.5):
  Migration 0001 created the ``relations`` table with several columns that were
  intentionally designed but never activated:

    - ``valid_from / valid_to``           — always NULL; populated by ConfidenceWorker
    - ``relation_period_type``            — always 'ONGOING'; no CHECK enforced
    - ``strongest_contra_score``          — always 0.0; populated by ContradictionBatchWorker
    - ``contra_count_by_type``            — always '{}'; populated by ContradictionBatchWorker
    - ``latest_contra_at``                — always NULL; populated by ContradictionBatchWorker

  This migration activates them with:
    1. A partial index on ``(latest_contra_at DESC) WHERE strongest_contra_score > 0.0``
       so ContradictionBatchWorker can quickly find recently contradicted relations.
    2. A partial index on ``(valid_from, valid_to) WHERE valid_to IS NULL AND
       relation_period_type = 'ONGOING'`` for efficient validity queries.
    3. A CHECK constraint on ``relation_period_type`` limiting it to the 3 intended
       values: POINT_IN_TIME, ONGOING, HISTORICAL.  Safe because all existing rows
       have the default value 'ONGOING' which passes the constraint.

FORWARD-COMPATIBILITY (R5):
  No new columns — only new indexes and a CHECK constraint on an existing column
  whose current value ('ONGOING') is valid under the new constraint.

DOWNGRADE:
  Drops both indexes and the CHECK constraint.

NOTE (BP-420 — partitioned table CONCURRENTLY restriction):
  ``relations`` is a Postgres *partitioned* table (relkind='p').  PostgreSQL
  does not support ``CREATE INDEX CONCURRENTLY`` on partitioned tables — only
  on ordinary heap tables.  (The reason: CONCURRENTLY builds indexes on each
  partition individually and requires a single-transaction wait mechanism that
  Postgres has not extended to partition parents.)  The original migration used
  ``CONCURRENTLY`` inside an ``autocommit_block()``, which caused
  ``FeatureNotSupported`` errors at runtime.  This revision removes CONCURRENTLY
  and the autocommit_block wrappers; index creation on the parent propagates to
  all existing and future partitions automatically.
"""

from __future__ import annotations

from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # 1. Contradiction activity index
    # Supports ContradictionBatchWorker's "find recently contradicted relations"
    # query and the confidence breakdown panel in the intelligence UI.
    #
    # NOTE: CONCURRENTLY is intentionally omitted — ``relations`` is a
    # partitioned table and Postgres does not support CONCURRENTLY on partition
    # parents (BP-420).  Non-concurrent creation locks the table briefly but is
    # correct and safe here because the table is empty at migration time.
    # -------------------------------------------------------------------------
    op.execute("""
CREATE INDEX IF NOT EXISTS idx_relations_contra_active
    ON relations (latest_contra_at DESC)
    WHERE strongest_contra_score > 0.0
""")

    # -------------------------------------------------------------------------
    # 2. Active-period (ongoing) index
    # Supports ConfidenceWorker's validity activation and the intelligence
    # page's "relations valid_from / valid_to" display.
    # -------------------------------------------------------------------------
    op.execute("""
CREATE INDEX IF NOT EXISTS idx_relations_active_period
    ON relations (valid_from, valid_to)
    WHERE valid_to IS NULL AND relation_period_type = 'ONGOING'
""")

    # -------------------------------------------------------------------------
    # 3. CHECK constraint on relation_period_type
    # All existing rows have value 'ONGOING' (the column default from 0001),
    # so this constraint is satisfied by every existing row immediately.
    # -------------------------------------------------------------------------
    op.execute("""
ALTER TABLE relations
    ADD CONSTRAINT chk_relation_period_type
        CHECK (relation_period_type IN ('POINT_IN_TIME', 'ONGOING', 'HISTORICAL'))
""")


def downgrade() -> None:
    op.execute("ALTER TABLE relations DROP CONSTRAINT IF EXISTS chk_relation_period_type")
    # Non-partitioned DROP INDEX syntax (no CONCURRENTLY on partitioned tables).
    op.execute("DROP INDEX IF EXISTS idx_relations_active_period")
    op.execute("DROP INDEX IF EXISTS idx_relations_contra_active")
