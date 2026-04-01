"""Standalone enriched article consumer entry point for the Knowledge Graph (S7).

Runs as an independent process (R22). Consumes ``nlp.article.enriched.v1``
from S6 and orchestrates Blocks 11 → 12a → 12b (canonicalization, graph
materialization, contradiction detection).

Requires an embedding client (Ollama) and a direct Kafka producer for
entity.dirtied.v1 events.  ML clients are wired best-effort — the process
exits if they cannot be initialized.

Run with::

    python -m knowledge_graph.infrastructure.messaging.consumers.enriched_consumer_main
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import sys

from observability import configure_logging, get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]


async def main() -> None:
    from confluent_kafka import Producer  # type: ignore[import-untyped]
    from ml_clients.adapters.ollama_embedding import OllamaEmbeddingAdapter  # type: ignore[import-not-found]

    from knowledge_graph.config import Settings
    from knowledge_graph.infrastructure.intelligence_db.session import _build_factories
    from knowledge_graph.infrastructure.messaging.consumers.enriched_consumer import (
        EnrichedArticleConsumer,
    )
    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
    from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]

    settings = Settings()
    configure_logging(
        service_name="knowledge-graph-enriched-consumer",
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("knowledge_graph.enriched_consumer_main")  # type: ignore[no-any-return]
    log.info("enriched_consumer_starting", service="knowledge-graph")

    stop_event = asyncio.Event()

    def _handle_signal(sig: int) -> None:
        log.info("shutdown_signal_received", signal=sig)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)

    # Session factory — write factory for hot-path graph writes
    engine, write_factory, _read_factory = _build_factories(settings)

    # Valkey for dedup
    valkey = create_valkey_client_from_url(settings.valkey_url)

    # Embedding client (required — exits if unavailable)
    embedding_client = OllamaEmbeddingAdapter(
        base_url=settings.otlp_endpoint or "http://ollama:11434",
        model_id="nomic-embed-text",
        semaphore=asyncio.Semaphore(4),
    )

    # Direct Kafka producer for entity.dirtied.v1 (produced outside outbox)
    direct_producer = Producer({"bootstrap.servers": settings.kafka_bootstrap_servers})

    config = ConsumerConfig(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=f"{settings.kafka_consumer_group}-enriched",
        topics=[settings.kafka_topic_enriched],
    )
    consumer = EnrichedArticleConsumer(
        config=config,
        session_factory=write_factory,
        embedding_client=embedding_client,  # type: ignore[arg-type]
        direct_producer=direct_producer,  # type: ignore[arg-type]
        entity_dirtied_topic=settings.kafka_topic_entity_dirtied,
        canonicalization_threshold=settings.relation_canonicalization_threshold,
        dedup_client=valkey,
    )

    try:
        consumer_task = asyncio.create_task(consumer.run())
        await stop_event.wait()
        consumer.stop()  # type: ignore[attr-defined]
        consumer_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await consumer_task
    except Exception as exc:
        log.error("enriched_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    else:
        log.info("enriched_consumer_stopped")
    finally:
        await valkey.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
