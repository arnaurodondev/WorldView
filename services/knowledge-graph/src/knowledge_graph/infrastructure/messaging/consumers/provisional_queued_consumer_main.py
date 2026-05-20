"""Standalone ProvisionalQueuedConsumer entry point for the Knowledge Graph (S7).

Runs as an independent process (R22). Consumes ``entity.provisional.queued.v1``
events emitted by S6 UnresolvedResolutionWorker and triggers immediate LLM
enrichment for newly-discovered provisional entities (PLAN-0061 Wave E).

Run with::

    python -m knowledge_graph.infrastructure.messaging.consumers.provisional_queued_consumer_main
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import sys
from typing import Any

from observability import configure_logging, get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]


async def main() -> None:
    from knowledge_graph.config import Settings
    from knowledge_graph.infrastructure.intelligence_db.session import _build_factories
    from knowledge_graph.infrastructure.messaging.consumers.provisional_queued_consumer import (
        ProvisionalQueuedConsumer,
    )
    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
    from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]

    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name="knowledge-graph-provisional-queued-consumer",
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("knowledge_graph.provisional_queued_consumer_main")  # type: ignore[no-any-return]
    log.info("provisional_queued_consumer_starting", service="knowledge-graph")

    stop_event = asyncio.Event()

    def _handle_signal(sig: int) -> None:
        log.info("shutdown_signal_received", signal=sig)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)

    engine, _read_engine, write_factory, _read_factory = _build_factories(settings)
    valkey = create_valkey_client_from_url(settings.valkey_url)

    # Build LLM client (same construction as scheduler_main) so this consumer
    # has access to the full DeepInfra → Ollama → Gemini extraction chain.
    _embedding_provider = settings.embedding_provider.lower()
    _embedding_api_key = settings.embedding_api_key.get_secret_value()  # DEF-005
    if _embedding_provider == "deepinfra" and _embedding_api_key:
        from ml_clients.adapters.deepinfra_embedding import DeepInfraEmbeddingAdapter  # type: ignore[import-not-found]

        embed_client: Any = DeepInfraEmbeddingAdapter(
            api_key=_embedding_api_key,
            model_id=settings.embedding_api_model_id,
            base_url=settings.embedding_api_base_url,
        )
        log.info(
            "kg_pq_consumer_embedding_deepinfra",
            model_id=settings.embedding_api_model_id,
        )
    else:
        from ml_clients.adapters.ollama_embedding import OllamaEmbeddingAdapter  # type: ignore[import-not-found]

        embed_client = OllamaEmbeddingAdapter(
            base_url=settings.ollama_base_url,
            model_id=settings.embedding_model_id,
            semaphore=asyncio.Semaphore(1),
        )
        log.info("kg_pq_consumer_embedding_ollama", model_id=settings.embedding_model_id)

    from knowledge_graph.infrastructure.intelligence_db.usage_log_factory import (
        SessionScopedKgUsageLogger,
    )
    from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient

    kg_usage_logger = SessionScopedKgUsageLogger(write_factory)

    _deepinfra_api_key = settings.deepinfra_api_key.get_secret_value()  # DEF-005
    deepinfra_ext: Any = None
    if _deepinfra_api_key:
        from ml_clients.adapters.deepseek_extraction import DeepSeekExtractionAdapter  # type: ignore[import-not-found]

        deepinfra_ext = DeepSeekExtractionAdapter(
            api_key=_deepinfra_api_key,
            model_id=settings.deepinfra_extraction_model_id,
            base_url=settings.deepinfra_extraction_base_url,
            semaphore=asyncio.Semaphore(settings.deepinfra_extraction_concurrency),
        )
        log.info(
            "kg_pq_consumer_extraction_deepinfra",
            model_id=settings.deepinfra_extraction_model_id,
        )
    else:
        log.info("kg_pq_consumer_extraction_deepinfra_key_absent_using_ollama_gemini_chain")

    # Only wire Ollama extraction when DeepInfra key is absent (same rule as scheduler_main).
    ollama_ext: Any = None
    if not _deepinfra_api_key:
        from ml_clients.adapters.ollama_extraction import OllamaExtractionAdapter  # type: ignore[import-not-found]

        _ollama_ext_model = "qwen3:0.6b"
        ollama_ext = OllamaExtractionAdapter(
            base_url=settings.ollama_base_url,
            model_id=_ollama_ext_model,
            semaphore=asyncio.Semaphore(1),
        )
        log.info("kg_pq_consumer_extraction_ollama_fallback_wired", model_id=_ollama_ext_model)
    else:
        log.info("kg_pq_consumer_extraction_ollama_skipped_deepinfra_key_present")

    llm_client = FallbackChainClient(
        deepinfra_extraction=deepinfra_ext,
        ollama_embedding=embed_client,
        ollama_extraction=ollama_ext,
        retry_delays_deepinfra=(5.0, 15.0),
        retry_delays_ollama=(5.0, 30.0),
        usage_logger=kg_usage_logger,
    )

    # Wire direct Kafka producer for entity.dirtied.v1 (fire-and-forget post-commit).
    direct_producer = None
    try:
        from confluent_kafka import Producer as _RawProducer  # type: ignore[import-untyped]

        from knowledge_graph.infrastructure.messaging.direct_producer import ConfluentDirectProducer

        direct_producer = ConfluentDirectProducer(_RawProducer({"bootstrap.servers": settings.kafka_bootstrap_servers}))
        log.info("kg_pq_consumer_direct_producer_ready")
    except Exception:
        log.warning("kg_pq_consumer_direct_producer_unavailable_dirtied_disabled", exc_info=True)

    config = ConsumerConfig(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_consumer_group_provisional_queued,
        topics=[settings.kafka_topic_provisional_queued],
    )

    # PRD-0089 F2 step 5: hot-path M-017 enforcement.  We construct a
    # MarketDataClient + MarketDataLookupAdapter here so tradable promotions
    # in this consumer also adopt the existing instrument_id instead of
    # minting a fresh UUID.  See scheduler.py for the polling-worker
    # equivalent.  ``aclose`` runs at consumer shutdown alongside the
    # other auxiliary resources.
    from knowledge_graph.infrastructure.http.market_data_client import MarketDataClient
    from knowledge_graph.infrastructure.http.market_data_lookup_adapter import MarketDataLookupAdapter
    from knowledge_graph.infrastructure.scheduler.scheduler import build_market_data_signer

    md_client = MarketDataClient(
        base_url=settings.market_data_internal_url,
        internal_jwt=build_market_data_signer(settings),
    )
    md_lookup = MarketDataLookupAdapter(md_client)

    consumer = ProvisionalQueuedConsumer(
        config=config,
        session_factory=write_factory,
        llm_client=llm_client,
        embed_model_id=settings.embedding_model_id,
        max_retries=settings.worker_provisional_enrichment_max_retries,
        dedup_client=valkey,
        direct_producer=direct_producer,
        # DEF-033 / BP-396 — thread the env-var-driven backoff window through
        # so the hot-path consumer honours the same exponential backoff as the
        # polling worker.  Without this kwarg the consumer silently used the
        # function defaults (2 / 1440) regardless of ops configuration.
        base_retry_minutes=settings.provisional_enrichment_base_retry_minutes,
        max_retry_minutes=settings.provisional_enrichment_max_retry_minutes,
        market_data_lookup=md_lookup,
    )

    try:
        consumer_task = asyncio.create_task(consumer.run())
        await stop_event.wait()
        consumer.stop()  # type: ignore[attr-defined]
        try:
            await asyncio.wait_for(consumer_task, timeout=30.0)
        except TimeoutError:
            consumer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await consumer_task
    except Exception as exc:
        log.error("provisional_queued_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    else:
        log.info("provisional_queued_consumer_stopped")
    finally:
        # F2 step 5 — close the market-data lookup client first; it owns an
        # httpx pool that will leak warnings on interpreter shutdown
        # otherwise.  Errors here are intentionally swallowed so a closed-
        # client teardown does not mask a real prior exception.
        with contextlib.suppress(Exception):
            await md_client.aclose()
        await valkey.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
