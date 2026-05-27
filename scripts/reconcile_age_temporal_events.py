"""Reconcile AGE TemporalEvent vertices with the relational ``temporal_events`` table.

PLAN-0096 W3 T-W3-03 — one-shot remediation tool for the silent-drop bug
documented in ``docs/audits/2026-05-26-age-temporal-event-sync-investigation.md``
(BP-574).

Context
-------
A SQLAlchemy session-cache bug in ``AgeSyncWorker._bootstrap_age_labels``
caused the worker to create the ``TemporalEvent`` vlabel and then run MERGE
statements on the *same* physical PostgreSQL connection. plpgsql cached the
pre-bootstrap schema, so every MERGE silently dropped — leaving 0 of 14,822
TemporalEvent vertices in AGE. The worker code is now fixed by invalidating
the connection after the bootstrap commit, but the existing backlog needs a
one-shot drain.

This script:
  1. Queries Postgres for every row in ``temporal_events``.
  2. For each row, runs an AGE Cypher MERGE that creates the vertex if it
     does not already exist (idempotent — safe to re-run).
  3. Reports a per-batch progress log and a final summary
     (scanned / created-or-merged / skipped).

The script opens a FRESH SQLAlchemy connection for the AGE writes (separate
from the read session) so the same session-cache pitfall cannot bite the
reconciliation itself.

Usage
-----
    # Dry-run: report what WOULD be reconciled, no AGE writes.
    python scripts/reconcile_age_temporal_events.py --dry-run

    # Real run.
    python scripts/reconcile_age_temporal_events.py

    # Bigger batch (default 500).
    python scripts/reconcile_age_temporal_events.py --batch-size 1000

Environment
-----------
    DATABASE_URL:        async DSN override; default points at the local
                         intelligence_db (asyncpg driver).
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Default DSN — same shape as scripts/ops/backfill_definition_embeddings.py.
_DEFAULT_DB_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/intelligence_db"

# Must match _AGE_GRAPH_NAME in
# services/knowledge-graph/src/knowledge_graph/infrastructure/workers/age_sync_worker.py
_AGE_GRAPH_NAME = "worldview_graph"

# Idempotent MERGE — matches the worker's _SQL_TEMPORAL_EVENT_MERGE so the
# script and the live worker converge on the same vertex shape.
_SQL_TEMPORAL_EVENT_MERGE = (
    "SELECT * FROM ag_catalog.cypher('worldview_graph', $$"
    " MERGE (t:TemporalEvent {event_id: $event_id})"
    " SET t.event_type = $event_type,"
    "     t.scope = $scope,"
    "     t.region = $region,"
    "     t.title = $title,"
    "     t.confidence = $confidence,"
    "     t.updated_at = $updated_at"
    " $$, :params) AS (result ag_catalog.agtype)"
)

# Read query — keep the column set in sync with the worker's _sync_temporal_events
# read query (services/knowledge-graph/.../age_sync_worker.py:_sync_temporal_events).
_SQL_READ_TEMPORAL_EVENTS = (
    "SELECT event_id, event_type, scope, region, title, confidence, updated_at "
    "FROM temporal_events "
    "ORDER BY updated_at ASC"
)

# stdlib logging is fine for a one-shot operator script (the rest of the
# platform uses structlog — see R12 — but stdout-friendly output matters more
# here than structured logging).
logger = logging.getLogger("reconcile_age_temporal_events")


async def _setup_age_session(session: AsyncSession) -> None:
    """Load the AGE extension on *session* so subsequent Cypher calls work.

    Mirrors ``_setup_age_session`` in age_sync_worker.py — every connection
    that issues Cypher MUST run these two statements first.
    """
    await session.execute(text("LOAD 'age'"))
    await session.execute(text('SET search_path = ag_catalog, "$user", public'))


async def _ensure_temporal_event_vlabel(session: AsyncSession) -> None:
    """Idempotently create the ``TemporalEvent`` vlabel.

    If the live AGE graph has never had the label created (the original
    pre-fix scenario) the MERGE statements below would fail with
    ``label does not exist``. Creating it here is a no-op when the worker
    already created it.
    """
    try:
        await session.execute(text(f"SELECT create_vlabel('{_AGE_GRAPH_NAME}', 'TemporalEvent')"))
    except Exception as exc:  # — idempotent best-effort
        if "already exists" in str(exc).lower():
            return
        raise


async def _scan_temporal_events(session: AsyncSession) -> list[dict[str, Any]]:
    """Pull every row from ``temporal_events`` into memory.

    14,822 rows by ~8 columns is well under 10 MB — no need to stream.
    """
    result = await session.execute(text(_SQL_READ_TEMPORAL_EVENTS))
    rows = result.fetchall()
    return [
        {
            "event_id": str(row.event_id),
            "event_type": row.event_type,
            "scope": row.scope,
            "region": row.region,
            "title": row.title,
            "confidence": float(row.confidence) if row.confidence is not None else 0.0,
            "updated_at": row.updated_at.isoformat() if row.updated_at is not None else None,
        }
        for row in rows
    ]


async def _merge_one(session: AsyncSession, row: dict[str, Any]) -> None:
    """Run the idempotent AGE MERGE for one row.

    AGE Cypher does not surface "created" vs "matched" cleanly through the
    Python adapter, so we treat every successful execute as "ok" and let the
    operator query AGE post-run for the final count.
    """
    import json

    await session.execute(
        text(_SQL_TEMPORAL_EVENT_MERGE),
        {"params": json.dumps(row)},
    )


async def reconcile(
    *,
    db_url: str,
    batch_size: int,
    dry_run: bool,
) -> tuple[int, int, int]:
    """Run the reconciliation loop. Returns ``(scanned, merged, skipped)``.

    ``skipped`` is non-zero only when an individual MERGE raises — we log the
    error and continue rather than aborting the whole drain. That matches the
    operational requirement: a poisoned row should not block the other 14,821.
    """
    engine = create_async_engine(db_url, echo=False)
    session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        engine,
        expire_on_commit=False,
    )

    scanned = 0
    merged = 0
    skipped = 0
    try:
        # Phase 1 — read every row in a short-lived session.
        async with session_factory() as read_session:
            rows = await _scan_temporal_events(read_session)
            scanned = len(rows)
            logger.info("scanned temporal_events: %d rows", scanned)

        if dry_run:
            logger.info("[dry-run] would MERGE %d rows in batches of %d", scanned, batch_size)
            return scanned, 0, 0

        # Phase 2 — write in a fresh session (so we never share connection
        # state with the read above; mirrors the post-fix worker contract).
        async with session_factory() as write_session:
            await _setup_age_session(write_session)
            await _ensure_temporal_event_vlabel(write_session)
            # Commit the bootstrap so the next MERGE is in a clean transaction,
            # then drop the connection (BP-574 — the very bug this script
            # exists to remediate). We let SQLAlchemy reopen on next execute.
            await write_session.commit()
            try:
                connection = await write_session.connection()
                await connection.invalidate()
            except Exception as exc:  # — best-effort cache reset
                logger.warning("connection invalidate failed: %s", exc)
            await _setup_age_session(write_session)

            for batch_start in range(0, scanned, batch_size):
                batch = rows[batch_start : batch_start + batch_size]
                for row in batch:
                    try:
                        await _merge_one(write_session, row)
                        merged += 1
                    except Exception as exc:  # — drain-best-effort
                        skipped += 1
                        logger.warning(
                            "MERGE failed for event_id=%s: %s",
                            row.get("event_id"),
                            exc,
                        )
                await write_session.commit()
                logger.info(
                    "batch committed: scanned=%d merged=%d skipped=%d",
                    batch_start + len(batch),
                    merged,
                    skipped,
                )
    finally:
        await engine.dispose()

    return scanned, merged, skipped


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report counts only; do not write to AGE.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=500,
        help="Number of MERGEs per transaction commit (default: 500).",
    )
    return parser.parse_args()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = _parse_args()

    db_url = os.environ.get("DATABASE_URL", _DEFAULT_DB_URL)
    logger.info(
        "starting reconcile_age_temporal_events: db_url=%s batch_size=%d dry_run=%s",
        db_url.split("@")[-1],  # redact credentials
        args.batch_size,
        args.dry_run,
    )

    scanned, merged, skipped = asyncio.run(
        reconcile(db_url=db_url, batch_size=args.batch_size, dry_run=args.dry_run),
    )

    logger.info(
        "DONE: scanned=%d merged=%d skipped=%d (dry_run=%s)",
        scanned,
        merged,
        skipped,
        args.dry_run,
    )
    # Non-zero exit only when something genuinely failed (skipped > 0 in a
    # real run); a clean dry-run always returns 0.
    return 1 if (skipped > 0 and not args.dry_run) else 0


if __name__ == "__main__":
    sys.exit(main())
