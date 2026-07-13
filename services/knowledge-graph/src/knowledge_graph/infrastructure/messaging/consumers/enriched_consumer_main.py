"""Standalone enriched article consumer entry point for the Knowledge Graph (S7).

Runs as an independent process (R22). Consumes ``nlp.article.enriched.v1``
from S6 and orchestrates Blocks 11 → 12a → 12b (canonicalization, graph
materialization, contradiction detection).

Requires an embedding client (DeepInfra or Ollama, per
KNOWLEDGE_GRAPH_EMBEDDING_PROVIDER) and a direct Kafka producer for
entity.dirtied.v1 events.  ML clients are wired best-effort — the process
exits if they cannot be initialized.

Run with::

    python -m knowledge_graph.infrastructure.messaging.consumers.enriched_consumer_main
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
    make_liveness_probe,
    start_metrics_server,
)

logger = get_logger(__name__)  # type: ignore[no-any-return]


def _build_embedding_adapter(settings: Any) -> tuple[Any, str]:
    """Select the embedding adapter by ``KNOWLEDGE_GRAPH_EMBEDDING_PROVIDER``.

    Mirrors the switch in ``scheduler_main``/``narrative_refresh``/``provisional_queued``
    so that prod (``deepinfra``) does NOT depend on a local Ollama server (Ollama was
    dropped 2026-07-06). ``BAAI/bge-large-en-v1.5`` (DeepInfra) and ``bge-large:latest``
    (Ollama) are both 1024-dim → vector-compatible with the ``vector(1024)`` column.

    Returns ``(raw_adapter, model_id)`` where ``raw_adapter.embed()`` takes a
    ``list[EmbeddingInput]``. Falls back to Ollama only when the provider is not
    ``deepinfra`` or its api_key is empty.
    """
    provider = settings.embedding_provider.lower()
    api_key = settings.embedding_api_key.get_secret_value()  # DEF-005
    if provider == "deepinfra" and api_key:
        from ml_clients.adapters.deepinfra_embedding import DeepInfraEmbeddingAdapter  # type: ignore[import-not-found]

        logger.info("kg_enriched_consumer_embedding_deepinfra", model_id=settings.embedding_api_model_id)
        return (
            DeepInfraEmbeddingAdapter(
                api_key=api_key,
                model_id=settings.embedding_api_model_id,
                base_url=settings.embedding_api_base_url,
            ),
            settings.embedding_api_model_id,
        )

    from ml_clients.adapters.ollama_embedding import OllamaEmbeddingAdapter  # type: ignore[import-not-found]

    logger.info("kg_enriched_consumer_embedding_ollama", model_id=settings.embedding_model_id)
    return (
        OllamaEmbeddingAdapter(
            base_url=settings.ollama_base_url,
            model_id=settings.embedding_model_id,
            semaphore=asyncio.Semaphore(4),
        ),
        settings.embedding_model_id,
    )


async def main() -> None:
    from confluent_kafka import Producer  # type: ignore[import-untyped]

    from knowledge_graph.config import Settings
    from knowledge_graph.infrastructure.intelligence_db.session import _build_factories
    from knowledge_graph.infrastructure.messaging.consumers.enriched_consumer import (
        EnrichedArticleConsumer,
    )
    from knowledge_graph.infrastructure.messaging.direct_producer import ConfluentDirectProducer
    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
    from messaging.kafka.consumer.supervisor import (  # type: ignore[import-untyped]
        ConsumerExited,
        run_consumer_supervised,
    )
    from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]

    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name="knowledge-graph-enriched-consumer",
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("knowledge_graph.enriched_consumer_main")  # type: ignore[no-any-return]
    log.info("enriched_consumer_starting", service="knowledge-graph")

    # Phase 3 worker-metrics rollout — expose Prometheus /metrics on a
    # dedicated port so the worker's counters/gauges become scrape-able.
    # F-005 / BP-704: bind a stall-aware liveness probe so /healthz on the
    # metrics port flips to 503 when the poll loop wedges or run() dies.
    liveness_probe = make_liveness_probe()
    metrics_handle = start_metrics_server(
        service_name="knowledge-graph-enriched-consumer",
        port=int(os.environ.get("METRICS_PORT", "9100")),
        liveness_probe=liveness_probe,
    )

    stop_event = asyncio.Event()

    def _handle_signal(sig: int) -> None:
        log.info("shutdown_signal_received", signal=sig)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)

    # Session factory — write factory for hot-path graph writes
    engine, _read_engine, write_factory, _read_factory = _build_factories(settings)

    # Valkey for dedup
    valkey = create_valkey_client_from_url(settings.valkey_url)

    # Embedding client (required — exits if unavailable). Provider selection is
    # extracted into _build_embedding_adapter() (below) so it is unit-testable.
    # _EmbeddingBridgeClient wraps whichever adapter (batch EmbeddingInput API) to
    # satisfy the canonicalization block's embed(str) -> list[float] protocol.
    # The adapter's embed() takes list[EmbeddingInput]; passing a bare str causes it
    # to iterate characters, crashing with "'str' has no attribute 'instruction_prefix'".
    _raw_embedding_adapter, _embedding_model_id = _build_embedding_adapter(settings)

    from ml_clients.dataclasses import EmbeddingInput  # type: ignore[import-not-found]

    class _EmbeddingBridgeClient:
        async def embed(self, text: str) -> list[float]:  # type: ignore[override]
            outputs = await _raw_embedding_adapter.embed([EmbeddingInput(text=text, model_id=_embedding_model_id)])
            # _raw_embedding_adapter is Any (provider-selected), so .embedding is Any.
            embedding: list[float] = outputs[0].embedding
            return embedding

    embedding_client: object = _EmbeddingBridgeClient()

    # Direct Kafka producer for entity.dirtied.v1 (produced outside outbox).
    # ConfluentDirectProducer wraps confluent_kafka.Producer to expose
    # produce_bytes() — confluent_kafka.Producer itself does not have this
    # method (BP-130).
    raw_producer = Producer({"bootstrap.servers": settings.kafka_bootstrap_servers})
    direct_producer = ConfluentDirectProducer(raw_producer)

    config = ConsumerConfig(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=f"{settings.kafka_consumer_group}-enriched",
        topics=[settings.kafka_topic_enriched],
        # PLAN-0113 FIX-2: opt-in Kafka static membership (KIP-345). Empty default
        # = dynamic membership (no behaviour change); a stable id skips rebalances.
        group_instance_id=settings.kafka_enriched_consumer_instance_id,
    )
    consumer = EnrichedArticleConsumer(
        config=config,
        session_factory=write_factory,
        embedding_client=embedding_client,  # type: ignore[arg-type]
        direct_producer=direct_producer,
        entity_dirtied_topic=settings.kafka_topic_entity_dirtied,
        canonicalization_threshold=settings.relation_canonicalization_threshold,
        dedup_client=valkey,
    )
    # Bind the probe so /healthz reflects this consumer's poll-loop progress.
    liveness_probe.bind(consumer)

    # PLAN-0107 B-4: emit single <service>_ready event after deps are wired.
    log_runtime_banner(
        "knowledge-graph-enriched-consumer",
        dependencies={
            "postgres_dsn": str(settings.database_url),
            "kafka_brokers": settings.kafka_bootstrap_servers,
            "valkey_url": getattr(settings, "valkey_url", None),
            "topics_subscribed": [settings.kafka_topic_enriched],
        },
    )

    try:
        # BP-704 supervision: races run() against the stop event so a crashed
        # run() can no longer leave an un-awaited dead task while main() hangs
        # on stop_event.wait(). A terminal run() exit raises ConsumerExited →
        # exit non-zero so Docker restarts the container cleanly.
        await run_consumer_supervised(consumer, stop_event, liveness_probe=liveness_probe)
    except ConsumerExited as exc:
        log.error("enriched_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    except Exception as exc:
        log.error("enriched_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    finally:
        await valkey.close()
        await engine.dispose()

        # Stop the Prometheus metrics HTTP server cleanly.
        with contextlib.suppress(Exception):
            await metrics_handle.aclose()
        log.info("enriched_consumer_stopped")


if __name__ == "__main__":
    asyncio.run(main())
