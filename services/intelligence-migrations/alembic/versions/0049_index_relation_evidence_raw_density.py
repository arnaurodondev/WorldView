"""Add density-subquery indexes on relation_evidence_raw (promoter hot-path).

Revision ID: 0049
Revises: 0048
Create Date: 2026-06-21

WHY THIS MIGRATION EXISTS:
  Worker 13B (``RelationEvidencePromoterWorker``) runs every 5 minutes and
  executes ``_FETCH_SQL`` which evaluates an E-3 "evidence density" gate for
  every low-confidence candidate row.  The density numerator/denominator are
  two correlated subqueries over ``relation_evidence_raw`` itself:

    numerator   : COUNT(*)              WHERE (subject, object, canonical_type) = row's triple
    denominator : COUNT(DISTINCT doc)   WHERE subject_entity_id IN (subj, obj)
                                           OR  object_entity_id  IN (subj, obj)

  With no composite triple index and no standalone ``object_entity_id`` index,
  the denominator's ``IN (...) OR IN (...)`` predicate could use NO index and
  fell back to a full sequential scan of ``relation_evidence_raw`` *per
  candidate row*.  On a ~95k-row staging table this produced an O(N^2) plan
  whose total cost exceeded 565,000,000 and a single run was observed alive in
  ``pg_stat_activity`` for 16,188 seconds (4.5 hours), pinning the shared
  Postgres instance at ~70% CPU and starving the UI-facing OLTP databases.

WHAT THIS MIGRATION ADDS:
  1. ``idx_raw_evidence_triple`` — composite btree on
     (subject_entity_id, object_entity_id, canonical_type).  Serves:
       * the JOIN to ``relations`` on the same triple,
       * the density numerator (Index-Only Scan),
       * the first leg of the denominator's BitmapOr (subject side).
  2. ``idx_raw_evidence_object`` — standalone btree on object_entity_id.
     Serves the second leg of the denominator's BitmapOr (object side).

  With both present the planner switches the denominator from a per-row Seq
  Scan (cost ~5,915 each) to a ``BitmapOr`` of two index scans (cost ~18),
  dropping the total plan cost from 565,604,762 to 4,922,132 (a ~115x
  reduction) and removing the quadratic blow-up.

WHY plain CREATE INDEX (no CONCURRENTLY):
  ``relation_evidence_raw`` is an ordinary (non-partitioned) heap, so
  CONCURRENTLY would be technically permitted.  However, worldview's
  intelligence-migrations are applied serially by a one-shot init container at
  deploy time (BP-393 / 0029 / 0033), where plain ``CREATE INDEX IF NOT
  EXISTS`` is the established convention — it is transactional, idempotent on
  re-run, and avoids the ``autocommit_block()`` ceremony CONCURRENTLY requires.
  The staging table is small relative to the brief AccessShareLock window.

IDEMPOTENCY:
  ``CREATE INDEX IF NOT EXISTS`` — safe to re-run against a DB that already has
  the indexes (e.g. a stale volume).

DOWNGRADE:
  Drops both indexes.  The promoter's behaviour is unchanged; only the query
  plan reverts to the slow O(N^2) form, so downgrade is safe but inadvisable
  on a populated staging table.
"""

from __future__ import annotations

from alembic import op

revision: str = "0049"
down_revision: str = "0048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Composite triple index — JOIN to relations + density numerator
    # (Index-Only Scan) + subject leg of the density-denominator BitmapOr.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_raw_evidence_triple
            ON relation_evidence_raw (subject_entity_id, object_entity_id, canonical_type)
        """
    )

    # Standalone object_entity_id index — object leg of the density-denominator
    # BitmapOr.  Without this the ``object_entity_id IN (...)`` half of the OR
    # has no index and forces a full Seq Scan, defeating the BitmapOr.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_raw_evidence_object
            ON relation_evidence_raw (object_entity_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_raw_evidence_object")
    op.execute("DROP INDEX IF EXISTS idx_raw_evidence_triple")
