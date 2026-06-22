"""Standalone earnings calendar dataset consumer entry point for S7 (Knowledge Graph).

Runs as an independent process (R22). Consumes ``market.dataset.fetched``
events where ``dataset_type='earnings_calendar'``, downloads the canonical
NDJSON envelope from MinIO, and upserts earnings events into ``temporal_events``
with ``event_type=CORPORATE``.

Consumer group: ``kg-earnings-calendar-dataset-group``

Run with::

    python -m knowledge_graph.infrastructure.messaging.consumers.earnings_calendar_dataset_consumer_main

PLAN-0068 Wave A-1 (consumer 13D-9).
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
    from knowledge_graph.config import Settings
    from knowledge_graph.infrastructure.intelligence_db.session import _build_factories
    from knowledge_graph.infrastructure.messaging.consumers.earnings_calendar_dataset_consumer import (
        EarningsCalendarDatasetConsumer,
    )
    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
    from messaging.kafka.consumer.supervisor import (  # type: ignore[import-untyped]
        ConsumerExited,
        run_consumer_supervised,
    )
    from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]

    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name="knowledge-graph-earnings-calendar-consumer",
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("knowledge_graph.earnings_calendar_dataset_consumer_main")  # type: ignore[no-any-return]
    log.info("earnings_calendar_consumer_starting", service="knowledge-graph")

    # Phase 3 worker-metrics rollout — expose Prometheus /metrics on a
    # dedicated port so the worker's counters/gauges become scrape-able.
    # F-005 / BP-704: bind a stall-aware liveness probe so /healthz on the
    # metrics port flips to 503 when the poll loop wedges or run() dies.
    liveness_probe = make_liveness_probe()
    metrics_handle = start_metrics_server(
        service_name="knowledge-graph-earnings-calendar-consumer",
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

    engine, _read_engine, write_factory, _read_factory = _build_factories(settings)
    valkey = create_valkey_client_from_url(settings.valkey_url)

    # Storage client — required for MinIO claim-check downloads
    storage_client = None
    try:
        from storage.factory import build_object_storage  # type: ignore[import-untyped]
        from storage.settings import StorageSettings  # type: ignore[import-untyped]

        storage_settings = StorageSettings(
            endpoint=settings.storage_endpoint,
            access_key=settings.storage_access_key,
            secret_key=settings.storage_secret_key,
        )
        storage_client = build_object_storage(settings=storage_settings)
    except Exception:
        log.warning("storage_not_configured_earnings_calendar_downloads_disabled", exc_info=True)

    config = ConsumerConfig(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id="kg-earnings-calendar-dataset-group",
        topics=[settings.kafka_topic_dataset_fetched],
    )
    consumer = EarningsCalendarDatasetConsumer(
        config=config,
        session_factory=write_factory,
        storage_client=storage_client,
        dedup_client=valkey,
    )
    # Bind the probe so /healthz reflects this consumer's poll-loop progress.
    liveness_probe.bind(consumer)

    # PLAN-0107 B-4: emit single <service>_ready event after deps are wired.
    log_runtime_banner(
        "knowledge-graph-earnings-calendar-consumer",
        dependencies={
            "postgres_dsn": str(settings.database_url),
            "kafka_brokers": settings.kafka_bootstrap_servers,
            "valkey_url": getattr(settings, "valkey_url", None),
            "topics_subscribed": [settings.kafka_topic_dataset_fetched],
        },
    )

    try:
        # BP-704 supervision: races run() against the stop event so a crashed
        # run() can no longer leave an un-awaited dead task while main() hangs
        # on stop_event.wait(). A terminal run() exit raises ConsumerExited →
        # exit non-zero so Docker restarts the container cleanly.
        await run_consumer_supervised(consumer, stop_event, liveness_probe=liveness_probe)
    except ConsumerExited as exc:
        log.error("earnings_calendar_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    except Exception as exc:
        log.error("earnings_calendar_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    finally:
        await valkey.close()
        await engine.dispose()

        # Stop the Prometheus metrics HTTP server cleanly.
        with contextlib.suppress(Exception):
            await metrics_handle.aclose()
        log.info("earnings_calendar_consumer_stopped")


if __name__ == "__main__":
    asyncio.run(main())
