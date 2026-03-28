"""FastAPI application factory with APScheduler + Kafka co-topology lifespan."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI

from knowledge_graph.config import Settings
from observability import get_logger  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

logger = get_logger(__name__)  # type: ignore[no-any-return]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start APScheduler + Kafka consumers; stop on shutdown.

    In production:
      1. Build intelligence_db session factory.
      2. Build embedding client and direct Kafka producer.
      3. Instantiate consumers and scheduler.
      4. Start scheduler (registers 8 job stubs) and consumer task.
      5. On shutdown: stop() scheduler and cancel consumer task.

    For Wave D-2 the infrastructure wiring is scaffolded here but the
    actual dependency construction is deferred until Wave D-4 (API + full
    integration).  The scheduler and consumers CAN be started by passing
    the required dependencies into ``KnowledgeGraphScheduler.start()``.
    """
    settings = Settings()
    logger.info("knowledge_graph_startup", service=settings.service_name)  # type: ignore[no-any-return]

    # Scaffold: scheduler and consumers will be wired here in Wave D-4.
    # For now the lifespan starts cleanly with no background tasks.
    yield

    logger.info("knowledge_graph_shutdown", service=settings.service_name)  # type: ignore[no-any-return]


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    Settings()  # Validate config on startup

    app = FastAPI(
        title="knowledge-graph",
        version="2025.6.0",
        lifespan=lifespan,
    )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> dict[str, str]:
        # TODO Wave D-4: check DB, Kafka, Ollama
        return {"status": "ok"}

    return app
