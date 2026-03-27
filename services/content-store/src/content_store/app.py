"""FastAPI application factory for content-store (S5)."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI

from content_store.api.dlq import router as dlq_router
from content_store.api.health import router as health_router
from content_store.config import Settings
from content_store.infrastructure.consumer.article_consumer import ArticleConsumer, ArticleConsumerConfig
from content_store.infrastructure.db.session import create_session_factory
from content_store.infrastructure.outbox.dispatcher import ContentStoreOutboxDispatcher
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

_log = get_logger(__name__)  # type: ignore[no-any-return]


async def _poll_metrics(settings: Settings, session_factory: object) -> None:
    """Periodically update Prometheus gauge metrics."""
    from sqlalchemy import func, select

    from content_store.infrastructure.db.models import DeadLetterQueueModel, OutboxEventModel
    from content_store.infrastructure.metrics.prometheus import s5_dlq_total, s5_outbox_pending_total

    interval = settings.outbox_metrics_poll_seconds
    while True:
        try:
            async with session_factory() as session:  # type: ignore[operator]
                outbox_result = await session.execute(
                    select(func.count())
                    .select_from(OutboxEventModel)
                    .where(OutboxEventModel.status.in_(["pending", "processing"]))
                )
                s5_outbox_pending_total.set(outbox_result.scalar() or 0)

                dlq_result = await session.execute(
                    select(func.count())
                    .select_from(DeadLetterQueueModel)
                    .where(DeadLetterQueueModel.status == "failed")
                )
                s5_dlq_total.set(dlq_result.scalar() or 0)
        except Exception:
            _log.warning("metrics_poll_failed", exc_info=True)

        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan — start consumer, dispatcher, metrics poller."""
    settings = Settings()
    session_factory = create_session_factory(settings)

    app.state.settings = settings
    app.state.session_factory = session_factory

    # Build object storage
    from storage.factory import build_object_storage  # type: ignore[import-untyped]
    from storage.settings import StorageSettings  # type: ignore[import-untyped]

    storage_settings = StorageSettings(
        endpoint=f"{'https' if settings.minio_secure else 'http'}://{settings.minio_endpoint}",
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        use_ssl=settings.minio_secure,
    )
    object_store = build_object_storage(settings=storage_settings)

    # Build Valkey LSH client
    from content_store.infrastructure.valkey.lsh_client import LSHConfig, ValkeyLSHClient
    from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]

    valkey_client = create_valkey_client_from_url(settings.valkey_url)
    lsh_config = LSHConfig(
        num_bands=settings.lsh_num_bands,
        rows_per_band=settings.lsh_rows_per_band,
        num_perm=settings.minhash_num_perm,
    )
    lsh_client = ValkeyLSHClient(valkey_client, lsh_config)
    app.state.valkey = valkey_client
    app.state.lsh_client = lsh_client

    # Build consumer
    consumer_config = ArticleConsumerConfig(settings)
    consumer = ArticleConsumer(
        config=consumer_config,
        session_factory=session_factory,
        object_store=object_store,
        lsh_client=lsh_client,
    )
    app.state.consumer = consumer
    app.state.consumer_alive = True

    # Build dispatcher (stored on app.state for lifecycle management)
    app.state.dispatcher = ContentStoreOutboxDispatcher(settings, session_factory)

    # Start background tasks
    tasks: list[asyncio.Task[None]] = []

    async def _run_metrics() -> None:
        await _poll_metrics(settings, session_factory)

    tasks.append(asyncio.create_task(_run_metrics()))

    _log.info("content_store_started", port=settings.port)

    yield

    # Shutdown
    for task in tasks:
        task.cancel()
    consumer.stop()
    _log.info("content_store_stopped")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="content-store",
        version="2025.6.0",
        lifespan=lifespan,
    )

    app.include_router(health_router)
    app.include_router(dlq_router)

    return app
