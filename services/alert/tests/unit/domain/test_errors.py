"""Unit tests for S10 domain error hierarchy."""

from __future__ import annotations

import pytest
from alert.domain.errors import (
    AlertNotFoundError,
    DeliveryError,
    DomainError,
    DuplicateAlertError,
    S1ClientError,
    S1UnavailableError,
    UserNotConnectedError,
)


class TestErrorHierarchy:
    @pytest.mark.unit
    def test_domain_error_is_base(self) -> None:
        assert issubclass(AlertNotFoundError, DomainError)
        assert issubclass(DuplicateAlertError, DomainError)
        assert issubclass(DeliveryError, DomainError)
        assert issubclass(S1ClientError, DomainError)

    @pytest.mark.unit
    def test_delivery_subtypes(self) -> None:
        assert issubclass(UserNotConnectedError, DeliveryError)

    @pytest.mark.unit
    def test_s1_subtypes(self) -> None:
        assert issubclass(S1UnavailableError, S1ClientError)

    @pytest.mark.unit
    def test_error_message(self) -> None:
        err = AlertNotFoundError("alert-123 not found")
        assert "alert-123" in str(err)
