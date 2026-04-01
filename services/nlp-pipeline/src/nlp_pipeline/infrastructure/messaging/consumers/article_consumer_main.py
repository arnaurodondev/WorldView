"""Standalone article processing consumer entry point for the NLP Pipeline (S6).

Runs as an independent process (R22) with its own DB sessions, ML clients,
Valkey cache, and signal handling.  Orchestrates Blocks 3-10 of the pipeline.

Run with::

    python -m nlp_pipeline.infrastructure.messaging.consumers.article_consumer_main
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import sys

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
    nlp_engine, nlp_sf, _nlp_read_sf = _build_nlp_factories(settings)
    intel_engine, intel_sf, _intel_read_sf = _build_intelligence_factories(settings)

    # Valkey + WatchlistCache
    valkey = create_valkey_client_from_url(settings.valkey_url)
    watchlist_cache = WatchlistCache(
        client=valkey._redis,  # type: ignore[attr-defined]
        key=settings.valkey_watchlist_key,
    )

    # ML clients
    from ml_clients.adapters.gliner_local import GLiNERLocalAdapter  # type: ignore[import-not-found]
    from ml_clients.adapters.ollama_embedding import (
        OllamaEmbeddingAdapter,  # type: ignore[import-not-found]
    )
    from ml_clients.adapters.ollama_extraction import (
        OllamaExtractionAdapter,  # type: ignore[import-not-found]
    )

    ml_sem = asyncio.Semaphore(settings.embedding_max_concurrent)
    ner_client = GLiNERLocalAdapter(
        model_path=settings.ner_model_id,
        semaphore=asyncio.Semaphore(1),
    )
    embedding_client = OllamaEmbeddingAdapter(
        base_url=settings.ollama_base_url,
        model_id=settings.embedding_model_id,
        semaphore=ml_sem,
    )
    extraction_client = OllamaExtractionAdapter(
        base_url=settings.ollama_base_url,
        model_id=settings.extraction_model_id,
        semaphore=ml_sem,
    )

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
    )
    consumer = ArticleProcessingConsumer(
        config=article_config,
        settings=settings,
        nlp_session_factory=nlp_sf,
        intelligence_session_factory=intel_sf,
        storage=None,
        watchlist_cache=watchlist_cache,
        ner_client=ner_client,
        embedding_client=embedding_client,
        extraction_client=extraction_client,
        backpressure=bp,
    )

    # Optional: configure MinIO storage
    try:
        from storage.factory import build_object_storage  # type: ignore[import-untyped]
        from storage.settings import StorageSettings  # type: ignore[import-untyped]

        storage_settings = StorageSettings(
            endpoint=settings.storage_endpoint,
            access_key=settings.storage_access_key,
            secret_key=settings.storage_secret_key,
        )
        storage = build_object_storage(settings=storage_settings)
        consumer._storage = storage  # type: ignore[attr-defined]
    except Exception:
        log.warning("minio_not_configured_article_downloads_disabled", exc_info=True)

    try:
        consumer_task = asyncio.create_task(consumer.run())
        await stop_event.wait()
        consumer.stop()  # type: ignore[attr-defined]
        consumer_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await consumer_task
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
