"""FastAPI application factory — S8 RAG/Chat service.

Observability wiring follows STANDARDS.md §5 (canonical lifespan pattern):
  1. configure_logging()   — always first
  2. configure_tracing()   — conditional on otlp_endpoint
  3. DB session factory    — R23 dual-URL (write + read)
  4. Valkey client
  5. Provider negative cache (populated by LLM client in later waves)
"""

from __future__ import annotations

import re
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

import structlog.contextvars
from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from observability import configure_logging, get_logger  # type: ignore[import-untyped]
from observability.metrics import add_prometheus_middleware, create_metrics  # type: ignore[import-untyped]
from observability.tracing import add_otel_middleware, configure_tracing  # type: ignore[import-untyped]
from rag_chat.api import health as health_router
from rag_chat.infrastructure.config.settings import RagChatSettings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable

_VALID_REQUEST_ID_RE = re.compile(r"^[a-zA-Z0-9\-]{1,64}$")


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Propagate X-Request-ID through the request lifecycle."""

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
    settings: RagChatSettings = app.state.settings

    # 1. Logging — always first
    configure_logging(
        service_name=settings.service_name,
        level=settings.log_level,
        json=settings.log_json,
    )
    log = get_logger("rag_chat.app")  # type: ignore[no-any-return]

    # 2. Tracing — conditional
    if settings.otlp_endpoint:
        configure_tracing(
            service_name=settings.service_name,
            otlp_endpoint=settings.otlp_endpoint,
        )

    # 3. DB session factory — R23 dual-URL
    from rag_chat.infrastructure.db.session import create_rag_session_factory

    engine, write_factory, read_factory = create_rag_session_factory(
        settings.rag_db_url,
        settings.rag_db_url_read,
    )
    app.state.engine = engine
    app.state.write_factory = write_factory
    app.state.read_factory = read_factory

    # 4. Valkey / Redis client
    import redis.asyncio as aioredis

    valkey: aioredis.Redis = aioredis.Redis.from_url(  # type: ignore[type-arg]
        settings.valkey_url,
        decode_responses=False,
    )
    app.state.valkey = valkey

    # 5. Provider negative cache (populated by LLM client in later waves)
    app.state.provider_cache = {}  # type: ignore[assignment]

    log.info("rag_chat_started", service=settings.service_name)  # type: ignore[no-any-return]
    yield

    # Shutdown — reverse order
    await valkey.aclose()
    await engine.dispose()
    log.info("rag_chat_stopped", service=settings.service_name)  # type: ignore[no-any-return]


def create_app(settings: RagChatSettings | None = None) -> FastAPI:
    """Create and configure the FastAPI application instance."""
    resolved = settings or RagChatSettings()  # type: ignore[call-arg]

    app = FastAPI(
        title="rag-chat",
        version="2025.6.0",
        lifespan=lifespan,
    )
    app.state.settings = resolved

    # Middleware (must be registered before startup)
    app.add_middleware(RequestIdMiddleware)
    metrics: Any = create_metrics(service_name=resolved.service_name)
    add_prometheus_middleware(app, metrics)
    add_otel_middleware(app)
    app.state.metrics = metrics

    # Routers
    app.include_router(health_router.router)

    return app
