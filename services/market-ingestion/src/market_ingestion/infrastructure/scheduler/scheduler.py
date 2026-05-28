"""Scheduler process class for market-ingestion.

Runs on a configurable interval and calls ``ScheduleDueTasksUseCase``
on each tick to enqueue tasks for all enabled polling policies.

Use ``scheduler_main.py`` as the standalone entry point::

    python -m market_ingestion.infrastructure.scheduler.scheduler_main
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import TYPE_CHECKING

from market_ingestion.application.use_cases.schedule_tasks import ScheduleDueTasksUseCase
from market_ingestion.infrastructure.db.session import _build_factories

if TYPE_CHECKING:
    from market_ingestion.config import Settings
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
        """Signal the scheduler loop to stop after the current tick.

        Also stops the FundamentalsRefreshWorker (PLAN-0099 W2-T02) if it was
        spawned, so SIGTERM tears down both loops together rather than leaving
        the refresh worker stranded.
        """
        self._stop_event.set()
        worker = getattr(self, "_fundamentals_refresh_worker", None)
        if worker is not None:
            worker.stop()

    async def run(self) -> None:
        """Run the scheduler loop until ``stop()`` is called."""
        logger.info(
            "scheduler_starting",
            tick_interval_seconds=self._tick_interval,
            max_tasks_per_tick=self._max_tasks_per_tick,
        )

        # PLAN-0055 A-2: spawn the auto-backfill orchestrator as a fire-and-forget
        # task so the first tick fires immediately. Gated by env so operators retain
        # a kill-switch. Errors inside the task are swallowed in _run_startup_backfill.
        if getattr(self._settings, "auto_backfill_on_startup", False):
            self._spawn_startup_backfill()

        # PLAN-0099 W2-T02: spawn the FundamentalsRefreshWorker as a fire-and-forget
        # task so its 6-hour loop runs concurrently with the scheduler tick loop.
        # Gated by ``fundamentals_refresh_enabled`` — off by default so this rolls
        # out per-deploy without surprising any environment that hasn't opted in.
        if getattr(self._settings, "fundamentals_refresh_enabled", False):
            self._spawn_fundamentals_refresh()

        while not self._stop_event.is_set():
            # WHY try/except here: _tick() catches DB errors internally, but an
            # unhandled exception from asyncio.wait_for or asyncio.shield (e.g. an
            # unexpected RuntimeError) would silently kill the scheduler loop.
            # Catching at the loop level ensures the scheduler always retries after
            # a short pause rather than dying silently.  CancelledError re-raises
            # so SIGTERM / stop() propagates correctly.
            try:
                await self._tick()
                with suppress(TimeoutError):
                    await asyncio.wait_for(
                        asyncio.shield(self._stop_event.wait()),
                        timeout=self._tick_interval,
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("scheduler_loop_error")
                await asyncio.sleep(5)

        logger.info("scheduler_stopped")

    def _spawn_startup_backfill(self) -> None:
        """Build the use case and detach it on a background task (PLAN-0055 A-2)."""
        from market_ingestion.application.services.provider_routing_cache import ProviderRoutingCache
        from market_ingestion.application.use_cases.run_startup_backfill import RunStartupBackfillUseCase

        try:
            routing = ProviderRoutingCache()
            routing.load_from_config(self._settings)
            use_case = RunStartupBackfillUseCase(
                uow_factory=lambda: SqlaUnitOfWork(self._write_factory, self._read_factory),
                settings=self._settings,
                routing=routing,
            )
            # Stash so the task isn't GC'd before completion (RUF006).
            self._startup_backfill_task = asyncio.create_task(
                self._run_startup_backfill(use_case),
                name="startup_backfill",
            )
        except Exception as exc:  # — scheduler must boot regardless
            logger.exception("startup_backfill_spawn_failed", error=str(exc))

    def _spawn_fundamentals_refresh(self) -> None:
        """Detach the fundamentals-refresh loop on a background task (PLAN-0099 W2-T02).

        The worker runs forever (until ``self.stop()`` is observed by the
        scheduler — we propagate via the worker's own ``stop()`` below).
        We stash the task handle so it isn't GC'd before completion (RUF006)
        and propagate ``stop()`` so SIGTERM cleanly tears it down with the
        scheduler.
        """
        from market_ingestion.infrastructure.workers.fundamentals_refresh_worker import (
            FundamentalsRefreshWorker,
        )

        try:
            worker = FundamentalsRefreshWorker(settings=self._settings)
            # Stash the worker so stop() can tear it down (see below).
            self._fundamentals_refresh_worker = worker
            self._fundamentals_refresh_task = asyncio.create_task(
                worker.run(),
                name="fundamentals_refresh_worker",
            )
        except Exception as exc:  # — scheduler must boot regardless
            logger.exception(
                "fundamentals_refresh_spawn_failed",
                error=str(exc),
            )

    @staticmethod
    async def _run_startup_backfill(use_case) -> None:  # type: ignore[no-untyped-def]
        try:
            summary = await use_case.execute()
            logger.info(
                "startup_backfill_task_completed",
                enqueued=summary.enqueued,
                skipped=summary.skipped,
                failed=summary.failed,
            )
        except Exception as exc:  # — fire-and-forget; never crash the loop
            logger.exception("startup_backfill_task_failed", error=str(exc))

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
