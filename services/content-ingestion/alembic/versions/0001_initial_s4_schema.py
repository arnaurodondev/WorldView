"""Initial S4 Content Ingestion schema.

Revision ID: 0001
Revises:
Create Date: 2026-03-22
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    op.execute("""
        CREATE TABLE sources (
            id          UUID        PRIMARY KEY,
            name        TEXT        UNIQUE NOT NULL,
            source_type TEXT        NOT NULL,
            enabled     BOOLEAN     NOT NULL DEFAULT TRUE,
            config      JSONB       NOT NULL DEFAULT '{}',
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE fetch_logs (
            id           UUID        PRIMARY KEY,
            source_id    UUID        NOT NULL REFERENCES sources(id),
            url          TEXT        NOT NULL,
            url_hash     TEXT        NOT NULL,
            http_status  INT,
            byte_size    INT,
            fetched_at   TIMESTAMPTZ NOT NULL,
            published_at TIMESTAMPTZ,
            is_backfill  BOOLEAN     NOT NULL DEFAULT FALSE,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_fetch_logs_url_hash UNIQUE (url_hash)
        )
    """)

    op.execute("""
        CREATE TABLE outbox_events (
            id             UUID        PRIMARY KEY,
            aggregate_type TEXT        NOT NULL,
            aggregate_id   UUID        NOT NULL,
            event_type     TEXT        NOT NULL,
            payload        JSONB       NOT NULL,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            dispatched_at  TIMESTAMPTZ,
            retry_count    INT         NOT NULL DEFAULT 0,
            status         TEXT        NOT NULL DEFAULT 'pending',
            error          TEXT
        )
    """)
    op.execute("CREATE INDEX ix_outbox_events_status_created_at ON outbox_events (status, created_at)")

    op.execute("""
        CREATE TABLE dlq_events (
            id                UUID        PRIMARY KEY,
            original_event_id UUID        NOT NULL,
            payload           JSONB       NOT NULL,
            error             TEXT        NOT NULL,
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            resolved_at       TIMESTAMPTZ,
            status            TEXT        NOT NULL DEFAULT 'open'
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS dlq_events")
    op.execute("DROP TABLE IF EXISTS outbox_events")
    op.execute("DROP TABLE IF EXISTS fetch_logs")
    op.execute("DROP TABLE IF EXISTS sources")
