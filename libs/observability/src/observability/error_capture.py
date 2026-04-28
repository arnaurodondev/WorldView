"""Shared FastAPI exception handler for unhandled errors."""

from __future__ import annotations

from typing import TYPE_CHECKING

from observability.logging import get_logger

if TYPE_CHECKING:
    from fastapi import FastAPI
    from starlette.requests import Request
    from starlette.responses import JSONResponse


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Log unhandled exceptions with full context and return a generic 500 response.

    Registered via :func:`register_error_handlers`. Without this handler, FastAPI
    swallows the traceback and returns a plain 500 with no structlog record, making
    incidents invisible to Loki/Grafana. (Audit finding F-008)
    """
    from starlette.responses import JSONResponse

    log = get_logger("error_capture")
    log.error(
        "unhandled_exception",
        method=request.method,
        path=str(request.url.path),
        request_id=request.headers.get("X-Request-ID", ""),
        exc_info=exc,
    )
    return JSONResponse(status_code=500, content={"detail": "internal server error"})


def register_error_handlers(app: FastAPI) -> None:
    """Register the unhandled exception handler on *app*.

    Call this immediately after creating the FastAPI app object, before adding
    other middleware, so the handler sits at the outermost layer of the stack.

    Example::

        app = FastAPI()
        register_error_handlers(app)
        app.add_middleware(...)
    """
    app.add_exception_handler(Exception, unhandled_exception_handler)  # type: ignore[arg-type]
