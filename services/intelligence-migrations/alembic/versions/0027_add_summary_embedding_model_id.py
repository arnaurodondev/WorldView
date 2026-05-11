"""Add summary_embedding_model_id + summary_last_embedded_at to relation_summaries.

Revision ID: 0027
Revises: 0026
Create Date: 2026-05-06

Changes:
  relation_summaries:
    - ADD COLUMN summary_embedding_model_id TEXT NULL
    - ADD COLUMN summary_last_embedded_at TIMESTAMPTZ NULL
    - CREATE INDEX idx_relation_summaries_model_id (partial: summary_embedding IS NOT NULL)

WHY (DEF-022 — EmbeddingRefreshWorker model_id tracking):
  ``relation_summaries.summary_embedding`` is a 1024-dim pgvector column used by
  HNSW ANN cosine search.  Today, every refreshed embedding is written without
  any record of WHICH model produced it.  When the embedding provider changes
  (e.g., Ollama bge-large -> DeepInfra BAAI/bge-large-en-v1.5, or a future
  upgrade to a different family), the `relation_summaries` table accumulates
  vectors from multiple models in a SHARED HNSW index.

  Cosine distance across models is meaningless: an entity-pair embedded with
  model A and a query embedded with model B will return spurious matches.
  This is the "mixed-model ANN drift" risk.

  Tracking ``summary_embedding_model_id`` per row enables:
    1. Audit — at any point we can SELECT GROUP BY model_id to detect drift.
    2. Targeted re-embedding — refresh only rows whose model_id != current.
    3. Future query-time filter — restrict ANN search to a single model.

  ``summary_last_embedded_at`` complements this with a refresh timestamp,
  used to age out stale embeddings independent of the (unrelated) summary
  ``generated_at`` field.

BACKFILL STRATEGY:
  Both columns are NULLABLE — no backfill needed (BP-126 avoided).
  Existing rows have ``summary_embedding`` already populated by the previous
  worker run; their model_id is unknown ("legacy / mixed-model"). They will
  be naturally refreshed on the next ``EmbeddingRefreshWorker`` cycle when
  ``summary_text`` changes (evidence_hash-driven re-summarization triggers
  ``summary_embedding`` re-population).

  Until refresh, mixed-model rows remain queryable via the existing partial
  HNSW index. The new partial index here (``idx_relation_summaries_model_id``)
  is used only by the auditing workflow above; it is NOT used at ANN query
  time.

FORWARD-COMPATIBILITY (R5):
  Additive nullable columns + additive partial index.  All existing reads
  and writes continue to work unchanged.  Worker code (Wave A-2 T-A2-02)
  populates the new columns on every refresh; readers that don't yet know
  about them simply ignore the extra fields.

DOWNGRADE:
  Drop the partial index, then drop both columns.
"""

from __future__ import annotations

from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Two nullable columns — no server_default needed (BP-126: only NOT NULL
    # without server_default is dangerous; nullable additions are safe).
    op.execute(
        """
        ALTER TABLE relation_summaries
            ADD COLUMN IF NOT EXISTS summary_embedding_model_id TEXT NULL,
            ADD COLUMN IF NOT EXISTS summary_last_embedded_at   TIMESTAMPTZ NULL
        """
    )

    # Partial index — only meaningful for rows that actually have an embedding.
    # Used by the auditing workflow ("which models are present in the index?")
    # and by future targeted re-embedding queries that filter on model_id.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_relation_summaries_model_id
            ON relation_summaries (summary_embedding_model_id)
            WHERE summary_embedding IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_relation_summaries_model_id")
    op.execute(
        """
        ALTER TABLE relation_summaries
            DROP COLUMN IF EXISTS summary_last_embedded_at,
            DROP COLUMN IF EXISTS summary_embedding_model_id
        """
    )
