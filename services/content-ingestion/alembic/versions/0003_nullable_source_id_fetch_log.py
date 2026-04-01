"""Make article_fetch_log.source_id nullable for manual/webhook submissions.

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-31

Manual submissions via the internal submit endpoint do not originate from
a registered polling source, so source_id should be nullable.
"""

from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the index that includes source_id first, then the FK constraint
    op.execute("DROP INDEX IF EXISTS ix_article_fetch_log_source")
    op.execute("ALTER TABLE article_fetch_log ALTER COLUMN source_id DROP NOT NULL")
    # Recreate the index without enforcing non-null (partial index for non-null rows)
    op.execute(
        "CREATE INDEX ix_article_fetch_log_source ON article_fetch_log (source_id, fetched_at) "
        "WHERE source_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_article_fetch_log_source")
    op.execute("ALTER TABLE article_fetch_log ALTER COLUMN source_id SET NOT NULL")
    op.execute("CREATE INDEX ix_article_fetch_log_source ON article_fetch_log (source_id, fetched_at)")
