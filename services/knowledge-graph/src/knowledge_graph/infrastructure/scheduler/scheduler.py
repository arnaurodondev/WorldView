"""APScheduler + Kafka co-topology (PRD §6.7 Block 13).

:class:`KnowledgeGraphScheduler` starts an :class:`~apscheduler.schedulers.asyncio.AsyncIOScheduler`
with 8 real worker jobs and a Kafka consumer coroutine in the **same**
asyncio event loop.

Graceful SIGTERM shutdown: ``stop()`` cancels the consumer task and
shuts the scheduler down cleanly — called from the FastAPI lifespan
``finally`` block.
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
    from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient

logger = get_logger(__name__)  # type: ignore[no-any-return]


class KnowledgeGraphScheduler:
    """Co-topology: 8 APScheduler worker slots + Kafka consumer task.

    All work runs in the same asyncio event loop as FastAPI.

    Args:
        settings: Service configuration (worker interval settings).
        workers:  Optional dict of worker instances; if None, stubs are used.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        workers: dict[str, Any] | None = None,
    ) -> None:
        self._settings = settings
        self._workers = workers or {}
        self._scheduler = AsyncIOScheduler()
        self._consumer_task: asyncio.Task[Any] | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self, consumer_coro: Coroutine[Any, Any, None]) -> None:
        """Start the scheduler and the consumer coroutine.

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
    # Job registration
    # ------------------------------------------------------------------

    def _register_jobs(self) -> None:
        """Register all 8 APScheduler jobs with configured intervals."""
        s = self._settings
        jobs: list[tuple[str, int, str]] = [
            ("confidence_recompute", s.worker_confidence_interval_s, "worker_13a_confidence"),
            ("contradiction_batch", s.worker_contradiction_interval_s, "worker_13b_contradiction"),
            ("summary_generation", s.worker_summary_interval_s, "worker_13c_summary"),
            ("definition_embedding", s.worker_definition_refresh_interval_s, "worker_13d1_definition"),
            ("narrative_embedding", s.worker_narrative_refresh_interval_s, "worker_13d2_narrative"),
            ("fundamentals_embedding", s.worker_fundamentals_refresh_interval_s, "worker_13d3_fundamentals"),
            ("provisional_enrichment", s.worker_embedding_refresh_interval_s, "worker_13e_provisional"),
            ("partition_management", s.worker_partition_interval_s, "worker_13f_partition"),
        ]
        for name, interval, job_id in jobs:
            fn = self._resolve_job(name)
            self._scheduler.add_job(
                fn,
                "interval",
                seconds=interval,
                id=job_id,
                max_instances=1,
                coalesce=True,
            )

    def _resolve_job(self, name: str) -> Any:
        """Return the real worker.run if available, otherwise a no-op stub."""
        worker = self._workers.get(name)
        if worker is not None and hasattr(worker, "run"):
            return worker.run
        return self._make_stub(name)

    @staticmethod
    def _make_stub(worker_name: str) -> Any:
        """Return an async stub coroutine function for *worker_name*."""

        async def _stub() -> None:
            logger.debug("worker_stub_noop", worker=worker_name)  # type: ignore[no-any-return]

        _stub.__name__ = f"stub_{worker_name}"
        return _stub


# ---------------------------------------------------------------------------
# Factory: build all workers from settings + dependencies
# ---------------------------------------------------------------------------


def build_workers(
    settings: Settings,
    session_factory: Any,
    llm_client: FallbackChainClient | None = None,
) -> dict[str, Any]:
    """Instantiate all 8 workers from service dependencies.

    Args:
        settings:        Service settings.
        session_factory: intelligence_db async_sessionmaker.
        llm_client:      FallbackChainClient (None → workers use stubs).

    Returns:
        Dict mapping scheduler job names to worker instances.
    """
    from knowledge_graph.infrastructure.workers.confidence import ConfidenceWorker
    from knowledge_graph.infrastructure.workers.contradiction_batch import ContradictionBatchWorker
    from knowledge_graph.infrastructure.workers.definition_refresh import DefinitionRefreshWorker
    from knowledge_graph.infrastructure.workers.embedding_refresh import EmbeddingRefreshWorker
    from knowledge_graph.infrastructure.workers.fundamentals_refresh import FundamentalsRefreshWorker
    from knowledge_graph.infrastructure.workers.narrative_refresh import NarrativeRefreshWorker
    from knowledge_graph.infrastructure.workers.partitions import MonthlyPartitionWorker
    from knowledge_graph.infrastructure.workers.provisional_enrichment import ProvisionalEnrichmentWorker
    from knowledge_graph.infrastructure.workers.summary import SummaryWorker

    workers: dict[str, Any] = {
        "confidence_recompute": ConfidenceWorker(session_factory, settings),
        "contradiction_batch": ContradictionBatchWorker(session_factory),
        "partition_management": MonthlyPartitionWorker(session_factory),
    }

    if llm_client is not None:
        def_worker = DefinitionRefreshWorker(session_factory, llm_client)
        workers.update(
            {
                "summary_generation": SummaryWorker(session_factory, llm_client),
                "definition_embedding": def_worker,
                "narrative_embedding": NarrativeRefreshWorker(session_factory, llm_client),
                "fundamentals_embedding": FundamentalsRefreshWorker(
                    session_factory,
                    llm_client,
                    market_data_base_url=getattr(settings, "market_data_base_url", "http://market-data:8003"),
                ),
                "provisional_enrichment": ProvisionalEnrichmentWorker(session_factory, llm_client),
                "worker_13e_provisional": ProvisionalEnrichmentWorker(session_factory, llm_client),
                "embedding_refresh": EmbeddingRefreshWorker(session_factory, llm_client),
            }
        )

    return workers
