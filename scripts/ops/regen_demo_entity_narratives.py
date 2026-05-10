# ruff: noqa: S608  -- ops script with hardcoded SQL patterns; no user-supplied SQL
"""Force-regenerate narratives for demo-critical entities still on template-v1.

SA-2 hardening pass (2026-05-10).

Context
-------
17 demo-critical entities (ETFs, index-tickers, portfolio holdings) carry
``model_id='template-v1'`` as their current narrative.  The periodic
``NarrativeGenerationWorker`` (Worker 13D-3) only fetches entities with
``current_narrative_version_id IS NULL``, so these are never re-queued.

Strategy
--------
1. Identify demo-critical entity IDs from the hard-coded canonical name list.
2. For each: NULL-out ``canonical_entities.current_narrative_version_id``
   and mark the template-v1 row ``is_current=false``.
3. Worker 13D-3 fires every 6h (next tick in ≤6h or immediately after a
   scheduler restart) and produces real LLM narratives for those rows.

Idempotent: running the script twice has no harmful side-effect — the second
run finds no template-v1 current rows for the listed entities and does nothing.

Usage
-----
    # Check what would be reset (dry-run):
    python scripts/ops/regen_demo_entity_narratives.py --dry-run

    # Apply:
    python scripts/ops/regen_demo_entity_narratives.py

Environment
-----------
    POSTGRES_DSN: optional DSN override
                  (default: postgresql://postgres:postgres@localhost:5432/intelligence_db)
"""

from __future__ import annotations

import argparse
import asyncio
import os

import asyncpg

_DEFAULT_DSN = "postgresql://postgres:postgres@localhost:5432/intelligence_db"

# Canonical names of demo-critical entities we want to force-regen.
# We match on ILIKE so minor spacing/punctuation differences are tolerated.
_DEMO_CRITICAL_PATTERNS = [
    # Portfolio ETF tickers
    "Invesco QQQ Trust",
    "MicroStrategy Incorporated",
    "iShares Bitcoin Trust",
    "iShares 20+ Year Treasury Bond ETF",
    "iShares 7-10 Year Treasury Bond ETF",
    "iShares 1-3 Year Treasury Bond ETF",
    # Sector ETFs held in portfolio
    "Energy Select Sector SPDR",
    "Health Care Select Sector SPDR",
    "Technology Select Sector SPDR",
    "Consumer Discretionary Select Sector SPDR",
    "Invesco Aerospace",
    # Other demo entities on template-v1
    "Tesla shares",
    "Alphabet Inc. Class C",
    "SPDR S&P 500 ETF Trust",
    "Vanguard S&P 500 ETF",
    "Vanguard Value ETF",
    "Vanguard Value Index Fund ETF Shares",
]


async def main(dry_run: bool) -> None:
    dsn = os.environ.get("POSTGRES_DSN", _DEFAULT_DSN)
    conn = await asyncpg.connect(dsn)
    try:
        # Build ILIKE OR predicate dynamically to find matching entities
        ilike_clauses = " OR ".join(f"ce.canonical_name ILIKE ${i + 1}" for i in range(len(_DEMO_CRITICAL_PATTERNS)))
        ilike_values = [f"%{p}%" for p in _DEMO_CRITICAL_PATTERNS]

        # S608: ilike_clauses is built from _DEMO_CRITICAL_PATTERNS (hardcoded strings).
        # Values are passed as positional parameters ($1..$N) to asyncpg — no injection risk.
        ilike_where = f"AND ({ilike_clauses})"
        sql = (
            "SELECT ce.entity_id, ce.canonical_name, nv.version_id, nv.model_id"
            " FROM canonical_entities ce"
            " JOIN entity_narrative_versions nv"
            "   ON nv.version_id = ce.current_narrative_version_id"
            " WHERE nv.model_id   = 'template-v1'"
            "   AND nv.is_current = true"
            f"  {ilike_where}"
            " ORDER BY ce.canonical_name"
        )
        rows = await conn.fetch(sql, *ilike_values)

        total_template = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM canonical_entities ce
            JOIN entity_narrative_versions nv
                ON nv.version_id = ce.current_narrative_version_id
            WHERE nv.model_id   = 'template-v1'
              AND nv.is_current = true
            """
        )

        print(f"Total template-v1 entities in DB:  {total_template}")
        print(f"Demo-critical matches to reset:    {len(rows)}")

        if not rows:
            print("All demo-critical entities already have LLM narratives. Nothing to do.")
            return

        print("\nEntities that will be reset:")
        for r in rows:
            print(f"  {r['entity_id']}  {r['canonical_name']}  (current model: {r['model_id']})")

        if dry_run:
            print("\n[dry-run] No changes written.")
            return

        entity_ids = [str(r["entity_id"]) for r in rows]
        version_ids = [str(r["version_id"]) for r in rows]

        # Step 1: NULL-out current_narrative_version_id on canonical_entities
        # so NarrativeGenerationWorker._fetch_stale_entities() picks them up.
        result = await conn.execute(
            """
            UPDATE canonical_entities
            SET current_narrative_version_id = NULL
            WHERE entity_id = ANY($1::uuid[])
            """,
            entity_ids,
        )
        updated_ce = int(result.split()[-1])

        # Step 2: Mark the stale template-v1 version rows as non-current so
        # insert_and_promote() does not need to fight a duplicate is_current=true.
        result2 = await conn.execute(
            """
            UPDATE entity_narrative_versions
            SET is_current = false
            WHERE version_id = ANY($1::uuid[])
              AND model_id   = 'template-v1'
              AND is_current = true
            """,
            version_ids,
        )
        updated_nv = int(result2.split()[-1])

        print(f"\nReset {updated_ce} canonical_entities rows (current_narrative_version_id → NULL).")
        print(f"Marked {updated_nv} entity_narrative_versions rows as non-current.")

        # Verify
        still_null = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM canonical_entities
            WHERE current_narrative_version_id IS NULL
            """
        )
        print(f"\nEntities now eligible for Worker 13D-3 (current_narrative_version_id IS NULL): {still_null}")
        print(
            "\nWorker 13D-3 fires every 6h (next tick ≤6h, or restart the knowledge-graph\n"
            "scheduler to trigger immediately: docker restart worldview-knowledge-graph-1)"
        )

    finally:
        await conn.close()


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run", action="store_true", help="Preview only — no DB changes")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(main(dry_run=args.dry_run))
