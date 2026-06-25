"""Standalone entry point for InstrumentDiscoveredConsumer (PLAN-0057 Wave D-2).

Runs as an independent process (R22) that consumes
``market.instrument.discovered.v1`` and seeds a lightweight canonical entity
in intelligence_db.  No LLM client is needed here — alias generation runs
later, when fundamentals enrichment delivers the real EODHD ``Name`` to the
existing ``InstrumentEntityConsumer`` (UPSERT-after-discover, T-D-2-05).

Run with::

    python -m knowledge_graph.infrastructure.messaging.consumers.instrument_discovered_consumer_main
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
    make_liveness_probe,
    start_metrics_server,
)

logger = get_logger(__name__)  # type: ignore[no-any-return]


async def main() -> None:
    from knowledge_graph.config import Settings
    from knowledge_graph.infrastructure.intelligence_db.session import _build_factories
    from knowledge_graph.infrastructure.messaging.consumers.instrument_discovered_consumer import (
        InstrumentDiscoveredConsumer,
    )
    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
    from messaging.kafka.consumer.supervisor import (  # type: ignore[import-untyped]
        ConsumerExited,
        run_consumer_supervised,
    )
    from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]

    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name="knowledge-graph-instrument-discovered-consumer",
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("knowledge_graph.instrument_discovered_consumer_main")  # type: ignore[no-any-return]
    log.info("instrument_discovered_consumer_starting", service="knowledge-graph")

    # PLAN-0107 B-3: expose Prometheus /metrics on dedicated port so this
    # consumer process is scrape-able alongside FastAPI services.
    # F-005 / BP-704: bind a stall-aware liveness probe so /healthz on the
    # metrics port flips to 503 when the poll loop wedges or run() dies.
    liveness_probe = make_liveness_probe()
    metrics_handle = start_metrics_server(
        service_name="knowledge-graph-instrument-discovered-consumer",
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

    engine, _read_engine, write_factory, _read_factory = _build_factories(settings)
    valkey = create_valkey_client_from_url(settings.valkey_url)

    # Topic name is hard-coded ``market.instrument.discovered.v1`` to match the
    # Avro schema filename.  We deliberately do NOT add a Settings field for
    # this — the topic is part of the cross-service contract and should not
    # be configurable per-deployment.
    config = ConsumerConfig(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=f"{settings.kafka_consumer_group}-instrument-discovered",
        topics=["market.instrument.discovered.v1"],
        # PLAN-0113 FIX-2: opt-in Kafka static membership (KIP-345). Empty default
        # = dynamic membership (no behaviour change); a stable id skips rebalances.
        group_instance_id=settings.kafka_instrument_discovered_consumer_instance_id,
    )
    consumer = InstrumentDiscoveredConsumer(
        config=config,
        session_factory=write_factory,
        dedup_client=valkey,
    )
    # Bind the probe so /healthz reflects this consumer's poll-loop progress.
    liveness_probe.bind(consumer)

    # PLAN-0107 B-4: emit single <service>_ready event after deps are wired.
    log_runtime_banner(
        "knowledge-graph-instrument-discovered-consumer",
        dependencies={
            "postgres_dsn": str(settings.database_url),
            "kafka_brokers": settings.kafka_bootstrap_servers,
            "valkey_url": getattr(settings, "valkey_url", None),
            "topics_subscribed": ["market.instrument.discovered.v1"],
        },
    )

    try:
        # BP-704 supervision: races run() against the stop event so a crashed
        # run() can no longer leave an un-awaited dead task while main() hangs
        # on stop_event.wait(). A terminal run() exit raises ConsumerExited →
        # exit non-zero so Docker restarts the container cleanly.
        await run_consumer_supervised(consumer, stop_event, liveness_probe=liveness_probe)
    except ConsumerExited as exc:
        log.error("instrument_discovered_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    except Exception as exc:
        log.error("instrument_discovered_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    finally:
        await valkey.close()
        await engine.dispose()
        with contextlib.suppress(Exception):
            await metrics_handle.aclose()
        log.info("instrument_discovered_consumer_stopped")


if __name__ == "__main__":
    asyncio.run(main())
