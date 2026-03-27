"""FastAPI application factory for content-store (S5)."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import structlog.contextvars
from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from content_store.api.dlq import router as dlq_router
from content_store.api.health import router as health_router
from content_store.config import Settings
from content_store.infrastructure.consumer.article_consumer import ArticleConsumer, ArticleConsumerConfig
from content_store.infrastructure.db.session import create_session_factory
from content_store.infrastructure.outbox.dispatcher import ContentStoreOutboxDispatcher
from observability import configure_logging, get_logger  # type: ignore[import-untyped]
from observability.metrics import add_prometheus_middleware, create_metrics  # type: ignore[import-untyped]
from observability.tracing import add_otel_middleware, configure_tracing  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

_log = get_logger(__name__)  # type: ignore[no-any-return]


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Propagate X-Request-ID through the request lifecycle."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        import common.ids

        request_id = request.headers.get("X-Request-ID") or common.ids.new_ulid()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = str(request_id)
        structlog.contextvars.clear_contextvars()
        return response


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
    settings: Settings = app.state.settings

    # 1. Logging — always first
    configure_logging(
        service_name=settings.service_name,
        level=settings.log_level,
        json=settings.log_json,
    )
    log = get_logger("content_store.app")

    # 2. Tracing config (optional — middleware already registered in create_app)
    if settings.otlp_endpoint:
        configure_tracing(
            service_name=settings.service_name,
            otlp_endpoint=settings.otlp_endpoint,
        )

    # 3. Database — returns (engine, factory) so we can dispose on shutdown
    engine, session_factory = create_session_factory(settings)

    app.state.session_factory = session_factory
    app.state.engine = engine

    # 5. Object storage
    from storage.factory import build_object_storage  # type: ignore[import-untyped]
    from storage.settings import StorageSettings  # type: ignore[import-untyped]

    storage_settings = StorageSettings(
        endpoint=f"{'https' if settings.minio_secure else 'http'}://{settings.minio_endpoint}",
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        use_ssl=settings.minio_secure,
    )
    object_store = build_object_storage(settings=storage_settings)

    # 6. Valkey LSH client
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

    # 7. Consumer
    consumer_config = ArticleConsumerConfig(settings)
    consumer = ArticleConsumer(
        config=consumer_config,
        session_factory=session_factory,
        object_store=object_store,
        lsh_client=lsh_client,
    )
    app.state.consumer = consumer
    app.state.consumer_alive = True

    # 8. Dispatcher
    app.state.dispatcher = ContentStoreOutboxDispatcher(settings, session_factory)

    # 9. Background tasks
    tasks: list[asyncio.Task[None]] = []

    async def _run_metrics() -> None:
        await _poll_metrics(settings, session_factory)

    tasks.append(asyncio.create_task(_run_metrics()))

    log.info("service_started", service=settings.service_name, port=settings.port)

    yield

    # Shutdown
    for task in tasks:
        task.cancel()
    consumer.stop()
    await engine.dispose()
    log.info("service_stopped", service=settings.service_name)


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = Settings()

    app = FastAPI(
        title="content-store",
        version="2025.6.0",
        lifespan=lifespan,
    )
    app.state.settings = settings

    # Middleware — must be registered before app starts (Starlette requirement)
    app.add_middleware(RequestIdMiddleware)
    metrics = create_metrics(service_name=settings.service_name)
    add_prometheus_middleware(app, metrics)
    add_otel_middleware(app)
    app.state.metrics = metrics

    app.include_router(health_router)
    app.include_router(dlq_router)

    return app
