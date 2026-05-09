"""Add tenant_id to documents and dedup_hashes for multi-tenant isolation.

Revision ID: 0005_add_tenant_id_to_content_store
Revises: 0004
Create Date: 2026-05-08
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add tenant_id to documents (NULL = public/global news, non-NULL = tenant-private)
    op.add_column("documents", sa.Column("tenant_id", UUID(as_uuid=True), nullable=True))
    op.execute("CREATE INDEX idx_documents_tenant_id ON documents(tenant_id) WHERE tenant_id IS NOT NULL")

    # 2. Fix documents.content_hash uniqueness — replace the global UNIQUE constraint
    #    with two partial indexes so global (public) and per-tenant dedups coexist.
    op.execute("DROP INDEX IF EXISTS uq_documents_content_hash")
    op.execute("ALTER TABLE documents DROP CONSTRAINT IF EXISTS documents_content_hash_key")
    op.execute(
        "CREATE UNIQUE INDEX uq_documents_content_hash_global" " ON documents(content_hash) WHERE tenant_id IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_documents_content_hash_tenant"
        " ON documents(tenant_id, content_hash) WHERE tenant_id IS NOT NULL"
    )

    # 3. Add tenant_id to dedup_hashes (scopes hash lookups per tenant)
    op.add_column("dedup_hashes", sa.Column("tenant_id", UUID(as_uuid=True), nullable=True))

    # 4. Fix dedup_hashes unique constraint — replace the table-level UniqueConstraint
    #    with two partial indexes so global and per-tenant hash spaces don't collide.
    # Migration 0004 renamed the UNIQUE constraint to uq_dedup_hashes_type_value.
    # PostgreSQL backs UNIQUE constraints with an index of the same name but that
    # index cannot be dropped via DROP INDEX — it must be dropped via DROP CONSTRAINT.
    op.execute("ALTER TABLE dedup_hashes DROP CONSTRAINT IF EXISTS uq_dedup_hashes_type_value")
    op.execute("DROP INDEX IF EXISTS uq_dedup_hashes_type_value")
    op.execute(
        "CREATE UNIQUE INDEX uq_dedup_hashes_global" " ON dedup_hashes(hash_type, hash_value) WHERE tenant_id IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX uq_dedup_hashes_tenant"
        " ON dedup_hashes(tenant_id, hash_type, hash_value) WHERE tenant_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_dedup_hashes_tenant")
    op.execute("DROP INDEX IF EXISTS uq_dedup_hashes_global")
    op.execute("CREATE UNIQUE INDEX uq_dedup_hashes_type_value ON dedup_hashes(hash_type, hash_value)")
    op.drop_column("dedup_hashes", "tenant_id")

    op.execute("DROP INDEX IF EXISTS uq_documents_content_hash_tenant")
    op.execute("DROP INDEX IF EXISTS uq_documents_content_hash_global")
    op.execute("DROP INDEX IF EXISTS idx_documents_tenant_id")
    op.drop_column("documents", "tenant_id")
