"""Standalone temporal event consumer entry point for S7 (Knowledge Graph).

Runs as an independent process (R22). Consumes ``intelligence.temporal_event.v1``
events, upserts ``temporal_events`` rows, and creates ``entity_event_exposures``
links in intelligence_db.

Run with::

    python -m knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer_main
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
    from knowledge_graph.infrastructure.messaging.consumers.temporal_event_consumer import (
        TemporalEventConsumer,
    )
    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
    from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]

    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name="knowledge-graph-temporal-event-consumer",
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("knowledge_graph.temporal_event_consumer_main")  # type: ignore[no-any-return]
    log.info("temporal_event_consumer_starting", service="knowledge-graph")

    # Phase 3 worker-metrics rollout — expose Prometheus /metrics on a
    # dedicated port so the worker's counters/gauges become scrape-able.
    metrics_handle = start_metrics_server(
        service_name="knowledge-graph-temporal-event-consumer",
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

    config = ConsumerConfig(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=f"{settings.kafka_consumer_group}-temporal-event",
        topics=[settings.kafka_topic_temporal_event],
    )
    consumer = TemporalEventConsumer(
        config=config,
        session_factory=write_factory,
        dedup_client=valkey,
    )

    # PLAN-0107 B-4: emit single <service>_ready event after deps are wired.
    log_runtime_banner(
        "knowledge-graph-temporal-event-consumer",
        dependencies={
            "postgres_dsn": str(settings.database_url),
            "kafka_brokers": settings.kafka_bootstrap_servers,
            "valkey_url": getattr(settings, "valkey_url", None),
            "topics_subscribed": [settings.kafka_topic_temporal_event],
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
        log.error("temporal_event_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    else:
        log.info("temporal_event_consumer_stopped")
    finally:
        await valkey.close()
        await engine.dispose()

        # Stop the Prometheus metrics HTTP server cleanly.
        with contextlib.suppress(Exception):
            await metrics_handle.aclose()


if __name__ == "__main__":
    asyncio.run(main())
