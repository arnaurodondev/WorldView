"""Backfill ``canonical_entities.metadata`` with sector/industry/asset_class for ETFs.

PLAN-0103 W8 / BP-629.

Problem
-------
The morning brief's ``risk_summary`` uses ``canonical_entities.metadata->>'sector'``
to compute sector exposure + HHI. For ETF holdings (QQQ, XLE, IBIT, XLK, …) we
never populated the sector column because the EODHD fundamentals path that
back-fills equities doesn't run for funds. The result is
``concentration_score=0.0`` and an empty ``sector_breakdown`` even when the user
is 100% in ETFs — the brief silently drops the Risk section.

Fix
---
Hand-curated table of the most-held ETFs by AUM with a sector / industry /
asset_class label. The labels are deliberately coarse — ``XLE → Energy``,
``QQQ → Information Technology`` — because the brief just needs a bucket to
aggregate by, not a 4-level GICS classification.

Idempotent: ``UPDATE canonical_entities SET metadata = metadata || jsonb_build_object(...)``
so re-running overwrites existing keys without dropping unrelated metadata.

Usage::

    # default: print the diff but don't write
    .venv312/bin/python scripts/backfill_etf_sectors.py

    # actually apply
    .venv312/bin/python scripts/backfill_etf_sectors.py --apply

Environment
-----------
Reads ``INTELLIGENCE_DB_URL`` (default: postgresql://postgres:postgres@localhost:5434/intelligence_db).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from typing import TypedDict

# Lazy import — keep import cost down for ``--help``.

# ── Curated ETF table ────────────────────────────────────────────────────────
# Sector labels match the GICS sector strings already in canonical_entities
# for equities ("Information Technology", "Energy", …) so the rag-chat risk
# aggregator can blend ETF + equity exposures into one bucket per sector.
# ``asset_class="ETF"`` is the secondary signal the endpoint fallback uses
# when ``sector`` is still null.


class _EtfRow(TypedDict):
    ticker: str
    sector: str
    industry: str
    asset_class: str


_ETF_TABLE: list[_EtfRow] = [
    # Broad US equity
    {"ticker": "SPY", "sector": "Diversified Equity", "industry": "US Large-Cap Blend", "asset_class": "ETF"},
    {"ticker": "VOO", "sector": "Diversified Equity", "industry": "US Large-Cap Blend", "asset_class": "ETF"},
    {"ticker": "VTI", "sector": "Diversified Equity", "industry": "US Total Market", "asset_class": "ETF"},
    {"ticker": "DIA", "sector": "Diversified Equity", "industry": "US Large-Cap Value", "asset_class": "ETF"},
    {"ticker": "IWM", "sector": "Diversified Equity", "industry": "US Small-Cap Blend", "asset_class": "ETF"},
    {"ticker": "QQQ", "sector": "Information Technology", "industry": "US Large-Cap Growth", "asset_class": "ETF"},
    # International equity
    {"ticker": "VEA", "sector": "Diversified Equity", "industry": "Developed-Markets ex-US", "asset_class": "ETF"},
    {"ticker": "VWO", "sector": "Diversified Equity", "industry": "Emerging Markets", "asset_class": "ETF"},
    # Sector SPDRs
    {"ticker": "XLE", "sector": "Energy", "industry": "US Energy Sector", "asset_class": "ETF"},
    {"ticker": "XLF", "sector": "Financials", "industry": "US Financials Sector", "asset_class": "ETF"},
    {"ticker": "XLK", "sector": "Information Technology", "industry": "US Tech Sector", "asset_class": "ETF"},
    {"ticker": "XLV", "sector": "Health Care", "industry": "US Health Care Sector", "asset_class": "ETF"},
    {"ticker": "XLY", "sector": "Consumer Discretionary", "industry": "US Cons. Discretionary", "asset_class": "ETF"},
    {"ticker": "XLP", "sector": "Consumer Staples", "industry": "US Consumer Staples", "asset_class": "ETF"},
    {"ticker": "XLI", "sector": "Industrials", "industry": "US Industrials Sector", "asset_class": "ETF"},
    {"ticker": "XLB", "sector": "Materials", "industry": "US Materials Sector", "asset_class": "ETF"},
    {"ticker": "XLU", "sector": "Utilities", "industry": "US Utilities Sector", "asset_class": "ETF"},
    {"ticker": "XLRE", "sector": "Real Estate", "industry": "US Real Estate Sector", "asset_class": "ETF"},
    {"ticker": "XLC", "sector": "Communication Services", "industry": "US Comm. Services", "asset_class": "ETF"},
    # Thematic / commodity / crypto
    {"ticker": "GLD", "sector": "Commodities", "industry": "Gold", "asset_class": "ETF"},
    {"ticker": "SLV", "sector": "Commodities", "industry": "Silver", "asset_class": "ETF"},
    {"ticker": "IBIT", "sector": "Digital Assets", "industry": "Spot Bitcoin", "asset_class": "ETF"},
    {"ticker": "ARKK", "sector": "Information Technology", "industry": "Disruptive Innovation", "asset_class": "ETF"},
    # Fixed income
    {"ticker": "BND", "sector": "Fixed Income", "industry": "US Aggregate Bond", "asset_class": "ETF"},
    {"ticker": "AGG", "sector": "Fixed Income", "industry": "US Aggregate Bond", "asset_class": "ETF"},
    {"ticker": "TLT", "sector": "Fixed Income", "industry": "US Long Treasuries", "asset_class": "ETF"},
]


# ── Async DB worker ──────────────────────────────────────────────────────────


async def _run(dsn: str, apply: bool) -> int:
    """Connect, scan, optionally update. Return process exit code."""
    import asyncpg  # local import — keeps ``--help`` cheap

    conn = await asyncpg.connect(dsn=dsn)
    try:
        updated_count = 0
        skipped_count = 0
        missing_count = 0

        for row in _ETF_TABLE:
            ticker = row["ticker"]
            # Pull every canonical_entities row for the ticker (there can be
            # duplicates due to historical bad data — fix them all).
            existing = await conn.fetch(
                """
                SELECT entity_id, canonical_name,
                       metadata->>'sector'      AS sector,
                       metadata->>'asset_class' AS asset_class
                FROM canonical_entities
                WHERE ticker = $1
                """,
                ticker,
            )
            if not existing:
                missing_count += 1
                print(f"  - {ticker}: no canonical_entities row, skipped")
                continue

            for entity in existing:
                eid = entity["entity_id"]
                cname = entity["canonical_name"]
                old_sector = entity["sector"]
                old_asset_class = entity["asset_class"]
                # Skip rows that are already labelled with the same sector +
                # asset_class — keeps the script idempotent and quiet.
                if old_sector == row["sector"] and old_asset_class == row["asset_class"]:
                    skipped_count += 1
                    continue

                patch = {
                    "sector": row["sector"],
                    "industry": row["industry"],
                    "asset_class": row["asset_class"],
                }
                print(f"  * {ticker} ({cname}): sector={old_sector!r} -> {row['sector']!r}")
                if apply:
                    await conn.execute(
                        """
                        UPDATE canonical_entities
                        SET metadata = COALESCE(metadata, '{}'::jsonb) || $2::jsonb,
                            updated_at = now()
                        WHERE entity_id = $1
                        """,
                        eid,
                        json.dumps(patch),
                    )
                    updated_count += 1

        mode = "APPLY" if apply else "DRY-RUN"
        print()
        print(f"[{mode}] updated={updated_count} already_ok={skipped_count} missing_ticker={missing_count}")
        return 0
    finally:
        await conn.close()


# ── CLI entrypoint ───────────────────────────────────────────────────────────


def _main() -> int:
    parser = argparse.ArgumentParser(description="Backfill ETF sectors in canonical_entities.metadata.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually write to the DB. Default is dry-run (prints the diff).",
    )
    parser.add_argument(
        "--dsn",
        default=os.environ.get(
            "INTELLIGENCE_DB_URL",
            "postgresql://postgres:postgres@localhost:5434/intelligence_db",
        ),
        help="asyncpg DSN. Defaults to INTELLIGENCE_DB_URL or the local Compose DSN.",
    )
    args = parser.parse_args()
    return asyncio.run(_run(args.dsn, apply=args.apply))


if __name__ == "__main__":
    sys.exit(_main())
