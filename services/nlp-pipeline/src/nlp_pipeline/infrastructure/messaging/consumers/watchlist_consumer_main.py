"""Standalone watchlist event consumer entry point for the NLP Pipeline (S6).

Runs as an independent process (R22) that maintains the Valkey SET of
watched entity symbols.  Lightweight — only needs Kafka + Valkey.

Run with::

    python -m nlp_pipeline.infrastructure.messaging.consumers.watchlist_consumer_main
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
    from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]
    from nlp_pipeline.config import Settings
    from nlp_pipeline.infrastructure.messaging.consumers.watchlist_consumer import (
        WatchlistEventConsumer,
    )
    from nlp_pipeline.infrastructure.valkey.watchlist_cache import WatchlistCache

    settings = Settings()
    configure_logging(
        service_name="nlp-pipeline-watchlist-consumer",
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("nlp_pipeline.watchlist_consumer_main")  # type: ignore[no-any-return]
    log.info("watchlist_consumer_starting", service="nlp-pipeline")

    stop_event = asyncio.Event()

    def _handle_signal(sig: int) -> None:
        log.info("shutdown_signal_received", signal=sig)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)

    # Valkey + WatchlistCache
    valkey = create_valkey_client_from_url(settings.valkey_url)
    watchlist_cache = WatchlistCache(
        client=valkey._redis,  # type: ignore[attr-defined]
        key=settings.valkey_watchlist_key,
    )

    # Consumer
    watchlist_config = ConsumerConfig(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_watchlist_consumer_group,
        topics=[settings.topic_watchlist_updated],
    )
    consumer = WatchlistEventConsumer(
        config=watchlist_config,
        watchlist_cache=watchlist_cache,
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
        log.error("watchlist_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    else:
        log.info("watchlist_consumer_stopped")
    finally:
        await valkey.close()


if __name__ == "__main__":
    asyncio.run(main())
