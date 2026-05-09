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
    # Note: document_source_metadata lives in content_db (S5), not in
    # intelligence_db.  When running against a standalone intelligence_db
    # (e.g., the dev Docker stack where both databases share the same Postgres
    # instance but document_source_metadata is in content_store_db), the table
    # simply does not exist in this schema and the UPDATE would raise
    # "relation does not exist".  We catch undefined_table to make the backfill
    # genuinely no-op in that case (BP-420).
    # -------------------------------------------------------------------------
    op.execute("""
DO $$
BEGIN
    UPDATE relation_evidence_raw rer
    SET    source_name = dsm.source_name,
           source_type = dsm.source_type
    FROM   document_source_metadata dsm
    WHERE  rer.source_document_id = dsm.document_id
      AND  (rer.source_name IS NULL OR rer.source_type IS NULL);
EXCEPTION
    WHEN undefined_table THEN
        -- document_source_metadata is not in this schema (cross-DB table living
        -- in content_store_db).  Skip the backfill — rows retain NULL values
        -- and will be populated correctly by the KG consumer at insert time.
        RAISE NOTICE 'document_source_metadata not found — skipping backfill (expected in standalone intelligence_db)';
END;
$$
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
        # IF NOT EXISTS guards against the case where a previous partial run
        # created this index in the autocommit block before the main transaction
        # rolled back (so alembic_version was NOT updated to 0035, but the index
        # already exists in pg_class).
        op.execute("""
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_relation_evidence_source_diversity
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
