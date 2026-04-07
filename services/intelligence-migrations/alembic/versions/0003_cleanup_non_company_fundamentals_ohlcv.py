"""Remove orphan fundamentals_ohlcv embeddings for non-company entities.

Revision ID: c3d4e5f6a1b2
Revises: b2c3d4e5f6a1
Create Date: 2026-04-07

Data-only migration (no DDL change).

Background (PRD-0017 §6.4):
  ensure_rows_exist() previously created 3 embedding rows for every entity
  regardless of type. Non-company entities (persons, countries, organizations,
  regulatory bodies, etc.) have no fundamentals data — their fundamentals_ohlcv
  row stays NULL forever, wastes storage, and pollutes ANN search results.

  This migration removes the orphan rows. Going forward, ensure_rows_exist()
  will create only 2 rows (definition + narrative) for non-financial_instrument
  entities.

Rollback note:
  downgrade() is intentionally a no-op. The deleted rows had NULL embeddings
  and provided no value. To restore them, re-run the embedding worker; it will
  not recreate fundamentals_ohlcv rows for non-company entities (by design).

Estimated rows deleted: unknown at migration time (depends on data volume).
Downtime: zero — DELETE does not lock reads on unaffected rows.
"""

from alembic import op

revision = "c3d4e5f6a1b2"
down_revision = "b2c3d4e5f6a1"
branch_labels = None
depends_on = None

_CLEANUP_SQL = """
DELETE FROM entity_embedding_state ees
WHERE ees.view_type = 'fundamentals_ohlcv'
  AND EXISTS (
      SELECT 1 FROM canonical_entities ce
      WHERE ce.entity_id = ees.entity_id
        AND ce.entity_type != 'financial_instrument'
  )
"""


def upgrade() -> None:
    op.execute(_CLEANUP_SQL)


def downgrade() -> None:
    # Intentional no-op: deleted rows cannot be meaningfully restored.
    # Re-run the embedding worker to recreate any legitimate rows.
    pass
