-- F-DB-006 — Long-skip ``entity_embedding_state`` rows whose ticker is not in
-- ``market_data_db.instruments`` at all. These canonicals were created by S6's
-- enrichment path but never reached market-ingestion, so the
-- FundamentalsRefreshWorker can NEVER refresh them — every cycle the lookup
-- 404s, the entity is reported as ``instrument_lookup_failed`` (312/cycle in
-- iter-11), and a worker slot is wasted.
--
-- Until PRD-XXXX wires a ``fi.canonical.created.v1 → market-ingestion`` event
-- (see docs/audits/2026-05-28-fundamentals-shape-audit.md Stage 6), the right
-- behaviour is to park these rows so the worker stops hammering them.
--
-- Idempotent: re-running on rows already marked ``terminal_no_market_data`` is
-- a no-op (the UPDATE only flips rows whose ``next_refresh_at`` is still in
-- the worker's normal cadence window).
--
-- USAGE (intelligence_db side):
--   psql -h postgres -U postgres -d intelligence_db \
--        -f services/intelligence-migrations/scripts/long_skip_fundamentals_data_gap.sql
--
-- The cross-database join uses ``dblink`` because ``market_data_db.instruments``
-- lives in a separate logical database on the same Postgres cluster. If
-- ``dblink`` is not available, fall back to the two-step approach in the
-- audit doc (dump the lists to /tmp, diff, then drive the UPDATE from a
-- temp-table).
--
-- NOTE (F-DB-006, 2026-05-28): The original committed version of this script
-- filtered ``WHERE active = true`` on the remote ``instruments`` query, but
-- the current ``market_data_db.instruments`` schema has no ``active`` (or
-- ``is_active``) column. The active/delisted indicator lives elsewhere
-- (``has_fundamentals``/``has_ohlcv`` capability flags), and the audit intent
-- was always "ticker not present at all" (see line 2: "active or not").
-- Removing the bogus predicate restores the intended semantics and unblocks
-- ops re-runs.

\set ON_ERROR_STOP on

-- Ensure dblink extension is available (cluster-scoped — safe to re-create).
CREATE EXTENSION IF NOT EXISTS dblink;

BEGIN;

-- Stage 1: assemble the set of FI canonicals whose ticker has NO matching row
-- in ``market_data_db.instruments`` at all. We use a temp table so the UPDATE
-- below has a clean set even if dblink's keepalive churns.
CREATE TEMP TABLE _data_gap_entities AS
SELECT ce.entity_id
FROM canonical_entities ce
WHERE ce.entity_type = 'financial_instrument'
  AND ce.ticker IS NOT NULL
  AND NOT EXISTS (
    SELECT 1
    FROM dblink(
      'host=postgres port=5432 user=postgres password=postgres dbname=market_data_db',
      'SELECT symbol FROM instruments'
    ) AS m(symbol text)
    WHERE m.symbol = ce.ticker
  );

-- Stage 2: long-skip every embedding_state row that targets a data-gap entity.
-- ``next_refresh_at = '9999-01-01'`` puts the row out of the worker's
-- ``WHERE next_refresh_at <= now()`` filter for ~7973 years — i.e. forever
-- in practice. If/when market-ingestion later imports the ticker, ops can
-- bulk-reset these rows via a counterpart script.
UPDATE entity_embedding_state ees
SET next_refresh_at = '9999-01-01'::timestamptz
WHERE ees.view_type = 'fundamentals_ohlcv'
  AND ees.entity_id IN (SELECT entity_id FROM _data_gap_entities)
  -- Don't churn rows already parked.
  AND ees.next_refresh_at < '9999-01-01'::timestamptz;

-- Reporting: how many rows did we park? Useful to compare against the
-- iter-11 audit baseline (~312 instrument_lookup_failed per cycle).
SELECT count(*) AS parked_rows FROM _data_gap_entities;

DROP TABLE _data_gap_entities;

COMMIT;
