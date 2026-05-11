"""Add ``processing_started_at TIMESTAMPTZ`` to ``provisional_entity_queue``.

Revision ID: 0030
Revises: 0029
Create Date: 2026-05-07

WHY (D-016 — fix false recovery in _recover_stale_processing_rows):
  ``_recover_stale_processing_rows()`` resets rows stuck in ``status='processing'``
  back to ``pending`` using the heuristic:

      WHERE status = 'processing'
        AND created_at < now() - interval '30 minutes'

  The problem: ``created_at`` records when the row was *inserted into the queue*
  (i.e. when the article was processed by the NLP pipeline), NOT when the row
  transitioned to ``processing`` status.  Under normal batch-ingest conditions,
  rows can sit in ``pending`` for hours before a worker claims them.  If a row was
  created 35 minutes ago but only started processing 1 minute ago, the old query
  incorrectly classifies it as stale and resets it — causing:

    1. **False recovery**: recently-started rows are reset, leading to duplicate
       enrichment work and wasted LLM calls (BP-417).
    2. **Missed recovery**: rows created < 30 minutes ago are never recovered,
       even if they have been stuck in ``processing`` for a long time because the
       worker that claimed them was killed.

  The fix is to record the actual processing-start timestamp when a row transitions
  to ``processing``, then use that value in the recovery predicate:

      WHERE status = 'processing'
        AND COALESCE(processing_started_at, created_at)
              < now() - interval '30 minutes'

  ``COALESCE`` provides backward compatibility: rows that were already in
  ``processing`` at the time of this migration have ``processing_started_at IS NULL``
  and fall back to ``created_at`` so existing stuck rows are still recoverable.

BACKWARD-COMPATIBILITY:
  - Column is nullable with no server_default — no backfill needed.
  - BP-126 does not apply: BP-126 forbids NOT-NULL columns without a server_default;
    this column is nullable so the rule is satisfied by construction.
  - Existing ``processing`` rows have ``processing_started_at IS NULL`` and fall
    back to ``created_at`` via ``COALESCE``, so no rows become permanently stuck.

DOWNGRADE:
  Drop the column.  The modified claim UPDATE and recovery UPDATE in
  ``provisional_enrichment.py`` must be reverted to the pre-D-016 SQL before
  applying this downgrade, otherwise those queries will fail with
  ``UndefinedColumn``.
"""

from __future__ import annotations

from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable column — no server_default needed.
    # Existing rows in 'processing' get NULL and fall back to created_at via
    # COALESCE in the recovery query (backward-compatible).
    op.execute(
        """
        ALTER TABLE provisional_entity_queue
            ADD COLUMN IF NOT EXISTS processing_started_at TIMESTAMPTZ NULL
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE provisional_entity_queue DROP COLUMN IF EXISTS processing_started_at")
