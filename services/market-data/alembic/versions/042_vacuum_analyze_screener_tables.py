"""Paired VACUUM (ANALYZE) for the screener tables alongside the NEW-6 rewrite.

Revision ID: 042
Revises: 041
Create Date: 2026-07-06

WHY THIS MIGRATION EXISTS (NEW-6, audit
``docs/audits/2026-07-06-r1-final-exhaustive-qa.md``):

  The screener (``fundamental_metrics_query.query_screen``) was timing out
  (~114 s in R1, then ``QueryCanceledError`` → 504 under host load in R2), so the
  screener + market-movers surfaces returned no data. ``EXPLAIN (ANALYZE)`` on the
  live DB isolated TWO compounding costs:

    1. QUERY SHAPE (fixed in code, same commit): the per-metric filter subquery
       ran a whole-partition ``GROUP BY instrument_id MAX(as_of_date)`` aggregate
       (~14,183 index rows, 7,030 ms, 4,689 heap fetches). It was rewritten to a
       ``DISTINCT ON (instrument_id)`` SkipScan on the existing covering index
       ``ix_fundamental_metrics_metric_instr_date_val`` — one row per instrument
       (~615 rows, ~1.2 s, 44 heap fetches). No NEW index is required: index 038
       already has the right shape ``(metric, instrument_id, as_of_date DESC)
       INCLUDE (value_numeric)``.

    2. STALE PLANNER STATS + VISIBILITY MAP (fixed here): despite migration 037's
       tightened per-table autovacuum, under sustained host CPU/IO contention
       (load ~150 on the dev host) autovacuum fell behind. A fresh ``EXPLAIN
       (ANALYZE)`` measured **1,728 ms of PLANNING TIME alone** on stale
       ``pg_statistic`` for the screener query, and index-only scans doing heap
       fetches against a stale visibility map. A one-shot ``VACUUM (ANALYZE)``
       dropped planning to **9 ms** and cut heap fetches — a ~190x planning
       improvement measured live.

  This migration ships the paired stats + visibility-map refresh so the rewritten
  DISTINCT ON plan is chosen (and planned cheaply) on first traffic after deploy,
  rather than waiting for the next autovacuum pass (BP-581 / BP-577: always pair a
  query-plan-altering change with an ANALYZE of the affected table). The durable
  ongoing fix — the tightened per-table autovacuum thresholds — already landed in
  migration 037; this is the one-shot reset that accompanies the code rewrite.

WHAT THIS MIGRATION DOES:
  ``VACUUM (ANALYZE) fundamental_metrics`` — the single hottest screener table
  (written continuously by ``computed_metrics_worker``). VACUUM reclaims dead
  tuples + refreshes the visibility map (so index-only scans stop heap-fetching);
  ANALYZE refreshes ``pg_statistic`` (so planning is fast and the SkipScan plan is
  chosen). On a low-dead-tuple table VACUUM skips already-clean pages via the
  visibility map, so the cost is bounded.

WHY ``autocommit_block()``:
  ``VACUUM`` cannot run inside an explicit transaction block, and the Alembic
  runner wraps every revision in a transaction by default. We temporarily exit it
  via ``op.get_context().autocommit_block()`` (same pattern as migrations 022 /
  037 / 038). All identifiers are hardcoded — no user input — so the literal SQL
  is safe.

R11 forward-compat: no schema change — maintenance only. Safe to apply ahead of
  or behind the code that benefits from it; safe to roll back.

DOWNGRADE: no-op. A VACUUM/ANALYZE cannot (and should not) be "undone" — reclaimed
  space and refreshed statistics are strictly beneficial and continue to be
  maintained by autovacuum. Kept as an explicit empty function so the revision is
  cleanly reversible in the Alembic history.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "042"
down_revision: str = "041"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """One-shot VACUUM (ANALYZE) of the hot screener table (paired with rewrite)."""
    with op.get_context().autocommit_block():
        # Reclaim dead tuples + refresh the visibility map (kills index-only-scan
        # heap fetches) AND refresh pg_statistic (fast planning + correct SkipScan
        # plan). Bounded cost on a table kept clean by migration 037's autovacuum
        # overrides. Literal SQL, no user input.
        op.execute("VACUUM (ANALYZE) fundamental_metrics")


def downgrade() -> None:
    """No-op: a VACUUM/ANALYZE is not reversible and is strictly beneficial."""
    # Intentionally empty — reclaimed space / refreshed stats are not undone and
    # continue to be maintained by autovacuum (see module docstring).
