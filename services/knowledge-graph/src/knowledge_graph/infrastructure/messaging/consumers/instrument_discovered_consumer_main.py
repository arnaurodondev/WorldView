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
import signal
import sys

from observability import configure_logging, get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]


async def main() -> None:
    from knowledge_graph.config import Settings
    from knowledge_graph.infrastructure.intelligence_db.session import _build_factories
    from knowledge_graph.infrastructure.messaging.consumers.instrument_discovered_consumer import (
        InstrumentDiscoveredConsumer,
    )
    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
    from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]

    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name="knowledge-graph-instrument-discovered-consumer",
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("knowledge_graph.instrument_discovered_consumer_main")  # type: ignore[no-any-return]
    log.info("instrument_discovered_consumer_starting", service="knowledge-graph")

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
    )
    consumer = InstrumentDiscoveredConsumer(
        config=config,
        session_factory=write_factory,
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
        log.error("instrument_discovered_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    else:
        log.info("instrument_discovered_consumer_stopped")
    finally:
        await valkey.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
