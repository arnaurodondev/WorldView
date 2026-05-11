"""document_source_llm_latest materialized view (PLAN-0055 C-3).

Revision ID: 0013
Revises: 0012
Create Date: 2026-04-30

The ``document_source_llm_scores`` ledger is append-only. Read paths (e.g.
``GET /api/v1/news/top``) want the **latest** score per (doc_id, score_type),
not a scan across the full history. A materialized view over
``DISTINCT ON (doc_id, score_type) ... ORDER BY generated_at DESC`` projects
that latest-row efficiently and is refreshed on a 5-minute APScheduler job
(Wave C-3 task T-C-3-02). The UNIQUE index makes
``REFRESH MATERIALIZED VIEW CONCURRENTLY`` legal so refreshes never block
concurrent worker writes.
"""

from __future__ import annotations

from alembic import op

# revision identifiers
revision: str = "0013"
down_revision: str = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE MATERIALIZED VIEW document_source_llm_latest AS
        SELECT DISTINCT ON (doc_id, score_type)
            doc_id,
            score_type,
            score_value,
            score_label,
            model_id,
            generated_at
        FROM document_source_llm_scores
        ORDER BY doc_id, score_type, generated_at DESC
        """
    )
    # UNIQUE index is required for REFRESH MATERIALIZED VIEW CONCURRENTLY.
    # Without it, refresh takes an exclusive lock and blocks worker INSERTs.
    op.execute("CREATE UNIQUE INDEX ix_dsl_latest_pk ON document_source_llm_latest(doc_id, score_type)")


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS document_source_llm_latest")
