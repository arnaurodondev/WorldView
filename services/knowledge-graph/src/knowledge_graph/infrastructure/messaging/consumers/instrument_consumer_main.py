"""Standalone instrument entity consumer entry point for the Knowledge Graph (S7).

Runs as an independent process (R22). Consumes ``market.instrument.created``
events and creates canonical entities with aliases and embeddings.

Requires an LLM client (FallbackChainClient) for alias generation and
definition embedding.  Exits if LLM client cannot be initialized.

Run with::

    python -m knowledge_graph.infrastructure.messaging.consumers.instrument_consumer_main
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import sys

from observability import (  # type: ignore[import-untyped]
    configure_logging,
    get_logger,
    log_runtime_banner,
    start_metrics_server,
)

logger = get_logger(__name__)  # type: ignore[no-any-return]


async def main() -> None:
    from knowledge_graph.config import Settings
    from knowledge_graph.infrastructure.intelligence_db.session import _build_factories
    from knowledge_graph.infrastructure.messaging.consumers.instrument_consumer import (
        InstrumentEntityConsumer,
    )
    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
    from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]

    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name="knowledge-graph-instrument-consumer",
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("knowledge_graph.instrument_consumer_main")  # type: ignore[no-any-return]
    log.info("instrument_consumer_starting", service="knowledge-graph")

    # Phase 3 worker-metrics rollout — expose Prometheus /metrics on a
    # dedicated port so the worker's counters/gauges become scrape-able.
    metrics_handle = start_metrics_server(
        service_name="knowledge-graph-instrument-consumer",
        port=int(os.environ.get("METRICS_PORT", "9100")),
    )

    stop_event = asyncio.Event()

    def _handle_signal(sig: int) -> None:
        log.info("shutdown_signal_received", signal=sig)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)

    engine, _read_engine, write_factory, _read_factory = _build_factories(settings)
    valkey = create_valkey_client_from_url(settings.valkey_url)

    # FallbackChainClient with no adapters — ML calls return None (graceful no-op)
    from knowledge_graph.infrastructure.intelligence_db.usage_log_factory import (
        SessionScopedKgUsageLogger,
    )
    from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient
    from knowledge_graph.infrastructure.workers.definition_refresh import DefinitionRefreshWorker

    # PLAN-0057 A-5 / F-CRIT-03: thread the session-scoped KG usage logger
    # into FallbackChainClient so every embed/extract attempt (success OR
    # failure) writes one row to intelligence_db.llm_usage_log.  Without
    # this, the KG cost-log table stayed permanently empty.
    kg_usage_logger = SessionScopedKgUsageLogger(write_factory)

    llm_client = FallbackChainClient(usage_logger=kg_usage_logger)
    definition_worker = DefinitionRefreshWorker(
        write_factory,
        llm_client,
        embedding_model_id=settings.embedding_model_id,
    )

    config = ConsumerConfig(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=f"{settings.kafka_consumer_group}-instrument",
        topics=[settings.kafka_topic_instrument_created],
    )
    consumer = InstrumentEntityConsumer(
        config=config,
        session_factory=write_factory,
        llm_client=llm_client,
        definition_worker=definition_worker,
        dedup_client=valkey,
    )

    # PLAN-0107 B-4: emit single <service>_ready event after deps are wired.
    log_runtime_banner(
        "knowledge-graph-instrument-consumer",
        dependencies={
            "postgres_dsn": str(settings.database_url),
            "kafka_brokers": settings.kafka_bootstrap_servers,
            "valkey_url": getattr(settings, "valkey_url", None),
            "topics_subscribed": [settings.kafka_topic_instrument_created],
        },
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
        log.error("instrument_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    else:
        log.info("instrument_consumer_stopped")
    finally:
        await valkey.close()
        await engine.dispose()

        # Stop the Prometheus metrics HTTP server cleanly.
        with contextlib.suppress(Exception):
            await metrics_handle.aclose()


if __name__ == "__main__":
    asyncio.run(main())
