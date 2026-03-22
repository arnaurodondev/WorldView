"""Create content_ingestion_db initial schema.

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
    op.execute("""
        CREATE TABLE fetch_log (
            fetch_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            source_type    VARCHAR(50)  NOT NULL,
            source_url     TEXT         NOT NULL,
            fetched_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
            status         VARCHAR(20)  NOT NULL DEFAULT 'success',
            raw_minio_key  TEXT,
            content_hash   VARCHAR(64),
            error_detail   TEXT
        )
    """)
    op.execute("CREATE INDEX idx_fetch_log_source_fetched ON fetch_log (source_type, fetched_at DESC)")
    op.execute("CREATE INDEX idx_fetch_log_hash ON fetch_log (content_hash)" " WHERE content_hash IS NOT NULL")

    op.execute("""
        CREATE TABLE outbox_events (
            event_id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            topic          VARCHAR(200)  NOT NULL,
            partition_key  TEXT          NOT NULL,
            payload_avro   BYTEA         NOT NULL,
            status         VARCHAR(20)   NOT NULL DEFAULT 'pending',
            created_at     TIMESTAMPTZ   NOT NULL DEFAULT now(),
            dispatched_at  TIMESTAMPTZ,
            retry_count    INT           NOT NULL DEFAULT 0,
            failed_at      TIMESTAMPTZ
        )
    """)
    op.execute("CREATE INDEX idx_outbox_s4_pending ON outbox_events (created_at)" " WHERE status = 'pending'")

    op.execute("""
        CREATE TABLE dead_letter_queue (
            dlq_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            original_event_id UUID         NOT NULL,
            topic             VARCHAR(200) NOT NULL,
            payload_avro      BYTEA        NOT NULL,
            error_detail      TEXT,
            status            VARCHAR(20)  NOT NULL DEFAULT 'failed',
            created_at        TIMESTAMPTZ  NOT NULL DEFAULT now(),
            resolved_at       TIMESTAMPTZ,
            resolution_note   TEXT
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS dead_letter_queue")
    op.execute("DROP TABLE IF EXISTS outbox_events")
    op.execute("DROP TABLE IF EXISTS fetch_log")
