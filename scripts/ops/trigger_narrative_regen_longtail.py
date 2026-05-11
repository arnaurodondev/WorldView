"""Trigger narrative regeneration for long-tail entities still on template-v1.

PLAN-0088 Phase 1 (2026-05-10).

Context
-------
P0-7 generated fresh LLM narratives for the 12 demo-critical tickers. However
689 entities that were seeded before the DeepInfraNarrativeChatClient fix still
carry ``model_id='template-v1'`` in their current ``entity_narrative_versions``
row.

The ``NarrativeGenerationWorker`` (Worker 13D-3) only processes entities with
``canonical_entities.current_narrative_version_id IS NULL``.  The template-v1
entities already have a non-NULL version ID — they are "current" from the
scheduler's perspective.

This script clears ``current_narrative_version_id`` for up to ``BATCH_SIZE``
template-v1 entities.  On the next Worker 13D-3 tick (fires every 6h, or in
60s on a fresh scheduler restart) those entities are treated as stale and
regenerated with the real LLM.

DEFER POLICY (PLAN-0088)
------------------------
If long-tail narrative regen would consume >$10 API cost, run only the first
100 entities. At ~$0.01/entity for Meta-Llama-3.1-8B-Instruct on DeepInfra
(~1k tokens per entity at $0.10/M), 100 entities cost ~$0.01 — well within
budget.  The scheduler will handle the remaining 589 over subsequent 6h windows
at ~83 entities/run (LIMIT 500 / 6 runs per day).

Usage
-----
    # Check what would be reset (dry-run):
    python scripts/ops/trigger_narrative_regen_longtail.py --dry-run

    # Reset first 100 template-v1 entities:
    python scripts/ops/trigger_narrative_regen_longtail.py

    # Reset more (e.g., 300):
    python scripts/ops/trigger_narrative_regen_longtail.py --batch 300

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
# Default batch: 100 per the PLAN-0088 defer policy (cost cap).
_DEFAULT_BATCH = 100


async def main(batch: int, dry_run: bool) -> None:
    dsn = os.environ.get("POSTGRES_DSN", _DEFAULT_DSN)
    conn = await asyncpg.connect(dsn)
    try:
        # Identify template-v1 entities: join canonical_entities ->
        # entity_narrative_versions WHERE model_id='template-v1' AND is_current=true.
        # These entities have a non-NULL current_narrative_version_id that points
        # to the stale template row.
        rows = await conn.fetch(
            """
            SELECT ce.entity_id, ce.canonical_name
            FROM canonical_entities ce
            JOIN entity_narrative_versions nv
                ON nv.version_id = ce.current_narrative_version_id
            WHERE nv.model_id   = 'template-v1'
              AND nv.is_current = true
            ORDER BY ce.entity_id
            LIMIT $1
            """,
            batch,
        )

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

        print(f"template-v1 entities (total): {total_template}")
        print(f"Entities to reset in this run: {len(rows)}")

        if not rows:
            print("Nothing to do.")
            return

        if dry_run:
            print("[dry-run] Would reset current_narrative_version_id for:")
            for r in rows[:5]:
                print(f"  {r['entity_id']}  {r['canonical_name']}")
            if len(rows) > 5:
                print(f"  ... and {len(rows) - 5} more")
            return

        # Clear current_narrative_version_id so Worker 13D-3 treats them as stale.
        entity_ids = [str(r["entity_id"]) for r in rows]
        result = await conn.execute(
            """
            UPDATE canonical_entities
            SET current_narrative_version_id = NULL
            WHERE entity_id = ANY($1::uuid[])
            """,
            entity_ids,
        )
        updated = int(result.split()[-1])
        print(f"Reset {updated} entities — Worker 13D-3 will regenerate on next tick.")

        # Also mark their current narrative version as non-current so the history
        # page still shows them (we don't delete, just de-index).
        # Re-fetch stale version IDs before the canonical NULL (already done above).
        # Since canonical_entities.current_narrative_version_id is now NULL we cannot
        # retrieve the version_id from there. We have to rely on the per-entity
        # entity_narrative_versions table directly.
        stale_versions = await conn.fetch(
            """
            SELECT DISTINCT version_id
            FROM entity_narrative_versions
            WHERE entity_id = ANY($1::uuid[])
              AND model_id  = 'template-v1'
              AND is_current = true
            """,
            entity_ids,
        )
        # The is_current flag may already be false if a concurrent run beat us.
        if stale_versions:
            stale_ids = [str(r["version_id"]) for r in stale_versions]
            await conn.execute(
                """
                UPDATE entity_narrative_versions
                SET is_current = false
                WHERE version_id = ANY($1::uuid[])
                """,
                stale_ids,
            )
            print(f"Marked {len(stale_ids)} template-v1 version rows as non-current.")

        # Verify
        after = await conn.fetchval(
            """
            SELECT COUNT(*)
            FROM canonical_entities
            WHERE current_narrative_version_id IS NULL
            """
        )
        print(f"Entities now eligible for regeneration (current_narrative_version_id IS NULL): {after}")

    finally:
        await conn.close()


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--batch", type=int, default=_DEFAULT_BATCH, help="Max entities to reset (default: 100)")
    p.add_argument("--dry-run", action="store_true", help="Preview only -- no DB changes")
    return p.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(main(batch=args.batch, dry_run=args.dry_run))
