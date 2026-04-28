"""FastAPI application factory for market-ingestion service."""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import structlog.contextvars
from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from market_ingestion.config import Settings
from market_ingestion.infrastructure.middleware.internal_jwt import InternalJWTMiddleware
from observability import configure_logging, get_logger, register_error_handlers  # type: ignore[import-untyped]
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
    """Manage application lifecycle: startup and shutdown."""
    settings: Settings = app.state.settings

    # 1. Logging — always first
    configure_logging(
        service_name=settings.service_name,
        level=settings.log_level,
        json=settings.log_json,
    )
    log = get_logger("market_ingestion.app")

    # 2. Tracing config (optional — middleware already registered in create_app)
    if settings.otlp_endpoint:
        configure_tracing(
            service_name=settings.service_name,
            otlp_endpoint=settings.otlp_endpoint,
        )

    # 3. DB session factories — built once at startup, shared across all requests
    from market_ingestion.infrastructure.db.session import _build_factories

    write_factory, read_factory = _build_factories(settings)
    app.state.write_session_factory = write_factory
    app.state.read_session_factory = read_factory

    # 4. InternalJWTMiddleware startup (PRD-0025 Wave D)
    jwt_middleware = InternalJWTMiddleware(
        app,
        jwks_url=f"{settings.api_gateway_url}/internal/jwks",
        skip_verification=settings.internal_jwt_skip_verification,
    )
    await jwt_middleware.startup()
    app.state._jwt_middleware = jwt_middleware

    log.info("service_started", service=settings.service_name, version=app.version)
    yield
    log.info("service_stopped", service=settings.service_name)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="market-ingestion",
        version="2026.3.0",
        lifespan=lifespan,
    )
    _settings = settings or Settings()  # type: ignore[call-arg]
    app.state.settings = _settings

    # Exception handlers — must be registered before middleware so that handler
    # responses are still processed by middleware layers (e.g. Prometheus timing).
    register_error_handlers(app)

    # Middleware — must be registered before app starts (Starlette requirement)
    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        InternalJWTMiddleware,
        jwks_url=f"{_settings.api_gateway_url}/internal/jwks",
        skip_verification=_settings.internal_jwt_skip_verification,
    )
    metrics = create_metrics(service_name=_settings.service_name)
    add_prometheus_middleware(app, metrics)
    add_otel_middleware(app)
    app.state.metrics = metrics

    from market_ingestion.api.routes import router

    app.include_router(router)

    return app
