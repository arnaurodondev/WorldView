"""Standalone instrument event consumer entry point.

Run with: python -m portfolio.infrastructure.messaging.consumers.instrument_consumer_main
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
    from portfolio.config import Settings
    from portfolio.infrastructure.db.session import _build_factories
    from portfolio.infrastructure.messaging.consumers.instrument_consumer import InstrumentEventConsumer

    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name=settings.service_name,
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("portfolio.instrument_consumer_main")  # type: ignore[no-any-return]
    log.info("instrument_consumer_starting", service=settings.service_name)

    # PLAN-0107 B-3: expose Prometheus /metrics so this consumer is scrape-able.
    # F-005/BP-704: bind a liveness probe so /healthz turns 503 when the poll
    # loop wedges or the run() task dies — otherwise a wedged consumer keeps a
    # GREEN healthcheck and is never restarted.
    liveness_probe = make_liveness_probe()
    metrics_handle = start_metrics_server(
        service_name="portfolio-instrument-consumer",
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

    _engine, _read_engine, write_factory, _read_factory = _build_factories(settings)

    consumer_config = ConsumerConfig(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.consumer_group_instrument,
        topics=[
            # PLAN-0057 Wave D-2: discovered.v1 is the new lightweight event
            # that fires BEFORE fundamentals enrichment, so we materialise
            # InstrumentRef as soon as ohlcv/quotes consumers see the symbol.
            settings.topic_instrument_discovered,
            settings.topic_instrument_created,
            settings.topic_instrument_updated,
        ],
        # PLAN-0113 FIX-2: opt-in static membership id (empty = dynamic, no-op).
        group_instance_id=settings.kafka_instrument_consumer_instance_id,
    )
    consumer = InstrumentEventConsumer(consumer_config, write_factory)
    # Bind the probe so /healthz reflects this consumer's poll-loop progress.
    liveness_probe.bind(consumer)

    # PLAN-0107 B-4: emit single <service>_ready event after deps are wired.
    log_runtime_banner(
        "portfolio-instrument-consumer",
        dependencies={
            "postgres_dsn": str(settings.database_url),
            "kafka_brokers": settings.kafka_bootstrap_servers,
            "topics_subscribed": [
                settings.topic_instrument_discovered,
                settings.topic_instrument_created,
                settings.topic_instrument_updated,
            ],
        },
    )

    try:
        # F-005/BP-704 FAILURE MODE 2 supervision: a crashed run() no longer
        # hangs main() behind a green healthcheck — it raises ConsumerExited so
        # we exit non-zero and Docker restarts the container.
        await run_consumer_supervised(consumer, stop_event, liveness_probe=liveness_probe)
    except ConsumerExited as exc:
        log.error("instrument_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    except Exception as exc:
        log.error("instrument_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    finally:
        await _engine.dispose()
        with contextlib.suppress(Exception):
            await metrics_handle.aclose()
        log.info("instrument_consumer_stopped")


if __name__ == "__main__":
    asyncio.run(main())
