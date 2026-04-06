"""Add chunk_text_key column to chunks table.

Revision ID: 0003
Revises: 0002
Create Date: 2026-04-06

Adds ``chunk_text_key TEXT`` (nullable) to ``nlp_db.chunks``.
The column stores a MinIO object key pointing to the full chunk text,
uploaded by Block 7 during document processing.

Nullable so existing rows and LIGHT-tier chunks (no embeddings) are
unaffected — ``chunk_text_key IS NULL`` means text is not available
and search falls back to ``heading_path or ""``.

ORM model: nlp_pipeline.infrastructure.nlp_db.models.ChunkModel (BP-008)
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE chunks ADD COLUMN chunk_text_key TEXT")


def downgrade() -> None:
    op.execute("ALTER TABLE chunks DROP COLUMN IF EXISTS chunk_text_key")
