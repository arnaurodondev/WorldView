"""Add per-row summary-attempt tracking to relations.

Revision ID: 0048
Revises: 0047
Create Date: 2026-05-23

PLAN-0093 Wave D-3 (T-D-3-02 + T-D-3-03).

WHY THIS MIGRATION EXISTS:
  SummaryWorker (Worker 13C) needs to:
    1. Order the claim batch so fresh-stale rows beat rows that have
       failed N times in a row (T-D-3-02 starve-avoidance).
    2. Count the number of consecutive summary attempts on a relation so we
       can increment summary_worker_stuck_relations_total when the count
       crosses 3 (T-D-3-03 pathological-relation detection).

  Today the ``relations`` table has no attempt-tracking fields — the worker
  has no way to tell a fresh-stale row from one that has failed 100 times
  in a row, so pathological rows dominate every claim batch.

WHAT IT DOES:
  Adds two nullable columns to ``relations``:
    * ``last_summary_attempt_at TIMESTAMPTZ NULL`` — UTC timestamp of the
      most recent attempt (success OR failure).  ``NULL`` means "never
      attempted" and sorts first under ``NULLS FIRST`` so brand-new stale
      rows go to the head of the queue.
    * ``summary_attempt_count INT NOT NULL DEFAULT 0`` — incremented on
      every attempt and reset to 0 on a successful insert into
      ``relation_summaries``.

  Both columns are forward-compatible (R11 — adding NULLABLE columns with
  defaults).  No data migration required; existing rows simply have
  ``last_summary_attempt_at IS NULL`` and ``summary_attempt_count = 0``,
  which is correct: SummaryWorker has not attempted them since this
  feature shipped, so the next sweep will revisit them.

DOWNGRADE:
  Drops both columns.  No data restoration possible (counts are not
  reconstructable from the existing schema).
"""

from __future__ import annotations

from alembic import op

revision: str = "0048"
down_revision: str = "0047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add last_summary_attempt_at + summary_attempt_count to relations.

    The ALTER is forward-compatible: nullable column + default 0 → no
    rewrite of existing rows.  Each partition (relations_p0..p7) inherits
    the column automatically because the parent declaration drives DDL.
    """
    # Parent table (relations is HASH-partitioned) — the ALTER cascades.
    op.execute("ALTER TABLE relations ADD COLUMN IF NOT EXISTS last_summary_attempt_at TIMESTAMPTZ NULL")
    op.execute("ALTER TABLE relations ADD COLUMN IF NOT EXISTS summary_attempt_count INT NOT NULL DEFAULT 0")


def downgrade() -> None:
    """Drop both columns (NOT atomic — both ALTERs run in their own txn)."""
    op.execute("ALTER TABLE relations DROP COLUMN IF EXISTS summary_attempt_count")
    op.execute("ALTER TABLE relations DROP COLUMN IF EXISTS last_summary_attempt_at")
