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


class IdempotencyConflictError(ConcurrencyError):
    """Raised when concurrent requests with the same idempotency key both attempt
    to commit simultaneously. The losing request should re-query for the original
    result or retry. Maps to HTTP 409 via ConcurrencyError in error_mapping.py.
    """

    error_code = "IDEMPOTENCY_RACE"


class IdempotencyKeyInvalidError(ValidationError):
    error_code = "IDEMPOTENCY_KEY_INVALID"


# ── Watchlist ──────────────────────────────────────────────────────────────────


class WatchlistNotFoundError(EntityNotFoundError):
    error_code = "WATCHLIST_NOT_FOUND"


class WatchlistAlreadyExistsError(EntityAlreadyExistsError):
    error_code = "WATCHLIST_ALREADY_EXISTS"


class WatchlistMemberNotFoundError(EntityNotFoundError):
    error_code = "WATCHLIST_MEMBER_NOT_FOUND"


class WatchlistMemberAlreadyExistsError(EntityAlreadyExistsError):
    error_code = "WATCHLIST_MEMBER_ALREADY_EXISTS"


# ── Alert preference ───────────────────────────────────────────────────────────


class AlertPreferenceNotFoundError(EntityNotFoundError):
    error_code = "ALERT_PREFERENCE_NOT_FOUND"


# ── Brokerage ──────────────────────────────────────────────────────────────────


class BrokerageConnectionNotFoundError(EntityNotFoundError):
    error_code = "BROKERAGE_CONNECTION_NOT_FOUND"


class BrokerageConnectionForbiddenError(AuthorizationError):
    error_code = "BROKERAGE_CONNECTION_FORBIDDEN"


class TosNotAcceptedError(ValidationError):
    error_code = "TOS_NOT_ACCEPTED"


class BrokerageConnectionStateError(BusinessRuleViolationError):
    error_code = "BROKERAGE_CONNECTION_STATE_ERROR"


class BrokerageConnectionAlreadyDisconnectedError(BrokerageConnectionStateError):
    error_code = "BROKERAGE_CONNECTION_ALREADY_DISCONNECTED"


class BrokerageApiError(DomainError):
    error_code = "BROKERAGE_API_ERROR"


class InstrumentResolutionTransientError(DomainError):
    """Raised when the market-data service (S3) is unreachable or returns a
    non-404 error during instrument resolution.

    This is a *transient* infrastructure failure — the symbol may still be valid;
    the lookup failed due to a downstream outage.  Callers should record the
    failure as ``SyncErrorType.API_ERROR`` rather than ``UNKNOWN_INSTRUMENT`` so
    that genuine "instrument not found" errors (404) remain distinguishable from
    transient network/5xx failures.
    """

    error_code = "INSTRUMENT_RESOLUTION_TRANSIENT"


# ── Auth / Provisioning ────────────────────────────────────────────────────────


class ProvisionConflictError(DomainError):
    """Raised when provisioning detects an email already linked to a different Zitadel sub.

    Maps to HTTP 409 in the provision route handler.
    """

    error_code = "PROVISION_CONFLICT"

    def __init__(self, email: str, conflict_sub: str | None) -> None:
        super().__init__(
            f"Email '{email}' is already linked to a different identity provider subject.",
            details={"email": email, "conflict_sub": conflict_sub or ""},
        )
        self.email = email
        self.conflict_sub = conflict_sub
