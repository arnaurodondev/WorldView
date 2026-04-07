"""email_preferences unique(tenant_id, user_id) + email_log updated_at

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-04-07

Changes:
- email_preferences: add UNIQUE(tenant_id, user_id) for per-tenant upsert safety (C-02)
- email_log: add nullable updated_at TIMESTAMPTZ to support outbox-first status updates (B-01)
"""

from alembic import op

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # C-02: composite unique constraint — user_id is globally unique but we enforce
    # the composite so per-tenant upsert conflict resolution works correctly with
    # index_elements=["tenant_id", "user_id"] in the repository.
    op.execute("ALTER TABLE email_preferences " "ADD CONSTRAINT uq_email_prefs_tenant_user UNIQUE (tenant_id, user_id)")

    # B-01: outbox-first pattern writes a pending_send log entry before attempting
    # the email send, then updates the same row to sent/failed afterwards.
    # updated_at is nullable because existing rows don't have a value.
    op.execute("ALTER TABLE email_log ADD COLUMN updated_at TIMESTAMPTZ")


def downgrade() -> None:
    op.execute("ALTER TABLE email_log DROP COLUMN updated_at")
    op.execute("ALTER TABLE email_preferences DROP CONSTRAINT uq_email_prefs_tenant_user")
