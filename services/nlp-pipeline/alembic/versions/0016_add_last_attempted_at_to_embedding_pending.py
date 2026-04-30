"""Add last_attempted_at to embedding_pending (PLAN-0057 Wave E-4 / F-MAJOR-05).

Revision ID: 0016
Revises: 0015
Create Date: 2026-05-01

The original migration 0004 stored ``next_retry_at`` (when the next attempt is
*due*) but never recorded *when* the most recent attempt actually ran.  Without
this column the operations team can't tell whether a row's ``retry_count`` is
high because the worker is genuinely retrying or because the worker has been
silently failing for hours; we also can't distinguish a freshly-claimed row
from one that has been stuck mid-flight after a worker crash.

This migration is forward-compatible and idempotent:
  * adds the column NULLABLE without a server default — backfilling avoids any
    write-amplification on a potentially large queue;
  * the EmbeddingRetryWorker stamps the column inside ``mark_failure``;
  * downgrade simply drops the column (no data loss for any caller).
"""

from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE embedding_pending ADD COLUMN IF NOT EXISTS last_attempted_at TIMESTAMPTZ")


def downgrade() -> None:
    op.execute("ALTER TABLE embedding_pending DROP COLUMN IF EXISTS last_attempted_at")
