"""Add content_ingestion_tasks table for scheduler-worker pattern.

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-29

Creates the content_ingestion_tasks table with indexes for:
  - Worker claim queries (status + created_at)
  - Scheduler dedup (source_id + window_start, unique partial)
  - Lease expiry scans (worker_id + lease_expires)

All TIMESTAMP columns are TIMESTAMPTZ (BP-005). All IDs are app-generated UUIDv7 (R10).
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE content_ingestion_tasks (
            id              UUID        PRIMARY KEY,
            source_id       UUID        NOT NULL REFERENCES sources(id),
            source_name     VARCHAR(255) NOT NULL,
            source_type     VARCHAR(50) NOT NULL,
            status          VARCHAR(20) NOT NULL DEFAULT 'pending',
            worker_id       VARCHAR(64),
            leased_at       TIMESTAMPTZ,
            lease_expires   TIMESTAMPTZ,
            attempt_count   INT         NOT NULL DEFAULT 0,
            max_attempts    INT         NOT NULL DEFAULT 5,
            error_detail    TEXT,
            is_backfill     BOOLEAN     NOT NULL DEFAULT FALSE,
            window_start    TIMESTAMPTZ,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    op.execute("CREATE INDEX ix_cit_status_created ON content_ingestion_tasks (status, created_at)")
    op.execute(
        "CREATE UNIQUE INDEX ix_cit_source_window ON content_ingestion_tasks (source_id, window_start)"
        " WHERE window_start IS NOT NULL"
    )
    op.execute("CREATE INDEX ix_cit_worker_lease ON content_ingestion_tasks (worker_id, lease_expires)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS content_ingestion_tasks")
