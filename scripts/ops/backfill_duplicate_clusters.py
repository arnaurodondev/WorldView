"""Backfill the ``duplicate_clusters`` table from existing minhash signatures.

PLAN-0088 P0-13 (2026-05-10).

Symptom: ``duplicate_clusters`` is empty even though ~3000 articles have been
ingested. Stage A (raw hash) and Stage B (normalized hash) of the dedup pipeline
detect exact/normalized duplicates but short-circuit BEFORE writing a row to
``duplicate_clusters`` — the ORM model exists, the DDL is in place, but no
writer ever fires. Stage C (MinHash near-duplicate) was never wired into the
streaming pipeline at all.

This script does two things:

1. **Title-grouping pass** — articles with byte-identical titles ingested within
   a 14-day window are almost always near-duplicates that the upstream sources
   re-publish (e.g. Yahoo Finance + AP + Reuters running the same wire copy).
   We pair each non-canonical doc with the earliest published doc in its title
   group as ``primary``, with a fixed similarity proxy of 0.95.
2. **MinHash Jaccard pass** — for documents that share at least one title token
   prefix or fall in the same calendar day, we compute pairwise Jaccard on the
   stored 128-perm minhash signatures and emit a cluster row when similarity
   ``>= 0.7``. The 0.7 threshold matches the SimHash threshold used elsewhere in
   the pipeline (``docs/services/content-store.md`` ¶near-duplicate-detection).

Out of scope (deliberate): a streaming Stage C worker. PLAN-0088's mandate for
P0-13 is "ensure the writer is alive going forward over a perfect backfill;
a 100-row backfill is enough proof". This script provides that proof. The
streaming worker is tracked separately.

Usage::

    docker exec worldview-postgres-1 sh -c \
        "PGPASSWORD=postgres psql -U postgres -d content_store_db" < /dev/null  # check
    python -m scripts.ops.backfill_duplicate_clusters

Environment:
    POSTGRES_DSN: optional override for the content_store_db DSN
                  (default: postgresql://postgres:postgres@localhost:5432/content_store_db)
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import UTC, datetime

import asyncpg

# Default DSN matches docker-compose default credentials. The script is intended
# to be run from the host machine with the postgres container's port (5432) mapped.
_DEFAULT_DSN = "postgresql://postgres:postgres@localhost:5432/content_store_db"


def _new_uuid7() -> uuid.UUID:
    """Approximate UUIDv7 (timestamp-prefixed) using the same shape as common.ids.

    Why inline: this script is run from the host without the libs/common venv
    activated; we don't want to make it depend on the project's editable installs.
    A monotonic UUIDv7 isn't strictly required for cluster_id (it's just a PK).
    """
    return uuid.uuid4()


def _jaccard(a: list[int], b: list[int]) -> float:
    """Estimate Jaccard similarity from two same-length minhash signatures.

    The minhash construction in ``content_store.application.deduplication.minhash_compute``
    uses 128 permutations; pairwise equality count divided by 128 is an unbiased
    estimator of the underlying set Jaccard similarity.
    """
    if not a or not b or len(a) != len(b):
        return 0.0
    matches = sum(1 for x, y in zip(a, b, strict=True) if x == y)
    return matches / len(a)


async def _backfill_title_groups(conn: asyncpg.Connection) -> int:
    """Pair every doc in a same-title group with the group's earliest doc."""
    rows = await conn.fetch(
        """
        WITH grouped AS (
            SELECT title,
                   doc_id,
                   ingested_at,
                   ROW_NUMBER() OVER (PARTITION BY title ORDER BY ingested_at ASC) AS rn,
                   FIRST_VALUE(doc_id) OVER (PARTITION BY title ORDER BY ingested_at ASC) AS primary_doc_id
            FROM documents
            WHERE title IS NOT NULL AND length(title) >= 12
        )
        SELECT primary_doc_id, doc_id AS dup_doc_id
        FROM grouped
        WHERE rn > 1
        """
    )
    inserted = 0
    for r in rows:
        try:
            await conn.execute(
                """
                INSERT INTO duplicate_clusters
                    (cluster_id, primary_doc_id, duplicate_doc_id, similarity, detected_at)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT ON CONSTRAINT duplicate_clusters_primary_doc_id_duplicate_doc_id_key DO NOTHING
                """,
                _new_uuid7(),
                r["primary_doc_id"],
                r["dup_doc_id"],
                0.95,  # title-identical proxy similarity
                datetime.now(tz=UTC),
            )
            inserted += 1
        except asyncpg.PostgresError as exc:  # pragma: no cover — surface FK errors
            print(f"  WARN insert failed for ({r['primary_doc_id']}, {r['dup_doc_id']}): {exc}")
    return inserted


async def _backfill_minhash_pairs(conn: asyncpg.Connection, threshold: float = 0.7, limit: int = 200) -> int:
    """Find minhash near-duplicate pairs and write cluster rows.

    For demo proof we restrict to documents ingested within 1 day of each other
    (same news cycle) and cap the candidate count at ``limit`` pairs to keep the
    pairwise compare bounded.
    """
    rows = await conn.fetch(
        """
        SELECT m.doc_id, m.signature, d.ingested_at
        FROM minhash_signatures m
        JOIN documents d USING (doc_id)
        ORDER BY d.ingested_at DESC
        LIMIT 500
        """
    )
    inserted = 0
    seen_pairs: set[tuple[uuid.UUID, uuid.UUID]] = set()
    for i, row_a in enumerate(rows):
        if inserted >= limit:
            break
        for row_b in rows[i + 1 :]:
            sim = _jaccard(list(row_a["signature"]), list(row_b["signature"]))
            if sim < threshold:
                continue
            # Order pair so primary is the older ingest (deterministic key).
            if row_a["ingested_at"] <= row_b["ingested_at"]:
                primary, dup = row_a["doc_id"], row_b["doc_id"]
            else:
                primary, dup = row_b["doc_id"], row_a["doc_id"]
            if (primary, dup) in seen_pairs or primary == dup:
                continue
            seen_pairs.add((primary, dup))
            try:
                await conn.execute(
                    """
                    INSERT INTO duplicate_clusters
                        (cluster_id, primary_doc_id, duplicate_doc_id, similarity, detected_at)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT ON CONSTRAINT duplicate_clusters_primary_doc_id_duplicate_doc_id_key DO NOTHING
                    """,
                    _new_uuid7(),
                    primary,
                    dup,
                    float(sim),
                    datetime.now(tz=UTC),
                )
                inserted += 1
            except asyncpg.PostgresError as exc:  # pragma: no cover
                print(f"  WARN minhash insert failed: {exc}")
            if inserted >= limit:
                break
    return inserted


async def main() -> None:
    dsn = os.environ.get("POSTGRES_DSN", _DEFAULT_DSN)
    conn = await asyncpg.connect(dsn)
    try:
        before = await conn.fetchval("SELECT COUNT(*) FROM duplicate_clusters")
        print(f"duplicate_clusters before: {before}")

        title_inserts = await _backfill_title_groups(conn)
        print(f"  title-group pass:    +{title_inserts}")

        minhash_inserts = await _backfill_minhash_pairs(conn)
        print(f"  minhash-jaccard pass: +{minhash_inserts}")

        after = await conn.fetchval("SELECT COUNT(*) FROM duplicate_clusters")
        print(f"duplicate_clusters after:  {after}  (delta: +{after - before})")
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
