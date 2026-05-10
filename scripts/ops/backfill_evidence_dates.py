"""Backfill evidence_date in relation_evidence from content_store_db published_at.

Problem
-------
All 438 rows in ``relation_evidence`` share ``evidence_date = today`` because the
promote_relation_evidence.py script used ``relation_evidence_raw.evidence_date``
which was set to ``now()`` at extraction/promotion time — not to the source
document's actual publication date.

Fix
---
We JOIN ``relation_evidence.doc_id`` to ``content_store_db.documents.published_at``
(cross-DB via two separate connections to the same postgres instance) and UPDATE
``evidence_date`` to the document's published_at date.

Partition concern: ``relation_evidence`` is RANGE-partitioned on ``evidence_date``
by month. Postgres 11+ automatically migrates rows across partitions when an
UPDATE changes the partition key — no manual partition management required.

Strategy: Option B — content_store_db.documents.published_at
--------------------------------------------------------------
- ``content_store_db.documents.published_at`` is the canonical publication
  timestamp for source documents.
- ``relation_evidence.doc_id = content_store_db.documents.doc_id`` (same UUID).
- No FDW is configured, so we connect to both DBs from Python and perform the
  update in two steps: (1) read doc_id→published_at map from content_store_db,
  (2) apply UPDATE to relation_evidence rows in intelligence_db.
- Fallback: if a doc has no published_at in content_store_db, skip it (leave the
  evidence_date as-is).

Idempotency
-----------
The WHERE clause filters to rows where evidence_date differs from the document's
published_at (truncated to day). Re-running after a full backfill updates 0 rows.

Usage
-----
    # Preview without writing:
    python scripts/ops/backfill_evidence_dates.py --dry-run

    # Apply changes:
    python scripts/ops/backfill_evidence_dates.py

    # Custom batch size:
    python scripts/ops/backfill_evidence_dates.py --batch-size 200

Environment
-----------
    INTELLIGENCE_DB_URL  (default: postgresql+asyncpg://postgres:postgres@localhost:5432/intelligence_db)
    CONTENT_STORE_DB_URL (default: postgresql+asyncpg://postgres:postgres@localhost:5432/content_store_db)
"""

from __future__ import annotations

import argparse
import asyncio
import os
from typing import Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ── Defaults ─────────────────────────────────────────────────────────────────

_DEFAULT_INTEL_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/intelligence_db"
_DEFAULT_CS_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/content_store_db"
_DEFAULT_BATCH_SIZE = 500

log: Any = structlog.get_logger(__name__)  # type: ignore[no-any-return]


# ── Step 1 — Collect published_at from content_store_db ──────────────────────


async def _load_published_at_map(
    cs_session: AsyncSession,
    doc_ids: list[str],
) -> dict[str, Any]:
    """Return {doc_id: published_at} for docs that have a non-null published_at."""
    if not doc_ids:
        return {}

    result = await cs_session.execute(
        text("SELECT doc_id, published_at FROM documents WHERE doc_id = ANY(:ids) AND published_at IS NOT NULL"),
        {"ids": doc_ids},
    )
    return {str(row[0]): row[1] for row in result.fetchall()}


# ── Step 2 — Collect distinct doc_ids from relation_evidence ─────────────────


async def _get_all_doc_ids(intel_session: AsyncSession) -> list[str]:
    """Return all distinct doc_ids in relation_evidence."""
    result = await intel_session.execute(text("SELECT DISTINCT doc_id::text FROM relation_evidence"))
    return [row[0] for row in result.fetchall()]


# ── Step 3 — Apply evidence_date updates in batches ──────────────────────────


async def _update_batch(
    intel_session: AsyncSession,
    doc_id: str,
    published_at: Any,
    dry_run: bool,
) -> tuple[int, int]:
    """Update all relation_evidence rows for a given doc_id.

    Only updates rows where date_trunc('day', evidence_date) differs from
    date_trunc('day', published_at) — ensures idempotency.

    Returns (rows_updated, rows_skipped_already_correct).
    """
    # Count rows that would change (used for dry-run reporting and idempotency check).
    # Cast :published_at to timestamptz explicitly — asyncpg requires unambiguous
    # types when calling date_trunc with a bound parameter (BP-180 pattern).
    count_result = await intel_session.execute(
        text(
            "SELECT count(*) FROM relation_evidence "
            "WHERE doc_id = :doc_id "
            "AND date_trunc('day', evidence_date) "
            "!= date_trunc('day', CAST(:published_at AS timestamptz))"
        ),
        {"doc_id": doc_id, "published_at": published_at},
    )
    to_update = count_result.scalar() or 0

    if to_update == 0:
        return 0, 1  # already correct

    if dry_run:
        log.debug(
            "dry_run_skip",
            doc_id=doc_id,
            published_at=str(published_at),
            rows_would_update=to_update,
        )
        return to_update, 0

    # Perform the actual UPDATE.
    # Postgres 11+ handles partition key changes automatically — rows are
    # DELETEd from the old partition and INSERTed into the correct one.
    await intel_session.execute(
        text(
            "UPDATE relation_evidence "
            "SET evidence_date = CAST(:published_at AS timestamptz) "
            "WHERE doc_id = :doc_id "
            "AND date_trunc('day', evidence_date) "
            "!= date_trunc('day', CAST(:published_at AS timestamptz))"
        ),
        {"doc_id": doc_id, "published_at": published_at},
    )

    return to_update, 0


# ── Orchestrator ─────────────────────────────────────────────────────────────


async def _run(
    intel_url: str,
    cs_url: str,
    batch_size: int,
    dry_run: bool,
) -> None:
    """Main orchestration loop."""
    log.info(
        "backfill_evidence_dates_start",
        dry_run=dry_run,
        batch_size=batch_size,
    )

    intel_engine = create_async_engine(intel_url, echo=False, pool_pre_ping=True)
    cs_engine = create_async_engine(cs_url, echo=False, pool_pre_ping=True)

    intel_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(intel_engine, expire_on_commit=False)
    cs_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(cs_engine, expire_on_commit=False)

    total_updated = 0
    total_skipped = 0
    total_no_pub = 0
    total_errors = 0

    try:
        # Phase 1: Collect all distinct doc_ids from relation_evidence
        async with intel_factory() as intel_session:
            all_doc_ids = await _get_all_doc_ids(intel_session)

        log.info("doc_ids_found", count=len(all_doc_ids))

        # Phase 2: Look up published_at in content_store_db in batches
        pub_at_map: dict[str, Any] = {}
        for i in range(0, len(all_doc_ids), batch_size):
            chunk = all_doc_ids[i : i + batch_size]
            async with cs_factory() as cs_session:
                chunk_map = await _load_published_at_map(cs_session, chunk)
            pub_at_map.update(chunk_map)

        log.info(
            "published_at_resolved",
            resolved=len(pub_at_map),
            unresolved=len(all_doc_ids) - len(pub_at_map),
        )

        # Phase 3: Apply updates in batches of batch_size doc_ids
        batch_doc_ids = list(pub_at_map.keys())
        for i in range(0, len(batch_doc_ids), batch_size):
            chunk = batch_doc_ids[i : i + batch_size]
            batch_updated = 0
            batch_skipped = 0

            async with intel_factory() as intel_session:
                for doc_id in chunk:
                    try:
                        # Use a nested savepoint so that a per-doc error does not
                        # abort the whole batch transaction (asyncpg InFailedSQL guard).
                        async with intel_session.begin_nested():
                            updated, skipped = await _update_batch(intel_session, doc_id, pub_at_map[doc_id], dry_run)
                        batch_updated += updated
                        batch_skipped += skipped
                    except Exception as exc:
                        log.error(
                            "update_row_error",
                            doc_id=doc_id,
                            error=str(exc),
                        )
                        total_errors += 1

                if not dry_run and batch_updated > 0:
                    await intel_session.commit()

            total_updated += batch_updated
            total_skipped += batch_skipped
            log.info(
                "batch_done",
                batch_start=i,
                batch_updated=batch_updated,
                batch_skipped=batch_skipped,
            )

        total_no_pub = len(all_doc_ids) - len(pub_at_map)

        # Final verification query
        async with intel_factory() as intel_session:
            result = await intel_session.execute(
                text(
                    "SELECT date_trunc('day', evidence_date) AS day_bucket, count(*) "
                    "FROM relation_evidence "
                    "GROUP BY 1 ORDER BY 1"
                )
            )
            rows = result.fetchall()
            distinct_days = len(rows)

        log.info(
            "evidence_date_backfill_complete",
            dry_run=dry_run,
            total_rows_updated=total_updated,
            total_rows_skipped_already_correct=total_skipped,
            total_docs_no_published_at=total_no_pub,
            total_errors=total_errors,
            distinct_evidence_days_after=distinct_days,
        )

        print("\n── Backfill result ──────────────────────────────────────────")
        print(f"  dry_run:                          {dry_run}")
        print(f"  rows updated:                     {total_updated}")
        print(f"  rows already correct (skipped):   {total_skipped}")
        print(f"  docs with no published_at:        {total_no_pub}")
        print(f"  errors:                           {total_errors}")
        print(f"  distinct evidence days (after):   {distinct_days}")
        print()
        print("  Day distribution:")
        for row in rows:
            print(f"    {str(row[0])[:10]}  {row[1]:>6} rows")

    finally:
        await intel_engine.dispose()
        await cs_engine.dispose()


# ── CLI entry point ───────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=_DEFAULT_BATCH_SIZE,
        help="Doc IDs per batch (default: 500)",
    )
    args = parser.parse_args()

    intel_url = os.environ.get("INTELLIGENCE_DB_URL", _DEFAULT_INTEL_URL)
    cs_url = os.environ.get("CONTENT_STORE_DB_URL", _DEFAULT_CS_URL)

    # Normalise sync URLs to asyncpg
    for attr, url in [("intel_url", intel_url), ("cs_url", cs_url)]:
        if url.startswith("postgresql://") and "+asyncpg" not in url:
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        if attr == "intel_url":
            intel_url = url
        else:
            cs_url = url

    print(
        f"backfill_evidence_dates: "
        f"intel_db={intel_url.split('@')[-1]}  "
        f"cs_db={cs_url.split('@')[-1]}  "
        f"batch={args.batch_size}  "
        f"dry_run={args.dry_run}"
    )
    asyncio.run(_run(intel_url, cs_url, args.batch_size, args.dry_run))


if __name__ == "__main__":
    main()
