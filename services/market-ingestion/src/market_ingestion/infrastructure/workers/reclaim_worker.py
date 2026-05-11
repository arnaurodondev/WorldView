"""PrimaryProviderReclaimWorker — periodic background worker.

Runs every 4 hours (configurable).  Each cycle:
  1. Queries SUCCEEDED tasks where ``fetched_by_provider IS NOT NULL``.
  2. Filters to tasks where the fetching provider differs from the
     routing cache's current primary for that (dataset_type, timeframe).
  3. Creates new tasks targeting the primary provider with the SAME
     ``dedupe_key`` so ``ON CONFLICT DO NOTHING`` makes the operation
     idempotent (BP-005).

Independent process (R22): NOT co-located with the task executor.

Usage (standalone)::

    python -m market_ingestion.infrastructure.workers.reclaim_worker_main
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING

from common.ids import new_ulid  # type: ignore[import-untyped]
from market_ingestion.domain.enums import Provider
from observability.logging import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Callable

    from market_ingestion.application.ports.unit_of_work import UnitOfWork
    from market_ingestion.application.services.provider_routing_cache import ProviderRoutingCache
    from market_ingestion.domain.entities.ingestion_task import IngestionTask

logger = get_logger(__name__)

# Default interval: 4 hours (14 400 seconds)
_DEFAULT_INTERVAL_SEC: int = 14_400

# Safety cap: never create more than 5 000 reclaim tasks per cycle
_DEFAULT_MAX_RECLAIM: int = 5_000


class PrimaryProviderReclaimWorker:
    """Background worker that periodically reclaims data from the primary provider.

    When a task was executed by a secondary (fallback) provider, this worker
    creates a new task targeting the primary provider so that the authoritative
    source is eventually fetched.  The shared ``dedupe_key`` ensures that if a
    primary-provider task already exists it is silently skipped (``ON CONFLICT
    DO NOTHING``).

    Args:
    ----
        uow_factory: Callable that produces a fresh ``UnitOfWork`` per cycle.
        routing_cache: Config-backed routing cache (``primary_for()``).
        interval_sec: Sleep duration between cycles (default 4 h).
        max_reclaim_per_run: Maximum reclaim tasks created per cycle (default 5 000).

    """

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork],
        routing_cache: ProviderRoutingCache,
        interval_sec: int = _DEFAULT_INTERVAL_SEC,
        max_reclaim_per_run: int = _DEFAULT_MAX_RECLAIM,
    ) -> None:
        self._uow_factory = uow_factory
        self._routing_cache = routing_cache
        self._interval_sec = interval_sec
        self._max_reclaim_per_run = max_reclaim_per_run
        self._stop_event = asyncio.Event()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def stop(self) -> None:
        """Signal the worker loop to stop after the current cycle."""
        self._stop_event.set()

    async def run(self) -> None:
        """Main loop: reclaim, sleep, repeat until stopped."""
        logger.info(
            "reclaim_worker_starting",
            interval_sec=self._interval_sec,
            max_reclaim_per_run=self._max_reclaim_per_run,
        )
        while not self._stop_event.is_set():
            await self._run_once()
            # Use wait() so that stop() interrupts the sleep immediately.
            # TimeoutError means it's time for the next cycle — not an error.
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._interval_sec,
                )
        logger.info("reclaim_worker_stopped")

    # ------------------------------------------------------------------
    # Single cycle
    # ------------------------------------------------------------------

    async def _run_once(self) -> None:
        """Execute one reclaim cycle.

        Steps:
          1. Open a UoW and query succeeded tasks with ``fetched_by_provider``.
          2. Filter to those needing reclaim (fetched by non-primary provider).
          3. Build new tasks targeting the primary provider (same dedupe_key).
          4. Bulk-insert with ``ON CONFLICT DO NOTHING`` (BP-005).
          5. Commit and log summary.
        """
        uow = self._uow_factory()
        try:
            async with uow:
                # Step 1 — query candidates (read from DB)
                candidates = await uow.tasks.find_succeeded_with_fetched_by(  # type: ignore[attr-defined]
                    limit=self._max_reclaim_per_run,
                )

                # Step 2 — filter to tasks that need reclaim
                to_reclaim = [t for t in candidates if self._needs_reclaim(t)]

                if not to_reclaim:
                    logger.info("primary_provider_reclaim_complete", reclaimed=0, candidates=len(candidates))
                    return

                # Step 3 — cap at max_reclaim_per_run (already limited by query,
                # but the filter may reduce the count below the cap).
                capped = to_reclaim[: self._max_reclaim_per_run]

                # Step 4 — build reclaim tasks
                reclaim_tasks = [self._make_reclaim_task(t) for t in capped]

                # Step 5 — bulk insert (ON CONFLICT DO NOTHING via add_many)
                inserted = await uow.tasks.add_many(reclaim_tasks)
                await uow.commit()

                logger.info(
                    "primary_provider_reclaim_complete",
                    reclaimed=inserted,
                    candidates=len(candidates),
                    filtered=len(to_reclaim),
                )
        except Exception as exc:
            logger.error("reclaim_worker_cycle_error", error=str(exc))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _needs_reclaim(self, task: IngestionTask) -> bool:
        """Return True if *task* was fetched by a non-primary provider.

        Tasks with ``fetched_by_provider=None`` are skipped (unknown provider).
        """
        if task.fetched_by_provider is None:  # type: ignore[attr-defined]
            return False
        primary = self._routing_cache.primary_for(str(task.dataset_type), task.timeframe)
        return task.fetched_by_provider != primary  # type: ignore[attr-defined, no-any-return]

    def _make_reclaim_task(self, original: IngestionTask) -> IngestionTask:
        """Create a new PENDING task targeting the primary provider.

        Re-uses the original's ``dedupe_key`` so that ``ON CONFLICT DO NOTHING``
        prevents duplicates (BP-005).  The new task gets a fresh ULID id.
        """
        from market_ingestion.domain.entities.ingestion_task import IngestionTask as TaskCls

        primary_str = self._routing_cache.primary_for(str(original.dataset_type), original.timeframe)
        return TaskCls(
            id=new_ulid(),
            provider=Provider(primary_str),
            dataset_type=original.dataset_type,
            symbol=original.symbol,
            exchange=original.exchange,
            timeframe=original.timeframe,
            variant=original.variant,
            range_start=original.range_start,
            range_end=original.range_end,
            dedupe_key=original.dedupe_key,
        )
