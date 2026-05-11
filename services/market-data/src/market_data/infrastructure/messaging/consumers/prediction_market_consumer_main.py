"""Prediction Market consumer standalone entry point for market-data.

Materialises market.prediction.v1 events into the database.
Intended to run as a separate container/process (R22).

Usage (standalone)::

    python -m market_data.infrastructure.messaging.consumers.prediction_market_consumer_main
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import sys

from observability import configure_logging, get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]


async def main() -> None:
    from market_data.config import Settings
    from market_data.infrastructure.db.session import build_read_engine, build_session_factory, build_write_engine
    from market_data.infrastructure.db.uow import SqlAlchemyUnitOfWork
    from market_data.infrastructure.messaging.consumers.prediction_market_consumer import (
        PredictionMarketConsumer,
    )
    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]

    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name=settings.service_name,
        level=settings.log_level,
        json=settings.log_json,
    )
    log = get_logger("market_data.prediction_market_consumer_main")  # type: ignore[no-any-return]
    log.info("prediction_market_consumer_starting", service=settings.service_name)

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

    consumer = PredictionMarketConsumer(
        uow_factory=uow_factory,
        config=ConsumerConfig(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id="market-data-prediction-markets",
            topics=["market.prediction.v1"],
            # WHY latest: Polymarket snapshots are upsert-keyed on (market_id,
            # snapshot_at). Replaying the full 60k+ history on restart doesn't
            # add durable state (duplicate events return is_new=False from
            # ingestion_events.create_if_not_exists and are discarded). Setting
            # latest ensures a consumer-restart doesn't accumulate lag from
            # replaying historical messages we've already materialised.
            # Operational note: this only applies when the consumer group has NO
            # committed offset (fresh start). Normal restarts resume from the
            # committed offset regardless of this setting.
            auto_offset_reset="latest",
        ),
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
        log.error("prediction_market_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    finally:
        await write_engine.dispose()
        if read_engine is not write_engine:
            await read_engine.dispose()
        log.info("prediction_market_consumer_stopped")


if __name__ == "__main__":
    asyncio.run(main())
