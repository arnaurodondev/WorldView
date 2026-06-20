"""Standalone manual holdings recompute consumer entry point.

PLAN-0114 W1 / T-W1-07.

Run with:
    python -m portfolio.infrastructure.messaging.consumers.manual_holdings_consumer_main
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
import sys

from observability import (  # type: ignore[import-untyped, attr-defined]
    configure_logging,
    get_logger,
    log_runtime_banner,
    make_liveness_probe,
    start_metrics_server,
)

logger = get_logger(__name__)  # type: ignore[no-any-return]


async def main() -> None:
    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
    from portfolio.config import Settings
    from portfolio.infrastructure.db.session import _build_factories
    from portfolio.infrastructure.messaging.consumers.manual_holdings_consumer import (
        ManualHoldingsRecomputeConsumer,
    )

    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name=settings.service_name,
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("portfolio.manual_holdings_consumer_main")  # type: ignore[no-any-return]
    log.info("manual_holdings_consumer_starting", service=settings.service_name)

    # Prometheus /metrics + liveness probe for Docker healthcheck
    liveness_probe = make_liveness_probe()
    metrics_handle = start_metrics_server(
        service_name="portfolio-manual-holdings-consumer",
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
        group_id="portfolio-manual-holdings-recompute",
        topics=["portfolio.holding.recompute_requested.v1"],
    )
    consumer = ManualHoldingsRecomputeConsumer(
        consumer_config,
        write_factory,
        emit_holding_changed_events=getattr(settings, "emit_holding_changed_events", False),
    )
    # Bind liveness probe so /healthz reflects poll-loop progress
    liveness_probe.bind(consumer)

    log_runtime_banner(
        "portfolio-manual-holdings-consumer",
        dependencies={
            "postgres_dsn": str(settings.database_url),
            "kafka_brokers": settings.kafka_bootstrap_servers,
            "topics_subscribed": ["portfolio.holding.recompute_requested.v1"],
        },
    )

    try:
        consumer_task = asyncio.create_task(consumer.run())
        await stop_event.wait()
        consumer.stop()
        try:
            await asyncio.wait_for(consumer_task, timeout=30.0)
        except TimeoutError:
            consumer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await consumer_task
    except Exception as exc:
        log.error("manual_holdings_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    finally:
        await _engine.dispose()
        with contextlib.suppress(Exception):
            await metrics_handle.aclose()
        log.info("manual_holdings_consumer_stopped")


if __name__ == "__main__":
    asyncio.run(main())
