"""Add dedup_hashes, duplicate_clusters tables; add dedup_result, corroborates_doc_id, is_backfill to documents.

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-26
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Fix documents table: add missing columns, make minio_silver_key nullable ──
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS dedup_result VARCHAR(30) NOT NULL DEFAULT 'unique'")
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS corroborates_doc_id UUID")
    op.execute("ALTER TABLE documents ADD COLUMN IF NOT EXISTS is_backfill BOOLEAN NOT NULL DEFAULT FALSE")
    op.execute("ALTER TABLE documents ALTER COLUMN minio_silver_key DROP NOT NULL")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_documents_corroborates"
        " ON documents (corroborates_doc_id)"
        " WHERE corroborates_doc_id IS NOT NULL"
    )

    # ── dedup_hashes ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS dedup_hashes (
            hash_id     UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
            doc_id      UUID        NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
            hash_type   VARCHAR(30) NOT NULL,
            hash_value  VARCHAR(64) NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (hash_type, hash_value)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_dedup_hashes_lookup ON dedup_hashes (hash_type, hash_value)")

    # ── duplicate_clusters ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS duplicate_clusters (
            cluster_id       UUID  PRIMARY KEY DEFAULT gen_random_uuid(),
            primary_doc_id   UUID  NOT NULL REFERENCES documents(doc_id),
            duplicate_doc_id UUID  NOT NULL REFERENCES documents(doc_id),
            similarity       FLOAT NOT NULL,
            detected_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (primary_doc_id, duplicate_doc_id)
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS duplicate_clusters")
    op.execute("DROP TABLE IF EXISTS dedup_hashes")
    op.execute("DROP INDEX IF EXISTS idx_documents_corroborates")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS is_backfill")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS corroborates_doc_id")
    op.execute("ALTER TABLE documents DROP COLUMN IF EXISTS dedup_result")
    op.execute("ALTER TABLE documents ALTER COLUMN minio_silver_key SET NOT NULL")
