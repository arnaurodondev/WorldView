"""Add partial index ix_messages_role_created_partial for citation-accuracy cron.

PLAN-0099 W4 (M-1): the daily citation-accuracy cron samples 50 recent
assistant messages with non-empty ``citations`` JSONB. Without a supporting
index the query falls back to a sequential scan + sort, which scales
linearly with the messages table. A partial index on
``(role, created_at DESC) WHERE citations IS NOT NULL`` lets PostgreSQL serve
the cron query with a single bounded index scan.

WHY a partial index (not full): the cron only ever filters on
``role='assistant'`` AND ``citations IS NOT NULL``; user/system messages and
assistant messages without citations are uninteresting. Excluding them keeps
the index small and write-cheap.

WHY CONCURRENTLY: ``messages`` is a hot write path (every chat turn). A
plain ``CREATE INDEX`` takes ``SHARE`` lock which blocks concurrent INSERTs
for the build duration. ``CONCURRENTLY`` uses a non-blocking build (per
BP-007 / existing convention in
``services/intelligence-migrations/alembic/versions/0022_*``).

WHY ``autocommit_block()``: ``CREATE INDEX CONCURRENTLY`` cannot run inside
a transaction, so we use Alembic's autocommit block (the same pattern as
intelligence-migrations 0022).
"""

from __future__ import annotations

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # CONCURRENTLY cannot run inside a transaction — autocommit block required.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_messages_role_created_partial "
            "ON messages (role, created_at DESC) "
            "WHERE citations IS NOT NULL"
        )


def downgrade() -> None:
    # Same autocommit requirement for DROP INDEX CONCURRENTLY.
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_messages_role_created_partial")
