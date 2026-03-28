"""Unit tests for API error mapping."""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit

from portfolio.api.error_mapping import domain_error_to_status
from portfolio.domain.errors import (
    AuthorizationError,
    BusinessRuleViolationError,
    ConcurrencyError,
    DomainError,
    EntityNotFoundError,
    IdempotencyKeyConflictError,
    PortfolioAccessDeniedError,
    PortfolioNotFoundError,
    TenantNotFoundError,
    ValidationError,
)


def test_not_found_errors() -> None:
    assert domain_error_to_status(EntityNotFoundError("x")) == 404
    assert domain_error_to_status(TenantNotFoundError("x")) == 404
    assert domain_error_to_status(PortfolioNotFoundError("x")) == 404


def test_authorization_errors() -> None:
    assert domain_error_to_status(AuthorizationError("x")) == 403
    assert domain_error_to_status(PortfolioAccessDeniedError("x")) == 403


def test_validation_errors() -> None:
    assert domain_error_to_status(ValidationError("x")) == 422


def test_business_rule_errors() -> None:
    assert domain_error_to_status(BusinessRuleViolationError("x")) == 409
    assert domain_error_to_status(IdempotencyKeyConflictError("x")) == 409
    assert domain_error_to_status(ConcurrencyError("x")) == 409


def test_fallback_to_500() -> None:
    class _UnknownError(DomainError):
        error_code = "UNKNOWN"

    assert domain_error_to_status(_UnknownError("x")) == 500
