"""Periodic gauge updater for S5 outbox/DLQ depth.

The Prometheus dashboard panels for outbox backlog and DLQ depth read from
``s5_outbox_pending_total`` and ``s5_dlq_total`` Gauges. These have no natural
event-driven update site, so we poll the database every 30 seconds from an
asyncio background task started in the FastAPI lifespan.

The loop is defensive: any exception (DB outage, transient connection error)
is logged but does not kill the task — the gauge simply keeps its last value
until the next successful poll.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog
from sqlalchemy import func, select

from content_store.infrastructure.db.models import DeadLetterQueueModel, OutboxEventModel
from content_store.infrastructure.metrics.prometheus import (
    s5_dlq_total,
    s5_outbox_pending_total,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import async_sessionmaker

logger = structlog.get_logger(__name__)  # type: ignore[no-any-return]

# Poll interval — short enough that operator dashboards stay responsive,
# long enough that a 30 s blip doesn't hammer the DB with COUNT(*) scans.
DEFAULT_POLL_INTERVAL_SECONDS = 30.0


async def update_gauges_once(session_factory: async_sessionmaker) -> None:
    """Run a single poll: query outbox pending + DLQ counts and update gauges.

    Wrapped in try/except per source so a failure of one query does not block
    the other.  Exceptions are logged at WARNING and swallowed — the gauge
    simply retains its previous value.
    """
    async with session_factory() as session:
        try:
            result = await session.execute(
                select(func.count())
                .select_from(OutboxEventModel)
                .where(OutboxEventModel.status.in_(["pending", "processing"]))
            )
            pending = int(result.scalar() or 0)
            s5_outbox_pending_total.set(pending)
        except Exception as exc:  # pragma: no cover - logged path
            logger.warning("outbox_gauge_update_failed", error=str(exc))

        try:
            result = await session.execute(
                select(func.count()).select_from(DeadLetterQueueModel).where(DeadLetterQueueModel.status == "failed")
            )
            dlq = int(result.scalar() or 0)
            s5_dlq_total.set(dlq)
        except Exception as exc:  # pragma: no cover - logged path
            logger.warning("dlq_gauge_update_failed", error=str(exc))


async def gauge_update_loop(
    session_factory: async_sessionmaker,
    interval_seconds: float = DEFAULT_POLL_INTERVAL_SECONDS,
) -> None:
    """Run ``update_gauges_once`` in a loop until cancelled.

    Intended to be launched via ``asyncio.create_task(...)`` from the FastAPI
    lifespan startup and cancelled on shutdown.
    """
    logger.info("s5_gauge_updater_started", interval_seconds=interval_seconds)
    try:
        while True:
            try:
                await update_gauges_once(session_factory)
            except Exception as exc:  # pragma: no cover - defensive guard
                # update_gauges_once already catches per-query errors; this is
                # only reached on a catastrophic unexpected error (e.g. import-
                # time issue).  Keep the loop alive regardless.
                logger.warning("gauge_updater_iteration_failed", error=str(exc))
            await asyncio.sleep(interval_seconds)
    except asyncio.CancelledError:
        logger.info("s5_gauge_updater_stopped")
        raise
