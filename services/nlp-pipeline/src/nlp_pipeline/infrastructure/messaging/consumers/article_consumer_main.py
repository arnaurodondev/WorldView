"""Standalone article processing consumer entry point for the NLP Pipeline (S6).

Runs as an independent process (R22) with its own DB sessions, ML clients,
Valkey cache, and signal handling.  Orchestrates Blocks 3-10 of the pipeline.

Run with::

    python -m nlp_pipeline.infrastructure.messaging.consumers.article_consumer_main
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import sys
from typing import Any

from observability import (  # type: ignore[import-untyped]
    configure_logging,
    get_logger,
    log_runtime_banner,
    start_metrics_server,
)

logger = get_logger(__name__)  # type: ignore[no-any-return]


async def main() -> None:
    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
    from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]
    from nlp_pipeline.config import Settings
    from nlp_pipeline.infrastructure.backpressure.controller import BackpressureController
    from nlp_pipeline.infrastructure.intelligence_db.session import (
        _build_intelligence_factories,
    )
    from nlp_pipeline.infrastructure.messaging.consumers.article_consumer import (
        ArticleProcessingConsumer,
    )
    from nlp_pipeline.infrastructure.nlp_db.session import _build_nlp_factories
    from nlp_pipeline.infrastructure.valkey.watchlist_cache import WatchlistCache

    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name="nlp-pipeline-article-consumer",
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("nlp_pipeline.article_consumer_main")  # type: ignore[no-any-return]
    log.info("article_consumer_starting", service="nlp-pipeline")

    # Phase 3 worker-metrics rollout — expose Prometheus /metrics on a
    # dedicated port so the worker's counters/gauges become scrape-able.
    metrics_handle = start_metrics_server(
        service_name="nlp-pipeline-article-consumer",
        port=int(os.environ.get("METRICS_PORT", "9100")),
    )

    stop_event = asyncio.Event()

    def _handle_signal(sig: int) -> None:
        log.info("shutdown_signal_received", signal=sig)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)

    # Databases — R23 dual factories
    nlp_engine, _nlp_read_engine, nlp_sf, _nlp_read_sf = _build_nlp_factories(settings)
    intel_engine, _intel_read_engine, intel_sf, _intel_read_sf = _build_intelligence_factories(settings)

    # Valkey + WatchlistCache
    valkey = create_valkey_client_from_url(settings.valkey_url)
    watchlist_cache = WatchlistCache(
        client=valkey._redis,  # type: ignore[attr-defined]
        key=settings.valkey_watchlist_key,
    )

    # ML clients
    from ml_clients.adapters.ollama_extraction import (
        OllamaExtractionAdapter,  # type: ignore[import-not-found]
    )

    ml_sem = asyncio.Semaphore(settings.embedding_max_concurrent)

    # Task #14: deep extraction gets its OWN semaphore sized to the per-replica
    # article concurrency.  The shared ``ml_sem`` (embedding_max_concurrent=4) would
    # otherwise cap concurrent DeepInfra extraction calls at 4 even when N=16 article
    # handlers are in flight, re-serialising the very latency we are trying to
    # overlap.  Embedding/NER keep the small shared pool because they are short and
    # CPU/GPU-bound; extraction is long and network-bound, so it needs its own width.
    extraction_sem = asyncio.Semaphore(settings.article_consumer_concurrency)

    # GLiNER: use HTTP adapter when gliner_base_url is configured (containerised),
    # otherwise fall back to in-process local adapter.
    if settings.gliner_base_url:
        from ml_clients.adapters.gliner_http import GLiNERHTTPAdapter  # type: ignore[import-not-found]

        ner_client = GLiNERHTTPAdapter(
            base_url=settings.gliner_base_url,
            semaphore=asyncio.Semaphore(settings.embedding_max_concurrent),
            # Per-request timeout must comfortably exceed the GLiNER server's
            # batched tail latency under concurrent load. Measured live at
            # 22-35s per serial forward pass while CPU-saturated; with a deep
            # micro-batch queue the tail request stacks behind several of those,
            # so the old 60s default was being tripped (spurious retries). See
            # NlpPipelineSettings.gliner_request_timeout_s for the full rationale.
            timeout_seconds=settings.gliner_request_timeout_s,
        )
        log.info("gliner_http_adapter_selected", base_url=settings.gliner_base_url)
    else:
        from ml_clients.adapters.gliner_local import GLiNERLocalAdapter  # type: ignore[import-not-found]

        ner_client = GLiNERLocalAdapter(  # type: ignore[assignment]
            model_path=settings.ner_model_id,
            semaphore=asyncio.Semaphore(1),
        )
        log.info("gliner_local_adapter_selected", model_path=settings.ner_model_id)

    # Embedding client — provider selected via NLP_PIPELINE_EMBEDDING_PROVIDER.
    # All providers produce 1024-dim vectors compatible with the pgvector schema.
    # WARNING: switching providers requires re-embedding all stored chunks.
    _embedding_provider = settings.embedding_provider.lower()
    _embedding_api_key = settings.embedding_api_key.get_secret_value()  # DEF-019
    _jina_api_key = settings.jina_api_key.get_secret_value()  # DEF-019
    if _embedding_provider == "deepinfra" and _embedding_api_key:
        from ml_clients.adapters.deepinfra_embedding import (  # type: ignore[import-not-found]
            DeepInfraEmbeddingAdapter,
        )

        embedding_client: Any = DeepInfraEmbeddingAdapter(
            api_key=_embedding_api_key,
            model_id=settings.embedding_api_model_id,
            base_url=settings.embedding_api_base_url,
        )
        log.info(
            "embedding_deepinfra_adapter_selected",
            model_id=settings.embedding_api_model_id,
            base_url=settings.embedding_api_base_url,
        )
    elif _embedding_provider == "jina" and _jina_api_key:
        from ml_clients.adapters.jina_embedding import (  # type: ignore[import-not-found]
            JinaEmbeddingAdapter,
        )

        embedding_client = JinaEmbeddingAdapter(  # type: ignore[assignment]
            api_key=_jina_api_key,
        )
        log.info("embedding_jina_adapter_selected")
    else:
        if _embedding_provider not in ("ollama", ""):
            log.warning(
                "embedding_provider_key_missing_fallback_to_ollama",
                provider=_embedding_provider,
            )
        from ml_clients.adapters.ollama_embedding import (  # type: ignore[import-not-found]
            OllamaEmbeddingAdapter,
        )

        embedding_client = OllamaEmbeddingAdapter(  # type: ignore[assignment]
            base_url=settings.ollama_base_url,
            model_id=settings.embedding_model_id,
            semaphore=ml_sem,
        )
        log.info("embedding_ollama_adapter_selected", model_id=settings.embedding_model_id)
    # Deep extraction: use DeepInfra (external API) when extraction_api_key is configured.
    # qwen2.5:7b-instruct is too large for CPU self-hosting (7B model); DeepInfra hosts it on GPUs.
    # Falls back to OllamaExtractionAdapter (which will fail gracefully) if no API key.
    _extraction_api_key = settings.extraction_api_key.get_secret_value()  # DEF-019
    if _extraction_api_key:
        from ml_clients.adapters.deepseek_extraction import (  # type: ignore[import-not-found]
            DeepSeekExtractionAdapter,
        )

        extraction_client = DeepSeekExtractionAdapter(  # type: ignore[assignment]
            api_key=_extraction_api_key,
            model_id=settings.extraction_api_model_id,
            base_url=settings.extraction_api_base_url,
            # Task #14: dedicated wide semaphore + sized httpx pool so N concurrent
            # article handlers each get an extraction slot without queuing.
            semaphore=extraction_sem,
            max_connections=settings.deepinfra_max_connections,
            max_keepalive_connections=settings.deepinfra_max_keepalive,
        )
        log.info(
            "extraction_deepinfra_adapter_selected",
            model_id=settings.extraction_api_model_id,
            base_url=settings.extraction_api_base_url,
        )
    else:
        extraction_client = OllamaExtractionAdapter(  # type: ignore[assignment]
            base_url=settings.ollama_base_url,
            model_id=settings.extraction_model_id,
            semaphore=ml_sem,
        )
        log.info("extraction_ollama_adapter_selected", model_id=settings.extraction_model_id)

    # Backpressure controller
    bp = BackpressureController(
        max_depth=settings.max_ollama_queue_depth,
        resume_depth=settings.resume_ollama_queue_depth,
    )

    # Consumer
    article_config = ConsumerConfig(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_consumer_group,
        topics=[settings.topic_article_stored],
        # bge-large CPU inference can take 2-5s per article; increase poll interval
        # to 30 minutes to prevent consumer from leaving the group mid-batch.
        max_poll_interval_ms=1_800_000,
        # DeepInfra deep-tier extraction (Qwen3-235B-A22B) has a bursty latency
        # tail; the default 45s watchdog fires before the extraction wall-clock cap,
        # causing a dead-letter loop (BP-324).  Sourced from config (default 450s,
        # paired with the 150s extraction cap) and env-overridable via
        # NLP_PIPELINE_MESSAGE_PROCESSING_TIMEOUT_S to stop dead-letter bleed.
        message_processing_timeout_s=settings.message_processing_timeout_s,
    )
    # Optional: configure MinIO storage (article downloads + chunk text upload)
    _object_storage = None
    try:
        from storage.factory import build_object_storage  # type: ignore[import-untyped]
        from storage.settings import StorageSettings  # type: ignore[import-untyped]

        storage_settings = StorageSettings(
            endpoint=settings.storage_endpoint,
            access_key=settings.storage_access_key,
            secret_key=settings.storage_secret_key,
        )
        _object_storage = build_object_storage(settings=storage_settings)
    except Exception:
        log.warning("minio_not_configured_article_downloads_disabled", exc_info=True)

    _chunk_text_store = None
    if _object_storage is not None:
        try:
            from nlp_pipeline.infrastructure.storage.chunk_text_store import MinIOChunkTextStore

            _chunk_text_store = MinIOChunkTextStore(_object_storage, settings.chunk_bucket)
            log.info("chunk_text_store_configured", bucket=settings.chunk_bucket)
        except Exception:
            log.warning("chunk_text_store_init_failed", exc_info=True)

    # PLAN-0057 A-5 / F-CRIT-03: wire a session-scoped NLP usage logger so each
    # deep-extraction LLM call appends a row to nlp_db.llm_usage_log.  Without
    # this the table was permanently empty despite tens of MEDIUM/DEEP-tier
    # extractions per cycle.
    from nlp_pipeline.infrastructure.nlp_db.usage_log_factory import (
        SessionScopedNlpUsageLogger,
    )

    # PLAN-0111 C-6: construct the learned router ONLY when shadow/live and a
    # DeepInfra key is present (it embeds headlines via EmbeddingGemma using the
    # shared NLP_PIPELINE_EXTRACTION_API_KEY). The artifact (joblib + meta) is
    # committed into the package, so construction loads it from disk with no
    # network. If the key is missing in a shadow-enabled env we log and leave the
    # router off rather than crash — shadow is non-critical.
    learned_router = None
    if settings.learned_router_mode != "off":
        if _extraction_api_key:
            from ml_clients.adapters.embeddinggemma_router import (  # type: ignore[import-not-found]
                EmbeddingGemmaRouterAdapter,
            )

            from nlp_pipeline.application.blocks.learned_routing import LearnedRouter

            router_embedder = EmbeddingGemmaRouterAdapter(
                api_key=_extraction_api_key,
                # 768d head — matches the exported artifact's embedding_dims.
                default_dimensions=768,
                # Generous timeout; the adapter wraps it in httpx.Timeout (BP-235).
                timeout=30.0,
            )

            # PLAN-0111 C-7: the LLM cascade tiebreaker, wired ONLY when
            # NLP_PIPELINE_LEARNED_ROUTER_CASCADE is on. It REUSES the existing
            # Llama-3.1-8B relevance scorer (same model id + prompt as
            # ArticleRelevanceScoringWorker) — no new model. It fires only on the
            # in-band slice inside LearnedRouter.propose.
            cascade_scorer = None
            if settings.learned_router_cascade:
                from nlp_pipeline.application.blocks.relevance_cascade import (
                    RelevanceCascadeScorer,
                )

                _relevance_key = settings.relevance_scoring_api_key.get_secret_value()
                cascade_api_key = _relevance_key or _extraction_api_key
                cascade_scorer = RelevanceCascadeScorer(
                    api_key=cascade_api_key,
                    base_url=settings.relevance_scoring_api_base_url,
                    # Reuse the SAME relevance model id (Llama-3.1-8B-Turbo).
                    model_id=settings.relevance_scoring_api_model_id,
                    timeout_seconds=15.0,
                    usage_logger=SessionScopedNlpUsageLogger(nlp_sf),
                )
                log.info(
                    "learned_router_cascade_enabled",
                    model_id=settings.relevance_scoring_api_model_id,
                    cutoff=settings.learned_router_cascade_relevance_cutoff,
                )

            learned_router = LearnedRouter(
                router_embedder,
                cascade_scorer=cascade_scorer,
                cascade_relevance_cutoff=settings.learned_router_cascade_relevance_cutoff,
            )
            log.info(
                "learned_router_enabled",
                mode=settings.learned_router_mode,
                cascade=settings.learned_router_cascade,
            )
        else:
            log.warning(
                "learned_router_mode_set_but_no_api_key",
                mode=settings.learned_router_mode,
            )

    consumer = ArticleProcessingConsumer(
        config=article_config,
        settings=settings,
        nlp_session_factory=nlp_sf,
        intelligence_session_factory=intel_sf,
        storage=_object_storage,
        watchlist_cache=watchlist_cache,
        ner_client=ner_client,
        embedding_client=embedding_client,
        extraction_client=extraction_client,
        backpressure=bp,
        chunk_text_store=_chunk_text_store,
        usage_logger=SessionScopedNlpUsageLogger(nlp_sf),
        # PLAN-0084 B-3: wire Valkey client for ValkeyDedupMixin fast-path dedup.
        # The same `valkey` instance used for WatchlistCache is reused here;
        # dedup keys are namespaced under "nlp:dedup:article_consumer" so there
        # is no key collision with the watchlist keys.
        valkey_client=valkey,
        # PLAN-0111 C-6: None unless mode is shadow/live (and key present).
        learned_router=learned_router,
    )

    # BP-239: Warm up Valkey connection before entering the Kafka consumer loop.
    # redis.asyncio uses lazy connection; the first call triggers DNS resolution
    # via socket.getaddrinfo() in a thread-pool executor.  If the connection
    # drops after a long idle period, reconnect happens mid-pipeline and the
    # non-cancellable thread blocks the graceful shutdown sequence.  Warming up
    # here ensures the connection is established at a safe, non-critical point.
    try:
        await watchlist_cache.get_all_watched()
        log.info("valkey_connection_warmed_up")
    except Exception:
        log.warning("valkey_warmup_failed", exc_info=True)

    # PLAN-0107 B-4: emit single <service>_ready event after deps are wired.
    log_runtime_banner(
        "nlp-pipeline-article-consumer",
        dependencies={
            "kafka_brokers": settings.kafka_bootstrap_servers,
            "valkey_url": getattr(settings, "valkey_url", None),
            "topics_subscribed": [settings.topic_article_stored],
        },
    )

    try:
        consumer_task = asyncio.create_task(consumer.run())

        # If the consumer task crashes before stop_event is set, the process would
        # stay alive (stuck on stop_event.wait()) but do no useful work.  The done
        # callback propagates the crash into the normal shutdown path so Docker sees
        # a clean non-zero exit and triggers restart with full error logging.
        def _on_consumer_done(task: asyncio.Task) -> None:  # type: ignore[type-arg]
            if task.cancelled():
                return
            exc = task.exception()
            if exc is not None:
                log.error("article_consumer_task_crashed", error=str(exc), exc_info=exc)
                stop_event.set()

        consumer_task.add_done_callback(_on_consumer_done)

        await stop_event.wait()
        consumer.stop()  # type: ignore[attr-defined]
        try:
            await asyncio.wait_for(consumer_task, timeout=30.0)
        except TimeoutError:
            consumer_task.cancel()
            try:
                # Give the task 5 s to honour the cancellation.  If it is stuck
                # in a thread-pool executor (e.g. socket.getaddrinfo) it cannot
                # be cancelled; sys.exit lets Docker reclaim the process cleanly.
                await asyncio.wait_for(consumer_task, timeout=5.0)
            except (asyncio.CancelledError, TimeoutError):
                log.warning("consumer_task_stuck_forcing_exit")
                sys.exit(1)
    except Exception as exc:
        log.error("article_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    else:
        log.info("article_consumer_stopped")
    finally:
        await valkey.close()
        await nlp_engine.dispose()
        await intel_engine.dispose()

        # Stop the Prometheus metrics HTTP server cleanly.
        with contextlib.suppress(Exception):
            await metrics_handle.aclose()


if __name__ == "__main__":
    asyncio.run(main())
