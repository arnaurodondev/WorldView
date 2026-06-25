"""Standalone watchlist consumer entry point for the Alert service (S10).

Runs as an independent process (R22) with its own Valkey client and signal
handling.  Invalidates the watchlist cache on item_deleted events.

Consumes:
  - ``portfolio.watchlist.updated.v1``

Run with::

    python -m alert.infrastructure.messaging.consumers.watchlist_consumer_main
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
    from alert.config import Settings
    from alert.infrastructure.cache.watchlist_cache import WatchlistCache
    from alert.infrastructure.clients.s1_client import S1Client
    from alert.infrastructure.messaging.consumers.watchlist_consumer import (
        WatchlistConsumer,
    )
    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
    from messaging.kafka.consumer.supervisor import (  # type: ignore[import-untyped]
        ConsumerExited,
        run_consumer_supervised,
    )
    from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]

    settings = Settings()
    configure_logging(
        service_name="alert-watchlist-consumer",
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("alert.watchlist_consumer_main")  # type: ignore[no-any-return]
    log.info("watchlist_consumer_starting", service="alert")

    # Phase 3 worker-metrics rollout — expose Prometheus /metrics on a
    # dedicated port so the worker's counters/gauges become scrape-able.
    #
    # BP-704: bind a stall-aware liveness probe so the Docker healthcheck's
    # ``GET /healthz`` flips to 503 when the poll loop wedges or ``run()`` dies —
    # without it a dead consumer kept a GREEN healthcheck and was never restarted.
    liveness_probe = make_liveness_probe()
    metrics_handle = start_metrics_server(
        service_name="alert-watchlist-consumer",
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

    # Valkey — dedup + cache backend
    valkey = create_valkey_client_from_url(settings.valkey_url)

    # S1 client — needed by WatchlistCache for cache-aside refresh
    s1_client = S1Client(settings)

    # Watchlist cache
    watchlist_cache = WatchlistCache(valkey, s1_client, ttl=settings.watchlist_cache_ttl_seconds)  # type: ignore[arg-type]

    # Consumer config
    config = ConsumerConfig(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id=settings.kafka_watchlist_consumer_group,
        topics=[settings.kafka_topic_watchlist],
        # PLAN-0113 FIX-2: opt-in static membership id (empty = dynamic, no-op).
        group_instance_id=settings.kafka_watchlist_consumer_instance_id,
    )
    consumer = WatchlistConsumer(
        config=config,
        watchlist_cache=watchlist_cache,
        dedup_client=valkey,
    )
    # BP-704: bind the probe so /healthz reflects this consumer's poll-loop
    # progress (``seconds_since_progress`` from the BP-700 heartbeat).
    liveness_probe.bind(consumer)

    # PLAN-0107 B-4: emit single <service>_ready event after deps are wired.
    log_runtime_banner(
        "alert-watchlist-consumer",
        dependencies={
            "kafka_brokers": settings.kafka_bootstrap_servers,
            "valkey_url": getattr(settings, "valkey_url", None),
            "topics_subscribed": [settings.kafka_topic_watchlist],
        },
    )

    try:
        # BP-704 supervision: race run() against the stop event so a crashed
        # run() (e.g. a GroupCoordinator connection-setup timeout) can no longer
        # leave an un-awaited dead task while main() hangs on
        # ``stop_event.wait()``. A terminal run() exit raises ConsumerExited →
        # we exit non-zero so Docker restarts the container cleanly. The probe
        # is passed through so the run() task is attached for /healthz.
        await run_consumer_supervised(consumer, stop_event, liveness_probe=liveness_probe)
    except ConsumerExited as exc:
        log.error("watchlist_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    except Exception as exc:
        log.error("watchlist_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    else:
        log.info("watchlist_consumer_stopped")
    finally:
        await s1_client.close()
        await valkey.close()

        # Stop the Prometheus metrics HTTP server cleanly.
        with contextlib.suppress(Exception):
            await metrics_handle.aclose()


if __name__ == "__main__":
    asyncio.run(main())
