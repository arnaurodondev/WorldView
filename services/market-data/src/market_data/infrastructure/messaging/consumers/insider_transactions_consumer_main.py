"""Insider transactions consumer standalone entry point (PLAN-0089 Wave L-4b).

Materialises per-transaction insider feed from object storage into Postgres.
Intended to run as a separate container/process (mirrors the
``ohlcv_consumer_main`` pattern, including the F-005 / BP-704 stall-aware
``/healthz`` wiring).

Usage (standalone)::

    python -m market_data.infrastructure.messaging.consumers.insider_transactions_consumer_main
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
    """Async entrypoint — mirrors ``ohlcv_consumer_main.main`` exactly."""
    from market_data.config import Settings
    from market_data.infrastructure.db.session import (
        build_read_engine,
        build_session_factory,
        build_write_engine,
    )
    from market_data.infrastructure.db.uow import SqlAlchemyUnitOfWork
    from market_data.infrastructure.messaging.consumers.insider_transactions_consumer import (
        InsiderTransactionsConsumer,
    )
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
    log = get_logger("market_data.insider_transactions_consumer_main")  # type: ignore[no-any-return]
    log.info("insider_transactions_consumer_starting", service=settings.service_name)

    # F-005 / BP-704: expose Prometheus /metrics + /healthz on 9100 so the Docker
    # healthcheck has a real endpoint to hit, and bind a stall-aware liveness
    # probe so /healthz flips to 503 when the poll loop wedges or run() dies —
    # without it this consumer had NO metrics server at all, so /healthz on 9100
    # refused connection and the container reported UNHEALTHY despite working.
    liveness_probe = make_liveness_probe()
    metrics_handle = start_metrics_server(
        service_name="market-data-insider-transactions-consumer",
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

    consumer = InsiderTransactionsConsumer(
        uow_factory=uow_factory,
        object_storage=object_storage,
        config=ConsumerConfig(
            bootstrap_servers=settings.kafka_bootstrap_servers,
            group_id="market-data-insider-transactions",
            topics=["market.dataset.fetched"],
        ),
        dedup_client=valkey,
    )
    # Bind the probe so /healthz reflects this consumer's poll-loop progress.
    liveness_probe.bind(consumer)

    # PLAN-0107 B-4: emit single <service>_ready event after deps are wired.
    log_runtime_banner(
        "insider-transactions-consumer",
        dependencies={
            "kafka_brokers": settings.kafka_bootstrap_servers,
            "valkey_url": getattr(settings, "valkey_url", None),
            "topics_subscribed": ["market.dataset.fetched"],
        },
    )

    try:
        # F-005 / BP-704 supervision: races run() against the stop event so a
        # crashed run() can no longer leave an un-awaited dead task while main()
        # hangs on ``stop_event.wait()``. A terminal run() exit raises
        # ConsumerExited → we exit non-zero so Docker restarts the container.
        await run_consumer_supervised(consumer, stop_event, liveness_probe=liveness_probe)
    except ConsumerExited as exc:
        log.error("insider_transactions_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    except Exception as exc:
        log.error("insider_transactions_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    finally:
        await valkey.close()
        await write_engine.dispose()
        if read_engine is not write_engine:
            await read_engine.dispose()
        with contextlib.suppress(Exception):
            await metrics_handle.aclose()
        log.info("insider_transactions_consumer_stopped")


if __name__ == "__main__":
    asyncio.run(main())
