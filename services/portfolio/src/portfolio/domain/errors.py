"""Domain error hierarchy for the Portfolio service."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from uuid import UUID


class DomainError(Exception):
    """Base class for all domain errors."""

    error_code: str = "DOMAIN_ERROR"

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        tenant_id: UUID | None = None,
        user_id: UUID | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details or {}
        self.tenant_id = tenant_id
        self.user_id = user_id

    def __str__(self) -> str:
        return f"[{self.error_code}] {self.message}"


# ── Not Found ─────────────────────────────────────────────────────────────────


class EntityNotFoundError(DomainError):
    error_code = "ENTITY_NOT_FOUND"


class TenantNotFoundError(EntityNotFoundError):
    error_code = "TENANT_NOT_FOUND"


class UserNotFoundError(EntityNotFoundError):
    error_code = "USER_NOT_FOUND"


class PortfolioNotFoundError(EntityNotFoundError):
    error_code = "PORTFOLIO_NOT_FOUND"


class TransactionNotFoundError(EntityNotFoundError):
    error_code = "TRANSACTION_NOT_FOUND"


class HoldingNotFoundError(EntityNotFoundError):
    error_code = "HOLDING_NOT_FOUND"


class InstrumentNotFoundError(EntityNotFoundError):
    error_code = "INSTRUMENT_NOT_FOUND"


# ── Already Exists ─────────────────────────────────────────────────────────────


class EntityAlreadyExistsError(DomainError):
    error_code = "ENTITY_ALREADY_EXISTS"


class TenantAlreadyExistsError(EntityAlreadyExistsError):
    error_code = "TENANT_ALREADY_EXISTS"


class UserAlreadyExistsError(EntityAlreadyExistsError):
    error_code = "USER_ALREADY_EXISTS"


class PortfolioAlreadyExistsError(EntityAlreadyExistsError):
    error_code = "PORTFOLIO_ALREADY_EXISTS"


# ── Validation ─────────────────────────────────────────────────────────────────


class ValidationError(DomainError):
    error_code = "VALIDATION_ERROR"


class InvalidCurrencyError(ValidationError):
    error_code = "INVALID_CURRENCY"


class InvalidQuantityError(ValidationError):
    error_code = "INVALID_QUANTITY"


class CurrencyMismatchError(ValidationError):
    error_code = "CURRENCY_MISMATCH"


class DuplicateExternalRefError(ValidationError):
    error_code = "DUPLICATE_EXTERNAL_REF"


# ── Authorization ──────────────────────────────────────────────────────────────


class AuthorizationError(DomainError):
    error_code = "AUTHORIZATION_ERROR"


class TenantAccessDeniedError(AuthorizationError):
    error_code = "TENANT_ACCESS_DENIED"


class PortfolioAccessDeniedError(AuthorizationError):
    error_code = "PORTFOLIO_ACCESS_DENIED"


# ── Business Rules ─────────────────────────────────────────────────────────────


class BusinessRuleViolationError(DomainError):
    error_code = "BUSINESS_RULE_VIOLATION"


class TenantInactiveError(BusinessRuleViolationError):
    error_code = "TENANT_INACTIVE"


class UserInactiveError(BusinessRuleViolationError):
    error_code = "USER_INACTIVE"


class PortfolioArchivedError(BusinessRuleViolationError):
    error_code = "PORTFOLIO_ARCHIVED"


class InsufficientHoldingsError(BusinessRuleViolationError):
    error_code = "INSUFFICIENT_HOLDINGS"


# ── Concurrency ────────────────────────────────────────────────────────────────


class ConcurrencyError(DomainError):
    error_code = "CONCURRENCY_ERROR"


# ── Idempotency ────────────────────────────────────────────────────────────────


class IdempotencyKeyConflictError(DomainError):
    error_code = "IDEMPOTENCY_KEY_CONFLICT"
