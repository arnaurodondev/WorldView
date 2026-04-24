"""Unit tests for ContentIngestionTask.next_attempt_at retry-backoff semantics.

PLAN-0036 W2-12: verifies that the new next_attempt_at field correctly gates
task claimability when a backoff window is active.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from content_ingestion.domain.entities import ContentIngestionTask, Source

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
# next_attempt_at defaults
# ---------------------------------------------------------------------------


class TestNextAttemptAtDefault:
    def test_next_attempt_at_defaults_to_none(self) -> None:
        """A freshly created task must have next_attempt_at=None (no backoff)."""
        task = _make_task()
        assert task.next_attempt_at is None

    def test_create_for_source_has_no_backoff(self) -> None:
        """Tasks created via the factory method also start with no backoff."""
        source = _make_source()
        task = ContentIngestionTask.create_for_source(source)
        assert task.next_attempt_at is None

    def test_can_set_next_attempt_at_explicitly(self) -> None:
        """next_attempt_at can be set to a future datetime when needed."""
        future = datetime.now(tz=UTC) + timedelta(minutes=5)
        task = _make_task(next_attempt_at=future)
        assert task.next_attempt_at == future


# ---------------------------------------------------------------------------
# is_claimable gating by next_attempt_at
# ---------------------------------------------------------------------------


class TestIsClaimableWithBackoff:
    def test_claimable_when_no_backoff(self) -> None:
        """PENDING task with next_attempt_at=None is claimable."""
        task = _make_task(status=IngestionTaskStatus.PENDING)
        assert task.is_claimable is True

    def test_not_claimable_when_backoff_in_future(self) -> None:
        """A PENDING task with next_attempt_at in the future must NOT be claimable.

        This is the core PLAN-0036 W2-12 requirement: tasks in an active backoff
        window must be skipped by the scheduler.
        """
        future = datetime.now(tz=UTC) + timedelta(hours=1)
        task = _make_task(
            status=IngestionTaskStatus.PENDING,
            next_attempt_at=future,
        )
        # Even though status is PENDING, the backoff blocks claiming
        assert task.is_claimable is False

    def test_not_claimable_retry_with_future_backoff(self) -> None:
        """A RETRY task with an active backoff window is also not claimable."""
        future = datetime.now(tz=UTC) + timedelta(minutes=30)
        task = _make_task(
            status=IngestionTaskStatus.RETRY,
            next_attempt_at=future,
        )
        assert task.is_claimable is False

    def test_claimable_when_backoff_has_expired(self) -> None:
        """Once next_attempt_at is in the past, the task becomes claimable again."""
        past = datetime.now(tz=UTC) - timedelta(seconds=1)
        task = _make_task(
            status=IngestionTaskStatus.PENDING,
            next_attempt_at=past,
        )
        assert task.is_claimable is True

    def test_claimable_retry_after_backoff_expires(self) -> None:
        """A RETRY task with an expired backoff is claimable."""
        past = datetime.now(tz=UTC) - timedelta(minutes=5)
        task = _make_task(
            status=IngestionTaskStatus.RETRY,
            next_attempt_at=past,
        )
        assert task.is_claimable is True

    def test_non_claimable_status_unaffected_by_backoff(self) -> None:
        """RUNNING/CLAIMED/SUCCEEDED/FAILED tasks remain non-claimable regardless
        of next_attempt_at — status gate is checked first."""
        past = datetime.now(tz=UTC) - timedelta(minutes=5)
        for status in (
            IngestionTaskStatus.RUNNING,
            IngestionTaskStatus.CLAIMED,
            IngestionTaskStatus.SUCCEEDED,
            IngestionTaskStatus.FAILED,
        ):
            task = _make_task(status=status, next_attempt_at=past)
            assert task.is_claimable is False, f"Expected not claimable for status={status}"
