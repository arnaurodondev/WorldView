"""Unit tests for ContentIngestionTask entity and state machine."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from content_ingestion.domain.entities import ContentIngestionTask, Source
from content_ingestion.domain.exceptions import InvalidStateTransition

from contracts.enums import ContentSourceType as SourceType  # type: ignore[import-untyped]
from contracts.enums import IngestionTaskStatus  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_source(**overrides: object) -> Source:
    """Create a minimal Source for testing."""
    defaults: dict[str, object] = {
        "name": "test-source",
        "source_type": SourceType.EODHD,
        "enabled": True,
        "config": {},
    }
    defaults.update(overrides)
    return Source(**defaults)  # type: ignore[arg-type]


def _make_task(**overrides: object) -> ContentIngestionTask:
    """Create a minimal ContentIngestionTask for testing."""
    source = _make_source()
    defaults: dict[str, object] = {
        "source_id": source.id,
        "source_name": source.name,
        "source_type": source.source_type,
    }
    defaults.update(overrides)
    return ContentIngestionTask(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Factory method
# ---------------------------------------------------------------------------


class TestCreateForSource:
    def test_create_for_source(self) -> None:
        source = _make_source(name="eodhd-news", source_type=SourceType.EODHD)
        task = ContentIngestionTask.create_for_source(source)

        assert task.source_id == source.id
        assert task.source_name == "eodhd-news"
        assert task.source_type == SourceType.EODHD
        assert task.status == IngestionTaskStatus.PENDING
        assert task.worker_id is None
        assert task.attempt_count == 0
        assert task.max_attempts == 5
        assert task.is_backfill is False
        assert task.window_start is None

    def test_create_for_source_backfill(self) -> None:
        source = _make_source()
        now = datetime.now(tz=UTC)
        task = ContentIngestionTask.create_for_source(source, is_backfill=True, window_start=now)

        assert task.is_backfill is True
        assert task.window_start == now


# ---------------------------------------------------------------------------
# claim()
# ---------------------------------------------------------------------------


class TestClaim:
    def test_claim_from_pending(self) -> None:
        task = _make_task()
        assert task.status == IngestionTaskStatus.PENDING

        task.claim(worker_id="worker-001", lease_seconds=300)

        assert task.status == IngestionTaskStatus.CLAIMED
        assert task.worker_id == "worker-001"
        assert task.leased_at is not None
        assert task.lease_expires is not None
        assert task.lease_expires > task.leased_at

    def test_claim_from_retry(self) -> None:
        task = _make_task(status=IngestionTaskStatus.RETRY)

        task.claim(worker_id="worker-002", lease_seconds=60)

        assert task.status == IngestionTaskStatus.CLAIMED
        assert task.worker_id == "worker-002"

    def test_claim_invalid_state_running(self) -> None:
        task = _make_task(status=IngestionTaskStatus.RUNNING)
        with pytest.raises(InvalidStateTransition, match="RUNNING"):
            task.claim(worker_id="w", lease_seconds=60)

    def test_claim_invalid_state_succeeded(self) -> None:
        task = _make_task(status=IngestionTaskStatus.SUCCEEDED)
        with pytest.raises(InvalidStateTransition, match="SUCCEEDED"):
            task.claim(worker_id="w", lease_seconds=60)

    def test_claim_invalid_state_failed(self) -> None:
        task = _make_task(status=IngestionTaskStatus.FAILED)
        with pytest.raises(InvalidStateTransition, match="FAILED"):
            task.claim(worker_id="w", lease_seconds=60)

    def test_claim_invalid_state_claimed(self) -> None:
        task = _make_task(status=IngestionTaskStatus.CLAIMED)
        with pytest.raises(InvalidStateTransition, match="CLAIMED"):
            task.claim(worker_id="w", lease_seconds=60)


# ---------------------------------------------------------------------------
# start()
# ---------------------------------------------------------------------------


class TestStart:
    def test_start_from_claimed(self) -> None:
        task = _make_task()
        task.claim(worker_id="w", lease_seconds=300)
        task.start()

        assert task.status == IngestionTaskStatus.RUNNING
        assert task.attempt_count == 1

    def test_start_invalid_state_pending(self) -> None:
        task = _make_task(status=IngestionTaskStatus.PENDING)
        with pytest.raises(InvalidStateTransition, match="PENDING"):
            task.start()

    def test_start_invalid_state_running(self) -> None:
        task = _make_task(status=IngestionTaskStatus.RUNNING)
        with pytest.raises(InvalidStateTransition, match="RUNNING"):
            task.start()


# ---------------------------------------------------------------------------
# succeed()
# ---------------------------------------------------------------------------


class TestSucceed:
    def test_succeed(self) -> None:
        task = _make_task()
        task.claim(worker_id="w", lease_seconds=300)
        task.start()
        task.succeed()

        assert task.status == IngestionTaskStatus.SUCCEEDED
        assert task.worker_id is None
        assert task.lease_expires is None

    def test_succeed_invalid_state(self) -> None:
        task = _make_task(status=IngestionTaskStatus.PENDING)
        with pytest.raises(InvalidStateTransition, match="PENDING"):
            task.succeed()


# ---------------------------------------------------------------------------
# fail()
# ---------------------------------------------------------------------------


class TestFail:
    def test_fail_with_retries_left(self) -> None:
        task = _make_task()
        task.claim(worker_id="w", lease_seconds=300)
        task.start()
        assert task.attempt_count == 1

        task.fail("timeout")

        assert task.status == IngestionTaskStatus.RETRY
        assert task.error_detail == "timeout"
        assert task.worker_id is None
        assert task.lease_expires is None

    def test_fail_exhausted(self) -> None:
        task = _make_task(max_attempts=1)
        task.claim(worker_id="w", lease_seconds=300)
        task.start()
        assert task.attempt_count == 1

        task.fail("permanent error")

        assert task.status == IngestionTaskStatus.FAILED
        assert task.error_detail == "permanent error"

    def test_fail_at_max_attempts_boundary(self) -> None:
        task = _make_task(max_attempts=3, attempt_count=2)
        task.status = IngestionTaskStatus.RUNNING
        task.attempt_count = 3  # simulates 3rd attempt already counted

        task.fail("third failure")

        assert task.status == IngestionTaskStatus.FAILED

    def test_fail_invalid_state(self) -> None:
        task = _make_task(status=IngestionTaskStatus.PENDING)
        with pytest.raises(InvalidStateTransition, match="PENDING"):
            task.fail("error")


# ---------------------------------------------------------------------------
# is_claimable
# ---------------------------------------------------------------------------


class TestIsClaimable:
    def test_claimable_pending(self) -> None:
        assert _make_task(status=IngestionTaskStatus.PENDING).is_claimable is True

    def test_claimable_retry(self) -> None:
        assert _make_task(status=IngestionTaskStatus.RETRY).is_claimable is True

    def test_not_claimable_running(self) -> None:
        assert _make_task(status=IngestionTaskStatus.RUNNING).is_claimable is False

    def test_not_claimable_succeeded(self) -> None:
        assert _make_task(status=IngestionTaskStatus.SUCCEEDED).is_claimable is False

    def test_not_claimable_failed(self) -> None:
        assert _make_task(status=IngestionTaskStatus.FAILED).is_claimable is False

    def test_not_claimable_claimed(self) -> None:
        assert _make_task(status=IngestionTaskStatus.CLAIMED).is_claimable is False


# ---------------------------------------------------------------------------
# is_lease_expired()
# ---------------------------------------------------------------------------


class TestIsLeaseExpired:
    def test_expired_when_past_deadline(self) -> None:
        task = _make_task()
        task.claim(worker_id="w", lease_seconds=60)
        future = datetime.now(tz=UTC) + timedelta(seconds=120)

        assert task.is_lease_expired(future) is True

    def test_not_expired_within_lease(self) -> None:
        task = _make_task()
        task.claim(worker_id="w", lease_seconds=300)
        now = datetime.now(tz=UTC)

        assert task.is_lease_expired(now) is False

    def test_not_expired_when_no_lease(self) -> None:
        task = _make_task()
        now = datetime.now(tz=UTC)

        assert task.is_lease_expired(now) is False
