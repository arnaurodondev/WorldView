#!/usr/bin/env python3
# ruff: noqa
"""BP-606 (PLAN-0100 W1 T-W1-04) — backfill `entity_mentions` from `chunks.entity_mentions` JSONB.

Belt-and-braces companion to the T-W1-01 SQL fix.  The read path
(`news_query._ENTITY_ARTICLES_SQL`) already UNIONs the denormalised JSONB
column with the normalised table, so the read-time fix is complete without
this script.  Running this backfill ALSO closes the lineage gap on the
write side so other consumers (BI exports, intelligence_db enrichment,
operator queries) see a consistent view.

Source: `chunks.entity_mentions` JSONB array of objects with shape
    {"entity_id": "<uuid|null>", "raw_text": "...", "entity_type": "...",
     "char_start": int, "char_end": int, "gliner_score": float}

Target: `entity_mentions` table rows with `resolved_entity_id = entity_id`
when the JSONB entity_id is non-null.

Idempotency: there is no natural unique constraint on entity_mentions
(see ``\\d entity_mentions``), so we de-duplicate at SQL time on the
``(doc_id, resolved_entity_id, char_start, char_end)`` natural key —
re-runs will not double-insert.  Dry-run mode is the default; pass
``--wet-run`` to actually insert.

Usage:
  python scripts/backfill_entity_mentions_from_chunks_jsonb.py --dry-run
  python scripts/backfill_entity_mentions_from_chunks_jsonb.py --wet-run

Env:
  PG_DSN_NLP — defaults to postgresql://postgres:postgres@localhost:5432/nlp_db

Run inside the worldview docker network:
  docker run --rm --network worldview_default \
    -e PG_DSN_NLP=postgresql://postgres:postgres@postgres:5432/nlp_db \
    python:3.12-slim sh -c \
      "pip install asyncpg==0.29 && \
       python scripts/backfill_entity_mentions_from_chunks_jsonb.py --dry-run"
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

import asyncpg

PG_DSN_NLP = os.getenv("PG_DSN_NLP", "postgresql://postgres:postgres@localhost:5432/nlp_db")

# Public-tenant sentinel — assigned by the article consumer when tenant
# resolution fails (BP-575). Backfilled rows inherit the chunk's tenant_id.
PUBLIC_TENANT_ID = "00000000-0000-0000-0000-000000000000"

# Selects every chunk JSONB entry that carries a non-null entity_id AND has
# no corresponding row in entity_mentions for the same
# (doc_id, resolved_entity_id, char_start, char_end) tuple.
# `jsonb_array_elements` expands the JSONB array; the LEFT JOIN ... IS NULL
# is the classic anti-join for set difference.
_CANDIDATES_SQL = """
WITH expanded AS (
    SELECT
        c.doc_id,
        c.section_id,
        COALESCE(c.tenant_id, %(public_tenant)s::uuid) AS tenant_id,
        (em.value->>'entity_id')::uuid                   AS resolved_entity_id,
        em.value->>'raw_text'                            AS mention_text,
        em.value->>'entity_type'                         AS mention_class,
        (em.value->>'gliner_score')::double precision    AS confidence,
        (em.value->>'char_start')::int                   AS char_start,
        (em.value->>'char_end')::int                     AS char_end
    FROM chunks c,
         jsonb_array_elements(c.entity_mentions) AS em(value)
    WHERE c.entity_mentions IS NOT NULL
      AND jsonb_array_length(c.entity_mentions) > 0
      AND em.value ? 'entity_id'
      AND em.value->>'entity_id' IS NOT NULL
      AND em.value->>'entity_id' <> 'null'
)
SELECT e.*
FROM expanded e
LEFT JOIN entity_mentions m
       ON m.doc_id = e.doc_id
      AND m.resolved_entity_id = e.resolved_entity_id
      AND m.char_start = e.char_start
      AND m.char_end   = e.char_end
WHERE m.mention_id IS NULL
""".replace("%(public_tenant)s", f"'{PUBLIC_TENANT_ID}'")

# resolution_outcome='backfill_jsonb' is a new outcome label so audit
# queries can tell backfilled rows apart from real-time resolver writes.
# resolution_stage=99 (above any production stage value) signals "synthetic".
_INSERT_SQL = """
INSERT INTO entity_mentions (
    doc_id, section_id, tenant_id,
    mention_text, mention_class, confidence,
    char_start, char_end,
    resolved_entity_id, resolution_confidence,
    resolution_stage, resolution_outcome,
    ner_model_id
)
SELECT
    $1::uuid, $2::uuid, $3::uuid,
    $4::text, $5::text, $6::double precision,
    $7::int, $8::int,
    $9::uuid, $6::double precision,
    99, 'backfill_jsonb',
    'backfill-jsonb-v1'
"""


async def run(dry_run: bool, limit: int | None) -> int:
    """Execute the backfill. Returns the number of candidate rows."""
    conn = await asyncpg.connect(PG_DSN_NLP)
    try:
        # Count candidates first — cheap, even on millions of chunks (the
        # GIN index on chunks.entity_mentions accelerates the expanded CTE).
        candidates = await conn.fetch(_CANDIDATES_SQL)
        total = len(candidates)
        print(f"[BP-606 backfill] candidates={total} dry_run={dry_run} limit={limit}")
        if total == 0:
            print("[BP-606 backfill] nothing to do — entity_mentions already covers chunks JSONB")
            return 0

        # Preview the first 5 rows so the operator can sanity-check shape.
        for row in candidates[:5]:
            print(
                f"  doc={row['doc_id']} entity={row['resolved_entity_id']} "
                f"text={row['mention_text']!r} class={row['mention_class']} "
                f"conf={row['confidence']}"
            )

        if dry_run:
            print("[BP-606 backfill] DRY-RUN — no inserts performed. Pass --wet-run to apply.")
            return total

        # Cap the wet-run batch size so an unexpected blowup is recoverable.
        to_insert = candidates if limit is None else candidates[:limit]
        print(f"[BP-606 backfill] WET-RUN — inserting {len(to_insert)} rows")
        # Single transaction so a mid-run failure rolls everything back; the
        # candidate set is small enough (target use case = a few thousand
        # rows for low-coverage tickers) to fit one txn comfortably.
        async with conn.transaction():
            for row in to_insert:
                await conn.execute(
                    _INSERT_SQL,
                    row["doc_id"],
                    row["section_id"],
                    row["tenant_id"],
                    row["mention_text"],
                    row["mention_class"],
                    row["confidence"],
                    row["char_start"],
                    row["char_end"],
                    row["resolved_entity_id"],
                )
        print(f"[BP-606 backfill] inserted {len(to_insert)} rows")
        return len(to_insert)
    finally:
        await conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    # Mutually-exclusive --dry-run / --wet-run so the operator NEVER triggers
    # writes by accident; --dry-run is the default if neither is passed.
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", dest="dry_run", action="store_true", default=True)
    mode.add_argument("--wet-run", dest="dry_run", action="store_false")
    parser.add_argument("--limit", type=int, default=None, help="cap rows inserted on wet-run")
    args = parser.parse_args()
    asyncio.run(run(dry_run=args.dry_run, limit=args.limit))
    return 0


if __name__ == "__main__":
    sys.exit(main())
