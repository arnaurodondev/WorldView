"""Merge duplicate ``instruments`` rows that share the same symbol.

Revision ID: 046
Revises: 045
Create Date: 2026-07-24

WHY THIS MIGRATION EXISTS (NFLX-duplicate-instrument incident, 2026-07):

  Two rows existed in ``instruments`` for symbol ``NFLX``:
    * ``019f6473-...-af07`` — ``exchange=''`` (placeholder), created 2026-07-15,
      stale fundamentals (data through 2026-03-31 only).
    * ``019f6839-...-3207`` — ``exchange='US'`` (canonical), created 2026-07-16,
      fresh fundamentals (through 2026-07-22).

  ROOT CAUSE (see the audit for the full chain): the ``uq_instruments_symbol_exchange``
  unique constraint is keyed on the EXACT ``(symbol, exchange)`` pair, so
  ``('NFLX', '')`` and ``('NFLX', 'US')`` are two distinct conflict targets —
  ``ON CONFLICT`` never catches this. The placeholder row was created by
  ``fundamentals_consumer`` when ``FundamentalsRefreshWorker`` triggered a
  fundamentals refresh for NFLX from a bare symbol list (no exchange context)
  BEFORE any OHLCV/quotes ingestion had ever created an instrument for it. The
  next day, regular OHLCV/quotes ingestion resolved NFLX's real exchange
  (``'US'``) and, finding no exact match at ``exchange='US'`` either, created a
  SECOND row. ``find_by_symbol_icase`` (no ``ORDER BY`` before this migration's
  companion resolver fix) then non-deterministically preferred the stale
  placeholder, serving stale fundamentals into rag-chat.

  This is a LIVE, recurring risk (not NFLX-specific, not one-time) — the same
  ordering can happen for any symbol. The application-level fix (see
  ``_instrument_dedup.py`` used by ``ohlcv_consumer``/``quotes_consumer``/
  ``fundamentals_consumer``) stops FUTURE duplicates; THIS migration repairs
  data already affected, generically, for ANY symbol currently duplicated —
  not just NFLX — in case other lower-volume tickers hit the same race
  undetected.

WHAT THIS MIGRATION DOES:

  For every group of ``instruments`` rows sharing the same ``upper(symbol)``:
    1. Pick the WINNER — same tie-break as the ``find_by_symbol_icase``
       resolver fix: non-empty/real ``exchange`` first, then most recent
       ``last_fundamentals_ingest_at`` (freshest data), then most recently
       created row.
    2. For every LOSER row, reassign every FK-referencing child row
       (17 fundamentals section tables, ``company_profiles``,
       ``instrument_fundamentals_snapshot``, ``fundamental_metrics``,
       ``insider_transactions``, ``earnings_calendar``, ``ohlcv_bars``,
       ``quotes``) to the winner's ``instrument_id`` — UNLESS the winner
       already has an equivalent row (checked via each table's natural
       key / uniqueness constraint), in which case the loser's (superseded /
       duplicate) row is dropped instead of colliding.
    3. Delete the loser ``instruments`` row once every child table has been
       reassigned or drained (the ``ON DELETE CASCADE`` on every child FK
       would otherwise silently delete any row we failed to move first — this
       migration NEVER relies on that cascade to do the data-preserving work;
       every table is walked explicitly BEFORE the ``DELETE FROM instruments``).

  NOTE: ``instruments.security_id`` -> ``securities.id`` is NOT touched. A
  loser's ``Security`` row (if not shared with the winner) may become
  unreferenced after this migration. That is intentionally left alone — it is
  an internal master-record row with no directly-referencing child data of
  its own (harmless orphan), not user-facing "real data" that this migration
  is scoped to protect.

SAFETY / IDEMPOTENCY:
  * Idempotent: after one pass every symbol group has exactly one row, so a
    re-run finds no groups with ``count(*) > 1`` and is a no-op.
  * ``lock_timeout`` / ``statement_timeout`` bound blast radius against the
    live ingestion consumers (mirrors migration 045's approach).
  * Table/column names used in dynamic SQL are a FIXED, hardcoded list (not
    derived from user input), so ``format(%I, ...)`` is safe.

R11 forward-compat: DATA-only migration; no schema change (the prevention
  guard — a partial unique index — is added separately in migration 047).
  IRREVERSIBLE — merged/deleted duplicate rows cannot be reconstructed, so
  ``downgrade`` is an intentional, documented no-op.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "046"
down_revision: str = "045"
branch_labels = None
depends_on = None

# Fundamentals section tables sharing the ``FundamentalsModelMixin`` shape:
# (instrument_id, period_type, period_end_date) is the natural dedup key,
# additionally enforced at the DB level by ``uq_{table}_instrument_period``
# (migration 001's ``_create_fundamentals_table`` helper).
#
# NOTE: ``dividend_summary`` is DELIBERATELY excluded. It has an ORM model
# (``fundamentals/dividend_summary.py``) but was never actually migrated —
# migrations 019/022/023 independently discovered and worked around the same
# gap (see their inline notes); ``EXECUTE ... ON dividend_summary`` here would
# raise ``UndefinedTable`` on every real environment.
_PERIOD_KEYED_TABLES = (
    "analyst_consensus",
    "cash_flow_statements",
    "dividend_history",
    "balance_sheets",
    "earnings_history",
    "earnings_annual_trends",
    "income_statements",
    "earnings_trends",
    "share_statistics",
    "highlights",
    "fund_holders",
    "insider_transactions_snapshot",
    "outstanding_shares",
    "valuation_ratios",
    "institutional_holders",
    "splits_dividends",
    "technicals_snapshots",
)

# Tables with exactly one row per instrument (PK/UNIQUE on instrument_id alone).
_SINGLE_ROW_TABLES = (
    "company_profiles",
    "instrument_fundamentals_snapshot",
    "quotes",
)

_MERGE_SQL = f"""
DO $$
DECLARE
    grp RECORD;
    winner_id uuid;
    loser_id uuid;
    loser_ids uuid[];
    tbl_name text;
    period_tables text[] := ARRAY[{",".join(f"'{t}'" for t in _PERIOD_KEYED_TABLES)}]::text[];
    single_row_tables text[] := ARRAY[{",".join(f"'{t}'" for t in _SINGLE_ROW_TABLES)}]::text[];
BEGIN
    -- Bound the blast radius against contention with live ingestion consumers
    -- (mirrors migration 045's approach); this migration is idempotent and
    -- resumable, so a timeout just means "re-run alembic upgrade".
    SET LOCAL lock_timeout = '10s';
    SET LOCAL statement_timeout = '15min';

    FOR grp IN
        SELECT array_agg(
                   id
                   ORDER BY (exchange <> '') DESC,
                            last_fundamentals_ingest_at DESC NULLS LAST,
                            created_at DESC
               ) AS ids
        FROM instruments
        GROUP BY upper(symbol)
        HAVING count(*) > 1
    LOOP
        winner_id := grp.ids[1];
        loser_ids := grp.ids[2 : array_length(grp.ids, 1)];

        FOREACH loser_id IN ARRAY loser_ids
        LOOP
            -- ── period-keyed fundamentals section tables ──────────────────
            FOREACH tbl_name IN ARRAY period_tables
            LOOP
                EXECUTE format(
                    'UPDATE %1$I t SET instrument_id = $1 '
                    'WHERE t.instrument_id = $2 '
                    'AND NOT EXISTS ('
                    '  SELECT 1 FROM %1$I t2 WHERE t2.instrument_id = $1 '
                    '  AND t2.period_type = t.period_type '
                    '  AND t2.period_end_date = t.period_end_date'
                    ')',
                    tbl_name
                ) USING winner_id, loser_id;
                EXECUTE format('DELETE FROM %I WHERE instrument_id = $1', tbl_name) USING loser_id;
            END LOOP;

            -- ── single-row-per-instrument tables ───────────────────────────
            FOREACH tbl_name IN ARRAY single_row_tables
            LOOP
                EXECUTE format(
                    'UPDATE %1$I SET instrument_id = $1 '
                    'WHERE instrument_id = $2 '
                    'AND NOT EXISTS (SELECT 1 FROM %1$I WHERE instrument_id = $1)',
                    tbl_name
                ) USING winner_id, loser_id;
                EXECUTE format('DELETE FROM %I WHERE instrument_id = $1', tbl_name) USING loser_id;
            END LOOP;

            -- ── fundamental_metrics: uq(instrument_id, as_of_date, metric, period_type) ──
            UPDATE fundamental_metrics t
            SET instrument_id = winner_id
            WHERE t.instrument_id = loser_id
              AND NOT EXISTS (
                  SELECT 1 FROM fundamental_metrics t2
                  WHERE t2.instrument_id = winner_id
                    AND t2.as_of_date = t.as_of_date
                    AND t2.metric = t.metric
                    AND t2.period_type IS NOT DISTINCT FROM t.period_type
              );
            DELETE FROM fundamental_metrics WHERE instrument_id = loser_id;

            -- ── insider_transactions: uq(instrument_id, filer_name, transaction_date, transaction_type, shares) ──
            UPDATE insider_transactions t
            SET instrument_id = winner_id
            WHERE t.instrument_id = loser_id
              AND NOT EXISTS (
                  SELECT 1 FROM insider_transactions t2
                  WHERE t2.instrument_id = winner_id
                    AND t2.filer_name = t.filer_name
                    AND t2.transaction_date = t.transaction_date
                    AND t2.transaction_type = t.transaction_type
                    AND t2.shares = t.shares
              );
            DELETE FROM insider_transactions WHERE instrument_id = loser_id;

            -- ── earnings_calendar: uq(instrument_id, report_date) ──────────
            UPDATE earnings_calendar t
            SET instrument_id = winner_id
            WHERE t.instrument_id = loser_id
              AND NOT EXISTS (
                  SELECT 1 FROM earnings_calendar t2
                  WHERE t2.instrument_id = winner_id
                    AND t2.report_date = t.report_date
              );
            DELETE FROM earnings_calendar WHERE instrument_id = loser_id;

            -- ── ohlcv_bars: PK(instrument_id, timeframe, bar_date) ──────────
            -- Only ``instrument_id`` is reassigned (never ``bar_date``, the
            -- hypertable partition key) — a plain non-partition-key UPDATE,
            -- safe on a TimescaleDB hypertable (see migration 045's notes).
            UPDATE ohlcv_bars t
            SET instrument_id = winner_id
            WHERE t.instrument_id = loser_id
              AND NOT EXISTS (
                  SELECT 1 FROM ohlcv_bars t2
                  WHERE t2.instrument_id = winner_id
                    AND t2.timeframe = t.timeframe
                    AND t2.bar_date = t.bar_date
              );
            DELETE FROM ohlcv_bars WHERE instrument_id = loser_id;

            -- ── finally, drop the now-childless loser row. Every table with
            -- an ``ON DELETE CASCADE`` FK to ``instruments.id`` has already
            -- been drained above, so this DELETE cascades to nothing.
            DELETE FROM instruments WHERE id = loser_id;

            RAISE NOTICE 'merged duplicate instrument % into %', loser_id, winner_id;
        END LOOP;
    END LOOP;
END
$$;
"""


def upgrade() -> None:
    # DATA migration only — merges duplicate same-symbol instrument rows
    # (created by the FundamentalsRefreshWorker / resolve-or-create race — see
    # module docstring) into a single canonical row per symbol, reassigning
    # every FK-referencing child row first so no real data is lost or
    # cascade-deleted. Idempotent and safe to re-run.
    op.execute(_MERGE_SQL)


def downgrade() -> None:
    # IRREVERSIBLE data migration: merged/deleted duplicate rows cannot be
    # reconstructed. Downgrade is an intentional no-op so ``alembic
    # downgrade`` does not fail, but it does NOT restore the removed rows.
    pass
