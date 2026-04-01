"""Background metrics poller for content-ingestion (S4).

Polls outbox and DLQ counts from the DB and updates Prometheus gauges.
Runs as a standalone coroutine inside the worker process (R22 — not in app.py lifespan).
"""

from __future__ import annotations

import asyncio

from content_ingestion.infrastructure.metrics.prometheus import s4_dlq_total, s4_outbox_pending_total
from observability.logging import get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]


async def _metrics_poller(session_factory: object, interval: int) -> None:
    """Periodically update outbox/DLQ gauge metrics."""
    from sqlalchemy import func, select

    from content_ingestion.infrastructure.db.models import DeadLetterQueueModel, OutboxEventModel

    while True:
        try:
            async with session_factory() as session:  # type: ignore[operator]
                outbox_result = await session.execute(
                    select(func.count()).select_from(OutboxEventModel).where(OutboxEventModel.status == "pending"),
                )
                s4_outbox_pending_total.set(outbox_result.scalar() or 0)

                dlq_result = await session.execute(
                    select(func.count())
                    .select_from(DeadLetterQueueModel)
                    .where(DeadLetterQueueModel.status == "failed"),
                )
                s4_dlq_total.set(dlq_result.scalar() or 0)
        except Exception:
            logger.debug("metrics_poll_error", exc_info=True)
        await asyncio.sleep(interval)
