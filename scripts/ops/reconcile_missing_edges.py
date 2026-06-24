"""One-shot reconciler: materialize the BP-694 missing-edge backlog.

Architecture context
--------------------
The knowledge-graph ``entity.canonical.created.v1`` consumer materializes a
graph edge when a deferred relation-evidence row's missing endpoint becomes
canonical. Its back-fill, however, keyed on ``entity_provisional = true`` — so
evidence whose endpoint became canonical via a DIFFERENT path (the flag was
already ``false``, the row was marked ``processed=true``, but the upsert was
skipped by the entity-existence gate at processing time) was NEVER revisited.

Result (audit ``docs/audits/2026-06-13-kg-entity-edge-ratio-deepdive.md``):
exactly **1,633** fully-canonical, processed triples that produce no
``relations`` row — a silent, permanent under-materialization of the graph.

This script sweeps that backlog using the EXACT SAME edge-materialization code
path as the consumer (``reconcile_missing_edges`` →
``_materialize_edges_for_triples`` → ``RelationRepository.upsert``), so it can
never diverge from the hot path. It is idempotent and re-runnable: once a
triple's edge exists, the selection predicate excludes it, so the backlog count
strictly decreases to zero.

The selection predicate (in
``knowledge_graph.infrastructure.messaging.consumers.entity_consumer._RECONCILE_BACKLOG_SQL``)
matches the audit's §10 query that counted 1,633 — see ``--dry-run`` to confirm
the live count BEFORE writing anything.

Usage
-----
    # Confirm the backlog count without writing (matches the audit's 1,633):
    python scripts/ops/reconcile_missing_edges.py --dry-run

    # Materialize the whole backlog (commits per batch):
    python scripts/ops/reconcile_missing_edges.py [--batch-size N]

Environment
-----------
Reads DATABASE_URL from env (or defaults to the local dev intelligence_db URL).
"""

from __future__ import annotations

import argparse
import asyncio
import os

from knowledge_graph.infrastructure.messaging.consumers.entity_consumer import (
    _RECONCILE_BACKLOG_SQL,
    reconcile_missing_edges,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# ── Config ────────────────────────────────────────────────────────────────────

_DEFAULT_DB_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/intelligence_db"
_BATCH_SIZE_DEFAULT = 500


# ── Backlog count (dry-run) ────────────────────────────────────────────────────


async def _count_backlog(session: AsyncSession) -> int:
    """Count the missing-edge backlog using the SAME predicate the reconciler uses.

    Wraps ``_RECONCILE_BACKLOG_SQL`` in a COUNT(*) over its DISTINCT triples (no
    LIMIT) so the number reported matches the audit's 1,633 exactly.
    """
    # Re-use the canonical predicate; strip the trailing LIMIT and wrap in COUNT.
    inner = str(_RECONCILE_BACKLOG_SQL).replace("LIMIT :limit", "").strip()
    # S608: `inner` is our own trusted constant SQL (the reconciler's predicate);
    # no user input is interpolated — only the LIMIT clause is stripped.
    count_sql = text(f"SELECT count(*) FROM ({inner}) AS backlog")  # noqa: S608
    result = await session.execute(count_sql)
    return int(result.scalar() or 0)


# ── Runner ──────────────────────────────────────────────────────────────────


async def _run(db_url: str, batch_size: int, dry_run: bool) -> None:
    """Materialize the backlog batch-by-batch until none remain."""
    engine = create_async_engine(db_url, echo=False, pool_pre_ping=True)
    session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with session_factory() as session:
            backlog = await _count_backlog(session)
        print(f"Missing-edge backlog (canonical triples with no relation): {backlog}")

        if dry_run:
            print("[DRY RUN] No writes performed. Re-run without --dry-run to materialize.")
            return

        total = 0
        pass_num = 0
        while True:
            pass_num += 1
            async with session_factory() as session:
                materialized = await reconcile_missing_edges(session, batch_size=batch_size)
                await session.commit()
            total += materialized
            print(f"Pass {pass_num}: materialized={materialized}, total={total}")
            if materialized == 0:
                break

        async with session_factory() as session:
            remaining = await _count_backlog(session)
        print("\n── Final state ──────────────────────────────────────────")
        print(f"  edges materialized this run: {total}")
        print(f"  remaining backlog:           {remaining}")
    finally:
        await engine.dispose()


# ── CLI entry point ──────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Report the backlog count without writing")
    parser.add_argument("--batch-size", type=int, default=_BATCH_SIZE_DEFAULT, help="Triples per commit")
    args = parser.parse_args()

    db_url = os.environ.get("DATABASE_URL", _DEFAULT_DB_URL)
    if db_url.startswith("postgresql://") and "+asyncpg" not in db_url:
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    print(f"reconcile_missing_edges: db={db_url.split('@')[-1]}  batch={args.batch_size}  dry_run={args.dry_run}")
    asyncio.run(_run(db_url, args.batch_size, args.dry_run))


if __name__ == "__main__":
    main()
