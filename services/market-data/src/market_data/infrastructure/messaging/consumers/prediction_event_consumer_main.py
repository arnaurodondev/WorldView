"""Prediction Event consumer standalone entry point for market-data.

Materialises market.prediction.event.v1 events into ``prediction_events``.
Intended to run as a separate container/process (R22).

Usage (standalone)::

    python -m market_data.infrastructure.messaging.consumers.prediction_event_consumer_main
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
    from market_data.config import Settings
    from market_data.infrastructure.db.session import build_read_engine, build_session_factory, build_write_engine
    from market_data.infrastructure.db.uow import SqlAlchemyUnitOfWork
    from market_data.infrastructure.messaging.consumers.prediction_event_consumer import (
        PredictionEventConsumer,
    )
    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
    from messaging.kafka.consumer.supervisor import (  # type: ignore[import-untyped]
        ConsumerExited,
        run_consumer_supervised,
    )

    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name=settings.service_name,
        level=settings.log_level,
        json=settings.log_json,
    )
    log = get_logger("market_data.prediction_event_consumer_main")  # type: ignore[no-any-return]
    log.info("prediction_event_consumer_starting", service=settings.service_name)

    # F-005 / BP-704: /metrics + /healthz on 9100 + stall-aware liveness probe.
    liveness_probe = make_liveness_probe()
    metrics_handle = start_metrics_server(
        service_name="market-data-prediction-event-consumer",
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

    write_engine = build_write_engine(settings)
    read_engine = build_read_engine(settings)
    write_factory = build_session_factory(write_engine)
    read_factory = build_session_factory(read_engine)

    def uow_factory() -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(write_factory, read_factory)

    consumer = PredictionEventConsumer(
        uow_factory=uow_factory,
        config=ConsumerConfig(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id="market-data-prediction-events",
            topics=["market.prediction.event.v1"],
            group_instance_id=settings.kafka_prediction_event_consumer_instance_id,
            # WHY earliest: event-group metadata is upsert-keyed on event_id; a
            # fresh group should absorb all known groups. Duplicates return
            # is_new=False and are discarded. Normal restarts resume from offset.
            auto_offset_reset="earliest",
        ),
    )
    liveness_probe.bind(consumer)

    log_runtime_banner(
        "market-data-prediction-event-consumer",
        dependencies={
            "kafka_brokers": settings.kafka_bootstrap_servers,
            "topics_subscribed": ["market.prediction.event.v1"],
        },
    )

    try:
        await run_consumer_supervised(consumer, stop_event, liveness_probe=liveness_probe)
    except ConsumerExited as exc:
        log.error("prediction_event_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    except Exception as exc:
        log.error("prediction_event_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    finally:
        await write_engine.dispose()
        if read_engine is not write_engine:
            await read_engine.dispose()
        log.info("prediction_event_consumer_stopped")

        with contextlib.suppress(Exception):
            await metrics_handle.aclose()


if __name__ == "__main__":
    asyncio.run(main())
