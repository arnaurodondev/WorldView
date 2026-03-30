"""Standalone instrument event consumer entry point.

Run with: python -m portfolio.infrastructure.messaging.consumers.instrument_consumer_main
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
    from portfolio.config import Settings
    from portfolio.infrastructure.db.session import create_session_factory
    from portfolio.infrastructure.messaging.consumers.instrument_consumer import InstrumentEventConsumer

    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name=settings.service_name,
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("portfolio.instrument_consumer_main")  # type: ignore[no-any-return]
    log.info("instrument_consumer_starting", service=settings.service_name)

    stop_event = asyncio.Event()

    def _handle_signal(sig: int) -> None:
        log.info("shutdown_signal_received", signal=sig)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)

    _engine, session_factory = create_session_factory(settings.database_url)

    consumer_config = ConsumerConfig(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.consumer_group_instrument,
        topics=[settings.topic_instrument_created, settings.topic_instrument_updated],
    )
    consumer = InstrumentEventConsumer(consumer_config, session_factory)

    try:
        consumer_task = asyncio.create_task(consumer.run())
        await stop_event.wait()
        consumer.stop()
        consumer_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await consumer_task
    except Exception as exc:
        log.error("instrument_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    finally:
        await _engine.dispose()
        log.info("instrument_consumer_stopped")


if __name__ == "__main__":
    asyncio.run(main())
