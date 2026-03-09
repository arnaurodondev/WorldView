"""Map domain errors to HTTP status codes."""

from __future__ import annotations

from portfolio.domain.errors import (
    AuthorizationError,
    BusinessRuleViolationError,
    ConcurrencyError,
    DomainError,
    EntityAlreadyExistsError,
    EntityNotFoundError,
    IdempotencyKeyConflictError,
    ValidationError,
)

ERROR_STATUS_MAP: dict[type[DomainError], int] = {
    EntityNotFoundError: 404,
    EntityAlreadyExistsError: 409,
    AuthorizationError: 403,
    ValidationError: 422,
    BusinessRuleViolationError: 409,
    IdempotencyKeyConflictError: 409,
    ConcurrencyError: 409,
}


def domain_error_to_status(exc: DomainError) -> int:
    """Return the HTTP status code for *exc*, walking the MRO."""
    for cls in type(exc).__mro__:
        if cls in ERROR_STATUS_MAP:
            return ERROR_STATUS_MAP[cls]
    return 500
