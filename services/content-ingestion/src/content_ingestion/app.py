"""FastAPI application factory — content-ingestion service (S4).

The API process handles HTTP requests only.  Background concerns (scheduler,
worker, outbox dispatcher) run as separate processes (R22).
"""

from __future__ import annotations

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
from content_ingestion.infrastructure.db.unit_of_work import SqlaReadOnlyUnitOfWork, SqlaUnitOfWork
from content_ingestion.infrastructure.middleware.internal_jwt import InternalJWTMiddleware
from content_ingestion.infrastructure.storage.minio_bronze import MinioBronzeAdapter
from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]
from observability import configure_logging, get_logger, register_error_handlers  # type: ignore[import-untyped]
from observability.metrics import (  # type: ignore[import-untyped]
    add_prometheus_middleware,
    create_metrics,
    create_ml_metrics,
)
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

    # 1b. Security: warn on startup if auth tokens are not configured (F-SEC-006).
    #     Prevents silent lock-out of admin endpoints in misconfigured deployments.
    if not settings.admin_token:
        log.warning("security_admin_token_not_configured", detail="admin endpoints will reject all requests")

    # 2. Tracing config (optional — middleware already registered in create_app)
    if settings.otlp_endpoint:
        configure_tracing(
            service_name=settings.service_name,
            otlp_endpoint=settings.otlp_endpoint,
        )

    # 3. Database — dual session factory (R23: read/write split)
    engine, read_engine, write_factory, read_factory = _build_factories(settings)
    app.state.engine = engine
    app.state.read_engine = read_engine
    app.state.write_factory = write_factory
    app.state.read_factory = read_factory
    app.state.uow_factory = lambda: SqlaUnitOfWork(write_factory, read_factory)
    app.state.read_uow_factory = lambda: SqlaReadOnlyUnitOfWork(read_factory)

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
    app.state.bronze_storage = MinioBronzeAdapter(storage)

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

    # 7. JWT middleware key fetch — must run after logging is configured
    jwt_mw = InternalJWTMiddleware(
        app,
        jwks_url=f"{settings.api_gateway_url}/internal/jwks",
        skip_verification=settings.internal_jwt_skip_verification,
    )
    await jwt_mw.startup()

    # PLAN-0055 A-3: seed NULL watermarks so the scheduler tick has a starting
    # cursor for every enabled source. Spawned as a non-blocking task — the API
    # process must answer /health within ~100ms, so seeding cannot block startup.
    if settings.backfill_on_startup:
        import asyncio as _asyncio

        from content_ingestion.application.use_cases.seed_source_watermarks import SeedSourceWatermarksUseCase

        seed_use_case = SeedSourceWatermarksUseCase(
            uow_factory=app.state.uow_factory,
            settings=settings,
        )

        async def _run_seed() -> None:
            try:
                await seed_use_case.execute()
            except Exception as exc:  # — fire-and-forget; never crash the API
                log.exception("startup_seed_watermarks_failed", error=str(exc))

        # Stash on app.state so the task isn't GC'd mid-flight (RUF006).
        app.state.startup_seed_task = _asyncio.create_task(_run_seed(), name="seed_source_watermarks")

    log.info("service_started", service=settings.service_name)
    yield

    # Shutdown — clean up API-owned resources only
    await http_client.aclose()
    await valkey.close()
    await engine.dispose()
    if read_engine is not engine:
        await read_engine.dispose()
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

    # Exception handlers — must be registered before middleware so that handler
    # responses are still processed by middleware layers (e.g. Prometheus timing).
    register_error_handlers(app)

    # Middleware — must be registered before app starts (Starlette requirement)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        InternalJWTMiddleware,
        jwks_url=f"{settings.api_gateway_url}/internal/jwks",
        skip_verification=settings.internal_jwt_skip_verification,
    )
    metrics = create_metrics(service_name=settings.service_name)
    ml_metrics = create_ml_metrics(settings.service_name)
    add_prometheus_middleware(app, metrics)
    add_otel_middleware(app)
    app.state.metrics = metrics
    app.state.ml_metrics = ml_metrics

    # Domain exception handlers
    _register_exception_handlers(app)

    app.include_router(health.router, tags=["health"])
    app.include_router(admin.router)
    app.include_router(dlq.router)
    app.include_router(internal.router)
    return app
