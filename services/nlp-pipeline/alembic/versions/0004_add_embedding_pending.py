"""Add embedding_pending table for retry infrastructure.

Revision ID: 0004
Revises: 0003
Create Date: 2026-04-08

Adds ``embedding_pending`` which stores section and chunk embedding failures
so that the EmbeddingRetryWorker can re-attempt them with exponential backoff.

Fields:
  - ``pending_id``    — UUIDv7 primary key
  - ``doc_id``        — parent document (for logging/triage)
  - ``section_id``    — set for section-level failures
  - ``chunk_id``      — set for chunk-level failures
  - ``embedding_text``— text to embed on retry (captured at failure time)
  - ``error_detail``  — error message for debugging
  - ``retry_count``   — incremented on each failed attempt
  - ``next_retry_at`` — when the next retry should run (exponential backoff)
  - ``created_at``    — when the failure was first recorded

ORM model: nlp_pipeline.infrastructure.nlp_db.models.EmbeddingPendingModel
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE embedding_pending (
            pending_id     UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            doc_id         UUID         NOT NULL,
            section_id     UUID,
            chunk_id       UUID,
            embedding_text TEXT         NOT NULL DEFAULT '',
            error_detail   TEXT,
            retry_count    INT          NOT NULL DEFAULT 0,
            next_retry_at  TIMESTAMPTZ  NOT NULL DEFAULT now(),
            created_at     TIMESTAMPTZ  NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX idx_embedding_pending_retry ON embedding_pending (next_retry_at, retry_count)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS embedding_pending")
