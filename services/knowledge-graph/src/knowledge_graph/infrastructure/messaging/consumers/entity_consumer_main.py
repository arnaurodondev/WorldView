"""Standalone entity created consumer entry point for the Knowledge Graph (S7).

Runs as an independent process (R22). Consumes ``entity.canonical.created.v1``
and unblocks provisional relation_evidence_raw rows for the new entity.

Run with::

    python -m knowledge_graph.infrastructure.messaging.consumers.entity_consumer_main
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
    from knowledge_graph.infrastructure.messaging.consumers.entity_consumer import (
        EntityCreatedConsumer,
    )
    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
    from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]

    settings = Settings()
    configure_logging(
        service_name="knowledge-graph-entity-consumer",
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("knowledge_graph.entity_consumer_main")  # type: ignore[no-any-return]
    log.info("entity_consumer_starting", service="knowledge-graph")

    stop_event = asyncio.Event()

    def _handle_signal(sig: int) -> None:
        log.info("shutdown_signal_received", signal=sig)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)

    engine, write_factory, _read_factory = _build_factories(settings)
    valkey = create_valkey_client_from_url(settings.valkey_url)

    config = ConsumerConfig(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=f"{settings.kafka_consumer_group}-entity",
        topics=[settings.kafka_topic_entity_created],
    )
    consumer = EntityCreatedConsumer(
        config=config,
        session_factory=write_factory,
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
        log.error("entity_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    else:
        log.info("entity_consumer_stopped")
    finally:
        await valkey.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
