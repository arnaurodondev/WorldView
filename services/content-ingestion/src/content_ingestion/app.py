"""FastAPI application factory — content-ingestion service (S4)."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import structlog.contextvars  # context binding only — logger via observability.get_logger
from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from content_ingestion.api.routes import health
from content_ingestion.config import Settings
from content_ingestion.infrastructure.db.session import create_session_factory
from content_ingestion.infrastructure.messaging.outbox.dispatcher import ContentIngestionOutboxDispatcher
from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]
from observability import configure_logging, get_logger  # type: ignore[import-untyped]
from observability.metrics import add_prometheus_middleware, create_metrics  # type: ignore[import-untyped]
from observability.tracing import add_otel_middleware, configure_tracing  # type: ignore[import-untyped]
from storage.factory import build_object_storage  # type: ignore[import-untyped]
from storage.settings import StorageSettings  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable


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


def _normalize_endpoint(endpoint: str) -> str:
    """Ensure MinIO endpoint has an explicit HTTP(S) scheme."""
    if endpoint.startswith("http://") or endpoint.startswith("https://"):
        return endpoint
    return f"http://{endpoint}"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = Settings()
    app.state.settings = settings

    # 1. Logging — always first
    configure_logging(
        service_name="content-ingestion",
        level=settings.log_level,
        json=settings.log_json,
    )
    logger = get_logger("content_ingestion.app")

    # 2. Metrics
    metrics = create_metrics(service_name="content-ingestion")
    add_prometheus_middleware(app, metrics)
    app.state.metrics = metrics

    # 3. Tracing (optional)
    if settings.otlp_endpoint:
        configure_tracing(
            service_name="content-ingestion",
            otlp_endpoint=settings.otlp_endpoint,
        )
        add_otel_middleware(app)

    # 4. Database
    session_factory = create_session_factory(settings)
    app.state.session_factory = session_factory

    # 5. Valkey
    valkey = create_valkey_client_from_url(settings.valkey_url)
    app.state.valkey = valkey

    # 6. Object storage (bronze tier)
    storage_settings = StorageSettings(
        endpoint=_normalize_endpoint(settings.minio_endpoint),
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        use_ssl=settings.minio_secure,
        default_bucket=settings.minio_bucket,
    )
    storage = build_object_storage(
        settings=storage_settings,
    )
    app.state.storage = storage

    # 7. Outbox dispatcher (background task)
    dispatcher = ContentIngestionOutboxDispatcher(
        settings=settings,
        session_factory=session_factory,
    )
    dispatch_task: asyncio.Task[Any] = asyncio.create_task(dispatcher.run())
    app.state.dispatcher = dispatcher

    logger.info("service_started", service="content-ingestion")
    yield

    dispatcher.stop()
    await dispatch_task
    await valkey.close()
    logger.info("service_stopped", service="content-ingestion")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="content-ingestion",
        version="2025.6.0",
        lifespan=lifespan,
    )
    app.add_middleware(RequestIdMiddleware)
    app.include_router(health.router, tags=["health"])
    return app
