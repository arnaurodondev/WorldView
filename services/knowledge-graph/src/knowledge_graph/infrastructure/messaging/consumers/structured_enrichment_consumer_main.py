"""Standalone structured enrichment consumer entry point (Worker 13J hot path).

Runs as an independent process. Consumes ``entity.canonical.created.v1`` and
immediately triggers the structured enrichment cascade (PRD-0073 §9.5).

Run with::

    python -m knowledge_graph.infrastructure.messaging.consumers.structured_enrichment_consumer_main
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import sys

from observability import configure_logging, get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]


async def main() -> None:
    from knowledge_graph.config import Settings
    from knowledge_graph.infrastructure.intelligence_db.session import _build_factories
    from knowledge_graph.infrastructure.messaging.consumers.structured_enrichment_consumer import (
        StructuredEnrichmentConsumer,
    )
    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
    from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]

    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name="knowledge-graph-structured-enrichment-consumer",
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("knowledge_graph.structured_enrichment_consumer_main")  # type: ignore[no-any-return]
    log.info("structured_enrichment_consumer_starting", service="knowledge-graph")

    stop_event = asyncio.Event()

    def _handle_signal(sig: int) -> None:
        log.info("shutdown_signal_received", signal=sig)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)

    engine, _read_engine, write_factory, _read_factory = _build_factories(settings)
    valkey = create_valkey_client_from_url(settings.valkey_url)

    # Build MarketDataClient + description client + use case
    from knowledge_graph.application.use_cases.structured_enrichment import (
        StructuredEnrichmentUseCase,
    )
    from knowledge_graph.infrastructure.http.market_data_client import MarketDataClient
    from knowledge_graph.infrastructure.intelligence_db.adapters.entity_enrichment_adapter import (
        EntityEnrichmentAdapter,
    )
    from knowledge_graph.infrastructure.scheduler.scheduler import _build_description_client

    enrichment_adapter = EntityEnrichmentAdapter(write_factory)
    market_data_client = MarketDataClient(
        base_url=settings.market_data_internal_url,
        internal_jwt="",  # dev: no JWT required when skip_verification=true
    )
    description_client = _build_description_client(settings, valkey)

    use_case = StructuredEnrichmentUseCase(
        enrichment_adapter=enrichment_adapter,
        market_data_client=market_data_client,
        description_client=description_client,
        session_factory=write_factory,
    )

    config = ConsumerConfig(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_consumer_group_structured_enrichment,
        topics=[settings.kafka_topic_entity_created],
    )
    consumer = StructuredEnrichmentConsumer(
        config=config,
        session_factory=write_factory,
        use_case=use_case,
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
        log.error("structured_enrichment_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    else:
        log.info("structured_enrichment_consumer_stopped")
    finally:
        await valkey.close()
        await market_data_client.aclose()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
