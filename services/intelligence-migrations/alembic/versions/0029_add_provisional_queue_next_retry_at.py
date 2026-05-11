"""Add ``next_retry_at TIMESTAMPTZ`` to ``provisional_entity_queue``.

Revision ID: 0029
Revises: 0028
Create Date: 2026-05-06

WHY (DEF-033 — exponential backoff for LLM-outage resilience):
  ``ProvisionalEnrichmentWorker`` (Worker 13E) and the hot-path
  ``ProvisionalQueuedConsumer`` both call out to the extraction + embedding
  LLM chain.  When that chain experiences an outage (DeepInfra 5xx, network
  partition, model rate-limit), every row that fails simply flips back to
  ``status='pending'`` and is re-claimed on the next 5-minute polling cycle.
  With a hot batch of up to 2,500 permanently-failing rows this hammers the
  upstream API at full intensity until ``retry_count`` finally hits the cap
  ~25 minutes later — by which point we have spent significant money on
  guaranteed-to-fail calls and may have triggered provider-side throttling.

  Adding ``next_retry_at`` lets the worker compute an exponential backoff
  (``2^retry_count`` minutes, capped at 24h) on every failed attempt and
  filter it out of the Phase-1 SELECT until the deadline elapses.  A single
  outage now self-throttles instead of compounding.

BACKWARD-COMPATIBILITY:
  - Column is **nullable** with no server default — existing rows have
    ``next_retry_at IS NULL`` and the modified ``claim_batch`` SELECT
    explicitly treats NULL as "immediately eligible"
    (``next_retry_at IS NULL OR next_retry_at <= now()``).  No backfill is
    required and no row becomes stuck on upgrade.
  - BP-126 does not apply: BP-126 forbids NOT-NULL columns without a
    ``server_default``; this column is nullable so the rule is satisfied
    by construction.

INDEX RATIONALE:
  The Phase-1 SELECT already filters on ``status='pending'``.  Adding a
  partial index restricted to that status (``WHERE status = 'pending' AND
  next_retry_at IS NOT NULL``) keeps the index very small (only rows
  currently waiting for a retry deadline), and makes the filter
  ``next_retry_at <= now()`` an index range scan instead of a full
  partition scan when the queue is large.  Rows with NULL retry are not
  in the index — the planner will fall back to the existing per-row scan,
  which is fine because those rows are immediately eligible anyway.

WHY NOT CONCURRENTLY (BP-393):
  ``provisional_entity_queue`` is currently un-partitioned, but the
  worldview convention is to use plain ``CREATE INDEX IF NOT EXISTS`` on
  parent tables so the DDL stays valid if the table is later partitioned
  (PG16 forbids ``CREATE INDEX CONCURRENTLY`` on partitioned parents).
  This is a thesis-grade dev system where the brief lock is acceptable.

DOWNGRADE:
  Drop the partial index then drop the column.  The ``claim_batch`` SQL
  always emits ``next_retry_at IS NULL OR ...``; removing the column would
  cause that predicate to fail with ``UndefinedColumn``, so the worker /
  consumer must be redeployed with the pre-Wave-A-4 SQL before applying
  this downgrade.
"""

from __future__ import annotations

from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Nullable column — no server_default needed (existing rows = NULL = eligible).
    op.execute(
        """
        ALTER TABLE provisional_entity_queue
            ADD COLUMN IF NOT EXISTS next_retry_at TIMESTAMPTZ NULL
        """
    )

    # Partial index — only rows currently waiting on a retry deadline appear in
    # the index, keeping it compact and making the
    # ``next_retry_at <= now()`` filter an index range scan.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_provisional_queue_retry_at
            ON provisional_entity_queue (next_retry_at)
            WHERE status = 'pending' AND next_retry_at IS NOT NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_provisional_queue_retry_at")
    op.execute("ALTER TABLE provisional_entity_queue DROP COLUMN IF EXISTS next_retry_at")
