"""Covering index for the screener default-sort page selection.

Revision ID: 038
Revises: 037
Create Date: 2026-06-12

WHY THIS MIGRATION EXISTS (Theme B regression, audit
``docs/audits/2026-06-12-post-fix-failure-rootcause.md``):

  Commit ``2d71ba1ae`` added a default ``ORDER BY market_capitalization DESC``
  to the screener. The no-filter (GET) page-selection branch resolved that sort
  by building an UN-SCOPED subquery over the entire ``metric =
  'market_capitalization'`` partition of ``fundamental_metrics``:

      SELECT instrument_id, MAX(as_of_date)
      FROM fundamental_metrics
      WHERE metric = 'market_capitalization'
      GROUP BY instrument_id           -- whole-partition aggregate
      ... self-JOIN back for value ... ORDER BY value DESC LIMIT N

  Because the page IDs are not yet known (this subquery is what *selects* them),
  the aggregate had to run BEFORE the LIMIT — re-introducing the exact
  full-scan-before-LIMIT the earlier 3-step fix (afde005a9 / c61e86c0b) had
  removed for the display joins. On a cold page cache the planner chose a
  nested-loop and blew the 8 s ``statement_timeout`` → 504 →
  ``screen_universe`` transport_error.

  The repository was rewritten (same commit as this migration) to a single
  ``DISTINCT ON (instrument_id) ... ORDER BY instrument_id, as_of_date DESC``
  scan instead of the aggregate + self-JOIN. That rewrite needs an index whose
  leading columns are ``(metric, instrument_id, as_of_date DESC)`` so the
  WHERE-metric filter + per-instrument latest pick is satisfied directly from
  the index; ``INCLUDE (value_numeric)`` makes the whole thing an INDEX-ONLY
  scan (no heap fetch for the sorted value).

  Neither existing index fits:
    * ``ix_fundamental_metrics_metric_date`` = ``(metric, as_of_date)`` —
      leads with metric (good for the WHERE) but cannot dedup per instrument
      and does not carry ``instrument_id`` second or ``value_numeric``.
    * ``ix_fundamental_metrics_instrument_metric`` = ``(instrument_id, metric,
      as_of_date)`` — leads with ``instrument_id``, so a ``WHERE metric = X``
      scan over all instruments cannot use it as a prefix.

WHAT THIS MIGRATION DOES:
  Creates one covering btree index on ``fundamental_metrics``:

      (metric, instrument_id, as_of_date DESC) INCLUDE (value_numeric)

  This supports the rewritten page-sort subquery (and any future "latest value
  per instrument for one metric, ranked by value" query, e.g. the metric-filter
  branch's default sort) as an index-only scan. After creation it ANALYZEs the
  table so the planner picks the new index on first traffic (BP-581: always
  ship a paired ANALYZE with a query-plan-altering index).

WHY ``CREATE INDEX IF NOT EXISTS`` (not CONCURRENTLY): BP-393 — the Alembic
  runner wraps each revision in a transaction and ``CREATE INDEX CONCURRENTLY``
  cannot run inside one. ``fundamental_metrics`` is a plain table (NOT a
  TimescaleDB hypertable), so a plain ``CREATE INDEX`` is correct here. The
  ANALYZE runs inside ``autocommit_block()`` because ANALYZE cannot run inside a
  transaction block (migration 022 precedent).

R11 forward-compat: additive index only — no column add/remove/rename, no data
  change. Safe to apply ahead of the code that uses it; safe to roll back.

DOWNGRADE: drops the index. Query plans revert to the pre-038 behaviour (the
  DISTINCT ON scan still works, just without the covering index — a heap-fetch
  sort over the latest-per-instrument set instead of index-only).
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "038"
down_revision: str = "037"
branch_labels = None
depends_on = None


_INDEX_NAME = "ix_fundamental_metrics_metric_instr_date_val"


def upgrade() -> None:
    # Covering btree: leading (metric, instrument_id, as_of_date DESC) satisfies
    # the WHERE-metric filter + DISTINCT ON (instrument_id) ORDER BY as_of_date
    # DESC; INCLUDE (value_numeric) lets the page-sort read the ranked value
    # without a heap fetch (index-only scan). All identifiers are hardcoded — no
    # user input — so the literal SQL is safe.
    op.execute(
        "CREATE INDEX IF NOT EXISTS " + _INDEX_NAME + " "
        "ON fundamental_metrics (metric, instrument_id, as_of_date DESC) "
        "INCLUDE (value_numeric)"
    )
    # Paired ANALYZE so the planner picks the new index on first traffic rather
    # than after the next autovacuum pass (BP-581). ANALYZE cannot run inside the
    # migration's transaction block, hence autocommit_block().
    with op.get_context().autocommit_block():
        op.execute("ANALYZE fundamental_metrics")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS " + _INDEX_NAME)
