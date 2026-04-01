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
    # ── dedup_hashes — app-generated UUIDv7 (R10, M-8) ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS dedup_hashes (
            hash_id     UUID        PRIMARY KEY,
            doc_id      UUID        NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
            hash_type   VARCHAR(30) NOT NULL,
            hash_value  VARCHAR(64) NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            UNIQUE (hash_type, hash_value)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_dedup_hashes_lookup ON dedup_hashes (hash_type, hash_value)")

    # ── duplicate_clusters — app-generated UUIDv7 (R10, M-8) ──
    op.execute("""
        CREATE TABLE IF NOT EXISTS duplicate_clusters (
            cluster_id       UUID  PRIMARY KEY,
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
