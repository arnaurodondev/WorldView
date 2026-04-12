"""FastAPI application factory for content-store (S5).

Background processes (consumer, dispatcher) run as standalone entry points
per R22 — see ``dispatcher_main.py`` and ``article_consumer_main.py`` under
``infrastructure/messaging/``.
"""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import structlog.contextvars
from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from content_store.api.dlq import router as dlq_router
from content_store.api.documents import router as documents_router
from content_store.api.health import router as health_router
from content_store.config import Settings
from content_store.infrastructure.db.session import _build_factories
from content_store.infrastructure.middleware.internal_jwt import InternalJWTMiddleware
from observability import configure_logging, get_logger  # type: ignore[import-untyped]
from observability.metrics import add_prometheus_middleware, create_metrics  # type: ignore[import-untyped]
from observability.tracing import add_otel_middleware, configure_tracing  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

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


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan — sets up database and infrastructure for API endpoints.

    Background processes (consumer, dispatcher) run as standalone entry points
    per R22.  This lifespan only initialises resources the API layer needs.
    """
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

    # 3. Database — returns (engine, read_engine, write_factory, read_factory) for R23 split
    engine, read_engine, write_factory, read_factory = _build_factories(settings)

    app.state.session_factory = write_factory
    app.state.write_factory = write_factory
    app.state.read_factory = read_factory
    app.state.engine = engine
    app.state.read_engine = read_engine

    # 4. Object storage
    from storage.factory import build_object_storage  # type: ignore[import-untyped]
    from storage.settings import StorageSettings  # type: ignore[import-untyped]

    storage_settings = StorageSettings(
        endpoint=f"{'https' if settings.minio_secure else 'http'}://{settings.minio_endpoint}",
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        use_ssl=settings.minio_secure,
    )
    object_store = build_object_storage(settings=storage_settings)
    app.state.object_store = object_store

    # 5. Valkey LSH client
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

    # 6. Internal JWT middleware startup — fetch JWKS from S9 (PRD-0025)
    jwt_middleware: InternalJWTMiddleware | None = getattr(app.state, "_jwt_middleware", None)
    if jwt_middleware is not None:
        await jwt_middleware.startup()

    log.info("service_started", service=settings.service_name, port=settings.port)

    yield

    # Graceful shutdown — dispose DB engine(s) and Valkey
    await engine.dispose()
    if read_engine is not engine:
        await read_engine.dispose()
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

    # InternalJWTMiddleware (RS256 verifier — PRD-0025)
    # Store instance on app.state so lifespan can call startup() on it.
    jwks_url = f"{settings.api_gateway_url}/internal/jwks"
    jwt_middleware = InternalJWTMiddleware(app, jwks_url=jwks_url)
    app.state._jwt_middleware = jwt_middleware
    app.add_middleware(InternalJWTMiddleware, jwks_url=jwks_url)

    # Middleware — must be registered before app starts (Starlette requirement)
    app.add_middleware(RequestIdMiddleware)
    metrics = create_metrics(service_name=settings.service_name)
    add_prometheus_middleware(app, metrics)
    add_otel_middleware(app)
    app.state.metrics = metrics

    app.include_router(health_router)
    app.include_router(dlq_router)
    app.include_router(documents_router)

    return app
