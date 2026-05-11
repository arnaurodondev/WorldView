"""add email_preferences and email_log tables

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-07
"""

from alembic import op

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE email_preferences (
        user_id                 UUID        PRIMARY KEY,
        tenant_id               UUID        NOT NULL,
        weekly_digest_enabled   BOOLEAN     NOT NULL DEFAULT true,
        send_day_of_week        SMALLINT    NOT NULL DEFAULT 6
            CONSTRAINT ck_email_prefs_day CHECK (send_day_of_week BETWEEN 0 AND 6),
        send_hour_utc           SMALLINT    NOT NULL DEFAULT 8
            CONSTRAINT ck_email_prefs_hour CHECK (send_hour_utc BETWEEN 0 AND 23),
        email_address           TEXT,
        last_digest_sent_at     TIMESTAMPTZ,
        created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
        updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """)
    op.execute("""
    CREATE INDEX idx_email_prefs_scheduler
        ON email_preferences (tenant_id, weekly_digest_enabled, send_day_of_week)
    """)

    op.execute("""
    CREATE TABLE email_log (
        log_id               UUID        PRIMARY KEY,
        user_id              UUID        NOT NULL,
        tenant_id            UUID        NOT NULL,
        email_type           TEXT        NOT NULL,
        sent_at              TIMESTAMPTZ NOT NULL,
        provider             TEXT        NOT NULL,
        provider_message_id  TEXT,
        status               TEXT        NOT NULL,
        error_detail         TEXT,
        created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """)
    op.execute("CREATE INDEX idx_email_log_user_sent_at ON email_log (user_id, sent_at DESC)")
    op.execute("CREATE INDEX idx_email_log_status_sent_at ON email_log (status, sent_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS email_log CASCADE")
    op.execute("DROP TABLE IF EXISTS email_preferences CASCADE")
