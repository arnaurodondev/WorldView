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

from knowledge_graph.infrastructure.metrics.prometheus import s7_worker_crash_total
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from ml_clients.usage_log import LlmUsageLogProtocol  # type: ignore[import-untyped]

    from knowledge_graph.config import Settings
    from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient

logger = get_logger(__name__)  # type: ignore[no-any-return]


class KnowledgeGraphScheduler:
    """Co-topology: 8 APScheduler worker slots + Kafka consumer task.

    All work runs in the same asyncio event loop as FastAPI.

    Args:
    ----
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
        ----
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
        """Register all APScheduler jobs with configured intervals."""
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
            ("age_sync", s.worker_age_sync_interval_s, "worker_13f_age_sync"),
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

        # Workers 13D-6, 13D-7, 13D-8 have been migrated to Kafka consumers.
        # They no longer run as cron-scheduled APScheduler jobs.

    def _resolve_job(self, name: str) -> Any:
        """Return the real worker.run if available, otherwise a no-op stub."""
        worker = self._workers.get(name)
        if worker is not None and hasattr(worker, "run"):
            return self._wrap_worker(name, worker.run)
        return self._make_stub(name)

    def _wrap_worker(self, name: str, fn: Any) -> Any:
        """Wrap a worker.run coroutine function with crash instrumentation.

        On unhandled exception: increments ``s7_worker_crash_total``, logs
        ``kg_worker_crashed`` at ERROR, then re-raises so APScheduler can
        record the failure and apply coalesce/retry logic.
        """

        async def _instrumented() -> None:
            try:
                await fn()
            except Exception:
                s7_worker_crash_total.labels(worker=name).inc()
                logger.error(  # type: ignore[no-any-return]
                    "kg_worker_crashed",
                    worker=name,
                    exc_info=True,
                )
                raise

        _instrumented.__name__ = f"instrumented_{name}"
        return _instrumented

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
    valkey_client: Any | None = None,
    usage_logger: LlmUsageLogProtocol | None = None,
) -> dict[str, Any]:
    """Instantiate all workers from service dependencies.

    Args:
    ----
        settings:        Service settings.
        session_factory: intelligence_db async_sessionmaker.
        llm_client:      FallbackChainClient (None → workers use stubs).
        valkey_client:   ValkeyClient for watermark storage (None → age_sync stub).
        usage_logger:    PLAN-0057 A-5 / F-CRIT-03 — fire-and-forget LLM cost
                         logger threaded into ``DefinitionRefreshWorker`` and
                         ``ProvisionalEnrichmentWorker``.  When None the
                         workers stay backward-compatible (no logging).

    Returns:
    -------
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

    if valkey_client is not None:
        from knowledge_graph.infrastructure.workers.age_sync_worker import AgeSyncWorker

        workers["age_sync"] = AgeSyncWorker(session_factory, valkey_client, settings)

    if llm_client is not None:
        description_client = _build_description_client(settings, valkey_client)
        embed_model = settings.embedding_model_id
        # PLAN-0057 A-5 / F-CRIT-03: thread the cost logger into workers that
        # explicitly accept it.  ``DefinitionRefreshWorker`` already exposes
        # ``usage_logger`` (used by GeminiDescriptionAdapter); the new
        # ``ProvisionalEnrichmentWorker`` accepts the logger and forwards it
        # into its FallbackChainClient calls (see provisional_enrichment.py).
        def_worker = DefinitionRefreshWorker(
            session_factory,
            llm_client,
            description_client,
            usage_logger=usage_logger,
            embedding_model_id=embed_model,
        )
        workers.update(
            {
                "summary_generation": SummaryWorker(session_factory, llm_client),
                "definition_embedding": def_worker,
                "narrative_embedding": NarrativeRefreshWorker(
                    session_factory,
                    llm_client,
                    embedding_model_id=embed_model,
                ),
                "fundamentals_embedding": FundamentalsRefreshWorker(
                    session_factory,
                    llm_client,
                    market_data_base_url=getattr(settings, "market_data_base_url", "http://market-data:8003"),
                    embedding_model_id=embed_model,
                ),
                "provisional_enrichment": ProvisionalEnrichmentWorker(
                    session_factory,
                    llm_client,
                    embedding_model_id=embed_model,
                    usage_logger=usage_logger,
                ),
                "worker_13e_provisional": ProvisionalEnrichmentWorker(
                    session_factory,
                    llm_client,
                    embedding_model_id=embed_model,
                    usage_logger=usage_logger,
                ),
                "embedding_refresh": EmbeddingRefreshWorker(
                    session_factory,
                    llm_client,
                    embedding_model_id=embed_model,
                ),
            },
        )

    return workers


def _build_description_client(settings: Settings, valkey_client: Any | None = None) -> Any:
    """Construct the EntityDescriptionClient based on ``KNOWLEDGE_GRAPH_DESCRIPTION_PROVIDER``.

    - ``"gemini"`` → ``GeminiDescriptionAdapter`` with the configured API key and cost cap.
    - anything else → ``NullDescriptionAdapter`` (no external calls; fallback template always used).

    Args:
    ----
        settings:      Service configuration.
        valkey_client:  ValkeyClient for atomic cost tracking (G-005 fix).
                        Passed as ``cost_tracker`` to ``GeminiDescriptionAdapter``.

    """
    import asyncio

    from ml_clients.description_client import NullDescriptionAdapter  # type: ignore[import-untyped]

    if settings.description_provider.lower() != "gemini":
        return NullDescriptionAdapter()

    api_key = settings.gemini_api_key.get_secret_value()
    if not api_key:
        logger.warning(  # type: ignore[no-any-return]
            "description_client_gemini_key_missing",
            message="KNOWLEDGE_GRAPH_GEMINI_API_KEY is empty; falling back to NullDescriptionAdapter",
        )
        return NullDescriptionAdapter()

    from ml_clients.adapters.gemini_description import GeminiDescriptionAdapter  # type: ignore[import-untyped]

    semaphore = asyncio.Semaphore(settings.description_gemini_concurrency)
    return GeminiDescriptionAdapter(
        api_key=api_key,
        semaphore=semaphore,
        cost_tracker=valkey_client,
        max_monthly_usd=settings.description_max_monthly_usd,
    )
