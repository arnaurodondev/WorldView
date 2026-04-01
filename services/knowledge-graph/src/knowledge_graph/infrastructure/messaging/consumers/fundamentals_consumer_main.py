"""Standalone fundamentals description consumer entry point for S7 (Knowledge Graph).

Runs as an independent process (R22). Consumes ``market.dataset.fetched``
events where ``dataset_type='fundamentals'``, detects description changes
via SHA-256 comparison, and triggers definition re-embedding when changed.

Run with::

    python -m knowledge_graph.infrastructure.messaging.consumers.fundamentals_consumer_main
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
    from knowledge_graph.infrastructure.messaging.consumers.fundamentals_consumer import (
        FundamentalsDescriptionConsumer,
    )
    from knowledge_graph.infrastructure.workers.definition_refresh import DefinitionRefreshWorker
    from messaging.kafka.consumer.base import ConsumerConfig  # type: ignore[import-untyped]
    from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]

    settings = Settings()
    configure_logging(
        service_name="knowledge-graph-fundamentals-consumer",
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("knowledge_graph.fundamentals_consumer_main")  # type: ignore[no-any-return]
    log.info("fundamentals_consumer_starting", service="knowledge-graph")

    stop_event = asyncio.Event()

    def _handle_signal(sig: int) -> None:
        log.info("shutdown_signal_received", signal=sig)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)

    engine, write_factory, _read_factory = _build_factories(settings)
    valkey = create_valkey_client_from_url(settings.valkey_url)

    # Storage client — best-effort (needed for claim-check downloads)
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
        log.warning("storage_not_configured_fundamentals_downloads_disabled", exc_info=True)

    # Definition worker — FallbackChainClient with no adapters acts as no-op for ML calls
    from knowledge_graph.infrastructure.llm.fallback_chain import FallbackChainClient

    llm_client = FallbackChainClient()
    definition_worker = DefinitionRefreshWorker(write_factory, llm_client)

    config = ConsumerConfig(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        group_id="kg-fundamentals-group",
        topics=[settings.kafka_topic_dataset_fetched],
    )
    consumer = FundamentalsDescriptionConsumer(
        config=config,
        session_factory=write_factory,
        definition_worker=definition_worker,
        storage_client=storage_client,
        dedup_client=valkey,
    )

    try:
        consumer_task = asyncio.create_task(consumer.run())
        await stop_event.wait()
        consumer.stop()  # type: ignore[attr-defined]
        consumer_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await consumer_task
    except Exception as exc:
        log.error("fundamentals_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    else:
        log.info("fundamentals_consumer_stopped")
    finally:
        await valkey.close()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
