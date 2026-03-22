"""create alert_db schema

Revision ID: a1b2c3d4e5f6
Revises:
Create Date: 2026-03-22
"""

from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE alert_subscriptions (
        subscription_id UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id         UUID        NOT NULL,
        entity_id       UUID        NOT NULL,
        watchlist_id    UUID        NOT NULL,
        alert_types     TEXT[]      NOT NULL DEFAULT '{}',
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        deleted_at      TIMESTAMPTZ,
        UNIQUE (user_id, entity_id, watchlist_id)
    )
    """)
    op.execute("""
    CREATE INDEX idx_subscriptions_entity ON alert_subscriptions (entity_id)
        WHERE deleted_at IS NULL
    """)
    op.execute("""
    CREATE INDEX idx_subscriptions_user ON alert_subscriptions (user_id)
        WHERE deleted_at IS NULL
    """)

    op.execute("""
    CREATE TABLE alerts (
        alert_id        UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
        entity_id       UUID        NOT NULL,
        alert_type      VARCHAR(100) NOT NULL,
        source_event_id UUID        NOT NULL,
        source_topic    VARCHAR(200) NOT NULL,
        payload         JSONB       NOT NULL,
        dedup_key       VARCHAR(200) NOT NULL,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
        UNIQUE (dedup_key)
    )
    """)
    op.execute("CREATE INDEX idx_alerts_entity ON alerts (entity_id, created_at DESC)")

    op.execute("""
    CREATE TABLE alert_deliveries (
        delivery_id  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
        alert_id     UUID        NOT NULL REFERENCES alerts(alert_id),
        user_id      UUID        NOT NULL,
        channel      VARCHAR(20) NOT NULL DEFAULT 'websocket',
        status       VARCHAR(20) NOT NULL DEFAULT 'delivered',
        delivered_at TIMESTAMPTZ,
        created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """)
    op.execute("CREATE INDEX idx_deliveries_alert ON alert_deliveries (alert_id)")
    op.execute("""
    CREATE INDEX idx_deliveries_user_pending ON alert_deliveries (user_id, created_at DESC)
        WHERE status = 'pending'
    """)

    op.execute("""
    CREATE TABLE pending_alerts (
        pending_id   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
        user_id      UUID        NOT NULL,
        alert_id     UUID        NOT NULL REFERENCES alerts(alert_id),
        created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
        delivered_at TIMESTAMPTZ,
        UNIQUE (user_id, alert_id)
    )
    """)
    op.execute("""
    CREATE INDEX idx_pending_alerts_user ON pending_alerts (user_id, created_at)
        WHERE delivered_at IS NULL
    """)

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
    op.execute("CREATE INDEX idx_outbox_s10_pending ON outbox_events (created_at) WHERE status = 'pending'")

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
    op.execute("DROP TABLE IF EXISTS dead_letter_queue CASCADE")
    op.execute("DROP TABLE IF EXISTS outbox_events CASCADE")
    op.execute("DROP TABLE IF EXISTS pending_alerts CASCADE")
    op.execute("DROP TABLE IF EXISTS alert_deliveries CASCADE")
    op.execute("DROP TABLE IF EXISTS alerts CASCADE")
    op.execute("DROP TABLE IF EXISTS alert_subscriptions CASCADE")
