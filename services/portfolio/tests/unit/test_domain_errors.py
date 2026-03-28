"""Unit tests for Portfolio domain error hierarchy."""

from __future__ import annotations

import uuid

import pytest
from portfolio.domain.errors import (
    AuthorizationError,
    BusinessRuleViolationError,
    ConcurrencyError,
    CurrencyMismatchError,
    DomainError,
    DuplicateExternalRefError,
    EntityAlreadyExistsError,
    EntityNotFoundError,
    HoldingNotFoundError,
    IdempotencyKeyConflictError,
    InstrumentNotFoundError,
    InsufficientHoldingsError,
    InvalidCurrencyError,
    InvalidQuantityError,
    PortfolioAccessDeniedError,
    PortfolioAlreadyExistsError,
    PortfolioArchivedError,
    PortfolioNotFoundError,
    TenantAccessDeniedError,
    TenantAlreadyExistsError,
    TenantInactiveError,
    TenantNotFoundError,
    TransactionNotFoundError,
    UserAlreadyExistsError,
    UserInactiveError,
    UserNotFoundError,
    ValidationError,
)

pytestmark = pytest.mark.unit

# ── DomainError base ──────────────────────────────────────────────────────────


class TestDomainError:
    def test_error_code_attribute(self) -> None:
        err = DomainError("something failed")
        assert err.error_code == "DOMAIN_ERROR"

    def test_message_attribute(self) -> None:
        err = DomainError("something failed")
        assert err.message == "something failed"

    def test_details_defaults_to_empty_dict(self) -> None:
        err = DomainError("oops")
        assert err.details == {}

    def test_details_kwarg(self) -> None:
        err = DomainError("oops", details={"key": "value"})
        assert err.details == {"key": "value"}

    def test_tenant_id_kwarg(self) -> None:
        tenant_id = uuid.uuid4()
        err = DomainError("oops", tenant_id=tenant_id)
        assert err.tenant_id == tenant_id

    def test_user_id_kwarg(self) -> None:
        user_id = uuid.uuid4()
        err = DomainError("oops", user_id=user_id)
        assert err.user_id == user_id

    def test_str_includes_error_code_and_message(self) -> None:
        err = DomainError("bad thing happened")
        assert "[DOMAIN_ERROR]" in str(err)
        assert "bad thing happened" in str(err)

    def test_is_exception(self) -> None:
        err = DomainError("oops")
        assert isinstance(err, Exception)

    def test_can_be_raised_and_caught(self) -> None:
        with pytest.raises(DomainError, match="test"):
            raise DomainError("test")


# ── EntityNotFoundError hierarchy ─────────────────────────────────────────────


class TestEntityNotFoundError:
    def test_error_code(self) -> None:
        err = EntityNotFoundError("not found")
        assert err.error_code == "ENTITY_NOT_FOUND"

    def test_is_domain_error(self) -> None:
        err = EntityNotFoundError("not found")
        assert isinstance(err, DomainError)

    def test_tenant_not_found_is_entity_not_found(self) -> None:
        err = TenantNotFoundError("tenant missing")
        assert isinstance(err, EntityNotFoundError)

    def test_tenant_not_found_error_code(self) -> None:
        err = TenantNotFoundError("tenant missing")
        assert err.error_code == "TENANT_NOT_FOUND"

    def test_user_not_found_is_entity_not_found(self) -> None:
        err = UserNotFoundError("user missing")
        assert isinstance(err, EntityNotFoundError)

    def test_user_not_found_error_code(self) -> None:
        err = UserNotFoundError("user missing")
        assert err.error_code == "USER_NOT_FOUND"

    def test_portfolio_not_found_is_entity_not_found(self) -> None:
        err = PortfolioNotFoundError("portfolio missing")
        assert isinstance(err, EntityNotFoundError)

    def test_portfolio_not_found_error_code(self) -> None:
        err = PortfolioNotFoundError("portfolio missing")
        assert err.error_code == "PORTFOLIO_NOT_FOUND"

    def test_transaction_not_found_error_code(self) -> None:
        err = TransactionNotFoundError("txn missing")
        assert err.error_code == "TRANSACTION_NOT_FOUND"
        assert isinstance(err, EntityNotFoundError)

    def test_holding_not_found_error_code(self) -> None:
        err = HoldingNotFoundError("holding missing")
        assert err.error_code == "HOLDING_NOT_FOUND"
        assert isinstance(err, EntityNotFoundError)

    def test_instrument_not_found_error_code(self) -> None:
        err = InstrumentNotFoundError("instrument missing")
        assert err.error_code == "INSTRUMENT_NOT_FOUND"
        assert isinstance(err, EntityNotFoundError)


# ── EntityAlreadyExistsError hierarchy ────────────────────────────────────────


class TestEntityAlreadyExistsError:
    def test_error_code(self) -> None:
        err = EntityAlreadyExistsError("already exists")
        assert err.error_code == "ENTITY_ALREADY_EXISTS"

    def test_is_domain_error(self) -> None:
        assert isinstance(EntityAlreadyExistsError("x"), DomainError)

    def test_tenant_already_exists_error_code(self) -> None:
        err = TenantAlreadyExistsError("tenant exists")
        assert err.error_code == "TENANT_ALREADY_EXISTS"
        assert isinstance(err, EntityAlreadyExistsError)

    def test_user_already_exists_error_code(self) -> None:
        err = UserAlreadyExistsError("user exists")
        assert err.error_code == "USER_ALREADY_EXISTS"
        assert isinstance(err, EntityAlreadyExistsError)

    def test_portfolio_already_exists_error_code(self) -> None:
        err = PortfolioAlreadyExistsError("portfolio exists")
        assert err.error_code == "PORTFOLIO_ALREADY_EXISTS"
        assert isinstance(err, EntityAlreadyExistsError)


# ── ValidationError hierarchy ─────────────────────────────────────────────────


class TestValidationError:
    def test_error_code(self) -> None:
        err = ValidationError("invalid")
        assert err.error_code == "VALIDATION_ERROR"

    def test_is_domain_error(self) -> None:
        assert isinstance(ValidationError("x"), DomainError)

    def test_invalid_currency_error_code(self) -> None:
        err = InvalidCurrencyError("bad currency")
        assert err.error_code == "INVALID_CURRENCY"
        assert isinstance(err, ValidationError)

    def test_invalid_quantity_error_code(self) -> None:
        err = InvalidQuantityError("bad qty")
        assert err.error_code == "INVALID_QUANTITY"
        assert isinstance(err, ValidationError)

    def test_currency_mismatch_error_code(self) -> None:
        err = CurrencyMismatchError("mismatch")
        assert err.error_code == "CURRENCY_MISMATCH"
        assert isinstance(err, ValidationError)

    def test_duplicate_external_ref_error_code(self) -> None:
        err = DuplicateExternalRefError("duplicate ref")
        assert err.error_code == "DUPLICATE_EXTERNAL_REF"
        assert isinstance(err, ValidationError)


# ── AuthorizationError hierarchy ──────────────────────────────────────────────


class TestAuthorizationError:
    def test_error_code(self) -> None:
        err = AuthorizationError("unauthorized")
        assert err.error_code == "AUTHORIZATION_ERROR"

    def test_is_domain_error(self) -> None:
        assert isinstance(AuthorizationError("x"), DomainError)

    def test_tenant_access_denied_error_code(self) -> None:
        err = TenantAccessDeniedError("denied")
        assert err.error_code == "TENANT_ACCESS_DENIED"
        assert isinstance(err, AuthorizationError)

    def test_portfolio_access_denied_error_code(self) -> None:
        err = PortfolioAccessDeniedError("denied")
        assert err.error_code == "PORTFOLIO_ACCESS_DENIED"
        assert isinstance(err, AuthorizationError)


# ── BusinessRuleViolationError hierarchy ──────────────────────────────────────


class TestBusinessRuleViolationError:
    def test_error_code(self) -> None:
        err = BusinessRuleViolationError("violated rule")
        assert err.error_code == "BUSINESS_RULE_VIOLATION"

    def test_is_domain_error(self) -> None:
        assert isinstance(BusinessRuleViolationError("x"), DomainError)

    def test_tenant_inactive_error_code(self) -> None:
        err = TenantInactiveError("tenant inactive")
        assert err.error_code == "TENANT_INACTIVE"
        assert isinstance(err, BusinessRuleViolationError)

    def test_user_inactive_error_code(self) -> None:
        err = UserInactiveError("user inactive")
        assert err.error_code == "USER_INACTIVE"
        assert isinstance(err, BusinessRuleViolationError)

    def test_portfolio_archived_error_code(self) -> None:
        err = PortfolioArchivedError("portfolio archived")
        assert err.error_code == "PORTFOLIO_ARCHIVED"
        assert isinstance(err, BusinessRuleViolationError)

    def test_insufficient_holdings_error_code(self) -> None:
        err = InsufficientHoldingsError("not enough")
        assert err.error_code == "INSUFFICIENT_HOLDINGS"
        assert isinstance(err, BusinessRuleViolationError)

    def test_insufficient_holdings_with_details(self) -> None:
        err = InsufficientHoldingsError("not enough", details={"instrument_id": "abc123"})
        assert err.details["instrument_id"] == "abc123"


# ── ConcurrencyError ──────────────────────────────────────────────────────────


class TestConcurrencyError:
    def test_error_code(self) -> None:
        err = ConcurrencyError("concurrent modification")
        assert err.error_code == "CONCURRENCY_ERROR"

    def test_is_domain_error(self) -> None:
        assert isinstance(ConcurrencyError("x"), DomainError)

    def test_can_be_raised_and_caught(self) -> None:
        with pytest.raises(ConcurrencyError):
            raise ConcurrencyError("conflict")


# ── IdempotencyKeyConflictError ───────────────────────────────────────────────


class TestIdempotencyKeyConflictError:
    def test_error_code(self) -> None:
        err = IdempotencyKeyConflictError("duplicate event")
        assert err.error_code == "IDEMPOTENCY_KEY_CONFLICT"

    def test_is_domain_error(self) -> None:
        assert isinstance(IdempotencyKeyConflictError("x"), DomainError)

    def test_can_be_raised_and_caught(self) -> None:
        with pytest.raises(IdempotencyKeyConflictError):
            raise IdempotencyKeyConflictError("already processed")
