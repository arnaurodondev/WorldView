"""Standalone entity-refresh consumer entry point for the NLP Pipeline (S6).

Consumes ``entity.refresh.v1`` (REQ-003 / TASK-W0-06) and marks
``entity_embedding_state`` rows as due so S7's DefinitionRefreshWorker
re-fetches descriptions on its next cycle.

Run with::

    python -m nlp_pipeline.infrastructure.messaging.consumers.entity_refresh_consumer_main

Lifecycle pattern is identical to ``watchlist_consumer_main`` (R22: background
processes run as independent processes, not lifespan tasks).
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import sys

from observability import configure_logging, get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]


async def main() -> None:
    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
    from nlp_pipeline.config import Settings
    from nlp_pipeline.infrastructure.intelligence_db.session import (
        _build_intelligence_factories,
    )
    from nlp_pipeline.infrastructure.messaging.consumers.entity_refresh_consumer import (
        EntityRefreshConsumer,
    )

    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name="nlp-pipeline-entity-refresh-consumer",
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("nlp_pipeline.entity_refresh_consumer_main")  # type: ignore[no-any-return]
    log.info("entity_refresh_consumer_starting", service="nlp-pipeline")

    stop_event = asyncio.Event()

    def _handle_signal(sig: int) -> None:
        log.info("shutdown_signal_received", signal=sig)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)

    # intelligence_db session factories — R23 dual factory.  This consumer
    # uses the WRITE factory for the UPDATE statement; the read factory is
    # discarded (no reads needed in this consumer).
    intel_engine, intel_read_engine, intel_sf, _intel_read_sf = _build_intelligence_factories(settings)

    config = ConsumerConfig(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_entity_refresh_consumer_group,
        topics=[settings.topic_entity_refresh],
    )
    consumer = EntityRefreshConsumer(
        config=config,
        intelligence_session_factory=intel_sf,
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
        log.error("entity_refresh_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    else:
        log.info("entity_refresh_consumer_stopped")
    finally:
        await intel_engine.dispose()
        if intel_read_engine is not intel_engine:
            await intel_read_engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
