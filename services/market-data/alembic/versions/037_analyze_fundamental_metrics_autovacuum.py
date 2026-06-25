"""ANALYZE fundamental_metrics + tighten its autovacuum so it does not re-rot.

Revision ID: 037
Revises: 036
Create Date: 2026-06-11

Fix 2 of the screener limit=100 cold-cache 504 investigation.

WHY THIS MIGRATION EXISTS:
  EXPLAIN ANALYZE of the cold screener page (limit=100) showed the second of
  two compounding costs that blow past the 8s ``statement_timeout``:
  ``fundamental_metrics`` had ~396k dead tuples and EMPTY ``last_vacuum`` /
  ``last_analyze`` columns. With stale ``pg_statistic`` the planner's
  index-only-scan subqueries for the 12 displayed key metrics degraded to
  ~462 heap fetches each (visibility-map misses on the bloated heap).

  ``fundamental_metrics`` is the single hottest screener table: it is written
  continuously by ``computed_metrics_worker`` (one row per instrument*metric
  *period, upserted on every recompute) yet PostgreSQL's *default* autovacuum
  thresholds (``autovacuum_analyze_scale_factor = 0.1`` = analyse only after
  10% of the table changes) are far too lax for a table this churn-heavy — by
  the time 10% has changed the table has already accumulated enough dead
  tuples + stat drift to regress the plan. Default autovacuum is mis-tuned for
  THIS table specifically, so we override the per-table storage parameters
  rather than touching the cluster-wide GUC.

WHAT THIS MIGRATION DOES:
  1. ``ALTER TABLE`` sets tighter per-table autovacuum/autoanalyze scale
     factors so PostgreSQL vacuums + reanalyses ``fundamental_metrics`` an
     order of magnitude sooner, preventing the dead-tuple + stale-stats
     re-rot that produced this 504. This is the durable fix.
  2. A one-shot ``VACUUM (ANALYZE) fundamental_metrics`` reclaims the existing
     ~396k dead tuples and refreshes statistics immediately, so the speedup is
     realised on first traffic rather than after the next autovacuum cycle
     (BP-577: ship a paired ANALYZE whenever a change is meant to alter a hot
     query plan).

WHY ``autocommit_block()``:
  ``VACUUM`` (like ``ANALYZE`` in migration 022 / ``CREATE INDEX CONCURRENTLY``
  per BP-393) cannot run inside an explicit transaction block. The Alembic
  runner wraps every revision in a transaction by default, so we temporarily
  exit it via ``op.get_context().autocommit_block()`` for the VACUUM. The
  ``ALTER TABLE ... SET (...)`` is transactional and could live outside the
  block, but we keep it inside so the whole maintenance step is one logical
  unit in the operator log.

DOWNGRADE:
  Reset the per-table autovacuum overrides to cluster defaults. The VACUUM is
  not undoable (nor would we want to "un-reclaim" dead tuples); statistics are
  refreshed in place and continue to be maintained by autovacuum.
"""

from __future__ import annotations

from alembic import op

revision = "037"
down_revision = "036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Tighten autovacuum for fundamental_metrics, then VACUUM ANALYZE it once."""
    with op.get_context().autocommit_block():
        # Durable fix: vacuum after 2% churn (vs default 10%) and analyse after
        # 1% (vs default 10%), with small fixed thresholds so the percentages
        # kick in promptly on this high-write table. Identifiers/values are all
        # hardcoded here — no user input — so the literal SQL is safe.
        op.execute(
            "ALTER TABLE fundamental_metrics SET ("
            "autovacuum_vacuum_scale_factor = 0.02, "
            "autovacuum_vacuum_threshold = 1000, "
            "autovacuum_analyze_scale_factor = 0.01, "
            "autovacuum_analyze_threshold = 1000"
            ")"
        )
        # One-shot reclaim + stats refresh so the plan improves on first traffic
        # rather than waiting for the next autovacuum pass.
        op.execute("VACUUM (ANALYZE) fundamental_metrics")


def downgrade() -> None:
    """Reset the per-table autovacuum overrides to cluster defaults."""
    # RESET removes the per-table storage parameters so the table falls back to
    # the cluster-wide autovacuum GUCs. The reclaimed space / refreshed stats
    # from the upgrade's VACUUM ANALYZE are intentionally not reverted.
    op.execute(
        "ALTER TABLE fundamental_metrics RESET ("
        "autovacuum_vacuum_scale_factor, "
        "autovacuum_vacuum_threshold, "
        "autovacuum_analyze_scale_factor, "
        "autovacuum_analyze_threshold"
        ")"
    )
