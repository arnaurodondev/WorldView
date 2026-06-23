"""Covering (entity, doc) indexes for the set-based density denominator.

Revision ID: 0062
Revises: 0061
Create Date: 2026-06-22

WHY THIS MIGRATION EXISTS:
  Migration 0060 added ``idx_raw_evidence_triple`` and ``idx_raw_evidence_object``
  which dropped the density subquery's *per-evaluation* cost ~115x (565M → 4.9M
  planner cost) by turning a per-row Seq Scan into a BitmapOr of index scans.
  That was necessary but NOT sufficient: Worker 13B's density denominator was a
  *correlated* subquery evaluated once per candidate row, so the total cost was
  still O(frontier_rows × per-eval).  On the live instance a single denominator
  evaluation measured ~531 ms (BitmapOr + Bitmap Heap Scan over ~250 heap blocks
  + DISTINCT sort), and with ~612 candidate rows the full gate cost ~325 s —
  reliably exceeding the 60 s statement_timeout and crashing every 5-minute run
  (``QueryCanceledError``).

  The fix (see relation_evidence_promoter.py) rewrites both ``_FETCH_SQL`` and
  ``_COUNT_GATED_QUALITY_SQL`` to PRECOMPUTE, in a single GROUP BY pass, the
  per-entity document fan-out
      entity_id → COUNT(DISTINCT source_document_id)
  for every entity referenced by the gated frontier, then hash-joins it back —
  replacing 612 correlated scans with one set-based aggregate.

WHAT THIS MIGRATION ADDS:
  Two covering btree indexes that let that per-entity aggregate run as
  INDEX-ONLY scans (no heap fetch), since ``source_document_id`` is carried in
  the index payload:

    1. idx_raw_evidence_subject_doc  ON (subject_entity_id, source_document_id)
    2. idx_raw_evidence_object_doc   ON (object_entity_id,  source_document_id)

  The new ``entity_doc_counts`` CTE joins relation_evidence_raw on
  ``subject_entity_id = e OR object_entity_id = e`` and counts distinct docs;
  with these covering indexes each leg is an Index-Only Scan rather than a
  Bitmap Heap Scan, eliminating the ~250-heap-block fetch + recheck that
  dominated the previous 531 ms per-evaluation cost.

  NOTE: the pre-existing ``idx_raw_evidence_subject`` is
  ``(subject_entity_id, extracted_at DESC)`` — it does NOT cover
  ``source_document_id``, so it cannot serve an index-only doc-count.  Hence the
  dedicated covering index here.

WHY plain CREATE INDEX (no CONCURRENTLY):
  Same rationale as migration 0060: ``relation_evidence_raw`` is an ordinary
  heap and intelligence-migrations are applied serially by a one-shot init
  container at deploy time, where plain ``CREATE INDEX IF NOT EXISTS`` is the
  established, transactional, idempotent convention (BP-393).

IDEMPOTENCY:
  ``CREATE INDEX IF NOT EXISTS`` — safe to re-run against a DB that already has
  the indexes (e.g. a stale volume).

DOWNGRADE:
  Drops both covering indexes.  The promoter still functions (the set-based
  query just falls back to Bitmap Heap Scans for the per-entity aggregate, a
  modest slowdown), so downgrade is safe.
"""

from __future__ import annotations

from alembic import op

revision: str = "0062"
down_revision: str = "0061"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Covering index for the subject leg of the per-entity document-count
    # aggregate: (subject_entity_id, source_document_id) lets
    # COUNT(DISTINCT source_document_id) WHERE subject_entity_id = e run as an
    # Index-Only Scan.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_raw_evidence_subject_doc
            ON relation_evidence_raw (subject_entity_id, source_document_id)
        """
    )

    # Covering index for the object leg.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_raw_evidence_object_doc
            ON relation_evidence_raw (object_entity_id, source_document_id)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_raw_evidence_object_doc")
    op.execute("DROP INDEX IF EXISTS idx_raw_evidence_subject_doc")
