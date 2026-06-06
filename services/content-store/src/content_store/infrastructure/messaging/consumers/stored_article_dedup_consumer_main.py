"""Standalone entry point for the H-5 Stage C streaming near-dup writer.

Reads ``content.article.stored.v1`` events and writes near-duplicate pairs
into ``duplicate_clusters``.  Runs as an independent process inside the
``content-store-dedup-consumer`` Docker container.

Run with::

    python -m content_store.infrastructure.messaging.consumers.stored_article_dedup_consumer_main
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
    start_metrics_server,
)

logger = get_logger(__name__)  # type: ignore[no-any-return]


async def main() -> None:
    from content_store.config import Settings
    from content_store.infrastructure.db.session import _build_factories
    from content_store.infrastructure.messaging.consumers.stored_article_dedup_consumer import (
        StoredArticleDedupConsumer,
    )

    settings = Settings()
    configure_logging(
        service_name="content-store-dedup-consumer",
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("content_store.stored_article_dedup_consumer_main")  # type: ignore[no-any-return]
    log.info("stored_article_dedup_consumer_starting", service="content-store")

    # Phase 3 worker-metrics rollout — expose Prometheus /metrics on a
    # dedicated port so the worker's counters/gauges become scrape-able.
    metrics_handle = start_metrics_server(
        service_name="content-store-dedup-consumer",
        port=int(os.environ.get("METRICS_PORT", "9100")),
    )

    stop_event = asyncio.Event()

    def _handle_signal(sig: int) -> None:
        log.info("shutdown_signal_received", signal=sig)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)

    # Database — write session factory only; this consumer writes cluster rows.
    _engine, _read_engine, write_factory, _read_factory = _build_factories(settings)

    # Consumer group is separate from the raw-article consumer group so this
    # consumer gets its own independent offset tracking on content.article.stored.v1.
    consumer = StoredArticleDedupConsumer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id="content-store-dedup-consumer",
        session_factory=write_factory,
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
        log.error("stored_article_dedup_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    else:
        log.info("stored_article_dedup_consumer_stopped")
    finally:
        await _engine.dispose()
        if _read_engine is not _engine:
            await _read_engine.dispose()

        # Stop the Prometheus metrics HTTP server cleanly.
        with contextlib.suppress(Exception):
            await metrics_handle.aclose()


if __name__ == "__main__":
    asyncio.run(main())
