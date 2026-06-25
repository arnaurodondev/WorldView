"""Durable last-success store for scheduled background workers.

PLAN-0089 L-3 ops follow-up (audit 2026-06-16-prd0089-l3-computed-metrics-ops
Lens 2). Backs the ``worker_runs`` table (migration 040) so a worker's
skip-guard and liveness metric survive a container restart / deploy.

Two tiny helpers, both raw-SQL against ``worker_runs``:
  * :func:`read_last_success` — load the stored UTC timestamp (or ``None``).
  * :func:`record_success`    — UPSERT the latest successful-run timestamp.

WHY raw SQL (no ORM model): the table is a single-purpose operational cache
written/read by the scheduler loops only, never projected through the API or
domain layer. A 3-column UPSERT is clearer as ``text()`` than a mapped class,
and avoids adding a model that the introspection guards would have to know
about.

FAIL-SOFT: ``read_last_success`` swallows errors and returns ``None`` (the
caller then behaves as "no prior run" — safe, the run is idempotent). This is
deliberate: a missing/locked ``worker_runs`` row must never wedge the nightly
refresh. ``record_success`` lets errors propagate to the caller's existing
try/except so a write failure is logged, not silently dropped.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import text

from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger(__name__)


async def read_last_success(
    session_factory: async_sessionmaker[AsyncSession],
    worker_name: str,
) -> datetime | None:
    """Return the last successful-run timestamp for ``worker_name`` (UTC) or None.

    Fail-soft: any error (table missing on a lagging DB, transient connectivity)
    returns ``None`` so the caller treats it as "no prior run" rather than
    crashing the loop on startup.
    """
    try:
        async with session_factory() as session:
            result = await session.execute(
                text("SELECT last_success_at FROM worker_runs WHERE worker_name = :name"),
                {"name": worker_name},
            )
            row = result.first()
            if row is None:
                return None
            value = row[0]
            return value if isinstance(value, datetime) else None
    except Exception as exc:  # pragma: no cover - defensive startup path
        logger.warning("worker_runs.read_failed", worker_name=worker_name, error=str(exc))
        return None


async def record_success(
    session_factory: async_sessionmaker[AsyncSession],
    worker_name: str,
    last_success_at: datetime,
) -> None:
    """UPSERT the last successful-run timestamp for ``worker_name``.

    ``last_success_at`` must be a timezone-aware UTC datetime. Errors propagate
    to the caller (the scheduler loop already wraps the run in try/except).
    """
    async with session_factory() as session:
        await session.execute(
            text(
                """
                INSERT INTO worker_runs (worker_name, last_success_at, updated_at)
                VALUES (:name, :ts, now())
                ON CONFLICT (worker_name) DO UPDATE
                    SET last_success_at = EXCLUDED.last_success_at,
                        updated_at      = now()
                """
            ),
            {"name": worker_name, "ts": last_success_at},
        )
        await session.commit()
