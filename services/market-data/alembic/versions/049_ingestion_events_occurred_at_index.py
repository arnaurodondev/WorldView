"""Add ix_ingestion_events_occurred_at CONCURRENTLY (retention pruner is non-functional without it).

Revision ID: 049
Revises: 048
Create Date: 2026-07-25

WHY THIS MIGRATION EXISTS:

  ``libs/messaging/kafka/maintenance/table_retention.py`` (built after the
  2026-07-18 disk-full outage — see its module docstring) runs a periodic
  ``RetentionCleanupWorker`` against ``market_data_db.ingestion_events``
  inside the dispatcher process (``dispatcher_main.py``). Its DELETE is::

      DELETE FROM ingestion_events WHERE id IN (
          SELECT id FROM ingestion_events
          WHERE occurred_at < :cutoff
          ORDER BY occurred_at
          LIMIT :batch
          FOR UPDATE SKIP LOCKED
      )

  ``ingestion_events`` was created by migration 001 with only a primary key
  on ``id``, a unique constraint on ``event_id``, and a partial index on
  ``(content_sha256, event_type)`` — **no index on ``occurred_at``**. On a
  small/fresh table the pruner's ``ORDER BY occurred_at LIMIT :batch`` plan
  is a cheap sort of a few rows; at production scale it forces a full
  ``Seq Scan`` + sort of the entire table on every batch.

  Confirmed live on 2026-07-25: ``ingestion_events`` has grown to ~25M rows /
  7.4 GB (the same table implicated in the 2026-07-18 disk-full outage — see
  ``dispatcher_main.py``'s module docstring, "~1 GB / 3.7M rows" at the time
  of that incident, now ~7x larger). The dispatcher's retention loop fails
  its very first pass after this deploy with::

      {"table": "ingestion_events", "error": "... QueryCanceledError: canceling
      statement due to statement timeout ...", "event": "table_retention_loop_error"}

  ``run_retention_loop`` is intentionally fail-open (catches, logs, and
  retries on the next 3600s interval — see its docstring), so this does not
  crash the dispatcher, but it also means the pruner has NEVER successfully
  completed a pass against this table since it was deployed: every attempt
  times out before deleting a single batch. Without a usable index, the
  pruner cannot ever catch up, and ``ingestion_events`` will grow unbounded
  again — recreating the exact disk-full risk this pruner was built to
  prevent. This is the missing piece, not a behavior change to the pruner
  itself.

WHAT THIS MIGRATION DOES:

  Adds a plain btree index on ``occurred_at`` so the pruner's
  ``WHERE occurred_at < :cutoff ORDER BY occurred_at LIMIT :batch`` can use
  an efficient index range scan instead of a full-table sort. Built
  ``CONCURRENTLY`` (mirrors the pattern in
  ``services/intelligence-migrations/alembic/versions/0011_concurrent_alias_norm_index.py``)
  since ``ingestion_events`` is a live, high-write idempotency table and a
  plain ``CREATE INDEX`` would take an ``ACCESS EXCLUSIVE`` lock for the
  duration of the build.

  ``CREATE INDEX CONCURRENTLY`` cannot run inside a transaction, so this uses
  ``op.get_context().autocommit_block()`` exactly like migration 0011.

  Operational note: at ~25M rows the concurrent build itself may take
  meaningful wall-clock time (minutes) and should be run during a
  lower-traffic window per the existing migration runbook; it does not block
  concurrent INSERT/UPDATE/DELETE on the table while building.

Downgrade drops the index (idempotent).
"""

from __future__ import annotations

from alembic import op

revision = "049"
down_revision = "048"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add the missing ``occurred_at`` index CONCURRENTLY (no write lock)."""
    # CONCURRENTLY requires autocommit — Alembic normally wraps everything in a tx.
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_ingestion_events_occurred_at ON ingestion_events (occurred_at)"
        )


def downgrade() -> None:
    """Drop the index. Idempotent — safe to run repeatedly."""
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_ingestion_events_occurred_at")
