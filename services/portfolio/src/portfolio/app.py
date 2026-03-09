"""FastAPI application factory."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import FastAPI

from portfolio.api.exception_handlers import domain_error_handler, unhandled_exception_handler
from portfolio.api.routes import api_router
from portfolio.config import Settings
from portfolio.domain.errors import DomainError
from portfolio.infrastructure.db.session import create_session_factory

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    engine, session_factory = create_session_factory(settings.database_url)
    app.state.session_factory = session_factory
    app.state.engine = engine
    yield
    await engine.dispose()


def create_app() -> FastAPI:
    settings = Settings()
    app = FastAPI(
        title="portfolio",
        version="2025.6.0",
        lifespan=lifespan,
    )
    app.state.settings = settings

    app.add_exception_handler(DomainError, domain_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)

    app.include_router(api_router)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz() -> dict[str, str]:
        return {"status": "ok"}

    return app
