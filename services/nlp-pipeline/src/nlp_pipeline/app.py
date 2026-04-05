"""FastAPI application factory — NLP Pipeline service (S6).

Background processes (consumers, dispatcher) run as standalone entry points
per R22 — see ``dispatcher_main.py``, ``article_consumer_main.py``, and
``watchlist_consumer_main.py`` under ``infrastructure/messaging/``.

Lifespan sequence (STANDARDS.md §5):
  1. configure_logging()   ← always first
  2. configure_tracing()   ← conditional on otlp_endpoint
  3. Database engines (nlp_db + intelligence_db)
  4. Valkey client + WatchlistCache
"""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

import structlog.contextvars
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from nlp_pipeline.api.routes import dlq, entities, health, search, signals
from nlp_pipeline.config import Settings
from nlp_pipeline.infrastructure.intelligence_db.session import (
    _build_intelligence_factories,
)
from nlp_pipeline.infrastructure.nlp_db.session import _build_nlp_factories
from observability import configure_logging, get_logger  # type: ignore[import-untyped]
from observability.metrics import add_prometheus_middleware, create_metrics  # type: ignore[import-untyped]
from observability.tracing import add_otel_middleware, configure_tracing  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

logger = get_logger("nlp_pipeline.app")  # type: ignore[no-any-return]

_VALID_REQUEST_ID_RE = re.compile(r"^[a-zA-Z0-9\-]{1,64}$")


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Propagate X-Request-ID through the request lifecycle (STANDARDS.md §5)."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        import common.ids  # type: ignore[import-untyped]

        raw_id = request.headers.get("X-Request-ID", "")
        request_id = raw_id if _VALID_REQUEST_ID_RE.match(raw_id) else common.ids.new_ulid()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = str(request_id)
        structlog.contextvars.clear_contextvars()
        return response


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan — sets up database and Valkey for API endpoints.

    Background processes (consumers, dispatcher) run as standalone entry points
    per R22.  This lifespan only initialises resources the API layer needs.
    """
    settings: Settings = app.state.settings

    # 1. Logging — always first
    configure_logging(
        service_name=settings.service_name,
        level=settings.log_level,
        json=settings.log_json,
    )
    log = get_logger("nlp_pipeline.app")  # type: ignore[no-any-return]

    # 2. Tracing (conditional)
    if settings.otlp_endpoint:
        configure_tracing(
            service_name=settings.service_name,
            otlp_endpoint=settings.otlp_endpoint,
        )

    # 3. Database engines — R23 dual factory (write + read) for both DBs
    nlp_engine, nlp_sf, nlp_read_sf = _build_nlp_factories(settings)
    intel_engine, intel_sf, intel_read_sf = _build_intelligence_factories(settings)
    app.state.nlp_engine = nlp_engine
    app.state.intel_engine = intel_engine
    app.state.nlp_session_factory = nlp_sf
    app.state.nlp_write_factory = nlp_sf
    app.state.nlp_read_factory = nlp_read_sf
    app.state.intelligence_session_factory = intel_sf
    app.state.intel_write_factory = intel_sf
    app.state.intel_read_factory = intel_read_sf

    # 4. Valkey + WatchlistCache
    from messaging.valkey import create_valkey_client_from_url  # type: ignore[import-untyped]
    from nlp_pipeline.infrastructure.valkey.watchlist_cache import WatchlistCache

    valkey = create_valkey_client_from_url(settings.valkey_url)
    watchlist_cache = WatchlistCache(client=valkey._redis, key=settings.valkey_watchlist_key)  # type: ignore[attr-defined]
    app.state.valkey = valkey
    app.state.watchlist_cache = watchlist_cache

    log.info("service_started", service=settings.service_name)
    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    await valkey.close()
    await nlp_engine.dispose()
    await intel_engine.dispose()
    log.info("service_stopped", service=settings.service_name)


def _register_exception_handlers(app: FastAPI) -> None:
    from nlp_pipeline.domain.errors import NLPDomainError

    @app.exception_handler(NLPDomainError)
    async def _domain_error(_request: Request, exc: NLPDomainError) -> JSONResponse:
        logger.warning("domain_error", error=str(exc))  # type: ignore[no-any-return]
        return JSONResponse(status_code=422, content={"error": "domain_error", "detail": str(exc)})

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_error", error=str(exc))  # type: ignore[no-any-return]
        return JSONResponse(status_code=500, content={"error": "internal_error"})


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the NLP Pipeline FastAPI application."""
    app = FastAPI(
        title="nlp-pipeline",
        version="2025.6.0",
        lifespan=lifespan,
    )
    settings = settings or Settings()
    app.state.settings = settings

    # Middleware (must be registered before lifespan starts)
    app.add_middleware(RequestIdMiddleware)
    metrics = create_metrics(service_name=settings.service_name)
    add_prometheus_middleware(app, metrics)
    add_otel_middleware(app)
    app.state.metrics = metrics

    _register_exception_handlers(app)

    app.include_router(health.router, tags=["health"])
    app.include_router(signals.router)
    app.include_router(entities.router)
    app.include_router(search.router)
    app.include_router(dlq.router)

    return app
