"""Tests for the Kafka consumer error hierarchy (T-030)."""

from __future__ import annotations

import pytest

from messaging.kafka.consumer.errors import (
    BusinessRuleViolationError,
    ConsumerError,
    DatabaseConnectionError,
    FatalError,
    MalformedDataError,
    MissingRequiredFieldError,
    NetworkTimeoutError,
    RateLimitedError,
    RetryableError,
    SchemaVersionError,
    ServiceUnavailableError,
    StorageUnavailableError,
)


class TestErrorHierarchyRoots:
    def test_consumer_error_is_exception(self) -> None:
        assert issubclass(ConsumerError, Exception)

    def test_retryable_is_consumer_error(self) -> None:
        assert issubclass(RetryableError, ConsumerError)

    def test_fatal_is_consumer_error(self) -> None:
        assert issubclass(FatalError, ConsumerError)


class TestRetryableBranch:
    @pytest.mark.parametrize(
        "cls",
        [
            StorageUnavailableError,
            DatabaseConnectionError,
            NetworkTimeoutError,
            ServiceUnavailableError,
            RateLimitedError,
        ],
    )
    def test_is_retryable(self, cls: type) -> None:
        assert issubclass(cls, RetryableError)
        assert issubclass(cls, ConsumerError)

    def test_instantiation_with_message(self) -> None:
        err = NetworkTimeoutError("upstream timed out after 5 s")
        assert "5 s" in str(err)
        assert isinstance(err, RetryableError)

    def test_caught_as_retryable(self) -> None:
        with pytest.raises(RetryableError):
            raise StorageUnavailableError("minio down")

    def test_caught_as_consumer_error(self) -> None:
        with pytest.raises(ConsumerError):
            raise RateLimitedError("429")


class TestFatalBranch:
    @pytest.mark.parametrize(
        "cls",
        [
            SchemaVersionError,
            MalformedDataError,
            MissingRequiredFieldError,
            BusinessRuleViolationError,
        ],
    )
    def test_is_fatal(self, cls: type) -> None:
        assert issubclass(cls, FatalError)
        assert issubclass(cls, ConsumerError)

    def test_instantiation_with_message(self) -> None:
        err = SchemaVersionError("schema v3 not supported")
        assert isinstance(err, FatalError)
        assert "v3" in str(err)

    def test_fatal_not_retryable(self) -> None:
        err = MalformedDataError("bad payload")
        assert not isinstance(err, RetryableError)

    def test_caught_as_fatal(self) -> None:
        with pytest.raises(FatalError):
            raise MissingRequiredFieldError("event_id missing")


class TestBranchSeparation:
    def test_retryable_is_not_fatal(self) -> None:
        assert not issubclass(RetryableError, FatalError)

    def test_fatal_is_not_retryable(self) -> None:
        assert not issubclass(FatalError, RetryableError)

    def test_cannot_catch_storage_as_fatal(self) -> None:
        with pytest.raises(RetryableError):
            raise StorageUnavailableError("down")
        # Should NOT be caught by FatalError handler
        try:
            raise StorageUnavailableError("down")
        except FatalError:
            pytest.fail("StorageUnavailableError should not be caught as FatalError")
        except RetryableError:
            pass  # expected


class TestRootImport:
    """All exceptions must be importable from the messaging root package."""

    def test_import_from_root(self) -> None:
        from messaging import (  # noqa: F401
            BusinessRuleViolationError,
            ConsumerError,
            DatabaseConnectionError,
            FatalError,
            MalformedDataError,
            MissingRequiredFieldError,
            NetworkTimeoutError,
            RateLimitedError,
            RetryableError,
            SchemaVersionError,
            ServiceUnavailableError,
            StorageUnavailableError,
        )
