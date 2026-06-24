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
    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
    from messaging.kafka.consumer.supervisor import (  # type: ignore[import-untyped]
        ConsumerExited,
        run_consumer_supervised,
    )
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

    # PLAN-0107 B-3: expose Prometheus /metrics so this consumer is scrape-able.
    # Compose already declares ``expose: ["9100"]`` for this service.
    # BP-704 FAILURE MODE 2: bind a liveness probe so /healthz turns 503 when
    # the poll loop wedges or the run() task dies — without it a wedged consumer
    # keeps a GREEN healthcheck and is never restarted.
    liveness_probe = make_liveness_probe()
    metrics_handle = start_metrics_server(
        service_name="nlp-pipeline-entity-refresh-consumer",
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

    # intelligence_db session factories — R23 dual factory.  This consumer
    # uses the WRITE factory for the UPDATE statement; the read factory is
    # discarded (no reads needed in this consumer).
    intel_engine, intel_read_engine, intel_sf, _intel_read_sf = _build_intelligence_factories(settings)

    config = ConsumerConfig(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_entity_refresh_consumer_group,
        topics=[settings.topic_entity_refresh],
        # PLAN-0113 FIX-2: opt-in static membership id (empty = dynamic, no-op).
        group_instance_id=settings.kafka_entity_refresh_consumer_instance_id,
    )
    consumer = EntityRefreshConsumer(
        config=config,
        intelligence_session_factory=intel_sf,
    )
    # Bind the probe so /healthz reflects this consumer's poll-loop progress.
    liveness_probe.bind(consumer)

    # PLAN-0107 B-4: emit single <service>_ready event after deps are wired.
    log_runtime_banner(
        "nlp-pipeline-entity-refresh-consumer",
        dependencies={
            "kafka_brokers": settings.kafka_bootstrap_servers,
            "topics_subscribed": ["entity.refresh.v1"],
        },
    )

    try:
        # BP-704 supervision: race run() against the stop event so a crashed
        # run() can no longer leave an un-awaited dead task while main() hangs
        # on stop_event.wait(). A terminal run() exit raises ConsumerExited →
        # exit non-zero so Docker restarts the container cleanly.
        await run_consumer_supervised(consumer, stop_event, liveness_probe=liveness_probe)
    except ConsumerExited as exc:
        log.error("entity_refresh_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    except Exception as exc:
        log.error("entity_refresh_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    finally:
        await intel_engine.dispose()
        if intel_read_engine is not intel_engine:
            await intel_read_engine.dispose()
        with contextlib.suppress(Exception):
            await metrics_handle.aclose()
        log.info("entity_refresh_consumer_stopped")


if __name__ == "__main__":
    asyncio.run(main())
