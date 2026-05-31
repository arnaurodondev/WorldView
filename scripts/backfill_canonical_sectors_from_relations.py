"""Backfill ``canonical_entities.metadata.{sector,industry,asset_class}`` from existing relations.

PLAN-0103 W19 / BP-637.

Background
----------
The EODHD ``FundamentalsRefreshWorker`` (see
``services/knowledge-graph/src/knowledge_graph/infrastructure/workers/fundamentals_refresh.py``)
has — for months — written sector/industry as graph relations
(``is_in_sector`` / ``is_in_industry``) but never mirrored those values into
the ``canonical_entities.metadata`` JSONB column. The rag-chat
``risk_summary`` aggregator and the ``GET /internal/v1/entities/sectors``
endpoint both read ``metadata->>'sector'``, NOT the relation, so 683/1108
(~62 %) of tickered canonical entities looked "sectorless" to every
downstream consumer despite the EODHD round-trip having succeeded.

Forward fix
-----------
``_write_sector_relations`` now also calls
``CanonicalEntityRepository.patch_metadata`` — every new fundamentals run
keeps the JSONB column in sync.

This one-shot
-------------
For all existing relations, mirror the data we already paid EODHD for into
the metadata column. Zero EODHD HTTP calls, single-digit-second wall time.

Idempotent: re-running overwrites identical keys without touching unrelated
metadata (``metadata = metadata || jsonb_build_object(...)``).

Usage
-----
::

    # default: print the diff but don't write
    .venv312/bin/python scripts/backfill_canonical_sectors_from_relations.py

    # actually apply
    .venv312/bin/python scripts/backfill_canonical_sectors_from_relations.py --apply

Reads ``INTELLIGENCE_DB_URL`` (default:
``postgresql://postgres:postgres@localhost:5434/intelligence_db``).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys


async def _run(dsn: str, *, apply: bool) -> int:
    """Connect, scan, optionally update. Return process exit code."""
    # Local import to keep ``--help`` cheap on a cold machine.
    import asyncpg

    conn = await asyncpg.connect(dsn=dsn)
    try:
        # Pull every (subject_entity_id, sector_name, industry_name) triple
        # for instruments whose metadata.sector is still NULL. We aggregate
        # both relation types in one query so we make a single round-trip
        # per entity even when both sector AND industry need a backfill.
        rows = await conn.fetch(
            """
            SELECT
              ce.entity_id,
              ce.ticker,
              ce.canonical_name,
              max(CASE WHEN r.canonical_type = 'is_in_sector'
                       THEN se.canonical_name END) AS sector_name,
              max(CASE WHEN r.canonical_type = 'is_in_industry'
                       THEN se.canonical_name END) AS industry_name
            FROM canonical_entities ce
            JOIN relations r
              ON r.subject_entity_id = ce.entity_id
             AND r.canonical_type IN ('is_in_sector', 'is_in_industry')
            JOIN canonical_entities se
              ON se.entity_id = r.object_entity_id
            WHERE ce.metadata->>'sector' IS NULL
            GROUP BY ce.entity_id, ce.ticker, ce.canonical_name
            """,
        )

        total = len(rows)
        with_sector = sum(1 for r in rows if r["sector_name"])
        with_industry = sum(1 for r in rows if r["industry_name"])
        print(
            f"  scanning {total} entities with relations but NULL metadata.sector "
            f"(sector={with_sector}, industry={with_industry})",
        )

        updated_count = 0
        skipped_count = 0
        for row in rows:
            sector = row["sector_name"]
            industry = row["industry_name"]
            if not sector and not industry:
                skipped_count += 1
                continue

            # We always tag asset_class="Equity" for relation-sourced rows:
            # the EODHD GICS classification only runs for equities, never for
            # funds. ETFs go through the separate curated CSV path.
            patch: dict[str, str] = {"asset_class": "Equity"}
            if sector:
                patch["sector"] = sector
            if industry:
                patch["industry"] = industry

            print(f"  * {row['ticker'] or '-':>6} ({row['canonical_name'][:40]:<40}) sector={sector!r}")
            if apply:
                await conn.execute(
                    """
                    UPDATE canonical_entities
                    SET metadata = COALESCE(metadata, '{}'::jsonb) || $2::jsonb,
                        updated_at = now()
                    WHERE entity_id = $1
                    """,
                    row["entity_id"],
                    json.dumps(patch),
                )
                updated_count += 1

        mode = "APPLY" if apply else "DRY-RUN"
        print()
        print(f"[{mode}] updated={updated_count} skipped_no_data={skipped_count} total_scanned={total}")
        return 0
    finally:
        await conn.close()


def _main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Mirror sector/industry from `relations` into canonical_entities.metadata. "
            "Zero EODHD calls — pure DB copy."
        ),
    )
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
