"""Scheduler process entrypoint for market-ingestion.

Runs on a configurable interval and calls ``ScheduleDueTasksUseCase``
on each tick to enqueue tasks for all enabled polling policies.

Usage (standalone)::

    python -m market_ingestion.infrastructure.schedulers.scheduler
"""

from __future__ import annotations

import asyncio
import signal
from contextlib import suppress

from market_ingestion.application.use_cases.schedule_tasks import ScheduleDueTasksUseCase
from market_ingestion.config import Settings
from market_ingestion.infrastructure.db.session import _build_factories
from market_ingestion.infrastructure.db.unit_of_work import SqlaUnitOfWork
from observability.logging import get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)


class SchedulerProcess:
    """Tick-based scheduler that periodically enqueues ingestion tasks.

    Args:
        settings: Service configuration.
        tick_interval_seconds: Time between scheduler ticks in seconds.
        max_tasks_per_tick: Cap on tasks enqueued per tick.
    """

    def __init__(
        self,
        settings: Settings,
        tick_interval_seconds: float | None = None,
        max_tasks_per_tick: int = 1000,
    ) -> None:
        self._settings = settings
        self._tick_interval = tick_interval_seconds or getattr(settings, "scheduler_tick_interval_seconds", 60.0)
        self._max_tasks_per_tick = max_tasks_per_tick
        self._stop_event = asyncio.Event()
        self._write_factory, self._read_factory = _build_factories(settings)

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
        """Execute one scheduler tick."""
        uow = SqlaUnitOfWork(self._write_factory, self._read_factory)
        use_case = ScheduleDueTasksUseCase(
            uow=uow,
            max_tasks_per_tick=self._max_tasks_per_tick,
        )
        try:
            result = await use_case.execute()
            logger.info(
                "scheduler_tick",
                tasks_enqueued=result.tasks_enqueued,
                policies_evaluated=result.policies_evaluated,
                budget_limited=result.budget_limited,
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
    """Synchronous entry-point for ``python -m market_ingestion.infrastructure.schedulers.scheduler``."""
    asyncio.run(_run_scheduler())


if __name__ == "__main__":
    main()
