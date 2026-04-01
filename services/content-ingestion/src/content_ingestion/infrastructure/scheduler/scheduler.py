"""APScheduler-based polling scheduler for content ingestion.

Adds one ``IntervalTrigger`` job per enabled source.  Each job acquires
a PostgreSQL advisory lock (non-blocking) so that at most one replica
processes a given source at any time.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from content_ingestion.domain.entities import SourceType
from content_ingestion.infrastructure.adapters.eodhd.adapter import EODHDAdapter
from content_ingestion.infrastructure.adapters.finnhub.adapter import FinnhubAdapter
from content_ingestion.infrastructure.adapters.newsapi.adapter import NewsAPIAdapter
from content_ingestion.infrastructure.adapters.sec_edgar.adapter import SECEdgarAdapter
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from content_ingestion.domain.entities import Source
    from content_ingestion.infrastructure.adapters.base import SourceAdapter

logger = get_logger(__name__)  # type: ignore[no-any-return]

ADAPTER_REGISTRY: dict[SourceType, type[SourceAdapter]] = {
    SourceType.EODHD: EODHDAdapter,
    SourceType.SEC_EDGAR: SECEdgarAdapter,
    SourceType.FINNHUB: FinnhubAdapter,
    SourceType.NEWSAPI: NewsAPIAdapter,
}


class IngestionScheduler:
    """Schedules periodic fetch jobs for enabled sources.

    Each job calls the provided *run_fn* callback, which should
    execute the full fetch-and-write use-case (including advisory lock
    acquisition).

    Uses exponential backoff on consecutive failures:
    ``min(interval * 2^failures, max_backoff)``, reset on success.

    Args:
        interval_seconds: Seconds between polling runs per source.
        run_fn: ``async (source) -> Any`` callback invoked per tick.
        max_backoff_seconds: Upper bound on backoff delay (default 3600).
    """

    def __init__(
        self,
        interval_seconds: int,
        run_fn: Callable[[Source], Awaitable[Any]],
        max_backoff_seconds: int = 3600,
    ) -> None:
        self._interval_seconds = interval_seconds
        self._run_fn = run_fn
        self._max_backoff = max_backoff_seconds
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._running = False

    async def start(self, sources: list[Source]) -> None:
        """Start periodic polling for each enabled source."""
        self._running = True
        for source in sources:
            self._start_source(source)

    def _start_source(self, source: Source) -> bool:
        """Start polling for a single source. Returns True if started."""
        if not source.enabled:
            logger.info("scheduler_source_disabled", source=source.name)
            return False
        if source.source_type not in ADAPTER_REGISTRY:
            logger.warning("scheduler_no_adapter", source=source.name, source_type=source.source_type)
            return False
        if source.name in self._tasks:
            logger.warning("scheduler_source_duplicate", source=source.name)
            return False
        task = asyncio.create_task(self._poll_loop(source))
        self._tasks[source.name] = task
        logger.info(
            "scheduler_job_added",
            source=source.name,
            interval_seconds=self._interval_seconds,
        )
        return True

    def add_source(self, source: Source) -> bool:
        """Hot-add a new source to the running scheduler.

        Returns True if the source was added, False if rejected
        (disabled, no adapter, or duplicate).
        """
        if not self._running:
            return False
        return self._start_source(source)

    def remove_source(self, source_name: str) -> bool:
        """Remove and cancel a polling source by name.

        Returns True if the source was found and removed.
        """
        task = self._tasks.pop(source_name, None)
        if task is None:
            return False
        task.cancel()
        logger.info("scheduler_source_removed", source=source_name)
        return True

    async def _poll_loop(self, source: Source) -> None:
        """Run the polling loop for a single source with exponential backoff."""
        failures = 0
        while self._running:
            try:
                await self._run_fn(source)
                failures = 0  # reset on success
            except Exception:
                failures += 1
                logger.exception("scheduler_job_error", source=source.name, consecutive_failures=failures)
            if failures > 0:
                delay = min(self._interval_seconds * (2**failures), self._max_backoff)
            else:
                delay = self._interval_seconds
            await asyncio.sleep(delay)

    async def stop(self) -> None:
        """Cancel all polling tasks and wait for them to finish."""
        self._running = False
        for name, task in self._tasks.items():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                logger.debug("scheduler_task_cancelled", source=name)
        self._tasks.clear()
        logger.info("scheduler_stopped")
