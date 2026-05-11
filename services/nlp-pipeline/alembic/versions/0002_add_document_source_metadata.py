"""Add document_source_metadata table.

Revision ID: 0002
Revises: 0001
Create Date: 2026-04-05

Adds the ``document_source_metadata`` table to ``nlp_db``.
Populated by the S6 article consumer as a best-effort side effect;
queried by S8 RAG pipeline for inline citation data.

PRD reference: PLAN-0015 Wave B-1
ORM model: nlp_pipeline.infrastructure.nlp_db.models.DocumentSourceMetadataModel (BP-008)
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE document_source_metadata (
            doc_id         UUID         PRIMARY KEY,
            title          TEXT,
            url            TEXT,
            published_at   TIMESTAMPTZ,
            source_name    VARCHAR(100),
            source_type    VARCHAR(50),
            word_count     INT,
            created_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS document_source_metadata")
