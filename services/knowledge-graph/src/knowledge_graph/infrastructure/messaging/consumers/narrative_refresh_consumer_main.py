"""Standalone NarrativeRefreshKafkaConsumer entry point for the Knowledge Graph (S7).

Runs as an independent process (R22). Consumes ``entity.narrative.generated.v1``
events emitted by the S7 NarrativeGenerationWorker and triggers immediate
narrative embedding refresh without waiting for the hourly polling cycle
(PLAN-0074 T-C-05).

Run with::

    python -m knowledge_graph.infrastructure.messaging.consumers.narrative_refresh_consumer_main
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
    from knowledge_graph.infrastructure.workers.narrative_refresh import (
        NarrativeRefreshKafkaConsumer,
    )
    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
    from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]

    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name="knowledge-graph-narrative-refresh-consumer",
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("knowledge_graph.narrative_refresh_consumer_main")  # type: ignore[no-any-return]
    log.info("narrative_refresh_consumer_starting", service="knowledge-graph")

    stop_event = asyncio.Event()

    def _handle_signal(sig: int) -> None:
        log.info("shutdown_signal_received", signal=sig)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)

    # Session factory — write factory (Phase 3 upserts write entity_embedding_state).
    engine, _read_engine, write_factory, _read_factory = _build_factories(settings)

    # Valkey for dedup — NarrativeRefreshKafkaConsumer uses ValkeyDedupMixin.
    valkey = create_valkey_client_from_url(settings.valkey_url)

    # Build embedding client.
    # This consumer only uses the embedding path of FallbackChainClient;
    # no extraction adapter is needed.
    _embedding_provider = settings.embedding_provider.lower()
    _embedding_api_key = settings.embedding_api_key.get_secret_value()  # DEF-005

    embed_client: Any
    if _embedding_provider == "deepinfra" and _embedding_api_key:
        from ml_clients.adapters.deepinfra_embedding import DeepInfraEmbeddingAdapter  # type: ignore[import-not-found]

        embed_client = DeepInfraEmbeddingAdapter(
            api_key=_embedding_api_key,
            model_id=settings.embedding_api_model_id,
            base_url=settings.embedding_api_base_url,
        )
        log.info(
            "kg_narrative_consumer_embedding_deepinfra",
            model_id=settings.embedding_api_model_id,
        )
    else:
        from ml_clients.adapters.ollama_embedding import OllamaEmbeddingAdapter  # type: ignore[import-not-found]

        embed_client = OllamaEmbeddingAdapter(
            base_url=settings.ollama_base_url,
            model_id=settings.embedding_model_id,
            semaphore=asyncio.Semaphore(1),
        )
        log.info(
            "kg_narrative_consumer_embedding_ollama",
            model_id=settings.embedding_model_id,
        )

    from knowledge_graph.infrastructure.intelligence_db.usage_log_factory import (
        SessionScopedKgUsageLogger,
    )
    from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient

    kg_usage_logger = SessionScopedKgUsageLogger(write_factory)

    # FallbackChainClient: extraction adapters are None because this consumer
    # only calls embed().  The chain safely no-ops on missing extraction adapters.
    llm_client = FallbackChainClient(
        deepinfra_extraction=None,
        ollama_embedding=embed_client,
        ollama_extraction=None,
        retry_delays_deepinfra=(5.0, 15.0),
        retry_delays_ollama=(5.0, 30.0),
        usage_logger=kg_usage_logger,
    )

    config = ConsumerConfig(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_consumer_group_narrative_refresh,
        topics=[settings.kafka_topic_narrative_generated],
    )
    consumer = NarrativeRefreshKafkaConsumer(
        config=config,
        session_factory=write_factory,
        llm_client=llm_client,
        embed_model_id=settings.embedding_model_id,
        dedup_client=valkey,
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
        log.error("narrative_refresh_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    else:
        log.info("narrative_refresh_consumer_stopped")
    finally:
        await valkey.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
