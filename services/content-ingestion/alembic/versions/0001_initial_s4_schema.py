"""Initial S4 Content Ingestion schema.

Revision ID: 0001
Revises:
Create Date: 2026-03-26

Creates all 5 tables matching the ORM models exactly (guard BP-008):
  - sources
  - source_adapter_state
  - article_fetch_log
  - outbox_events
  - dead_letter_queue
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
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
        CREATE TABLE source_adapter_state (
            source_id       UUID        PRIMARY KEY REFERENCES sources(id),
            last_watermark  TIMESTAMPTZ,
            last_cursor     TEXT,
            last_run_at     TIMESTAMPTZ,
            next_run_at     TIMESTAMPTZ,
            error_count     INT         NOT NULL DEFAULT 0,
            last_error      TEXT,
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)

    op.execute("""
        CREATE TABLE article_fetch_log (
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
            CONSTRAINT uq_article_fetch_log_url_hash UNIQUE (url_hash)
        )
    """)
    op.execute("CREATE INDEX ix_article_fetch_log_source ON article_fetch_log (source_id, fetched_at)")
    op.execute(
        "CREATE INDEX ix_article_fetch_log_published_at ON article_fetch_log (published_at DESC)"
        " WHERE published_at IS NOT NULL"
    )

    op.execute("""
        CREATE TABLE outbox_events (
            id             UUID        PRIMARY KEY,
            aggregate_type TEXT        NOT NULL,
            aggregate_id   UUID        NOT NULL,
            event_type     TEXT        NOT NULL,
            topic          TEXT        NOT NULL DEFAULT 'content.article.raw.v1',
            payload        JSONB       NOT NULL DEFAULT '{}',
            status         TEXT        NOT NULL DEFAULT 'pending',
            lease_owner    TEXT,
            leased_until   TIMESTAMPTZ,
            attempts       SMALLINT    NOT NULL DEFAULT 0,
            max_attempts   SMALLINT    NOT NULL DEFAULT 5,
            created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
            dispatched_at  TIMESTAMPTZ
        )
    """)
    op.execute("""
        CREATE INDEX ix_outbox_claimable ON outbox_events (status, leased_until)
        WHERE status IN ('pending', 'processing')
    """)

    op.execute("""
        CREATE TABLE dead_letter_queue (
            dlq_id            UUID        PRIMARY KEY,
            original_event_id UUID        NOT NULL,
            topic             TEXT        NOT NULL,
            payload_avro      BYTEA       NOT NULL,
            error_detail      TEXT,
            status            TEXT        NOT NULL DEFAULT 'failed',
            created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
            resolved_at       TIMESTAMPTZ,
            resolution_note   TEXT
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS dead_letter_queue")
    op.execute("DROP TABLE IF EXISTS outbox_events")
    op.execute("DROP TABLE IF EXISTS article_fetch_log")
    op.execute("DROP TABLE IF EXISTS source_adapter_state")
    op.execute("DROP TABLE IF EXISTS sources")
