"""Unit tests for S4 DomainError base class (T-R3-1-04)."""

from __future__ import annotations

import pytest
from content_ingestion.domain.exceptions import (
    AdapterError,
    ConfigurationError,
    DomainError,
    QuotaExhaustedError,
    StorageError,
)

pytestmark = pytest.mark.unit


class TestDomainErrorBase:
    def test_domain_error_is_exception_subclass(self) -> None:
        assert issubclass(DomainError, Exception)

    def test_storage_error_inherits_domain_error(self) -> None:
        assert issubclass(StorageError, DomainError)

    def test_configuration_error_inherits_domain_error(self) -> None:
        assert issubclass(ConfigurationError, DomainError)

    def test_quota_exhausted_error_inherits_domain_error(self) -> None:
        assert issubclass(QuotaExhaustedError, DomainError)

    def test_adapter_error_inherits_domain_error(self) -> None:
        assert issubclass(AdapterError, DomainError)

    def test_can_catch_storage_error_as_domain_error(self) -> None:
        with pytest.raises(DomainError):
            raise StorageError("minio unavailable")

    def test_can_catch_adapter_error_as_domain_error(self) -> None:
        with pytest.raises(DomainError):
            raise AdapterError("eodhd request failed")

    def test_can_catch_quota_exhausted_as_domain_error(self) -> None:
        with pytest.raises(DomainError):
            raise QuotaExhaustedError("daily limit reached")

    def test_all_domain_errors_catchable_as_base_exception(self) -> None:
        errors: list[type[DomainError]] = [
            StorageError,
            ConfigurationError,
            QuotaExhaustedError,
            AdapterError,
        ]
        for error_class in errors:
            with pytest.raises(Exception):  # noqa: B017
                raise error_class("test")
