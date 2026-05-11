"""Standalone insider transactions dataset consumer entry point for S7 (Knowledge Graph).

Runs as an independent process (R22). Consumes ``market.dataset.fetched``
events where ``dataset_type='insider_transactions'``, downloads the canonical
NDJSON envelope from MinIO, and upserts ``has_executive`` relations into the
knowledge graph.

Run with::

    python -m knowledge_graph.infrastructure.messaging.consumers.insider_transactions_dataset_consumer_main
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
import sys

from observability import configure_logging, get_logger  # type: ignore[import-untyped]

logger = get_logger(__name__)  # type: ignore[no-any-return]


async def main() -> None:
    from knowledge_graph.config import Settings
    from knowledge_graph.infrastructure.intelligence_db.session import _build_factories
    from knowledge_graph.infrastructure.messaging.consumers.insider_transactions_dataset_consumer import (
        InsiderTransactionsDatasetConsumer,
    )
    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
    from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]

    settings = Settings()  # type: ignore[call-arg]
    configure_logging(
        service_name="knowledge-graph-insider-transactions-consumer",
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("knowledge_graph.insider_transactions_dataset_consumer_main")  # type: ignore[no-any-return]
    log.info("insider_transactions_consumer_starting", service="knowledge-graph")

    stop_event = asyncio.Event()

    def _handle_signal(sig: int) -> None:
        log.info("shutdown_signal_received", signal=sig)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)

    engine, _read_engine, write_factory, _read_factory = _build_factories(settings)
    valkey = create_valkey_client_from_url(settings.valkey_url)

    # Storage client — required for claim-check downloads
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
        log.warning("storage_not_configured_insider_transactions_downloads_disabled", exc_info=True)

    config = ConsumerConfig(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id="kg-insider-transactions-dataset-group",
        topics=[settings.kafka_topic_dataset_fetched],
    )
    consumer = InsiderTransactionsDatasetConsumer(
        config=config,
        session_factory=write_factory,
        storage_client=storage_client,
        dedup_client=valkey,
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
        log.error("insider_transactions_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    else:
        log.info("insider_transactions_consumer_stopped")
    finally:
        await valkey.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
