"""Denormalize latest snapshot volume_24h onto prediction_markets.

Revision ID: 046
Revises: 045
Create Date: 2026-07-24

WHY THIS MIGRATION EXISTS (list_markets 500 root cause):

  ``list_markets`` (the ``/api/v1/prediction-markets`` list endpoint's repo
  query, ``prediction_market_repo.py``) does a per-open-market
  ``LEFT JOIN LATERAL`` against the ``prediction_market_snapshots``
  hypertable to fetch each market's newest ``volume_24h`` for sorting
  ("recently-traded first"). PLAN-0056 QA already bounded that LATERAL to a
  recent time window (``prediction_market_list_volume_window_days``) to let
  TimescaleDB prune chunks, which helped a lot (~1.8s -> ~60-370ms) but the
  query still re-does a per-market lookup on every single list request, and
  under concurrent load a handful of those lookups still occasionally tip
  over the 8s ``statement_timeout`` (``asyncpg.QueryCanceledError`` ->
  HTTP 500 -> gateway 502 -> frontend widget blank). ~20 occurrences observed
  in 3h; immediate retry usually succeeds (a query-scaling problem, not a
  missing index — the LATERAL's own index, ``ix_pms_market_time``, is fine).

  The structural fix is to stop re-deriving "latest volume" per request at
  all: denormalize it onto ``prediction_markets`` (mirroring the existing
  ``last_snapshot_at`` column added by migration 006 for the same "D-01"
  reason) and keep it in sync at WRITE time (see the ingestion consumer /
  snapshot repo change in the same commit). The list query then reads a
  plain column with no per-row join.

WHAT THIS MIGRATION DOES:

  1. Adds ``latest_volume_24h NUMERIC(20, 4)`` to ``prediction_markets``,
     nullable — mirrors ``prediction_market_snapshots.volume_24h``'s type
     exactly (migration 005) and ``last_snapshot_at``'s nullable convention
     (migration 006).
  2. Backfills existing rows in ONE bulk ``UPDATE ... FROM (SELECT ...
     DISTINCT ON (market_id) ...)`` — a single set-based statement, run once
     at migration time (not a per-request cost), identical in shape to
     migration 006's ``last_snapshot_at`` backfill. It UNCONDITIONALLY
     overwrites ``last_snapshot_at`` (not just when NULL) with the true
     newest snapshot_at per market: migration 006 backfilled that column
     once, but nothing kept it in sync afterwards (no code path wrote it)
     until this migration's write-path change (the snapshot repo now
     updates it on every write), so most existing rows already have a
     NON-NULL but STALE value that must be corrected here, not preserved.
     Going forward the ingestion consumer keeps both columns current.

  BACKFILL SAFETY (reviewed for this migration — see PR description):
  the backfill is a single ``UPDATE ... FROM`` driven by a
  ``GROUP BY market_id`` aggregate over ``prediction_market_snapshots``
  (one row emitted per market_id, using the existing ``ix_pms_market_time``
  index for the per-market MAX pattern), joined back to ``prediction_markets``
  on the market's natural key. ``prediction_markets`` itself is a small,
  non-hypertable table (~hundreds to low-thousands of rows — same
  cardinality migration 006 already updated the same way), so the number of
  rows touched by the ``UPDATE`` is bounded by that table's size, not by the
  (much larger) snapshots hypertable. Locking is a normal row-level
  ``UPDATE`` (ACCESS SHARE on snapshots for the read, ROW EXCLUSIVE on the
  touched ``prediction_markets`` rows) — no ``ALTER TABLE ... ADD COLUMN
  ... DEFAULT <non-null>`` rewrite (the column is nullable with no server
  default, so ``ADD COLUMN`` itself is a fast metadata-only change on
  PG11+). No explicit lock escalation, no long-held table lock is expected.
  Operators should still run this during a low-traffic window per the
  runbook, since the backfill's UPDATE does briefly take row locks on every
  ``prediction_markets`` row that has snapshot history.

Downgrade drops both denormalized columns' new addition (only
``latest_volume_24h`` — ``last_snapshot_at`` predates this migration and is
owned by migration 006's downgrade).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "046"
down_revision = "045"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add latest_volume_24h to prediction_markets (nullable — back-filled
    # below). Same NUMERIC(20, 4) precision as
    # prediction_market_snapshots.volume_24h (migration 005) so the value
    # round-trips without loss when copied across.
    op.add_column(
        "prediction_markets",
        sa.Column("latest_volume_24h", sa.Numeric(20, 4), nullable=True),
    )

    # 2. Backfill latest_volume_24h (and last_snapshot_at, for any row that
    # still has it NULL despite having snapshot history — see module
    # docstring) from the most recent snapshot per market. ONE bulk
    # set-based UPDATE, run once here — never a per-request cost.
    #
    # DISTINCT ON (market_id) ... ORDER BY market_id, snapshot_at DESC picks
    # exactly one (the newest) snapshot row per market, using the same
    # access pattern as ix_pms_market_time (market_id, snapshot_at DESC).
    # WHY unconditional overwrite (not COALESCE(pm.last_snapshot_at, ...)):
    # `sub.snapshot_at` is, by construction of the DISTINCT ON above, the TRUE
    # newest snapshot_at for that market — it is always >= whatever value (if
    # any) is already stored in pm.last_snapshot_at, so it is always safe and
    # always correct to overwrite unconditionally. A prior draft of this
    # migration used COALESCE(pm.last_snapshot_at, sub.snapshot_at), which
    # would have kept migration 006's one-time backfill value for every market
    # that already had a non-NULL last_snapshot_at — i.e. STALE for every
    # market that received a snapshot after migration 006 ran (last_snapshot_at
    # was never kept in sync between migration 006 and this one; see module
    # docstring). That stale value would have broken list_markets()'s
    # volume_window_days CASE (`last_snapshot_at >= now() - N days`) for
    # currently-active markets on the very deploy meant to fix the endpoint —
    # reviewed and caught before merge; see the dedicated regression test that
    # seeds a stale non-NULL last_snapshot_at and asserts it gets corrected.
    op.execute(
        """
        UPDATE prediction_markets pm
        SET
            latest_volume_24h = sub.volume_24h,
            last_snapshot_at = sub.snapshot_at
        FROM (
            SELECT DISTINCT ON (market_id) market_id, snapshot_at, volume_24h
            FROM prediction_market_snapshots
            ORDER BY market_id, snapshot_at DESC
        ) sub
        WHERE pm.market_id = sub.market_id
        """
    )


def downgrade() -> None:
    op.drop_column("prediction_markets", "latest_volume_24h")
