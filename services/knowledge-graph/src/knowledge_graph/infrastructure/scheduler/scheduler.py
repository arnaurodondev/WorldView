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

    Workers registered:
      - worker_13j_enrichment_sweep: daily at 02:00 UTC (CronTrigger)
      - All others: interval-based (seconds)
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

        # F-X15 (PLAN-0073 fix): iterate ALL workers and close any that expose
        # ``aclose()`` so httpx pools, MarketDataClient, and description LLM
        # clients release sockets cleanly at service shutdown.  Previously only
        # the provisional worker was closed, which leaked Worker 13J's
        # MarketDataClient TCP pool on every restart.
        for worker_name, worker in self._workers.items():
            if worker is None:
                continue
            if hasattr(worker, "aclose"):
                try:
                    await worker.aclose()
                except Exception:
                    logger.warning(  # type: ignore[no-any-return]
                        "scheduler_worker_aclose_failed",
                        worker=worker_name,
                        exc_info=True,
                    )

        # F-X15 (PLAN-0073 fix): explicitly close auxiliary clients owned by
        # Worker 13J that are not exposed through the worker's ``aclose`` (the
        # description LLM client + MarketDataClient).  Stored on
        # ``self._aux_aclose`` by ``_add_structured_enrichment_worker``.
        for label, closer in getattr(self, "_aux_aclose", []):
            try:
                await closer()
            except Exception:
                logger.warning(  # type: ignore[no-any-return]
                    "scheduler_aux_aclose_failed",
                    component=label,
                    exc_info=True,
                )

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
            ("provisional_enrichment", s.worker_provisional_enrichment_interval_s, "worker_13e_provisional"),
            ("embedding_refresh", s.worker_embedding_refresh_interval_s, "worker_13f_embedding"),
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

        # Worker 13J: nightly structured enrichment sweep at 02:00 UTC (PRD-0073).
        fn_13j = self._resolve_job("structured_enrichment")
        self._scheduler.add_job(
            fn_13j,
            "cron",
            hour=2,
            minute=0,
            id="worker_13j_enrichment_sweep",
            max_instances=1,
            coalesce=True,
        )

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

    # Worker 13J: structured enrichment (PRD-0073). Built unconditionally —
    # uses NullDescriptionAdapter when no LLM is configured.
    _add_structured_enrichment_worker(workers, settings, session_factory, valkey_client)

    if llm_client is not None:
        description_client = _build_description_client(settings, valkey_client)
        embed_model = settings.embedding_model_id
        embed_batch_limit = settings.worker_embedding_batch_limit
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
            batch_limit=embed_batch_limit,
        )
        workers.update(
            {
                "summary_generation": SummaryWorker(
                    session_factory=session_factory,
                    llm_client=llm_client,
                    force_regen_batch_size=settings.summary_worker_force_regen_batch_size,
                ),
                "definition_embedding": def_worker,
                "narrative_embedding": NarrativeRefreshWorker(
                    session_factory,
                    llm_client,
                    embedding_model_id=embed_model,
                    batch_limit=embed_batch_limit,
                ),
                "fundamentals_embedding": FundamentalsRefreshWorker(
                    session_factory,
                    llm_client,
                    market_data_base_url=getattr(settings, "market_data_base_url", "http://market-data:8003"),
                    embedding_model_id=embed_model,
                    concurrency=settings.worker_fundamentals_concurrency,
                    # F-015: pass the RS256 private key when configured so the worker
                    # issues a cryptographically verifiable JWT for market-data calls.
                    # Falls back to HS256 dev token when the key is absent.
                    internal_jwt_private_key_pem=getattr(
                        settings, "internal_jwt_private_key", type("_", (), {"get_secret_value": lambda _: ""})()
                    ).get_secret_value(),
                ),
                "provisional_enrichment": ProvisionalEnrichmentWorker(
                    session_factory,
                    llm_client,
                    embedding_model_id=embed_model,
                    usage_logger=usage_logger,
                    batch_limit=settings.worker_provisional_enrichment_batch_size,
                    max_retries=settings.worker_provisional_enrichment_max_retries,
                    concurrency=settings.worker_provisional_enrichment_concurrency,
                    # PLAN-0072 T-72-1-01: Layer 2 noise classifier reuses the
                    # existing DeepInfra API key; when empty Layer 2 is skipped
                    # (fail-open) and rows go directly to Layer 3 extraction.
                    noise_classifier_api_key=settings.deepinfra_api_key.get_secret_value(),  # DEF-005
                    noise_classifier_api_base_url=settings.deepinfra_extraction_base_url,
                    # Wave A-4 / DEF-033: exponential backoff so a transient LLM
                    # outage does not cause every retry sweep to re-hit the API.
                    base_retry_minutes=settings.provisional_enrichment_base_retry_minutes,
                    max_retry_minutes=settings.provisional_enrichment_max_retry_minutes,
                ),
                "embedding_refresh": EmbeddingRefreshWorker(
                    session_factory,
                    llm_client,
                    embedding_model_id=embed_model,
                    batch_limit=embed_batch_limit,
                    # Wave A-2 / DEF-022: persist a stable, configurable model
                    # id alongside each embedding so the HNSW index is auditable
                    # for mixed-model drift even when ``embed_model`` differs
                    # by environment (Ollama tag vs. DeepInfra slug).
                    summary_embedding_model_id=settings.summary_embedding_model_id,
                ),
            },
        )

    return workers


def build_market_data_signer(settings: Settings) -> Any:
    """Return a zero-arg callable that signs a fresh internal JWT per call.

    F-A02 / F-X06 / F-S02 (PLAN-0073 fix): every call to
    ``MarketDataClient.lookup`` / ``on_demand_profile`` needs an
    ``X-Internal-JWT`` because S3 enforces ``require_internal_jwt`` on the
    enrichment endpoints.  Mirrors :func:`fundamentals_refresh._system_jwt_headers`
    but returns the raw token (the ``MarketDataClient`` builds the header).

    Falls back to an HS256 dev token when ``internal_jwt_private_key`` is
    empty — this is only accepted by S3 when
    ``MARKET_DATA_INTERNAL_JWT_SKIP_VERIFICATION=true`` (dev/test only).
    """
    import time

    import jwt

    # Same dev-only HS256 secret as ``fundamentals_refresh`` so behaviour is
    # consistent across all worker → market-data calls in dev.
    _internal_jwt_dev_key = "dev-skip-verification-key-for-kg-structured-enrichment"

    private_key_pem = settings.internal_jwt_private_key.get_secret_value()

    # F-P2-06 (PLAN-0073): startup-time warning so the dev-key fallback shows
    # up in the bootstrap log even if no requests are made.  The per-call
    # warning below catches the prod case where the bootstrap log has rolled.
    if not private_key_pem:
        logger.warning(  # type: ignore[no-any-return]
            "structured_enrichment_no_rs256_key",
            message="KNOWLEDGE_GRAPH_INTERNAL_JWT_PRIVATE_KEY is empty; "
            "MarketDataClient will sign HS256 dev tokens — production "
            "S3 will return 401 unless MARKET_DATA_INTERNAL_JWT_SKIP_VERIFICATION=true",
        )

    # Closure-local counter so we can rate-limit the per-call warning to one
    # log per N tokens — full burst-firing would drown out other logs.
    _dev_key_warn_state = {"count": 0}
    _dev_key_warn_every = 100

    def _sign() -> str:
        now = int(time.time())
        payload = {
            "iss": "worldview-gateway",
            "sub": "system:kg-structured-enrichment",
            "user_id": "00000000-0000-0000-0000-000000000000",
            "tenant_id": "00000000-0000-0000-0000-000000000000",
            "role": "system",
            "iat": now,
            # Short TTL keeps the blast radius small if a token is somehow
            # leaked.  The signer issues a fresh token on every request so the
            # 5-minute window is more than enough for one HTTP call.
            "exp": now + 300,
        }
        if private_key_pem:
            from cryptography.hazmat.primitives.serialization import load_pem_private_key

            private_key = load_pem_private_key(private_key_pem.encode(), password=None)
            return jwt.encode(payload, private_key, algorithm="RS256")  # type: ignore[no-any-return]

        # F-P2-06: warn periodically (not once) so a long-running consumer
        # whose bootstrap log has rolled away still surfaces the dev-key
        # state.  Every Nth token avoids drowning the rest of the logs.
        _dev_key_warn_state["count"] += 1
        if _dev_key_warn_state["count"] % _dev_key_warn_every == 1:
            logger.warning(  # type: ignore[no-any-return]
                "structured_enrichment_signing_with_dev_key",
                message="MarketDataClient is signing with the HS256 dev key; "
                "set KNOWLEDGE_GRAPH_INTERNAL_JWT_PRIVATE_KEY for production.",
                tokens_signed_with_dev_key=_dev_key_warn_state["count"],
            )
        return jwt.encode(payload, _internal_jwt_dev_key, algorithm="HS256")  # type: ignore[no-any-return]

    return _sign


class _EntityDirtiedProducerAdapter:
    """Adapter: bridges DirectProducerProtocol → ConfluentDirectProducer.

    F-A01 / F-X02 (PLAN-0073 fix): the structured-enrichment use case calls
    ``produce_entity_dirtied(entity_id, reason)`` on a high-level port.  The
    only Kafka producer in this service is the lower-level
    :class:`ConfluentDirectProducer` which exposes ``produce_bytes(topic, key,
    value)``.  This adapter glues the two together by serialising the event
    via the same helper used elsewhere in S7
    (``provisional_enrichment_core._build_dirtied_event``) so the wire format
    matches every other producer (Confluent Avro magic byte + framing).
    """

    def __init__(self, direct_producer: Any, topic: str) -> None:
        self._dp = direct_producer
        self._topic = topic

    def produce_entity_dirtied(self, *, entity_id: Any, reason: str) -> None:
        # Lazy import keeps ``messaging.*`` and the heavy serializer cost out
        # of the application/domain import paths; this code path runs only at
        # most once per entity so the import overhead is irrelevant.
        from knowledge_graph.infrastructure.workers.provisional_enrichment_core import (
            _build_dirtied_event,
        )

        value = _build_dirtied_event(entity_id, dirty_reason=reason)
        self._dp.produce_bytes(
            topic=self._topic,
            key=str(entity_id).encode(),
            value=value,
        )


def _build_entity_dirtied_producer(settings: Settings) -> tuple[Any | None, Any | None]:
    """Construct a DirectProducerProtocol adapter for entity.dirtied.v1.

    Returns ``(adapter, raw_producer)`` where ``raw_producer`` is the
    confluent-kafka ``Producer`` instance — exposed so the caller can flush
    it on shutdown.  ``(None, None)`` if confluent_kafka is not importable
    (we still log a warning so operators see why entity.dirtied.v1 is silent).
    """
    try:
        from confluent_kafka import Producer  # type: ignore[import-untyped]

        from knowledge_graph.infrastructure.messaging.direct_producer import ConfluentDirectProducer
    except Exception:
        logger.warning(  # type: ignore[no-any-return]
            "structured_enrichment_direct_producer_unavailable",
            message="confluent_kafka not importable; entity.dirtied.v1 will be silently skipped",
            exc_info=True,
        )
        return None, None

    raw = Producer({"bootstrap.servers": settings.kafka_bootstrap_servers})
    adapter = _EntityDirtiedProducerAdapter(
        ConfluentDirectProducer(raw),
        topic=settings.kafka_topic_entity_dirtied,
    )
    return adapter, raw


def _add_structured_enrichment_worker(
    workers: dict[str, Any],
    settings: Settings,
    session_factory: Any,
    valkey_client: Any | None,
) -> None:
    """Instantiate StructuredEnrichmentWorker (Worker 13J) and add to workers dict.

    Wires the cascade dependencies: per-request JWT signer (F-A02), the
    entity.dirtied.v1 producer adapter (F-A01), and the description LLM
    client.  Each non-Worker resource that owns a network handle is also
    registered on ``self._aux_aclose`` so :meth:`KnowledgeGraphScheduler.stop`
    closes it cleanly (F-X15).
    """
    from knowledge_graph.application.use_cases.structured_enrichment import (
        StructuredEnrichmentUseCase,
    )
    from knowledge_graph.infrastructure.http.market_data_client import MarketDataClient
    from knowledge_graph.infrastructure.intelligence_db.adapters.entity_enrichment_adapter import (
        EntityEnrichmentAdapter,
    )
    from knowledge_graph.infrastructure.workers.structured_enrichment_worker import (
        StructuredEnrichmentWorker,
    )

    enrichment_adapter = EntityEnrichmentAdapter(session_factory)

    # F-A02 / F-X06 / F-S02: per-request RS256 signer (HS256 fallback in dev).
    signer = build_market_data_signer(settings)
    market_data_client = MarketDataClient(
        base_url=settings.market_data_internal_url,
        internal_jwt=signer,
    )
    description_client = _build_description_client(settings, valkey_client)

    # F-A01 / F-X02: wire the entity.dirtied.v1 producer adapter.
    direct_producer, raw_producer = _build_entity_dirtied_producer(settings)
    if direct_producer is None:
        logger.warning(  # type: ignore[no-any-return]
            "structured_enrichment_no_producer",
            message="entity.dirtied.v1 producer unavailable; embedding refresh chain "
            "for Worker 13J will rely solely on the watermark-based fallback (PRD §13.7)",
        )

    use_case = StructuredEnrichmentUseCase(
        enrichment_adapter=enrichment_adapter,
        market_data_client=market_data_client,
        description_client=description_client,
        session_factory=session_factory,
        direct_producer=direct_producer,
    )
    workers["structured_enrichment"] = StructuredEnrichmentWorker(
        enrichment_adapter=enrichment_adapter,
        use_case=use_case,
        session_factory=session_factory,
    )

    # F-X15 (PLAN-0073 fix): register cleanup hooks for the resources owned
    # outside the worker proper (the worker itself has no aclose).  These run
    # in :meth:`KnowledgeGraphScheduler.stop` after the consumer task is gone.
    aux: list[tuple[str, Any]] = []
    aux.append(("structured_enrichment_market_data_client", market_data_client.aclose))
    if hasattr(description_client, "aclose"):
        aux.append(("structured_enrichment_description_client", description_client.aclose))
    if raw_producer is not None:

        async def _flush_producer() -> None:
            # ``flush`` is sync on confluent_kafka.Producer; run in a thread so
            # it does not block the asyncio loop on shutdown.
            await asyncio.get_event_loop().run_in_executor(None, raw_producer.flush, 5.0)

        aux.append(("structured_enrichment_direct_producer", _flush_producer))
    workers.setdefault("_aux_aclose", []).extend(aux)


def _build_description_client(settings: Settings, valkey_client: Any | None = None) -> Any:
    """Construct the EntityDescriptionClient based on ``KNOWLEDGE_GRAPH_DESCRIPTION_PROVIDER``.

    - ``"deepinfra"`` → ``DeepInfraDescriptionAdapter`` (Qwen3-235B-A22B primary, Qwen3-32B fallback).
    - ``"gemini"``    → ``GeminiDescriptionAdapter`` (gemini-3.1-flash-lite).
    - anything else  → ``NullDescriptionAdapter`` (no external calls; fallback template always used).

    Args:
    ----
        settings:      Service configuration.
        valkey_client:  ValkeyClient for atomic cost tracking (G-005 fix).

    """
    import asyncio

    from ml_clients.description_client import NullDescriptionAdapter  # type: ignore[import-untyped]

    provider = settings.description_provider.lower()

    if provider == "deepinfra":
        api_key = settings.deepinfra_api_key.get_secret_value()  # DEF-005
        if not api_key:
            logger.warning(  # type: ignore[no-any-return]
                "description_client_deepinfra_key_missing",
                message="KNOWLEDGE_GRAPH_DEEPINFRA_API_KEY is empty; falling back to NullDescriptionAdapter",
            )
            return NullDescriptionAdapter()

        from ml_clients.adapters.deepinfra_description import (
            DeepInfraDescriptionAdapter,  # type: ignore[import-untyped]
        )

        semaphore = asyncio.Semaphore(settings.description_deepinfra_concurrency)
        return DeepInfraDescriptionAdapter(
            api_key=api_key,
            primary_model_id=settings.description_deepinfra_model_id,
            fallback_model_id=settings.description_deepinfra_fallback_model_id,
            semaphore=semaphore,
            cost_tracker=valkey_client,
            max_monthly_usd=settings.description_max_monthly_usd,
        )

    if provider == "gemini":
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

    return NullDescriptionAdapter()
