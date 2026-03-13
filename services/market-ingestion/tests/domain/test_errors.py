"""Tests for market_ingestion domain error hierarchy."""

from __future__ import annotations

import pytest
from market_ingestion.domain.errors import (
    DomainError,
    DuplicateTask,
    InvalidStateTransition,
    ProviderAuthError,
    ProviderDataError,
    ProviderRateLimited,
    ProviderUnavailable,
    RetryableDomainError,
    StorageUnavailable,
    TaskLeaseLost,
    WatermarkViolation,
)

# ── Base class ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_domain_error_is_exception() -> None:
    err = DomainError("base error")
    assert isinstance(err, Exception)
    assert str(err) == "base error"


@pytest.mark.unit
def test_domain_error_not_retryable() -> None:
    assert DomainError("x").is_retryable is False


@pytest.mark.unit
def test_retryable_domain_error_is_retryable() -> None:
    assert RetryableDomainError("x").is_retryable is True


@pytest.mark.unit
def test_retryable_domain_error_is_domain_error() -> None:
    assert isinstance(RetryableDomainError("x"), DomainError)


# ── Retryable errors ──────────────────────────────────────────────────────────


@pytest.mark.unit
def test_provider_rate_limited_is_retryable() -> None:
    err = ProviderRateLimited("rate limit hit")
    assert err.is_retryable is True
    assert str(err) == "rate limit hit"
    assert isinstance(err, DomainError)


@pytest.mark.unit
def test_provider_unavailable_is_retryable() -> None:
    err = ProviderUnavailable("service down")
    assert err.is_retryable is True
    assert isinstance(err, DomainError)


@pytest.mark.unit
def test_storage_unavailable_is_retryable() -> None:
    err = StorageUnavailable("minio timeout")
    assert err.is_retryable is True
    assert isinstance(err, DomainError)


@pytest.mark.unit
def test_task_lease_lost_is_retryable() -> None:
    err = TaskLeaseLost("lease expired")
    assert err.is_retryable is True
    assert isinstance(err, DomainError)


@pytest.mark.unit
def test_all_retryable_errors_inherit_retryable_base() -> None:
    for cls in (ProviderRateLimited, ProviderUnavailable, StorageUnavailable, TaskLeaseLost):
        assert issubclass(cls, RetryableDomainError)


# ── Fatal errors ──────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_provider_auth_error_not_retryable() -> None:
    err = ProviderAuthError("invalid api key")
    assert err.is_retryable is False
    assert str(err) == "invalid api key"
    assert isinstance(err, DomainError)


@pytest.mark.unit
def test_provider_data_error_not_retryable() -> None:
    err = ProviderDataError("unexpected format")
    assert err.is_retryable is False
    assert isinstance(err, DomainError)


@pytest.mark.unit
def test_invalid_state_transition_not_retryable() -> None:
    err = InvalidStateTransition("cannot transition FAILED -> RUNNING")
    assert err.is_retryable is False
    assert isinstance(err, DomainError)


@pytest.mark.unit
def test_watermark_violation_not_retryable() -> None:
    err = WatermarkViolation("new_ts <= current_ts")
    assert err.is_retryable is False
    assert isinstance(err, DomainError)


@pytest.mark.unit
def test_duplicate_task_not_retryable() -> None:
    err = DuplicateTask("dedupe_key already exists")
    assert err.is_retryable is False
    assert isinstance(err, DomainError)


@pytest.mark.unit
def test_fatal_errors_do_not_inherit_retryable_base() -> None:
    for cls in (ProviderAuthError, ProviderDataError, InvalidStateTransition, WatermarkViolation, DuplicateTask):
        assert not issubclass(cls, RetryableDomainError)


@pytest.mark.unit
def test_errors_can_be_raised_and_caught_as_domain_error() -> None:
    with pytest.raises(DomainError):
        raise ProviderRateLimited("rate limited")

    with pytest.raises(DomainError):
        raise InvalidStateTransition("bad transition")


@pytest.mark.unit
def test_retryable_errors_can_be_caught_as_retryable() -> None:
    with pytest.raises(RetryableDomainError):
        raise StorageUnavailable("unavailable")
