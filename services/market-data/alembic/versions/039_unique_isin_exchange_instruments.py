"""Prevent same-ISIN duplicate instruments: dedup + UNIQUE(isin, exchange) guard.

Revision ID: 039
Revises: 038
Create Date: 2026-06-13

Background
----------
The existing indexes ``uq_instruments_symbol_exchange`` and
``idx_instruments_ticker_exchange_active (upper(symbol), exchange)`` prevent
EXACT ``symbol+exchange`` duplicates but NOT two rows for the SAME underlying
security that differ only in TICKER NOTATION (``BRK-B`` vs ``BRK.B``), in a
ticker RENAME (``ABC`` → ``COR``), or that carry a BLANK exchange.  Each such
row gets a distinct ``security_id``, so OHLCV/quotes/fundamentals fragment
across the duplicates.  Live 2026-06-13: 4 ISINs duplicated across 9 rows.

What this migration does
------------------------
1. DATA REPAIR (mirrors migration 036's crypto merge): for every same-ISIN
   cluster, pick a survivor and fold the duplicates into it, then DELETE the
   losers (``ON DELETE CASCADE`` sweeps their fact rows).  The survivor is:
     * the row WITH OHLCV bars and a NON-BLANK exchange (the live, tradable
       listing) — this matches the deterministic rule in
       ``scripts/data/merge_duplicate_instruments.py`` for the live-ticker
       choice; for the full notation-vs-canonical reconciliation run that script
       FIRST (it consults intelligence_db.canonical_entities and re-points the
       fundamentals too).  This migration is the durable backstop so a fresh /
       partially-migrated DB still converges before the constraint is added.
   Before deleting losers we re-point their OHLCV bars onto the survivor
   (``INSERT ... ON CONFLICT DO NOTHING`` — the hypertable PK keeps the
   survivor's bar when both cover the same (timeframe, bar_date)).

2. PREVENTION: add a partial unique index
   ``UNIQUE (isin, exchange) WHERE isin IS NOT NULL AND exchange <> ''`` so the
   notation/rename divergence cannot recur.  Blank-exchange and NULL-ISIN rows
   are exempt (they are the enrichment-stub class the dedup removes).

Recommended workflow (canonical-aware)
--------------------------------------
Run ``scripts/data/merge_duplicate_instruments.py --apply`` BEFORE applying this
migration.  That script consults ``intelligence_db.canonical_entities`` and picks
the survivor whose NOTATION matches the surviving canonical (BRK-A dash / BRK.B
dot / BF.B dot / COR) and re-points the fundamentals too.  When it has run, step
1 here finds no duplicates and only the constraint (step 2) is applied.

Step 1 is the canonical-AGNOSTIC backstop for a fresh / partially-migrated DB
that never ran the script: it cannot reach intelligence_db (R9 — no cross-DB
access), so it picks the data-bearing live listing (non-blank exchange + most
OHLCV).  Its notation choice may differ from the script's (e.g. it keeps BRK-B,
the higher-bar-count row, rather than the canonical BRK.B); this is acceptable
for the backstop because its only hard guarantee is "exactly one row per
(isin, exchange) so the unique index can build" — the canonical reconciliation
is the script's job and SHOULD be run first.

Ordering note
-------------
The data repair (step 1) MUST complete before the constraint (step 2) — a
``UNIQUE`` index build fails if duplicates remain.  Both run in the single
migration transaction.

Idempotency / safe-on-clean-DB
------------------------------
If ``scripts/data/merge_duplicate_instruments.py --apply`` already ran (or the
DB is fresh with no dups), step 1 finds nothing to merge and step 2's
``IF NOT EXISTS`` index build is a no-op.

Downgrade
---------
Drops the unique index.  The data merge is irreversible (the duplicates were
bug artifacts); recreating them would re-introduce the fragmentation.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

# ---------------------------------------------------------------------------
# Alembic identifiers
# ---------------------------------------------------------------------------
revision = "039"
down_revision = "038"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()

    # ── Step 1a: pick one survivor per same-ISIN cluster ─────────────────────
    # Survivor = a row with a non-blank exchange, preferring one that already has
    # OHLCV (the live tradable listing); tie-break on lexicographically smallest
    # id for determinism.  DISTINCT ON collapses each ISIN to its survivor.
    conn.execute(
        sa.text(
            """
            CREATE TEMP TABLE _instr_survivor ON COMMIT DROP AS
            SELECT DISTINCT ON (isin) isin, id AS survivor_id
            FROM instruments
            WHERE isin IS NOT NULL
              AND isin IN (
                    SELECT isin FROM instruments
                    WHERE isin IS NOT NULL
                    GROUP BY isin HAVING count(*) > 1
              )
            ORDER BY isin,
                     (exchange <> '') DESC,   -- non-blank exchange first
                     has_ohlcv DESC,          -- live listing (has price data) next
                     id                       -- deterministic tie-break
            """
        )
    )

    # ── Step 1b: re-point OHLCV bars from each loser onto its ISIN survivor ───
    # INSERT ... ON CONFLICT DO NOTHING: the hypertable PK
    # (instrument_id, timeframe, bar_date) keeps the survivor's bar when both
    # rows cover the same (tf, date); the loser's UNIQUE dates are carried over.
    conn.execute(
        sa.text(
            """
            INSERT INTO ohlcv_bars (
                instrument_id, timeframe, bar_date, open, high, low, close,
                volume, adjusted_close, source, provider_priority,
                is_derived, is_partial
            )
            SELECT s.survivor_id, b.timeframe, b.bar_date, b.open, b.high, b.low,
                   b.close, b.volume, b.adjusted_close, b.source,
                   b.provider_priority, b.is_derived, b.is_partial
            FROM ohlcv_bars b
            JOIN instruments loser ON loser.id = b.instrument_id
            JOIN _instr_survivor s ON s.isin = loser.isin
            WHERE loser.id <> s.survivor_id
            ON CONFLICT (instrument_id, timeframe, bar_date) DO NOTHING
            """
        )
    )

    # ── Step 1c: refresh survivor flags from the merged data ─────────────────
    conn.execute(
        sa.text(
            """
            UPDATE instruments i SET
                has_ohlcv = EXISTS (SELECT 1 FROM ohlcv_bars o WHERE o.instrument_id = i.id),
                has_quotes = EXISTS (SELECT 1 FROM quotes q WHERE q.instrument_id = i.id),
                has_fundamentals = EXISTS (
                    SELECT 1 FROM instrument_fundamentals_snapshot f WHERE f.instrument_id = i.id
                )
            FROM _instr_survivor s
            WHERE i.id = s.survivor_id
            """
        )
    )

    # ── Step 1d: delete the loser instruments (CASCADE sweeps their fact rows) ─
    conn.execute(
        sa.text(
            """
            DELETE FROM instruments loser
            USING _instr_survivor s
            WHERE loser.isin = s.isin
              AND loser.id <> s.survivor_id
            """
        )
    )

    # ── Step 1e: delete now-orphaned securities (loser instruments are gone) ──
    conn.execute(
        sa.text(
            """
            DELETE FROM securities sec
            WHERE NOT EXISTS (
                SELECT 1 FROM instruments i WHERE i.security_id = sec.id
            )
            """
        )
    )

    # ── Step 2: prevention guard ─────────────────────────────────────────────
    # Partial unique index: one (isin, exchange) pair per tradable listing.
    # Blank-exchange + NULL-isin rows are exempt (the enrichment-stub class).
    conn.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS uq_instruments_isin_exchange
            ON instruments (isin, exchange)
            WHERE isin IS NOT NULL AND exchange <> ''
            """
        )
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_instruments_isin_exchange")
    # The data merge is irreversible — see module docstring.
