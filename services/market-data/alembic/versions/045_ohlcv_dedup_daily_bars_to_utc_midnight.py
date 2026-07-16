"""Dedup duplicate non-intraday OHLCV bars to ONE UTC-midnight row per day.

Revision ID: 045
Revises: 044
Create Date: 2026-07-16

WHY THIS MIGRATION EXISTS (OHLCV-DUP-BARS root cause):

  ``ohlcv_bars`` PK is ``(instrument_id, timeframe, bar_date)`` with NO
  ``source`` column, and ``bar_date`` is a ``timestamptz``.  Providers stamp
  their DAILY bars at DIFFERENT wall-clock times — EODHD @ 00:00Z, Yahoo @
  04:00/05:00Z, Alpaca @ 04:00Z — so each provider's copy of the SAME trading
  day landed on a DISTINCT ``bar_date`` and therefore a distinct PK row.  The
  provider-priority ``ON CONFLICT`` upsert never collided across providers, so
  every provider's daily copy coexisted.

  Live blast radius (2026-07-16, prod ``market_data_db``):
    * 1d rows: 323,850 total vs 273,805 distinct (instrument, calendar-day)
      → 50,045 EXCESS rows (~15% inflation) across 503/548 instruments.
    * Composition of duplicated days: 40,488 eodhd+yahoo (81%, historical —
      Yahoo is deprecated from routing) + 9,557 alpaca+eodhd (19%, recent).
    * 53,978 of the 1d rows are stamped at a non-midnight wall-clock time.

  Correctness impact: the read-time weekly/monthly derivation
  (``derive_bars_in_memory``) buckets by calendar week/month and SUMS volume
  over the daily input, so a day present N times contributed N x its true
  volume (double/triple-counted), and OHLC could mix across providers.  The
  instrument daily chart also rendered doubled candles.

WHAT THIS MIGRATION DOES:

  For every ``timeframe IN ('1d','1w','1M')`` group keyed by
  ``(instrument_id, timeframe, calendar-day-in-UTC)``:
    1. Pick the WINNER row — highest ``provider_priority`` (Alpaca 110 >
       Yahoo 80 > EODHD 60), ties broken by the newest wall-clock stamp
       (``bar_date DESC``).
    2. UPSERT the winner at ``bar_date`` = that calendar day's UTC midnight
       (unconditional ``ON CONFLICT DO UPDATE`` so a pre-existing midnight row
       is overwritten with the winner's OHLCV / priority / source).
    3. DELETE every remaining row in the group whose ``bar_date`` is NOT
       midnight — the winner's data already lives at midnight, so this is safe.

  This both DEDUPES cross-provider copies AND NORMALIZES every surviving
  non-intraday bar to UTC midnight, matching the new ingest-path behaviour
  (``_normalize_bar_date``) so future providers collide on the conflict target
  and the priority guard resolves them to one row.

CHUNK-SAFETY (``ohlcv_bars`` is a TimescaleDB hypertable, ``bar_date`` is the
  partition key):
    * TimescaleDB forbids UPDATE-ing the partition key in place, so moving a
      bar to midnight is done as DELETE + INSERT (never ``UPDATE bar_date``).
      The midnight target and its non-midnight source share the same calendar
      day → the same chunk, so no data leaves its time range.
    * ``INSERT ... ON CONFLICT`` targets the PK, which INCLUDES the partition
      key — supported on hypertables (TimescaleDB 2.x, live PG16.6 / TS here).
    * The work is done in a PL/pgSQL loop, ONE instrument per iteration, so the
      per-iteration working set (and lock footprint) stays small (548
      instruments) instead of one table-wide statement.

IDEMPOTENT + RESUMABLE:
    * Idempotent: after a full pass every non-intraday group has exactly one
      row at midnight, so a re-run re-selects the same winner, upserts it onto
      itself (no-op), and finds no non-midnight rows to delete.
    * Resumable: the whole migration runs in one Alembic transaction, so an
      interruption rolls back cleanly and re-applying ``alembic upgrade`` (the
      revision was never stamped) redoes the work from a consistent state.

R11 forward-compat: DATA-only migration; no schema change.  IRREVERSIBLE — the
  duplicate rows are destructively merged, so ``downgrade`` cannot restore them
  and is a safe, documented no-op.
"""

from __future__ import annotations

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "045"
down_revision: str = "044"
branch_labels = None
depends_on = None

# Non-intraday timeframes carry ONE bar per calendar day/week/month and must be
# normalized to UTC midnight.  Intraday (1m..4h) is intentionally untouched — the
# time-of-day IS the bar identity there.
_NON_INTRADAY = ("1d", "1w", "1M")

_DEDUP_SQL = """
DO $$
DECLARE
    r RECORD;
    v_deleted   BIGINT := 0;
    v_del       BIGINT;
BEGIN
    -- Truncate ``bar_date`` at UTC midnight regardless of the server's default
    -- timezone (all bars are stored in UTC; date_trunc on a timestamptz uses
    -- the session tz, so pin it to UTC for the whole block).
    SET LOCAL timezone = 'UTC';

    FOR r IN
        SELECT DISTINCT instrument_id
        FROM ohlcv_bars
        WHERE timeframe IN ('1d', '1w', '1M')
    LOOP
        -- Step 1+2: choose the winner per (timeframe, calendar-day) and UPSERT it
        -- at UTC midnight.  DISTINCT ON keeps the first row per group under the
        -- ORDER BY, i.e. highest priority, newest wall-clock on a tie.
        WITH winners AS (
            SELECT DISTINCT ON (timeframe, date_trunc('day', bar_date))
                timeframe,
                date_trunc('day', bar_date) AS norm_bar_date,
                open, high, low, close, volume, adjusted_close,
                source, provider_priority, is_derived, is_partial
            FROM ohlcv_bars
            WHERE instrument_id = r.instrument_id
              AND timeframe IN ('1d', '1w', '1M')
            ORDER BY timeframe,
                     date_trunc('day', bar_date),
                     provider_priority DESC,
                     bar_date DESC
        )
        INSERT INTO ohlcv_bars (
            instrument_id, timeframe, bar_date,
            open, high, low, close, volume, adjusted_close,
            source, provider_priority, is_derived, is_partial
        )
        SELECT
            r.instrument_id, timeframe, norm_bar_date,
            open, high, low, close, volume, adjusted_close,
            source, provider_priority, is_derived, is_partial
        FROM winners
        ON CONFLICT (instrument_id, timeframe, bar_date) DO UPDATE SET
            open              = EXCLUDED.open,
            high              = EXCLUDED.high,
            low               = EXCLUDED.low,
            close             = EXCLUDED.close,
            volume            = EXCLUDED.volume,
            adjusted_close    = EXCLUDED.adjusted_close,
            source            = EXCLUDED.source,
            provider_priority = EXCLUDED.provider_priority,
            is_derived        = EXCLUDED.is_derived,
            is_partial        = EXCLUDED.is_partial;

        -- Step 3: every group now has its winner at midnight, so any remaining
        -- non-midnight non-intraday row for this instrument is a superseded /
        -- relocated duplicate and is safe to delete (DELETE + INSERT, never an
        -- in-place partition-key UPDATE).
        DELETE FROM ohlcv_bars o
        WHERE o.instrument_id = r.instrument_id
          AND o.timeframe IN ('1d', '1w', '1M')
          AND o.bar_date <> date_trunc('day', o.bar_date);
        GET DIAGNOSTICS v_del = ROW_COUNT;
        v_deleted := v_deleted + v_del;
    END LOOP;

    RAISE NOTICE 'ohlcv_bars dedup complete: deleted % non-midnight non-intraday rows', v_deleted;
END
$$;
"""


def upgrade() -> None:
    # DATA migration only — merges cross-provider duplicate non-intraday bars to
    # ONE UTC-midnight row per (instrument, timeframe, calendar-day).  Idempotent
    # and safe to re-run (see module docstring).  ``_NON_INTRADAY`` is documented
    # for reference; the timeframe list is inlined in the guarded SQL.
    assert _NON_INTRADAY == ("1d", "1w", "1M")
    op.execute(_DEDUP_SQL)


def downgrade() -> None:
    # IRREVERSIBLE data migration: the duplicate rows were destructively merged
    # and cannot be reconstructed.  Downgrade is an intentional no-op so an
    # ``alembic downgrade`` does not fail, but it does NOT restore the removed
    # duplicate bars.
    pass
