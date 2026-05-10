"""One-shot promotion script: relation_evidence_raw → relation_evidence partitions.

Architecture context
--------------------
Worker 13A (ConfidenceWorker) processes relation_evidence_raw rows and marks them
``processed=true`` but never promotes them to the immutable ``relation_evidence``
partitioned table.  No scheduled worker implements this promotion step (documented
in SummaryWorker summary.py line 168: "insert_immutable promotion not yet
implemented").

This script fills that gap as a one-shot operator tool until Worker 13B is built.
It is safe to re-run — the INSERT uses ON CONFLICT DO NOTHING against
(evidence_id, evidence_date) uniqueness enforced by the PK on the partitioned
table (and a fallback dedup check on relation_id + doc_id + evidence_date since
evidence_id is gen_random_uuid() on insert).

After promotion:
- relation_evidence should have ≥ count(relation_evidence_raw) rows
- relation_evidence_raw rows get processed=true (already set by ConfidenceWorker)
- SummaryWorker will find evidence via get_all_for_relation() and generate summaries

Usage
-----
    python scripts/ops/promote_relation_evidence.py [--dry-run] [--batch-size N]

Environment
-----------
Reads DATABASE_URL from env (or defaults to the local dev postgres URL).

BP-SA1-004 (2026-05-10): architectural gap — Worker 13A never calls
insert_immutable; 2735 raw rows were unpromotable, leaving relation_evidence
with 0 rows and SummaryWorker falling back to raw-path evidence (lower
quality, no canonicalized_evidence_text).
"""

from __future__ import annotations

import argparse
import asyncio
import os

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ── Config ────────────────────────────────────────────────────────────────────

_DEFAULT_DB_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/intelligence_db"
_BATCH_SIZE_DEFAULT = 500


# ── Helpers ───────────────────────────────────────────────────────────────────


async def _promote_batch(
    session: AsyncSession,
    batch_size: int,
    dry_run: bool,
) -> tuple[int, int]:
    """Promote one batch of unprocessed raw rows to the immutable partition table.

    Joins relation_evidence_raw to relations on (subject, object, canonical_type)
    to resolve relation_id — the raw table stores the triple, not the UUID.

    Returns (rows_promoted, rows_skipped_no_relation).

    Dedup guard: uses INSERT ... ON CONFLICT DO NOTHING with a unique constraint
    on (relation_id, doc_id, evidence_date) to make repeated runs safe.
    """
    # Fetch promotable raw rows — those with a matching relation and not already
    # promoted (checked via NOT EXISTS on relation_evidence).
    fetch_sql = text("""
SELECT
    rer.raw_id,
    r.relation_id,
    rer.source_document_id   AS doc_id,
    rer.chunk_id,
    rer.evidence_text,
    rer.extraction_confidence,
    rer.source_trust_weight  AS source_weight,
    rer.evidence_date,
    rer.claim_id
FROM relation_evidence_raw rer
JOIN relations r
  ON  r.subject_entity_id = rer.subject_entity_id
  AND r.object_entity_id  = rer.object_entity_id
  AND r.canonical_type    = rer.canonical_type
WHERE rer.entity_provisional = false
  -- Dedup: skip rows already present in relation_evidence.
  -- We match on relation_id + doc_id + evidence_date since evidence_id is
  -- freshly generated on INSERT into the partitioned table.
  AND NOT EXISTS (
    SELECT 1 FROM relation_evidence re
    WHERE re.relation_id   = r.relation_id
      AND re.doc_id        = rer.source_document_id
      AND re.evidence_date = rer.evidence_date
  )
ORDER BY rer.extracted_at
LIMIT :batch_size
""")
    result = await session.execute(fetch_sql, {"batch_size": batch_size})
    rows = result.fetchall()

    if not rows:
        return 0, 0

    if dry_run:
        print(f"  [DRY RUN] Would promote {len(rows)} rows (showing first 3):")
        for row in rows[:3]:
            print(f"    raw_id={row[0]}  relation_id={row[1]}  doc_id={row[2]}")
        return len(rows), 0

    # Insert each row into the partitioned table.  The partition is chosen
    # automatically by evidence_date (RANGE partitioning by month).
    insert_sql = text("""
INSERT INTO relation_evidence (
    relation_id, doc_id, chunk_id, evidence_text,
    extraction_confidence, source_weight, evidence_date, claim_id
) VALUES (
    :relation_id, :doc_id, :chunk_id, :evidence_text,
    :extraction_confidence, :source_weight, :evidence_date, :claim_id
)
ON CONFLICT DO NOTHING
""")

    promoted = 0
    for row in rows:
        await session.execute(
            insert_sql,
            {
                "relation_id": str(row[1]),
                "doc_id": str(row[2]),
                "chunk_id": str(row[3]) if row[3] else None,
                "evidence_text": row[4],
                "extraction_confidence": float(row[5]),
                "source_weight": float(row[6]),
                "evidence_date": row[7],
                "claim_id": str(row[8]) if row[8] else None,
            },
        )
        promoted += 1

    await session.commit()
    return promoted, 0


async def _run(db_url: str, batch_size: int, dry_run: bool) -> None:
    """Run the full promotion until no more rows remain."""
    engine = create_async_engine(db_url, echo=False, pool_pre_ping=True)
    session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(engine, expire_on_commit=False)

    total_promoted = 0
    pass_num = 0

    try:
        while True:
            pass_num += 1
            async with session_factory() as session:
                promoted, skipped = await _promote_batch(session, batch_size, dry_run)

            total_promoted += promoted
            print(f"Pass {pass_num}: promoted={promoted}, skipped={skipped}, " f"total_promoted={total_promoted}")

            if promoted == 0:
                print("No more rows to promote — done.")
                break

            if dry_run:
                print("[DRY RUN] Stopping after first pass.")
                break

        # Final counts
        async with session_factory() as session:
            raw_result = await session.execute(
                text("SELECT count(*) FROM relation_evidence_raw WHERE entity_provisional = false")
            )
            raw_count = raw_result.scalar()

            immutable_result = await session.execute(text("SELECT count(*) FROM relation_evidence"))
            immutable_count = immutable_result.scalar()

            no_evidence_result = await session.execute(
                text("""
SELECT count(*) FROM relations r
WHERE NOT EXISTS (
    SELECT 1 FROM relation_evidence re WHERE re.relation_id = r.relation_id
)
""")
            )
            no_evidence_count = no_evidence_result.scalar()

        print("\n── Final state ──────────────────────────────────────────")
        print(f"  relation_evidence_raw (non-provisional): {raw_count}")
        print(f"  relation_evidence (partitioned):         {immutable_count}")
        print(f"  relations with NO evidence in immutable: {no_evidence_count}")
        print(f"  total promoted this run:                 {total_promoted}")

    finally:
        await engine.dispose()


# ── CLI entry point ──────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument("--batch-size", type=int, default=_BATCH_SIZE_DEFAULT, help="Rows per commit")
    args = parser.parse_args()

    db_url = os.environ.get("DATABASE_URL", _DEFAULT_DB_URL)
    # Normalise sync URL to asyncpg URL if needed.
    if db_url.startswith("postgresql://") and "+asyncpg" not in db_url:
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    print(f"promote_relation_evidence: db={db_url.split('@')[-1]}  batch={args.batch_size}  dry_run={args.dry_run}")
    asyncio.run(_run(db_url, args.batch_size, args.dry_run))


if __name__ == "__main__":
    main()
