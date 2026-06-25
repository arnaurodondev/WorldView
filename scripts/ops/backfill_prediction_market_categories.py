"""Backfill NULL ``prediction_markets.category`` rows from question text.

Backend-gaps wave 3 (2026-06-11), audit `2026-06-11-fullstack-rework-waves.md`
item 4 ("256/525 prediction markets have NULL category").

WHY these rows are NULL: the category derivation lives in S4's Polymarket
adapter (``content_ingestion.domain.entities``, PLAN-0053 T-C-3-04) and only
runs at INGEST time; the S3 consumer upserts with COALESCE so a NULL stays
NULL until Polymarket re-sends the market. The 256 NULL rows pre-date the
T-C-3-04 title-keyword heuristics (or their markets closed and are never
re-fetched), so they can only be healed by a data-side backfill.

This script re-derives the category from the stored ``question`` text using
the SAME canonical buckets and rule ORDER as S4's ``_categorize_by_title``
(macro → politics → sports → crypto), extended with the league/competition
keywords that dominate the actual NULL population (Bundesliga, Premier
League, Serie A, "top goal scorer", ... — verified by sampling the table).
Rows that still match nothing remain NULL (honest: no "other" bucket).

Idempotent and additive: only rows with ``category IS NULL`` are touched.

Usage::

    python -m scripts.ops.backfill_prediction_market_categories

Environment variables:
    MARKET_DATA_DSN : asyncpg DSN (default postgres@localhost:5432/market_data_db)
"""

from __future__ import annotations

import asyncio
import os

import asyncpg

_DEFAULT_DSN = "postgresql://postgres:postgres@localhost:5432/market_data_db"

# Mirrors S4 _TITLE_HEURISTIC_RULES (order matters: macro first — a "Fed cuts
# rates AND BTC > 100k" market is macro for finance UX), with sports extended
# by the soccer-league vocabulary observed in the live NULL rows.
_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "macro",
        (
            "fed",
            "rate",
            "inflation",
            "gdp",
            "cpi",
            "unemployment",
            "recession",
            "fomc",
            "payroll",
            "pce",
            "treasury",
            "yield",
            "deficit",
            "tariff",
            "economic",
            "fiscal",
            "monetary",
            "pmi",
        ),
    ),
    (
        "politics",
        (
            "election",
            "president",
            "presidential",
            "senate",
            "congress",
            "vote",
            "primary",
            "governor",
            "supreme court",
            "impeach",
        ),
    ),
    (
        "sports",
        (
            "nba",
            "nfl",
            "mlb",
            "nhl",
            "superbowl",
            "super bowl",
            "world cup",
            "olympics",
            "champion",
            "f1",
            "fifa",
            "uefa",
            # Extensions for the observed NULL population (soccer futures):
            "bundesliga",
            "premier league",
            "la liga",
            "serie a",
            "ligue 1",
            "goal scorer",
            "goalscorer",
            "relegat",  # relegated / relegation
            "promoted",
            "fa cup",
            "copa",
            "grand slam",
            "wimbledon",
            "heisman",
            "stanley cup",
        ),
    ),
    (
        "crypto",
        (
            "bitcoin",
            "ethereum",
            "btc",
            "eth",
            "crypto",
            "solana",
            "altcoin",
        ),
    ),
)


def _categorize(question: str) -> str | None:
    """Return the first matching canonical bucket, or None."""
    text = question.strip().lower()
    if not text:
        return None
    for canonical, keywords in _RULES:
        if any(kw in text for kw in keywords):
            return canonical
    return None


async def main() -> None:
    dsn = os.environ.get("MARKET_DATA_DSN", _DEFAULT_DSN)
    conn: asyncpg.Connection = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch("SELECT id, question FROM prediction_markets WHERE category IS NULL")
        print(f"[INFO] {len(rows)} prediction markets with NULL category")

        updates: list[tuple[str, str]] = []  # (category, id)
        unmatched = 0
        for r in rows:
            category = _categorize(r["question"] or "")
            if category is None:
                unmatched += 1
                continue
            updates.append((category, str(r["id"])))

        if updates:
            await conn.executemany(
                "UPDATE prediction_markets SET category = $1, updated_at = now() "
                "WHERE id = $2::uuid AND category IS NULL",
                updates,
            )
        print(f"[DONE] categorised {len(updates)} rows; {unmatched} remain NULL (no keyword match)")

        dist = await conn.fetch(
            "SELECT COALESCE(category,'<null>') c, count(*) FROM prediction_markets GROUP BY 1 ORDER BY 2 DESC"
        )
        for d in dist:
            print(f"  {d['c']:<10} {d['count']}")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
