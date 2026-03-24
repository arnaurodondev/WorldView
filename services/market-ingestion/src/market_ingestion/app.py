"""FastAPI application factory for market-ingestion service."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request, Response

from market_ingestion.config import Settings

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Manage application lifecycle: startup and shutdown."""
    from observability.logging import get_logger  # type: ignore[import-untyped]

    logger = get_logger(__name__)
    settings: Settings = app.state.settings

    logger.info("market_ingestion_starting", version=app.version)

    # Configure OTel tracing if endpoint configured (field added in T-MI-25)
    otlp_endpoint = getattr(settings, "otlp_endpoint", None)
    if otlp_endpoint:
        try:
            from observability.tracing import configure_tracing  # type: ignore[import-untyped]

            configure_tracing(service_name="market-ingestion", endpoint=otlp_endpoint)  # type: ignore[call-arg]
            logger.info("otel_tracing_configured", endpoint=otlp_endpoint)
        except Exception as exc:
            logger.warning("otel_tracing_setup_failed", error=str(exc))

    yield

    logger.info("market_ingestion_stopped")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    from observability.logging import get_logger  # type: ignore[import-untyped]

    logger = get_logger(__name__)
    settings = Settings()

    app = FastAPI(
        title="market-ingestion",
        version="2026.3.0",
        lifespan=lifespan,
    )
    app.state.settings = settings

    # Request-ID middleware: generate X-Request-ID if absent, bind to log context
    @app.middleware("http")
    async def request_id_middleware(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        import common.ids

        request_id = request.headers.get("X-Request-ID") or common.ids.new_ulid()
        try:
            import structlog

            structlog.contextvars.bind_contextvars(request_id=request_id)
        except Exception as exc:
            logger.debug("request_id_bind_failed", error=str(exc))
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response

    # Prometheus middleware
    try:
        from observability.metrics import add_prometheus_middleware  # type: ignore[import-untyped]

        add_prometheus_middleware(app)  # type: ignore[call-arg]
    except Exception as exc:
        logger.warning("prometheus_middleware_setup_failed", error=str(exc))

    # OTel middleware
    try:
        from observability.tracing import add_otel_middleware  # type: ignore[import-untyped]

        add_otel_middleware(app)  # type: ignore[call-arg]
    except Exception as exc:
        logger.warning("otel_middleware_setup_failed", error=str(exc))

    from market_ingestion.api.routes import router

    app.include_router(router)

    return app
