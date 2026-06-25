#!/usr/bin/env python3
"""Merge same-ISIN duplicate ``instruments`` into one survivor (market_data_db).

ROOT CAUSE
----------
The unique indexes ``uq_instruments_symbol_exchange`` and
``idx_instruments_ticker_exchange_active (upper(symbol), exchange)`` prevent
EXACT ``symbol+exchange`` duplicates, but NOT two rows for the SAME underlying
security that differ in *ticker notation* (``BRK-B`` vs ``BRK.B``) or in a
*ticker rename* (``ABC`` → ``COR``) or carry a *blank exchange*.  Each such row
gets a DISTINCT ``security_id`` and therefore its OHLCV bars, quotes,
fundamentals, etc. fragment across the duplicates (downstream joins
``entity → instrument → ohlcv/fundamentals`` silently split).

Two contributing minting paths:
  * Legacy seeding (pre-``_normalize_ticker``) wrote dash forms (``BRK-A``,
    ``BF-B``); the consumers now normalize to dot-form, but the old rows remain.
  * The ISIN/EODHD on-demand enrichment path created blank-exchange rows
    (``BRK.A`` / ``BF.B`` with ``exchange=''``).

Live snapshot 2026-06-13 (market_data_db.instruments, 651 rows): 4 ISINs are
duplicated across 9 rows.

DEPENDENCY MAP (verified against information_schema)
----------------------------------------------------
EVERY market-data fact table FKs ``instrument_id → instruments.id`` with
``ON DELETE CASCADE`` (26 tables incl. the ``ohlcv_bars`` TimescaleDB
hypertable chunks).  The ONLY thing FKing ``securities.id`` is ``instruments``
itself.  So the merge unit is the INSTRUMENT: re-point dependent rows from each
loser ``instrument_id`` onto the survivor's ``instrument_id`` (only where the
survivor lacks that row — the survivor's data wins on conflict), then delete the
loser instrument.  The loser's now-orphaned ``security`` is deleted afterwards
(each loser security is referenced 1:1 by its loser instrument — verified).

SURVIVOR RULE (deterministic, documented — see PLAN-0111 / memory)
------------------------------------------------------------------
Within a same-ISIN cluster, pick the survivor that:
  1. matches the SURVIVING canonical ticker (intelligence_db.canonical_entities)
     for that security — so the instrument and its canonical stay on ONE side
     and never re-diverge (the canonicals were already deduped to:
     ``BRK-A`` dash / ``BRK.B`` dot / ``BF.B`` dot / ``COR``).  This is the
     PRIMARY rule and is what makes notation/rename choices non-arbitrary.
  2. failing a canonical match (no canonical, or canonical ticker absent from
     the cluster), prefer the row WITH a non-blank exchange AND the most
     dependent data (OHLCV bars + quotes + fundamentals).
  3. NEVER a blank-exchange row.
  4. tie-break: most dependent rows, then lexicographically smallest id.

The chosen notation may NOT be the row with the most bars (e.g. BRK.B is the
canonical even though BRK-B has marginally more bars) — matching the canonical
side is more important than a few extra bars, which the re-point recovers anyway.

RE-POINT (idempotent, single transaction per cluster)
-----------------------------------------------------
For each dependent table, for each loser instrument_id:
  * UPDATE the loser rows to the survivor instrument_id, but SKIP any loser row
    whose (survivor_id, <other unique-key cols>) already exists on the survivor
    (its data is authoritative); those skipped rows are then DELETEd.
The unique conflict keys are read live from pg_index per table, so the script
adapts automatically if a fact table gains/loses a constraint.

SAFE TO RE-RUN: after a successful pass each ISIN has exactly one instrument, so
the cluster query returns nothing.

PREVENTION (separate, see services/market-data/alembic/versions): a migration
adds ``UNIQUE(isin, exchange) WHERE isin IS NOT NULL AND exchange <> ''`` so the
notation/rename divergence cannot recur once the data is clean.

Usage
-----
    python scripts/data/merge_duplicate_instruments.py             # DRY RUN (default)
    python scripts/data/merge_duplicate_instruments.py --apply     # WRITE
    python scripts/data/merge_duplicate_instruments.py --isin US0846707026
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field

import psycopg

# Default DSNs target the local docker-compose Postgres (single instance, many
# logical DBs).  Override via env for other environments.
_MARKET_DSN = os.environ.get(
    "MARKET_DATA_DB_DSN",
    "postgresql://postgres:postgres@localhost:5432/market_data_db",
)
_INTEL_DSN = os.environ.get(
    "INTELLIGENCE_DB_DSN",
    "postgresql://postgres:postgres@localhost:5432/intelligence_db",
)


@dataclass
class Member:
    """One instrument row inside a same-ISIN cluster."""

    instrument_id: str
    security_id: str
    symbol: str
    exchange: str
    has_ohlcv: bool
    has_quotes: bool
    has_fundamentals: bool
    name: str | None
    dep_count: int = 0  # total dependent rows across all fact tables
    price_count: int = 0  # ohlcv_bars + quotes rows (the live-ticker signal)


@dataclass
class Cluster:
    isin: str
    members: list[Member] = field(default_factory=list)


def _fetch_clusters(market: psycopg.Connection, isin: str | None) -> list[Cluster]:
    """Return same-ISIN instrument clusters with count > 1."""
    # Fixed SQL with one constant {clause} slot; the isin value is always a bound
    # parameter (never spliced), so there is no injection surface.
    base = """
SELECT i.isin, i.id, i.security_id, i.symbol, i.exchange,
       i.has_ohlcv, i.has_quotes, i.has_fundamentals, i.name
FROM instruments i
WHERE i.isin IS NOT NULL
  {clause}
  AND i.isin IN (
        SELECT isin FROM instruments
        WHERE isin IS NOT NULL
        GROUP BY isin HAVING count(*) > 1
  )
ORDER BY i.isin, i.symbol
"""
    sql = base.replace("{clause}", "AND i.isin = %(isin)s" if isin else "")
    rows = market.execute(sql, {"isin": isin} if isin else {}).fetchall()
    by_isin: dict[str, list[Member]] = {}
    for row in rows:
        by_isin.setdefault(str(row[0]), []).append(
            Member(
                instrument_id=str(row[1]),
                security_id=str(row[2]),
                symbol=row[3],
                exchange=row[4] or "",
                has_ohlcv=bool(row[5]),
                has_quotes=bool(row[6]),
                has_fundamentals=bool(row[7]),
                name=row[8],
            )
        )
    return [Cluster(isin=i, members=m) for i, m in by_isin.items() if len(m) > 1]


def _dependent_tables(market: psycopg.Connection) -> list[str]:
    """Every base table (no hypertable chunks) that FKs instruments via instrument_id."""
    rows = market.execute(
        """
SELECT c.table_name
FROM information_schema.columns c
JOIN information_schema.tables t
  ON t.table_name = c.table_name AND t.table_schema = c.table_schema
WHERE c.column_name = 'instrument_id'
  AND c.table_schema = 'public'
  AND t.table_type = 'BASE TABLE'
  AND c.table_name NOT LIKE '\\_hyper\\_%' ESCAPE '\\'
ORDER BY c.table_name
"""
    ).fetchall()
    return [str(r[0]) for r in rows]


def _unique_key_cols(market: psycopg.Connection, table: str) -> list[str]:
    """Return the columns of the table's *narrowest* unique index that includes
    ``instrument_id`` (its natural-key conflict key for the re-point)."""
    rows = market.execute(
        """
SELECT i.relname AS idx, a.attname AS col, ix.indnatts
FROM pg_index ix
JOIN pg_class i ON i.oid = ix.indexrelid
JOIN pg_class t ON t.oid = ix.indrelid
JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey)
WHERE ix.indisunique AND t.relname = %(t)s
ORDER BY i.relname, a.attnum
""",
        {"t": table},
    ).fetchall()
    by_idx: dict[str, list[str]] = {}
    for idx, col, _ in rows:
        by_idx.setdefault(str(idx), []).append(str(col))
    # Pick a unique index that contains instrument_id; prefer the narrowest one
    # that is NOT the surrogate ``id`` PK (which never constrains the re-point).
    candidates = [cols for cols in by_idx.values() if "instrument_id" in cols]
    if not candidates:
        return []
    candidates.sort(key=len)
    return candidates[0]


def _count_dependents(market: psycopg.Connection, tables: list[str], instrument_id: str) -> int:
    """Total dependent rows for one instrument across all fact tables."""
    total = 0
    for table in tables:
        # table is from a fixed information_schema-derived allowlist; id is bound.
        row = market.execute(
            f"SELECT count(*) FROM {table} WHERE instrument_id = %(id)s",  # noqa: S608
            {"id": instrument_id},
        ).fetchone()
        total += int(row[0]) if row else 0
    return total


def _surviving_canonical_tickers(intel: psycopg.Connection | None, isin: str) -> set[str]:
    """Return ALL canonical tickers (uppercased) for ``isin`` (intelligence_db).

    Used by the survivor rule: when EXACTLY ONE cluster member matches a canonical
    ticker, that match is decisive (notation dups — the canonicals were already
    deduped to one notation per security).  When the canonical side itself still
    carries multiple tickers for the ISIN (e.g. a ticker RENAME like ABC→COR where
    both canonicals linger), the match is ambiguous and we fall back to the
    price-data signal (the live ticker is the one receiving OHLCV/quotes).
    Returns an empty set when intelligence_db is unavailable or has no match.
    """
    if intel is None:
        return set()
    try:
        rows = intel.execute(
            "SELECT ticker FROM canonical_entities WHERE isin = %(isin)s AND ticker IS NOT NULL",
            {"isin": isin},
        ).fetchall()
    except psycopg.Error:
        return set()
    return {str(r[0]).upper() for r in rows if r[0]}


def _choose_survivor(cluster: Cluster, canonical_tickers: set[str]) -> Member:
    """Apply the documented survivor rule (see module docstring).

    Order:
      1. If EXACTLY ONE non-blank-exchange member matches a canonical ticker, it
         wins (notation dup — the canonical side is unambiguous).
      2. Otherwise (no match, or an ambiguous/renamed canonical side): never a
         blank-exchange row; prefer the member with PRICE data (ohlcv+quotes) —
         that is the live ticker (a rename's retired ticker stops receiving
         prices, e.g. ABC after the Cencora rename).
      3. Tie-break: total dependent rows, then lexicographically smallest id.
    """
    members = cluster.members
    if canonical_tickers:
        matches = [m for m in members if m.symbol.upper() in canonical_tickers and m.exchange]
        if len(matches) == 1:
            return matches[0]
        # 0 matches (canonical only as blank-exchange row) or >1 (ambiguous /
        # rename) → fall through to the price-data signal below.
    non_blank = [m for m in members if m.exchange]
    pool = non_blank or members
    # Live-ticker first (price data), then total data, then smallest id.
    return max(
        pool,
        key=lambda m: (m.price_count, m.dep_count, [-ord(c) for c in m.instrument_id]),
    )


def _repoint_table(
    market: psycopg.Connection,
    table: str,
    key_cols: list[str],
    survivor_id: str,
    loser_ids: list[str],
) -> dict[str, int]:
    """Re-point loser rows of ``table`` onto ``survivor_id``; survivor wins on conflict.

    Returns ``{f"{table}.repointed": n, f"{table}.dropped": m}`` (omitting zeros).
    """
    counts: dict[str, int] = {}
    p = {"survivor": survivor_id, "losers": loser_ids}

    # Build the non-instrument_id part of the conflict key for the EXISTS check.
    other_cols = [c for c in key_cols if c != "instrument_id"]
    if other_cols:
        # Re-point only loser rows that do NOT collide with an existing survivor
        # row on the natural key; survivor's data is authoritative.
        eq = " AND ".join(f"s.{c} = l.{c}" for c in other_cols)
        repoint_sql = (
            f"UPDATE {table} l SET instrument_id = %(survivor)s "  # noqa: S608 — table/cols from information_schema allowlist
            f"WHERE l.instrument_id = ANY(%(losers)s) "
            f"AND NOT EXISTS (SELECT 1 FROM {table} s "
            f"WHERE s.instrument_id = %(survivor)s AND {eq})"
        )
    else:
        # Unique key is instrument_id alone (e.g. quotes, company_profiles,
        # instrument_fundamentals_snapshot): re-point only if the survivor has
        # no row at all.
        repoint_sql = (
            f"UPDATE {table} SET instrument_id = %(survivor)s "  # noqa: S608
            f"WHERE instrument_id = ANY(%(losers)s) "
            f"AND NOT EXISTS (SELECT 1 FROM {table} s WHERE s.instrument_id = %(survivor)s)"
        )

    res = market.execute(repoint_sql, p)
    if res.rowcount:
        counts[f"{table}.repointed"] = res.rowcount

    # Any loser rows left (they collided with a survivor row) are now redundant.
    # They would otherwise block the loser-instrument DELETE only if the FK were
    # RESTRICT, but it is CASCADE — still, we delete them explicitly so the
    # dry-run plan shows the true effect and the survivor's data is the only copy.
    res = market.execute(
        f"DELETE FROM {table} WHERE instrument_id = ANY(%(losers)s)",  # noqa: S608
        {"losers": loser_ids},
    )
    if res.rowcount:
        counts[f"{table}.dropped"] = res.rowcount
    return counts


def _merge_cluster(
    market: psycopg.Connection,
    tables: list[str],
    key_cols_by_table: dict[str, list[str]],
    survivor: Member,
    losers: list[Member],
    *,
    apply: bool,
) -> dict[str, int]:
    """Re-point all dependent data from losers → survivor, delete losers + orphan
    securities.  ONE transaction; rolled back unless ``apply``."""
    counts: dict[str, int] = {}
    survivor_id = survivor.instrument_id
    loser_ids = [m.instrument_id for m in losers]
    loser_security_ids = [m.security_id for m in losers]

    for table in tables:
        counts.update(_repoint_table(market, table, key_cols_by_table[table], survivor_id, loser_ids))

    # Recompute the survivor flags from the merged data so has_ohlcv/has_quotes/
    # has_fundamentals reflect the consolidated rows (a loser may have carried
    # data the survivor lacked).
    market.execute(
        """
UPDATE instruments i SET
    has_ohlcv = (EXISTS (SELECT 1 FROM ohlcv_bars o WHERE o.instrument_id = i.id)),
    has_quotes = (EXISTS (SELECT 1 FROM quotes q WHERE q.instrument_id = i.id)),
    has_fundamentals = (EXISTS (SELECT 1 FROM instrument_fundamentals_snapshot f WHERE f.instrument_id = i.id))
WHERE i.id = %(survivor)s
""",
        {"survivor": survivor_id},
    )

    # Delete the loser instruments (CASCADE sweeps any straggler dependent rows).
    res = market.execute("DELETE FROM instruments WHERE id = ANY(%(losers)s)", {"losers": loser_ids})
    counts["instruments.deleted"] = res.rowcount

    # Delete the now-orphaned loser securities (each was referenced 1:1 by its
    # loser instrument; guard with NOT EXISTS so a shared security is never lost).
    res = market.execute(
        """
DELETE FROM securities s
WHERE s.id = ANY(%(sids)s)
  AND NOT EXISTS (SELECT 1 FROM instruments i WHERE i.security_id = s.id)
""",
        {"sids": loser_security_ids},
    )
    if res.rowcount:
        counts["securities.deleted"] = res.rowcount

    if apply:
        market.commit()
    else:
        market.rollback()
    return counts


def main() -> int:
    ap = argparse.ArgumentParser(description="Merge same-ISIN duplicate instruments (market_data_db).")
    ap.add_argument("--isin", help="Limit to a single ISIN (e.g. US0846707026).")
    ap.add_argument(
        "--apply",
        action="store_true",
        help="WRITE the merge. Default is a dry run (plan only, all writes rolled back).",
    )
    args = ap.parse_args()
    dry_run = not args.apply

    # intelligence_db is OPTIONAL: it supplies the surviving canonical ticker for
    # the primary survivor rule.  If it cannot be reached we fall back to the
    # data-bearing/non-blank rule and warn.
    intel: psycopg.Connection | None = None
    try:
        intel = psycopg.connect(_INTEL_DSN)
    except psycopg.Error as exc:  # pragma: no cover - environment dependent
        print(f"WARNING: intelligence_db unavailable ({exc}); survivor rule falls back to data-bearing only.\n")

    try:
        with psycopg.connect(_MARKET_DSN) as market:
            clusters = _fetch_clusters(market, args.isin)
            if not clusters:
                print("No same-ISIN duplicate instruments found. Nothing to merge.")
                return 0

            tables = _dependent_tables(market)
            key_cols_by_table = {t: (_unique_key_cols(market, t) or ["instrument_id"]) for t in tables}

            print(
                f"Found {len(clusters)} duplicate ISIN cluster(s) over {len(tables)} dependent table(s)"
                f"{' — DRY RUN (no writes)' if dry_run else ' — APPLYING'}.\n"
            )

            total_excess = 0
            for cluster in clusters:
                # Count dependents per member so the survivor rule + plan are data-aware.
                for m in cluster.members:
                    m.dep_count = _count_dependents(market, tables, m.instrument_id)
                    # Price-data signal (live ticker): ohlcv_bars + quotes only.
                    m.price_count = _count_dependents(market, ["ohlcv_bars", "quotes"], m.instrument_id)

                canonical_tickers = _surviving_canonical_tickers(intel, cluster.isin)
                survivor = _choose_survivor(cluster, canonical_tickers)
                losers = [m for m in cluster.members if m.instrument_id != survivor.instrument_id]
                total_excess += len(losers)

                print(
                    f"[{cluster.isin}] canonical_tickers={sorted(canonical_tickers) or '—'} | "
                    f"survivor={survivor.symbol!r} (exchange={survivor.exchange or '∅'}, "
                    f"price={survivor.price_count}, deps={survivor.dep_count}, id={survivor.instrument_id})"
                )
                for m in losers:
                    print(
                        f"    loser {m.symbol!r} (exchange={m.exchange or '∅'}, "
                        f"price={m.price_count}, deps={m.dep_count}, id={m.instrument_id})"
                    )

                counts = _merge_cluster(market, tables, key_cols_by_table, survivor, losers, apply=args.apply)
                for surface, n in sorted(counts.items()):
                    print(f"        {surface}: {n}")
                print()

            verb = "would be merged" if dry_run else "merged"
            print(f"Done. {total_excess} duplicate instrument(s) {verb} across {len(clusters)} ISIN(s).")
            if dry_run:
                print("\n(DRY RUN — re-run with --apply to write.)")
    finally:
        if intel is not None:
            intel.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
