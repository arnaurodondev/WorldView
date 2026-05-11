"""Add tenant_document_uploads table for multi-tenant document ingestion.

Revision ID: 0007_add_tenant_document_uploads
Revises: 0006_source_dedup_config_hash
Create Date: 2026-05-08

WHY (PLAN-0086 Wave D-2): Introduces the ``tenant_document_uploads`` table that
persists every document upload submitted via the tenant pipeline.  Rows are
owned by a single (tenant_id, id) pair — the repository always scopes queries
to both columns, so tenant A can never see tenant B's data even with a correct
doc_id.

The ``status`` column is constrained to the four lifecycle values defined by
``UploadStatus``.  Two composite indexes cover the common query patterns:
  - ``idx_tdu_tenant_status`` — list-by-tenant + optional status filter
  - ``idx_tdu_tenant_hash`` — per-tenant dedup check before storage
  - ``idx_tdu_uploaded_at`` — keyset pagination (DESC order on uploaded_at)
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers
revision: str = "0007_add_tenant_document_uploads"
down_revision: str = "0006_source_dedup_config_hash"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tenant_document_uploads",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("uploaded_by_user_id", UUID(as_uuid=True), nullable=False),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("content_type", sa.String(128), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.BigInteger, nullable=False),
        sa.Column("word_count", sa.Integer, nullable=True),
        sa.Column("chunk_count", sa.Integer, nullable=True),
        sa.Column(
            "status",
            sa.String(32),
            nullable=False,
            server_default="processing",
        ),
        sa.Column("minio_bronze_key", sa.String(1024), nullable=False),
        sa.Column("minio_silver_key", sa.String(1024), nullable=True),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ready_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('processing', 'ready', 'failed', 'deleted')",
            name="chk_tdu_status",
        ),
    )
    op.create_index("idx_tdu_tenant_status", "tenant_document_uploads", ["tenant_id", "status"])
    op.create_index("idx_tdu_tenant_hash", "tenant_document_uploads", ["tenant_id", "content_hash"])
    # Simple composite index on (tenant_id, uploaded_at) — DESC ordering is handled
    # by the ORDER BY clause in queries, not the index itself.
    op.create_index("idx_tdu_uploaded_at", "tenant_document_uploads", ["tenant_id", "uploaded_at"])


def downgrade() -> None:
    op.drop_index("idx_tdu_uploaded_at", "tenant_document_uploads")
    op.drop_index("idx_tdu_tenant_hash", "tenant_document_uploads")
    op.drop_index("idx_tdu_tenant_status", "tenant_document_uploads")
    op.drop_table("tenant_document_uploads")
