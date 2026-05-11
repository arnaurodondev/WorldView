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

    Order: structlog first, then Sentry. Structlog record exists even if Sentry errors.
    Sentry call is best-effort — a Sentry outage never replaces the user's 500 with
    a different error.
    """
    from starlette.responses import JSONResponse

    log = get_logger("error_capture")
    log.error(  # type: ignore[no-any-return]
        "unhandled_exception",
        method=request.method,
        path=str(request.url.path),
        request_id=request.headers.get("X-Request-ID", ""),
        exc_info=exc,
    )

    # Forward to Sentry when initialised. Detect via sentry_sdk.get_client() so
    # services that have not called init_sentry() are silently skipped.
    try:
        import sentry_sdk  # type: ignore[import-untyped]

        client = sentry_sdk.get_client()
        if client.is_active():
            sentry_sdk.capture_exception(exc)
    except Exception as sentry_exc:
        log.warning("sentry_capture_failed", exc_info=sentry_exc)  # type: ignore[no-any-return]

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
