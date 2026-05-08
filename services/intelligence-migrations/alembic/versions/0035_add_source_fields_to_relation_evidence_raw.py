"""Add ``source_name`` / ``source_type`` to ``relation_evidence_raw`` + backfill.

Revision ID: 0035
Revises: 0034
Create Date: 2026-05-08

WHY (T-A-05 — PRD-0074 §8.7):
  The corroboration bonus in the confidence formula counts
  ``DISTINCT (source_type, source_name)`` pairs per relation, but these fields
  have never been stored on ``relation_evidence_raw``.  Every evidence row
  contributes zero diversity signal, systematically undercomputing the
  corroboration bonus for all relations.

  Fix:
    1. ADD two nullable columns (source_name TEXT, source_type TEXT).
    2. Best-effort backfill from ``document_source_metadata``:
       JOIN on ``source_document_id = document_id`` and UPDATE rows where either
       column is currently NULL.  Rows without a matching metadata record retain
       NULL (acceptable — backfill is best-effort per PRD §8.7).
    3. Add a partial composite index for the corroboration aggregation query
       used by ConfidenceWorker:
         ``(canonical_type, source_type, source_name) WHERE processed = true``

  Note: ``document_source_metadata`` lives in ``content_db`` (S5), not in
  ``intelligence_db``.  The backfill UPDATE will update 0 rows if executed
  outside a database that has been cross-linked (e.g., via FDW or in a test
  environment with a shared Postgres instance).  This is expected and acceptable.
  At insert time (Wave B KG consumer), both fields will be populated correctly.

FORWARD-COMPATIBILITY (R5):
  Additive nullable columns + a backfill UPDATE + a new index.  No existing data
  is removed or renamed.  Safe on live databases.

DOWNGRADE:
  Drops the partial index, then drops both columns.
"""

from __future__ import annotations

from alembic import op

revision = "0035"
down_revision = "0034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # 1. Add columns — nullable, no server_default required (BP-126 satisfied).
    # -------------------------------------------------------------------------
    op.execute("""
ALTER TABLE relation_evidence_raw
    ADD COLUMN IF NOT EXISTS source_name TEXT,
    ADD COLUMN IF NOT EXISTS source_type TEXT
""")

    # -------------------------------------------------------------------------
    # 2. Best-effort backfill from document_source_metadata.
    # Rows without a matching document_source_metadata record keep NULL.
    # Note: document_source_metadata is in content_db; this UPDATE will be a
    # no-op if running against a standalone intelligence_db (e.g., test DB).
    # -------------------------------------------------------------------------
    op.execute("""
UPDATE relation_evidence_raw rer
SET    source_name = dsm.source_name,
       source_type = dsm.source_type
FROM   document_source_metadata dsm
WHERE  rer.source_document_id = dsm.document_id
  AND  (rer.source_name IS NULL OR rer.source_type IS NULL)
""")

    # -------------------------------------------------------------------------
    # 3. Composite partial index for corroboration aggregation.
    # Covers the ConfidenceWorker query:
    #   SELECT canonical_type, source_type, source_name, COUNT(*)
    #   FROM relation_evidence_raw
    #   WHERE processed = true
    #   GROUP BY canonical_type, source_type, source_name
    # -------------------------------------------------------------------------
    with op.get_context().autocommit_block():
        op.execute("""
CREATE INDEX CONCURRENTLY idx_relation_evidence_source_diversity
    ON relation_evidence_raw (canonical_type, source_type, source_name)
    WHERE processed = true
""")


def downgrade() -> None:
    op.execute("DROP INDEX CONCURRENTLY IF EXISTS idx_relation_evidence_source_diversity")
    op.execute("""
ALTER TABLE relation_evidence_raw
    DROP COLUMN IF EXISTS source_name,
    DROP COLUMN IF EXISTS source_type
""")
