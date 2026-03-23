"""Add published_at and is_backfill to fetch_logs.

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-23

Rationale: Adds the backfill support fields required by Option B (source API historical
range query).  ``published_at`` carries the source-reported publication datetime so that
S7 can set ``relation_evidence.evidence_date = published_at`` rather than the ingest
time, giving the temporal decay formula an accurate age for each piece of evidence.
``is_backfill`` propagates through the Kafka event to S10 so that alert fan-out is
suppressed for historical documents ingested during a boot-time backfill run.
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE fetch_logs
            ADD COLUMN published_at TIMESTAMPTZ,
            ADD COLUMN is_backfill  BOOLEAN NOT NULL DEFAULT FALSE
    """)
    op.execute(
        "CREATE INDEX ix_fetch_logs_published_at ON fetch_logs (published_at DESC)" " WHERE published_at IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_fetch_logs_published_at")
    op.execute("ALTER TABLE fetch_logs DROP COLUMN IF EXISTS is_backfill")
    op.execute("ALTER TABLE fetch_logs DROP COLUMN IF EXISTS published_at")
