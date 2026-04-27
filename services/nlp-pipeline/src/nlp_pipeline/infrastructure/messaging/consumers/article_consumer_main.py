"""Standalone article processing consumer entry point for the NLP Pipeline (S6).

Runs as an independent process (R22) with its own DB sessions, ML clients,
Valkey cache, and signal handling.  Orchestrates Blocks 3-10 of the pipeline.

Run with::

    python -m nlp_pipeline.infrastructure.messaging.consumers.article_consumer_main
"""

from __future__ import annotations

import asyncio
import signal
import sys
from typing import Any

from observability import configure_logging, get_logger  # type: ignore[import-untyped]

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

    settings = Settings()
    configure_logging(
        service_name="nlp-pipeline-article-consumer",
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("nlp_pipeline.article_consumer_main")  # type: ignore[no-any-return]
    log.info("article_consumer_starting", service="nlp-pipeline")

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

    # GLiNER: use HTTP adapter when gliner_base_url is configured (containerised),
    # otherwise fall back to in-process local adapter.
    if settings.gliner_base_url:
        from ml_clients.adapters.gliner_http import GLiNERHTTPAdapter  # type: ignore[import-not-found]

        ner_client = GLiNERHTTPAdapter(
            base_url=settings.gliner_base_url,
            semaphore=asyncio.Semaphore(settings.embedding_max_concurrent),
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
    if _embedding_provider == "deepinfra" and settings.embedding_api_key:
        from ml_clients.adapters.deepinfra_embedding import (  # type: ignore[import-not-found]
            DeepInfraEmbeddingAdapter,
        )

        embedding_client: Any = DeepInfraEmbeddingAdapter(
            api_key=settings.embedding_api_key,
            model_id=settings.embedding_api_model_id,
            base_url=settings.embedding_api_base_url,
        )
        log.info(
            "embedding_deepinfra_adapter_selected",
            model_id=settings.embedding_api_model_id,
            base_url=settings.embedding_api_base_url,
        )
    elif _embedding_provider == "jina" and settings.jina_api_key:
        from ml_clients.adapters.jina_embedding import (  # type: ignore[import-not-found]
            JinaEmbeddingAdapter,
        )

        embedding_client = JinaEmbeddingAdapter(  # type: ignore[assignment]
            api_key=settings.jina_api_key,
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
    if settings.extraction_api_key:
        from ml_clients.adapters.deepseek_extraction import (  # type: ignore[import-not-found]
            DeepSeekExtractionAdapter,
        )

        extraction_client = DeepSeekExtractionAdapter(  # type: ignore[assignment]
            api_key=settings.extraction_api_key,
            model_id=settings.extraction_api_model_id,
            base_url=settings.extraction_api_base_url,
            semaphore=ml_sem,
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


if __name__ == "__main__":
    asyncio.run(main())
