"""Scheduler process entrypoint for content-ingestion.

Runs on a configurable interval and calls ``ScheduleDueSourcesUseCase``
on each tick to enqueue tasks for all enabled sources.

Usage (standalone)::

    python -m content_ingestion.infrastructure.scheduler.scheduler_main
"""

from __future__ import annotations

import asyncio
import signal
from contextlib import suppress

import common.time  # type: ignore[import-untyped]
from content_ingestion.application.use_cases.schedule_sources import ScheduleDueSourcesUseCase
from content_ingestion.config import Settings
from content_ingestion.infrastructure.db.session import _build_factories
from content_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork
from observability.logging import get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)


class SchedulerProcess:
    """Tick-based scheduler that periodically enqueues content ingestion tasks.

    Args:
        settings: Service configuration.
        tick_interval_seconds: Time between scheduler ticks in seconds.
        max_tasks_per_tick: Cap on tasks enqueued per tick.
    """

    def __init__(
        self,
        settings: Settings,
        tick_interval_seconds: float | None = None,
        max_tasks_per_tick: int | None = None,
    ) -> None:
        self._settings = settings
        self._tick_interval = tick_interval_seconds or settings.scheduler_tick_interval_seconds
        self._max_tasks_per_tick = max_tasks_per_tick or settings.scheduler_max_tasks_per_tick
        self._stop_event = asyncio.Event()
        _, self._write_factory, self._read_factory = _build_factories(settings)

    def stop(self) -> None:
        """Signal the scheduler loop to stop after the current tick."""
        self._stop_event.set()

    async def run(self) -> None:
        """Run the scheduler loop until ``stop()`` is called."""
        logger.info(
            "scheduler_starting",
            tick_interval_seconds=self._tick_interval,
            max_tasks_per_tick=self._max_tasks_per_tick,
        )
        while not self._stop_event.is_set():
            await self._tick()
            with suppress(TimeoutError):
                await asyncio.wait_for(
                    asyncio.shield(self._stop_event.wait()),
                    timeout=self._tick_interval,
                )

        logger.info("scheduler_stopped")

    async def _tick(self) -> None:
        """Execute one scheduler tick.

        Recovery runs first so that sources blocked by crashed workers are
        unblocked before the scheduling pass evaluates them.
        """
        now = common.time.utc_now()

        # 1. Recover tasks whose worker lease has expired (crashed/killed workers).
        try:
            uow_recover = SqlaUnitOfWork(self._write_factory, self._read_factory)
            async with uow_recover:
                recovered = await uow_recover.tasks.recover_expired_leases(
                    now,
                    lease_timeout_seconds=self._settings.worker_lease_seconds,
                )
                await uow_recover.commit()
            if recovered:
                logger.warning(
                    "scheduler_leases_recovered",
                    count=recovered,
                    lease_timeout_seconds=self._settings.worker_lease_seconds,
                )
        except Exception as exc:
            logger.error("scheduler_lease_recovery_error", error=str(exc))

        # 2. Evaluate sources and enqueue new tasks.
        uow = SqlaUnitOfWork(self._write_factory, self._read_factory)
        use_case = ScheduleDueSourcesUseCase(
            uow=uow,
            scheduler_interval_seconds=self._settings.scheduler_interval_seconds,
            max_tasks_per_tick=self._max_tasks_per_tick,
        )
        try:
            result = await use_case.execute()
            logger.info(
                "scheduler_tick",
                tasks_enqueued=result.tasks_enqueued,
                sources_evaluated=result.sources_evaluated,
            )
        except Exception as exc:
            logger.error("scheduler_tick_error", error=str(exc))


async def _run_scheduler() -> None:
    """Async entry-point; installs signal handlers for graceful shutdown."""
    settings = Settings()  # type: ignore[call-arg]
    scheduler = SchedulerProcess(settings=settings)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, scheduler.stop)

    await scheduler.run()


def main() -> None:
    """Synchronous entry-point for ``python -m content_ingestion.infrastructure.scheduler.scheduler_main``."""
    asyncio.run(_run_scheduler())


if __name__ == "__main__":
    main()
