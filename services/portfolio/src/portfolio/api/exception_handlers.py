"""FastAPI exception handlers for domain and unhandled errors."""

from __future__ import annotations

from typing import TYPE_CHECKING

from fastapi.responses import JSONResponse

from observability import get_logger  # type: ignore[import-untyped]
from portfolio.api.error_mapping import domain_error_to_status
from portfolio.api.schemas import ErrorResponse
from portfolio.domain.errors import DomainError

if TYPE_CHECKING:
    from fastapi import Request

logger = get_logger(__name__)  # type: ignore[no-any-return]


async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
    status_code = domain_error_to_status(exc)
    body = ErrorResponse(
        error_code=exc.error_code,
        message=exc.message,
        details=exc.details,
    )
    return JSONResponse(status_code=status_code, content=body.model_dump())


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "unhandled_exception",
        path=str(request.url.path),
        error=str(exc),
        exc_info=True,
    )
    body = ErrorResponse(
        error_code="INTERNAL_ERROR",
        message="An unexpected error occurred.",
    )
    return JSONResponse(status_code=500, content=body.model_dump())
