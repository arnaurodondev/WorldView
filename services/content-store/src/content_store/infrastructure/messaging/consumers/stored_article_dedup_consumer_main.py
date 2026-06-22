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
    log_runtime_banner,
    make_liveness_probe,
    start_metrics_server,
)

logger = get_logger(__name__)  # type: ignore[no-any-return]


async def main() -> None:
    from content_store.config import Settings
    from content_store.infrastructure.db.session import _build_factories
    from content_store.infrastructure.messaging.consumers.stored_article_dedup_consumer import (
        StoredArticleDedupConsumer,
    )
    from messaging.kafka.consumer.supervisor import (  # type: ignore[import-untyped]
        ConsumerExited,
        run_consumer_supervised,
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
    # F-005/BP-704: bind a liveness probe so /healthz turns 503 when the poll
    # loop wedges or the run() task dies — otherwise a wedged consumer keeps a
    # GREEN healthcheck and is never restarted.
    liveness_probe = make_liveness_probe()
    metrics_handle = start_metrics_server(
        service_name="content-store-dedup-consumer",
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

    # Database — write session factory only; this consumer writes cluster rows.
    _engine, _read_engine, write_factory, _read_factory = _build_factories(settings)

    # Consumer group is separate from the raw-article consumer group so this
    # consumer gets its own independent offset tracking on content.article.stored.v1.
    consumer = StoredArticleDedupConsumer(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id="content-store-dedup-consumer",
        session_factory=write_factory,
    )
    # Bind the probe so /healthz reflects this consumer's poll-loop progress.
    liveness_probe.bind(consumer)

    # PLAN-0107 B-4: emit single <service>_ready event after deps are wired.
    log_runtime_banner(
        "content-store-dedup-consumer",
        dependencies={
            "postgres_dsn": str(settings.database_url),
            "kafka_brokers": settings.kafka_bootstrap_servers,
        },
    )

    try:
        # F-005/BP-704 FAILURE MODE 2 supervision: a crashed run() no longer
        # hangs main() behind a green healthcheck — it raises ConsumerExited so
        # we exit non-zero and Docker restarts the container.
        await run_consumer_supervised(consumer, stop_event, liveness_probe=liveness_probe)
    except ConsumerExited as exc:
        log.error("stored_article_dedup_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    except Exception as exc:
        log.error("stored_article_dedup_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    finally:
        await _engine.dispose()
        if _read_engine is not _engine:
            await _read_engine.dispose()

        # Stop the Prometheus metrics HTTP server cleanly.
        with contextlib.suppress(Exception):
            await metrics_handle.aclose()
        log.info("stored_article_dedup_consumer_stopped")


if __name__ == "__main__":
    asyncio.run(main())
