"""Add tenant_id to chunks/sections and document_title to chunks.

Revision ID: 0019_add_tenant_id_to_chunks_sections
Revises: 0018
Create Date: 2026-05-08

PLAN-0086 Wave B-2 — tenant isolation for the NLP chunking pipeline.

* ``sections.tenant_id``  — tags which tenant's document produced these
  sections; partial index for efficient per-tenant queries.
* ``chunks.tenant_id``    — primary tenant filter for HNSW ANN searches;
  partial index mirrors the sections one.
* ``chunks.document_title`` — denormalised document title stored alongside
  each chunk so the RAG citation path can surface the article title without
  a cross-service lookup back to S3/content-store.

All three columns are nullable so existing rows remain valid with IS NULL
acting as a "legacy / pre-multi-tenant" sentinel.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # sections: tag which tenant's document produced these sections
    op.add_column("sections", sa.Column("tenant_id", UUID(as_uuid=True), nullable=True))
    op.execute("CREATE INDEX idx_sections_tenant_id ON sections(tenant_id) WHERE tenant_id IS NOT NULL")

    # chunks: primary table for HNSW filtering
    op.add_column("chunks", sa.Column("tenant_id", UUID(as_uuid=True), nullable=True))
    op.execute("CREATE INDEX idx_chunks_tenant_id ON chunks(tenant_id) WHERE tenant_id IS NOT NULL")

    # document_title: denormalized for RAG citations (avoids cross-service lookup)
    op.add_column("chunks", sa.Column("document_title", sa.String(512), nullable=True))


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_chunks_tenant_id")
    op.drop_column("chunks", "document_title")
    op.drop_column("chunks", "tenant_id")
    op.execute("DROP INDEX IF EXISTS idx_sections_tenant_id")
    op.drop_column("sections", "tenant_id")
