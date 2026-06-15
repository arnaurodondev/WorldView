"""Tombstone orphan ``fundamentals_ohlcv`` embedding rows for non-FI entities.

Revision ID: 0057
Revises: 0056
Create Date: 2026-06-14

WHY THIS MIGRATION EXISTS (empty-entity-descriptions RC3):
  ``entity_embedding_state`` holds three per-entity views: ``definition``,
  ``narrative`` and ``fundamentals_ohlcv``. The ``fundamentals_ohlcv`` view is
  ONLY meaningful for ``financial_instrument`` entities — its source text is
  built from EODHD fundamentals + OHLCV pulled from market-data by ticker.

  An older version of ``ensure_rows_exist`` (before the entity-type guard added
  in PLAN-0093 T-C-4-03) created ``fundamentals_ohlcv`` placeholder rows for
  NON-FI entities too (organizations, indices, exchanges, sectors, …). At the
  time of this migration there are 3,676 such orphan rows.

  ``FundamentalsRefreshWorker.get_due_for_refresh`` filters the due queue to
  ``entity_type = 'financial_instrument'``, so these orphans are never
  processed AND never tombstoned. They sit with ``next_refresh_at`` in the past
  forever, inflating row counts and masking the real FI fundamentals
  population in ops dashboards (8,433 total rows vs ~4,757 legitimate).

WHAT 0057 DOES (data-only, idempotent):
  Pushes ``next_refresh_at`` of every orphan non-FI ``fundamentals_ohlcv`` row
  to the sentinel ``'9999-01-01'`` (the same tombstone value the worker uses
  for no-ticker FI entities). This drains them from the conceptual due queue
  and stops them inflating "due" / "failing" counts.

  We intentionally do NOT delete the rows: the FK to canonical_entities is
  ON DELETE CASCADE, and keeping the rows (tombstoned) is forward-compatible
  and reversible. The create-path is already fixed (entity-type guard in
  ``ensure_rows_exist``), so no NEW orphans are produced — this migration is a
  one-time cleanup of historical rows.

IDEMPOTENT: the WHERE clause excludes rows already at the sentinel, so a re-run
  matches zero rows. Re-running is a no-op.

DOWNGRADE: best-effort — resets ``next_refresh_at`` of the tombstoned orphan
  rows to ``now()`` so they re-enter the (worker-filtered) queue. This is not a
  perfect inverse (we cannot recover the original pre-tombstone timestamps) but
  restores the observable "due" state, which is acceptable for a data-only
  cleanup. The rows are inert for the worker regardless.
"""

from __future__ import annotations

from alembic import op

revision: str = "0057"
down_revision: str = "0056"
branch_labels = None
depends_on = None


# Tombstone sentinel — matches FundamentalsRefreshWorker's far-future defer for
# no-ticker entities (effectively "never re-process").
_TOMBSTONE = "9999-01-01 00:00:00+00"

_UPGRADE = f"""
UPDATE entity_embedding_state AS ees
   SET next_refresh_at = TIMESTAMPTZ '{_TOMBSTONE}'
  FROM canonical_entities AS ce
 WHERE ce.entity_id = ees.entity_id
   AND ees.view_type = 'fundamentals_ohlcv'
   AND ce.entity_type <> 'financial_instrument'
   -- Idempotency guard: skip rows already tombstoned so a re-run is a no-op.
   AND (ees.next_refresh_at IS NULL OR ees.next_refresh_at < TIMESTAMPTZ '{_TOMBSTONE}');
"""

_DOWNGRADE = f"""
UPDATE entity_embedding_state AS ees
   SET next_refresh_at = now()
  FROM canonical_entities AS ce
 WHERE ce.entity_id = ees.entity_id
   AND ees.view_type = 'fundamentals_ohlcv'
   AND ce.entity_type <> 'financial_instrument'
   AND ees.next_refresh_at >= TIMESTAMPTZ '{_TOMBSTONE}';
"""


def upgrade() -> None:
    """Tombstone orphan non-FI ``fundamentals_ohlcv`` rows (data-only, idempotent)."""
    op.execute(_UPGRADE)


def downgrade() -> None:
    """Best-effort: re-queue the tombstoned orphan rows (resets next_refresh_at = now())."""
    op.execute(_DOWNGRADE)
