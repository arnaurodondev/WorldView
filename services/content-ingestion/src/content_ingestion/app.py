"""FastAPI application factory — content-ingestion service (S4).

The API process handles HTTP requests only.  Background concerns (scheduler,
worker, outbox dispatcher) run as separate processes (R22).
"""

from __future__ import annotations

import asyncio
import contextlib
import re
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import httpx
import structlog.contextvars
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from content_ingestion.api.routes import admin, dlq, health, internal
from content_ingestion.config import Settings
from content_ingestion.infrastructure.db.session import _build_factories
from content_ingestion.infrastructure.metrics.prometheus import s4_dlq_total, s4_outbox_pending_total
from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]
from observability import configure_logging, get_logger  # type: ignore[import-untyped]
from observability.metrics import add_prometheus_middleware, create_metrics  # type: ignore[import-untyped]
from observability.tracing import add_otel_middleware, configure_tracing  # type: ignore[import-untyped]
from storage.factory import build_object_storage  # type: ignore[import-untyped]
from storage.settings import StorageSettings  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

logger_mod = get_logger("content_ingestion.app")  # type: ignore[no-any-return]


_VALID_REQUEST_ID_RE = re.compile(r"^[a-zA-Z0-9\-]{1,64}$")


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Propagate X-Request-ID through the request lifecycle.

    Validates the incoming header: only alphanumeric + hyphens, max 64 chars.
    Invalid or missing values are replaced with a fresh ULID.
    """

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        import common.ids

        raw_id = request.headers.get("X-Request-ID", "")
        request_id = raw_id if _VALID_REQUEST_ID_RE.match(raw_id) else common.ids.new_ulid()
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


async def _metrics_poller(session_factory: object, interval: int) -> None:
    """Periodically update outbox/DLQ gauge metrics."""
    from sqlalchemy import func, select

    from content_ingestion.infrastructure.db.models import DeadLetterQueueModel, OutboxEventModel

    while True:
        try:
            async with session_factory() as session:  # type: ignore[operator]
                outbox_result = await session.execute(
                    select(func.count()).select_from(OutboxEventModel).where(OutboxEventModel.status == "pending")
                )
                s4_outbox_pending_total.set(outbox_result.scalar() or 0)

                dlq_result = await session.execute(
                    select(func.count())
                    .select_from(DeadLetterQueueModel)
                    .where(DeadLetterQueueModel.status == "failed")
                )
                s4_dlq_total.set(dlq_result.scalar() or 0)
        except Exception:
            logger_mod.debug("metrics_poll_error", exc_info=True)
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings

    # 1. Logging — always first
    configure_logging(
        service_name=settings.service_name,
        level=settings.log_level,
        json=settings.log_json,
    )
    log = get_logger("content_ingestion.app")

    # 2. Tracing config (optional — middleware already registered in create_app)
    if settings.otlp_endpoint:
        configure_tracing(
            service_name=settings.service_name,
            otlp_endpoint=settings.otlp_endpoint,
        )

    # 3. Database — dual session factory (R23: read/write split)
    engine, write_factory, read_factory = _build_factories(settings)
    session_factory = write_factory  # backward compat alias
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.write_factory = write_factory
    app.state.read_factory = read_factory

    # 4. Valkey
    valkey = create_valkey_client_from_url(settings.valkey_url)
    app.state.valkey = valkey

    # 5. Object storage (bronze tier)
    storage_settings = StorageSettings(
        endpoint=_normalize_endpoint(settings.minio_endpoint),
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        use_ssl=settings.minio_secure,
        default_bucket=settings.minio_bucket,
    )
    storage = build_object_storage(settings=storage_settings)
    app.state.storage = storage

    # 6. HTTP client with SSRF-safe transport (DNS rebinding prevention — BP-024)
    from content_ingestion.infrastructure.http.ssrf_transport import SSRFSafeTransport

    http_client = httpx.AsyncClient(
        transport=SSRFSafeTransport(),
        timeout=httpx.Timeout(
            settings.http_client.timeout_seconds,
            connect=settings.http_client.connect_timeout_seconds,
        ),
    )
    app.state.http_client = http_client

    # 7. Metrics poller (lightweight — OK in API process)
    metrics_task: asyncio.Task[None] = asyncio.create_task(
        _metrics_poller(session_factory, settings.outbox_metrics_poll_seconds)
    )

    log.info("service_started", service=settings.service_name)
    yield

    # Shutdown — clean up API-owned resources only
    metrics_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await metrics_task

    await http_client.aclose()
    await valkey.close()
    await engine.dispose()
    log.info("service_stopped", service=settings.service_name)


def _register_exception_handlers(app: FastAPI) -> None:
    """Map domain exceptions to appropriate HTTP status codes."""
    from content_ingestion.domain.exceptions import AdapterError, ConfigurationError, QuotaExhaustedError, StorageError

    @app.exception_handler(AdapterError)
    async def _adapter_error(_request: Request, exc: AdapterError) -> JSONResponse:
        logger_mod.error("adapter_error", error=str(exc))
        return JSONResponse(status_code=502, content={"error": "bad_gateway", "detail": "Upstream source error"})

    @app.exception_handler(QuotaExhaustedError)
    async def _quota_error(_request: Request, exc: QuotaExhaustedError) -> JSONResponse:
        logger_mod.warning("quota_exhausted", error=str(exc))
        return JSONResponse(status_code=429, content={"error": "too_many_requests", "detail": "Quota exhausted"})

    @app.exception_handler(ConfigurationError)
    async def _config_error(_request: Request, exc: ConfigurationError) -> JSONResponse:
        logger_mod.error("configuration_error", error=str(exc))
        return JSONResponse(status_code=500, content={"error": "internal_error", "detail": "Service misconfiguration"})

    @app.exception_handler(StorageError)
    async def _storage_error(_request: Request, exc: StorageError) -> JSONResponse:
        logger_mod.error("storage_error", error=str(exc))
        return JSONResponse(status_code=503, content={"error": "service_unavailable", "detail": "Storage unavailable"})

    @app.exception_handler(Exception)
    async def _unhandled_error(_request: Request, exc: Exception) -> JSONResponse:
        logger_mod.exception("unhandled_error", error=str(exc))
        return JSONResponse(status_code=500, content={"error": "internal_error"})


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        settings: Optional pre-built settings (for testing). Created automatically if None.
    """
    app = FastAPI(
        title="content-ingestion",
        version="2025.6.0",
        lifespan=lifespan,
    )
    settings = settings or Settings()
    app.state.settings = settings

    # Middleware — must be registered before app starts (Starlette requirement)
    app.add_middleware(RequestIdMiddleware)
    metrics = create_metrics(service_name=settings.service_name)
    add_prometheus_middleware(app, metrics)
    add_otel_middleware(app)
    app.state.metrics = metrics

    # Domain exception handlers
    _register_exception_handlers(app)

    app.include_router(health.router, tags=["health"])
    app.include_router(admin.router)
    app.include_router(dlq.router)
    app.include_router(internal.router)
    return app
