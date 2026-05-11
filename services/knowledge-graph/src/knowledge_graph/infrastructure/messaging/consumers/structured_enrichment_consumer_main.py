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
    from knowledge_graph.infrastructure.scheduler.scheduler import (
        _build_description_client,
        _build_entity_dirtied_producer,
        build_market_data_signer,
    )

    enrichment_adapter = EntityEnrichmentAdapter(write_factory)

    # F-A02 / F-X06 / F-S02 (PLAN-0073): use the same per-request RS256 signer
    # as the APScheduler bootstrap so calls to S3 ``/on-demand-profile`` carry
    # a verifiable ``X-Internal-JWT`` header.  Falls back to an HS256 dev token
    # only when ``KNOWLEDGE_GRAPH_INTERNAL_JWT_PRIVATE_KEY`` is empty.
    signer = build_market_data_signer(settings)
    market_data_client = MarketDataClient(
        base_url=settings.market_data_internal_url,
        internal_jwt=signer,
    )
    description_client = _build_description_client(settings, valkey)

    # F-A01 / F-X02 (PLAN-0073): wire the entity.dirtied.v1 producer so the
    # consumer hot-path emits the post-commit signal that drives the
    # downstream embedding refresh chain (PRD §13.7).  ``raw_producer`` is
    # held so we can flush + close it on shutdown.
    direct_producer, raw_producer = _build_entity_dirtied_producer(settings)
    if direct_producer is None:
        log.warning(
            "structured_enrichment_consumer_no_producer",
            message="entity.dirtied.v1 producer unavailable; downstream "
            "embedding refresh will rely on watermark fallback only",
        )

    use_case = StructuredEnrichmentUseCase(
        enrichment_adapter=enrichment_adapter,
        market_data_client=market_data_client,
        description_client=description_client,
        session_factory=write_factory,
        direct_producer=direct_producer,
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
        # F-X15: flush + close the entity.dirtied.v1 producer cleanly so we
        # don't drop in-flight messages on container shutdown.
        if raw_producer is not None:
            try:
                raw_producer.flush(timeout=5.0)
            except Exception:
                log.warning("structured_enrichment_consumer_producer_flush_failed", exc_info=True)
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
