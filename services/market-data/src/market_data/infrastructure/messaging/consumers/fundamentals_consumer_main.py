"""Fundamentals consumer standalone entry point for market-data.

Materialises fundamental data from object storage into the database.
Intended to run as a separate container/process.

Usage (standalone)::

    python -m market_data.infrastructure.messaging.consumers.fundamentals_consumer_main
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
    from market_data.infrastructure.messaging.consumers.fundamentals_consumer import FundamentalsConsumer
    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
    from messaging.kafka.consumer.supervisor import (  # type: ignore[import-untyped]
        ConsumerExited,
        run_consumer_supervised,
    )
    from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]
    from storage.factory import build_object_storage  # type: ignore[import-untyped]
    from storage.settings import StorageSettings  # type: ignore[import-untyped]

    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name=settings.service_name,
        level=settings.log_level,
        json=settings.log_json,
    )
    log = get_logger("market_data.fundamentals_consumer_main")  # type: ignore[no-any-return]
    log.info("fundamentals_consumer_starting", service=settings.service_name)

    # F-005 / BP-704: expose Prometheus /metrics + /healthz on 9100 (so the
    # Docker healthcheck has a real endpoint) and bind a stall-aware liveness
    # probe so /healthz flips to 503 when the poll loop wedges or run() dies.
    liveness_probe = make_liveness_probe()
    metrics_handle = start_metrics_server(
        service_name="market-data-fundamentals-consumer",
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

    endpoint = settings.storage_endpoint
    if not endpoint.startswith("http"):
        endpoint = f"http://{endpoint}"
    object_storage = build_object_storage(
        StorageSettings(
            endpoint=endpoint,
            access_key=settings.storage_access_key.get_secret_value(),
            secret_key=settings.storage_secret_key.get_secret_value(),
        )
    )

    valkey = create_valkey_client_from_url(settings.valkey_url)

    # PLAN-0102 T-W6-02 / BP-617: bump the per-message watchdog timeout to
    # ``settings.fundamentals_timeout_s`` (default 90 s, env override via
    # ``MARKET_DATA_FUNDAMENTALS_TIMEOUT_S``). The library default of 45 s
    # was dead-lettering Russell-1000-scale payloads that ship 600+ sections
    # in one message.
    #
    # Invariant (see libs/messaging/.../consumer/base.py): the watchdog
    # MUST be strictly less than ``session_timeout_ms`` so the dead-letter
    # path wins the race against the Kafka group coordinator. Scale both
    # together: session 2x watchdog, heartbeat ~1/3 of session per librdkafka
    # guidance.
    timeout_s = settings.fundamentals_timeout_s
    session_timeout_ms = max(60_000, (timeout_s + 30) * 1_000)
    heartbeat_interval_ms = session_timeout_ms // 3
    consumer = FundamentalsConsumer(
        uow_factory=uow_factory,
        object_storage=object_storage,
        config=ConsumerConfig(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id="market-data-fundamentals",
            topics=["market.dataset.fetched"],
            message_processing_timeout_s=timeout_s,
            session_timeout_ms=session_timeout_ms,
            heartbeat_interval_ms=heartbeat_interval_ms,
        ),
        dedup_client=valkey,
    )
    # Bind the probe so /healthz reflects this consumer's poll-loop progress.
    liveness_probe.bind(consumer)

    # PLAN-0107 B-4: emit single <service>_ready event after deps are wired.
    log_runtime_banner(
        "market-data-fundamentals-consumer",
        dependencies={
            "kafka_brokers": settings.kafka_bootstrap_servers,
            "valkey_url": getattr(settings, "valkey_url", None),
            "topics_subscribed": ["market.dataset.fetched"],
        },
    )

    try:
        # F-005 / BP-704 supervision: races run() against the stop event so a
        # crashed run() can no longer leave a dead task while main() hangs on
        # stop_event.wait(); a terminal run() exit raises ConsumerExited → we
        # exit non-zero so Docker restarts the container cleanly.
        await run_consumer_supervised(consumer, stop_event, liveness_probe=liveness_probe)
    except ConsumerExited as exc:
        log.error("fundamentals_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    except Exception as exc:
        log.error("fundamentals_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    finally:
        await valkey.close()
        await write_engine.dispose()
        if read_engine is not write_engine:
            await read_engine.dispose()
        log.info("fundamentals_consumer_stopped")

        # Stop the Prometheus metrics HTTP server cleanly.
        with contextlib.suppress(Exception):
            await metrics_handle.aclose()


if __name__ == "__main__":
    asyncio.run(main())
