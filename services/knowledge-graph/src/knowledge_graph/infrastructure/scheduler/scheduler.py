"""APScheduler + Kafka co-topology scaffold (PRD §6.7 Block 13).

:class:`KnowledgeGraphScheduler` starts an :class:`~apscheduler.schedulers.asyncio.AsyncIOScheduler`
(8 worker job slots, stubs until Wave D-3) and a Kafka consumer coroutine
in the **same** asyncio event loop.

Graceful SIGTERM shutdown: ``stop()`` cancels the consumer task and
shuts the scheduler down cleanly — called from the FastAPI lifespan
``finally`` block.

Wave D-3 will replace the stub workers with real implementations.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import-untyped]

from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from knowledge_graph.config import Settings

logger = get_logger(__name__)  # type: ignore[no-any-return]


class KnowledgeGraphScheduler:
    """Co-topology: 8 APScheduler worker slots + Kafka consumer task.

    All work runs in the same asyncio event loop as FastAPI.

    Args:
        settings: Service configuration (worker interval settings).
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._scheduler = AsyncIOScheduler()
        self._consumer_task: asyncio.Task[Any] | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self, consumer_coro: Coroutine[Any, Any, None]) -> None:
        """Start the scheduler and the consumer coroutine.

        The consumer coroutine is wrapped in an asyncio Task.  Job stubs
        are registered with configured intervals.

        Args:
            consumer_coro: Coroutine to run as the main Kafka consumer.
        """
        self._register_jobs()
        self._scheduler.start()
        logger.info(
            "kg_scheduler_started",
            job_count=len(self._scheduler.get_jobs()),
        )
        self._consumer_task = asyncio.create_task(consumer_coro, name="kg_enriched_consumer")
        logger.info("kg_consumer_task_started")

    async def stop(self) -> None:
        """Graceful shutdown: stop scheduler and cancel the consumer task."""
        self._scheduler.shutdown(wait=False)
        logger.info("kg_scheduler_stopped")

        if self._consumer_task and not self._consumer_task.done():
            self._consumer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._consumer_task

        logger.info("kg_consumer_task_stopped")

    # ------------------------------------------------------------------
    # Job registration (8 slots — stubs until Wave D-3)
    # ------------------------------------------------------------------

    def _register_jobs(self) -> None:
        """Register all 8 APScheduler jobs with configured intervals."""
        s = self._settings
        _jobs: list[tuple[str, int, str]] = [
            # (worker_name, interval_seconds, job_id)
            ("confidence_recompute", s.worker_confidence_interval_s, "worker_13a_confidence"),
            ("contradiction_batch", s.worker_contradiction_interval_s, "worker_13b_contradiction"),
            ("summary_generation", s.worker_summary_interval_s, "worker_13c_summary"),
            ("definition_embedding", s.worker_definition_refresh_interval_s, "worker_13d1_definition"),
            ("narrative_embedding", s.worker_narrative_refresh_interval_s, "worker_13d2_narrative"),
            ("fundamentals_embedding", s.worker_fundamentals_refresh_interval_s, "worker_13d3_fundamentals"),
            ("provisional_enrichment", s.worker_embedding_refresh_interval_s, "worker_13e_provisional"),
            ("partition_management", s.worker_partition_interval_s, "worker_13f_partition"),
        ]
        for name, interval, job_id in _jobs:
            self._scheduler.add_job(
                self._make_stub(name),
                "interval",
                seconds=interval,
                id=job_id,
                max_instances=1,
                coalesce=True,
            )

    @staticmethod
    def _make_stub(worker_name: str) -> Any:
        """Return an async stub coroutine function for *worker_name*."""

        async def _stub() -> None:
            logger.debug("worker_stub_noop", worker=worker_name)  # type: ignore[no-any-return]

        _stub.__name__ = f"stub_{worker_name}"
        return _stub
