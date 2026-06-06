"""Standalone article consumer entry point for the Content Store service (S5).

Runs as an independent process (R22) with its own session factory, object store,
LSH client, and signal handling.

Run with::

    python -m content_store.infrastructure.messaging.consumers.article_consumer_main
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
    from content_store.infrastructure.messaging.consumers.article_consumer import (
        ArticleConsumer,
        ArticleConsumerConfig,
    )
    from content_store.infrastructure.valkey.lsh_client import LSHConfig, ValkeyLSHClient
    from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]
    from storage.factory import build_object_storage  # type: ignore[import-untyped]
    from storage.settings import StorageSettings  # type: ignore[import-untyped]

    settings = Settings()
    configure_logging(
        service_name="content-store-consumer",
        level=settings.log_level,
        json=settings.log_json,
    )

    log = get_logger("content_store.article_consumer_main")  # type: ignore[no-any-return]
    log.info("article_consumer_starting", service="content-store")

    # Phase 3 worker-metrics rollout — expose Prometheus /metrics on a
    # dedicated port so the worker's counters/gauges become scrape-able.
    metrics_handle = start_metrics_server(
        service_name="content-store-consumer",
        port=int(os.environ.get("METRICS_PORT", "9100")),
    )

    stop_event = asyncio.Event()

    def _handle_signal(sig: int) -> None:
        log.info("shutdown_signal_received", signal=sig)
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_signal, sig)

    # Database — write factory only (consumer writes processed_events + outbox)
    _engine, _read_engine, write_factory, _read_factory = _build_factories(settings)

    # Object storage (MinIO)
    storage_settings = StorageSettings(
        endpoint=f"{'https' if settings.minio_secure else 'http'}://{settings.minio_endpoint}",
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        use_ssl=settings.minio_secure,
    )
    object_store = build_object_storage(settings=storage_settings)

    # Valkey LSH client
    valkey_client = create_valkey_client_from_url(settings.valkey_url)
    lsh_config = LSHConfig(
        num_bands=settings.lsh_num_bands,
        rows_per_band=settings.lsh_rows_per_band,
        num_perm=settings.minhash_num_perm,
    )
    lsh_client = ValkeyLSHClient(valkey_client, lsh_config)

    # Consumer
    consumer_config = ArticleConsumerConfig(settings)
    consumer = ArticleConsumer(
        config=consumer_config,
        session_factory=write_factory,
        object_store=object_store,
        lsh_client=lsh_client,
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
        log.error("article_consumer_fatal_error", error=str(exc))
        sys.exit(1)
    else:
        log.info("article_consumer_stopped")
    finally:
        await valkey_client.close()
        await _engine.dispose()
        if _read_engine is not _engine:
            await _read_engine.dispose()

        # Stop the Prometheus metrics HTTP server cleanly.
        with contextlib.suppress(Exception):
            await metrics_handle.aclose()


if __name__ == "__main__":
    asyncio.run(main())
