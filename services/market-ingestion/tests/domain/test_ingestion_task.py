"""Tests for IngestionTask entity — state machine, backoff, factories."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest
from market_ingestion.domain.entities.ingestion_task import IngestionTask
from market_ingestion.domain.enums import DatasetType, FundamentalsVariant, IngestionTaskStatus, Provider
from market_ingestion.domain.errors import DomainError, InvalidStateTransition
from market_ingestion.domain.value_objects import DateRange, ObjectRef, Timeframe

UTC = UTC


def _make_task(status: IngestionTaskStatus = IngestionTaskStatus.PENDING) -> IngestionTask:
    task = IngestionTask(provider=Provider.EODHD, symbol="AAPL", dataset_type=DatasetType.OHLCV)
    task.status = status
    return task


def _date_range() -> DateRange:
    return DateRange(start=datetime(2024, 1, 1, tzinfo=UTC), end=datetime(2024, 12, 31, tzinfo=UTC))


def _object_ref() -> ObjectRef:
    return ObjectRef(
        bucket="canonical",
        key="market-ingestion/ohlcv/AAPL/data.parquet",
        sha256="abc",
        byte_length=512,
        mime_type="application/octet-stream",
    )


# ── Construction ──────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_task_default_status_is_pending() -> None:
    task = IngestionTask()
    assert task.status == IngestionTaskStatus.PENDING


@pytest.mark.unit
def test_task_id_is_ulid_string() -> None:
    task = IngestionTask()
    assert isinstance(task.id, str)
    assert len(task.id) == 26  # ULID length


@pytest.mark.unit
def test_task_created_at_is_utc_aware() -> None:
    task = IngestionTask()
    assert task.created_at.tzinfo is not None


# ── State transition: PENDING → RUNNING ───────────────────────────────────────


@pytest.mark.unit
def test_claim_from_pending_transitions_to_running() -> None:
    task = _make_task(IngestionTaskStatus.PENDING)
    task.claim("worker-1")
    assert task.status == IngestionTaskStatus.RUNNING


@pytest.mark.unit
def test_claim_increments_attempt_count() -> None:
    task = _make_task(IngestionTaskStatus.PENDING)
    task.claim("worker-1")
    assert task.attempt_count == 1


@pytest.mark.unit
def test_claim_sets_lease_owner_and_expiry() -> None:
    task = _make_task(IngestionTaskStatus.PENDING)
    task.claim("worker-1", lease_seconds=120)
    assert task.lease_owner == "worker-1"
    assert task.lease_expires is not None
    assert task.lease_expires > datetime.now(UTC)


@pytest.mark.unit
def test_claim_from_retry_is_valid() -> None:
    task = _make_task(IngestionTaskStatus.RETRY)
    task.claim("worker-2")
    assert task.status == IngestionTaskStatus.RUNNING


@pytest.mark.unit
def test_claim_from_running_raises_invalid_transition() -> None:
    task = _make_task(IngestionTaskStatus.RUNNING)
    with pytest.raises(InvalidStateTransition):
        task.claim("worker-1")


@pytest.mark.unit
def test_claim_from_failed_raises_invalid_transition() -> None:
    task = _make_task(IngestionTaskStatus.FAILED)
    with pytest.raises(InvalidStateTransition, match="must be PENDING or RETRY"):
        task.claim("worker-1")


# ── State transition: RUNNING → SUCCEEDED ────────────────────────────────────


@pytest.mark.unit
def test_succeed_transitions_to_succeeded() -> None:
    task = _make_task(IngestionTaskStatus.RUNNING)
    task.succeed(_object_ref())
    assert task.status == IngestionTaskStatus.SUCCEEDED


@pytest.mark.unit
def test_succeed_sets_result_ref_and_completed_at() -> None:
    task = _make_task(IngestionTaskStatus.RUNNING)
    ref = _object_ref()
    task.succeed(ref)
    assert task.result_ref == ref
    assert task.completed_at is not None
    assert task.lease_owner is None


@pytest.mark.unit
def test_succeed_from_pending_raises() -> None:
    task = _make_task(IngestionTaskStatus.PENDING)
    with pytest.raises(InvalidStateTransition):
        task.succeed(_object_ref())


# ── State transition: RUNNING → RETRY ────────────────────────────────────────


@pytest.mark.unit
def test_retry_transitions_to_retry_when_attempts_remain() -> None:
    task = _make_task(IngestionTaskStatus.RUNNING)
    task.attempt_count = 1
    task.retry(Exception("timeout"))
    assert task.status == IngestionTaskStatus.RETRY


@pytest.mark.unit
def test_retry_sets_error_message_and_next_attempt_at() -> None:
    task = _make_task(IngestionTaskStatus.RUNNING)
    task.attempt_count = 1
    task.retry(Exception("provider timeout"))
    assert task.error_message == "provider timeout"
    assert task.next_attempt_at is not None
    assert task.next_attempt_at > datetime.now(UTC)


@pytest.mark.unit
def test_retry_clears_lease() -> None:
    task = _make_task(IngestionTaskStatus.RUNNING)
    task.attempt_count = 1
    task.lease_owner = "worker-1"
    task.retry(Exception("error"))
    assert task.lease_owner is None
    assert task.lease_expires is None


@pytest.mark.unit
def test_retry_at_max_attempts_transitions_to_failed() -> None:
    task = _make_task(IngestionTaskStatus.RUNNING)
    task.attempt_count = IngestionTask.MAX_ATTEMPTS
    task.retry(Exception("final error"))
    assert task.status == IngestionTaskStatus.FAILED


# ── State transition: RUNNING → FAILED ───────────────────────────────────────


@pytest.mark.unit
def test_fail_transitions_to_failed() -> None:
    task = _make_task(IngestionTaskStatus.RUNNING)
    task.fail(Exception("fatal"))
    assert task.status == IngestionTaskStatus.FAILED


@pytest.mark.unit
def test_fail_sets_error_message_and_completed_at() -> None:
    task = _make_task(IngestionTaskStatus.RUNNING)
    task.fail(Exception("bad data"))
    assert task.error_message == "bad data"
    assert task.completed_at is not None


@pytest.mark.unit
def test_fail_from_pending_raises() -> None:
    task = _make_task(IngestionTaskStatus.PENDING)
    with pytest.raises(InvalidStateTransition):
        task.fail(Exception("error"))


# ── Invalid transition: claim on FAILED raises DomainError ───────────────────


@pytest.mark.unit
def test_sixth_attempt_claim_raises_domain_error() -> None:
    """After MAX_ATTEMPTS retries → FAILED, claiming the FAILED task raises DomainError."""
    task = _make_task(IngestionTaskStatus.PENDING)
    for _ in range(IngestionTask.MAX_ATTEMPTS):
        task.claim("worker")
        task.retry(Exception("error"))
    # task is now FAILED
    assert task.status == IngestionTaskStatus.FAILED
    with pytest.raises(DomainError):
        task.claim("worker")


# ── Lease expiration ──────────────────────────────────────────────────────────


@pytest.mark.unit
def test_lease_not_expired_when_fresh() -> None:
    task = _make_task(IngestionTaskStatus.RUNNING)
    task.lease_expires = datetime.now(UTC) + timedelta(seconds=300)
    assert task.is_lease_expired() is False


@pytest.mark.unit
def test_lease_expired_when_past_expiry() -> None:
    task = _make_task(IngestionTaskStatus.RUNNING)
    task.lease_expires = datetime.now(UTC) - timedelta(seconds=1)
    assert task.is_lease_expired() is True


@pytest.mark.unit
def test_lease_not_expired_when_none() -> None:
    task = _make_task(IngestionTaskStatus.PENDING)
    assert task.is_lease_expired() is False


# ── Backoff calculation ───────────────────────────────────────────────────────


@pytest.mark.unit
def test_backoff_formula_for_attempts_1_to_4() -> None:
    task = IngestionTask()
    jitter_max = IngestionTask.JITTER_FACTOR

    for attempt in range(1, 5):
        task.attempt_count = attempt
        expected_base = IngestionTask.BASE_BACKOFF_SECONDS * math.pow(2, attempt - 1)
        capped = min(expected_base, IngestionTask.MAX_BACKOFF_SECONDS)
        backoff = task._calculate_backoff()
        assert capped * (1 - jitter_max) <= backoff <= capped * (1 + jitter_max)


@pytest.mark.unit
def test_backoff_capped_at_max() -> None:
    task = IngestionTask()
    task.attempt_count = 100  # very large attempt count
    backoff = task._calculate_backoff()
    max_with_jitter = IngestionTask.MAX_BACKOFF_SECONDS * (1 + IngestionTask.JITTER_FACTOR)
    assert backoff <= max_with_jitter


@pytest.mark.unit
def test_backoff_jitter_within_20_percent() -> None:
    task = IngestionTask()
    task.attempt_count = 2
    expected_base = IngestionTask.BASE_BACKOFF_SECONDS * 2
    results = [task._calculate_backoff() for _ in range(50)]
    for r in results:
        low = expected_base * (1 - IngestionTask.JITTER_FACTOR)
        high = expected_base * (1 + IngestionTask.JITTER_FACTOR)
        assert low <= r <= high


# ── Dedupe key ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_dedupe_key_is_deterministic() -> None:
    dr = _date_range()
    k1 = IngestionTask._build_dedupe_key(Provider.EODHD, DatasetType.OHLCV, "AAPL", "1d", dr.start, dr.end)
    k2 = IngestionTask._build_dedupe_key(Provider.EODHD, DatasetType.OHLCV, "AAPL", "1d", dr.start, dr.end)
    assert k1 == k2


@pytest.mark.unit
def test_dedupe_key_differs_for_different_symbol() -> None:
    dr = _date_range()
    k1 = IngestionTask._build_dedupe_key(Provider.EODHD, DatasetType.OHLCV, "AAPL", "1d", dr.start, dr.end)
    k2 = IngestionTask._build_dedupe_key(Provider.EODHD, DatasetType.OHLCV, "TSLA", "1d", dr.start, dr.end)
    assert k1 != k2


# ── Factory methods ───────────────────────────────────────────────────────────


@pytest.mark.unit
def test_create_ohlcv_task_sets_correct_fields() -> None:
    dr = _date_range()
    task = IngestionTask.create_ohlcv_task(Provider.EODHD, "AAPL", Timeframe("1d"), dr, exchange="NASDAQ")
    assert task.dataset_type == DatasetType.OHLCV
    assert task.provider == Provider.EODHD
    assert task.symbol == "AAPL"
    assert task.exchange == "NASDAQ"
    assert task.timeframe == "1d"
    assert task.range_start == dr.start
    assert task.range_end == dr.end
    assert task.dedupe_key != ""


@pytest.mark.unit
def test_create_quote_task_sets_correct_fields() -> None:
    dr = _date_range()
    task = IngestionTask.create_quote_task(Provider.POLYGON, "MSFT", dr)
    assert task.dataset_type == DatasetType.QUOTES
    assert task.provider == Provider.POLYGON
    assert task.timeframe is None
    assert task.dedupe_key != ""


@pytest.mark.unit
def test_create_fundamentals_task_sets_correct_fields() -> None:
    dr = _date_range()
    task = IngestionTask.create_fundamentals_task(Provider.ALPHA_VANTAGE, "AAPL", FundamentalsVariant.ANNUAL, dr)
    assert task.dataset_type == DatasetType.FUNDAMENTALS
    assert task.variant == "annual"
    assert task.dedupe_key != ""
