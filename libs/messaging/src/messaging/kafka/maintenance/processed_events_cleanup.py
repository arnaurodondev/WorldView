"""Background cleanup for the ``processed_events`` idempotency table.

Context
-------
The Kafka consumer base class (:class:`messaging.kafka.consumer.base.BaseKafkaConsumer`)
records every successfully processed event id in a ``processed_events`` row so
that re-delivery (e.g. after a consumer offset rewind or rebalance replay) is
dropped via :meth:`is_duplicate`. Without retention this table grows
monotonically; at ~1M events/day per service it adds ~30M rows/month/DB —
disk pressure, btree degradation, and slow startup.

Design (LIB-001 / TASK-W1-06)
-----------------------------
* Default retention window: 30 days. Configurable per call site.
* Batched DELETE with ``FOR UPDATE SKIP LOCKED`` so the live consumer's
  ``INSERT INTO processed_events`` (inside its own transaction) is never
  blocked by cleanup, and so two concurrent cleanup invocations cannot fight
  over the same rows.
* PostgreSQL ``DELETE`` does not accept ``LIMIT`` directly — we use the
  canonical ``DELETE ... WHERE event_id IN (SELECT ... LIMIT N FOR UPDATE
  SKIP LOCKED)`` pattern.
* Yields between batches (small ``asyncio.sleep``) so a multi-million-row
  catch-up does not monopolise the event loop or hammer the DB.

Safety
------
``processed_events`` is belt-and-suspenders against operator-driven Kafka
offset rewinds. Primary at-least-once safety is the consumer offset itself.
Deleting old idempotency rows is therefore safe as long as the retention
window is comfortably longer than any plausible offset-rewind window the
operator might perform.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import text

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = get_logger(__name__)  # type: ignore[no-any-return]


class ProcessedEventsCleanupWorker:
    """Delete ``processed_events`` rows older than a retention window.

    The worker is stateless — it accepts a fresh :class:`AsyncSession` per
    invocation so the caller controls the engine and connection pool. It
    runs in batches and commits after each batch so other consumers see
    deletes promptly and the worker can be cancelled cleanly mid-run.

    Typical scheduling: invoke :meth:`run_once` daily (e.g. at 02:00 UTC)
    via the service's existing scheduler entry-point or a dedicated
    ``*_cleanup_main.py`` process (per R22).

    Args:
        service_name: Identifier of the calling service — only used for
            structured logging so a multi-service deployment can correlate
            cleanup runs in log aggregation.
        retention_days: Rows whose ``processed_at`` is older than
            ``now() - retention_days`` are deleted. Default 30 days.
        batch_size: Maximum rows deleted per transaction. Default 10 000.
            A smaller value reduces lock contention; a larger value
            reduces overhead on a large backlog.
    """

    # Default retention chosen so a routine consumer offset rewind (hours
    # to a few days) is still protected by the idempotency table.
    DEFAULT_RETENTION_DAYS = 30
    # 10k rows per batch keeps the per-transaction lock footprint small
    # while still amortising commit overhead on a million-row catch-up.
    BATCH_SIZE = 10_000
    # Yield to the event loop so a multi-batch run does not hot-loop and
    # so other consumer tasks on the same loop continue to make progress.
    INTER_BATCH_SLEEP_SECONDS = 0.1

    def __init__(
        self,
        *,
        service_name: str,
        retention_days: int = DEFAULT_RETENTION_DAYS,
        batch_size: int = BATCH_SIZE,
    ) -> None:
        if retention_days <= 0:
            raise ValueError("retention_days must be > 0")
        if batch_size <= 0:
            raise ValueError("batch_size must be > 0")
        self._service_name = service_name
        self._retention_days = retention_days
        self._batch_size = batch_size

    async def run_once(self, session: AsyncSession) -> int:
        """Run a single cleanup pass and return total rows deleted.

        The loop terminates as soon as a batch returns fewer rows than
        ``batch_size`` — meaning there are no more eligible rows to
        delete (or the remaining ones are locked by concurrent
        consumers, which we deliberately skip and pick up on the next
        scheduled run).
        """
        cutoff = datetime.now(UTC) - timedelta(days=self._retention_days)
        total_deleted = 0
        batches = 0
        while True:
            # The subquery + FOR UPDATE SKIP LOCKED pattern is critical:
            #   - PostgreSQL DELETE does not accept LIMIT directly.
            #   - SKIP LOCKED makes the cleanup non-blocking against the
            #     consumer's INSERT (which holds a row lock on its own
            #     event_id while its UoW is open).
            result = await session.execute(
                text(
                    "DELETE FROM processed_events "
                    "WHERE event_id IN ("
                    "  SELECT event_id FROM processed_events "
                    "  WHERE processed_at < :cutoff "
                    "  LIMIT :batch FOR UPDATE SKIP LOCKED"
                    ")"
                ),
                {"cutoff": cutoff, "batch": self._batch_size},
            )
            deleted = result.rowcount or 0  # type: ignore[attr-defined]
            total_deleted += deleted
            batches += 1
            await session.commit()
            if deleted < self._batch_size:
                # Either no more rows older than the cutoff, or the rest
                # are locked by live consumers — either way, stop.
                break
            # Cooperative yield so the event loop and DB get breathing
            # room between large batches.
            await asyncio.sleep(self.INTER_BATCH_SLEEP_SECONDS)

        logger.info(
            "processed_events_cleanup_completed",
            service=self._service_name,
            total_deleted=total_deleted,
            batches=batches,
            retention_days=self._retention_days,
            batch_size=self._batch_size,
            cutoff=cutoff.isoformat(),
        )
        return total_deleted
