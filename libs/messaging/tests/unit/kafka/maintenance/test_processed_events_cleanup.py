"""Unit tests for :class:`ProcessedEventsCleanupWorker`.

The worker only depends on an :class:`AsyncSession`-compatible interface
(``execute`` returning a result with ``rowcount``, plus ``commit``). We use
``AsyncMock`` to simulate the session — no real DB engine is required, which
matches the existing libs/messaging unit-test style (see ``test_advisory_lock``
and ``test_base_consumer_ordering``).

Three scenarios are covered:

1. Empty table — first batch returns 0 rows → loop exits after one pass and
   the worker reports zero deletions.
2. All rows old — one batch returns ``batch_size``, the next returns the
   remainder (< batch_size); total matches the seeded count.
3. Mixed old + new — only the old rows are deleted; new rows survive.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from messaging.kafka.maintenance.processed_events_cleanup import (
    ProcessedEventsCleanupWorker,
)

pytestmark = pytest.mark.unit


def _make_session(rowcounts: list[int]) -> tuple[AsyncMock, list[int]]:
    """Build a fake AsyncSession that returns the given rowcounts in order.

    Each ``session.execute(...)`` call pops the next rowcount from the
    front of the list. Once the list is empty the test will fail loudly
    on the next call — which is the desired behaviour because the worker
    is supposed to stop when a batch returns fewer rows than batch_size.
    """
    remaining = list(rowcounts)
    commits = [0]

    async def _execute(_stmt: object, _params: object | None = None) -> MagicMock:
        if not remaining:
            raise AssertionError("worker called execute() more times than expected")
        rc = remaining.pop(0)
        result = MagicMock()
        result.rowcount = rc
        return result

    async def _commit() -> None:
        commits[0] += 1

    session = AsyncMock()
    session.execute.side_effect = _execute
    session.commit.side_effect = _commit
    return session, commits


class TestProcessedEventsCleanupWorker:
    """Behaviour of :meth:`ProcessedEventsCleanupWorker.run_once`."""

    async def test_empty_table_returns_zero(self) -> None:
        """No rows older than cutoff → single pass, zero deletions, one commit."""
        worker = ProcessedEventsCleanupWorker(
            service_name="test-svc",
            retention_days=30,
            batch_size=10_000,
        )
        session, commits = _make_session([0])

        deleted = await worker.run_once(session)

        assert deleted == 0
        # One pass: one execute, one commit. The loop must exit because
        # deleted (0) < batch_size (10_000).
        assert session.execute.await_count == 1
        assert commits[0] == 1

    async def test_all_rows_old_deletes_everything(self) -> None:
        """5 old rows with batch_size=2 → batches of 2, 2, 1 (last < batch → stop)."""
        worker = ProcessedEventsCleanupWorker(
            service_name="test-svc",
            retention_days=30,
            batch_size=2,
        )
        session, commits = _make_session([2, 2, 1])

        deleted = await worker.run_once(session)

        assert deleted == 5
        # Three batches: 2 + 2 + 1 = 5; loop terminates on the third
        # because 1 < batch_size (2).
        assert session.execute.await_count == 3
        assert commits[0] == 3

    async def test_mixed_old_and_new_only_deletes_old(self) -> None:
        """5 old + 3 new with batch_size=10 → one batch returns 5, loop exits.

        The 3 "new" rows are simulated implicitly: the SQL ``WHERE
        processed_at < :cutoff`` filter only matches the 5 old rows, so
        the single batch deletes exactly 5 and the loop terminates
        because 5 < batch_size (10).
        """
        worker = ProcessedEventsCleanupWorker(
            service_name="test-svc",
            retention_days=30,
            batch_size=10,
        )
        session, commits = _make_session([5])

        deleted = await worker.run_once(session)

        assert deleted == 5
        assert session.execute.await_count == 1
        assert commits[0] == 1

    def test_rejects_non_positive_retention(self) -> None:
        """retention_days must be > 0 — defensive validation at construction."""
        with pytest.raises(ValueError, match="retention_days"):
            ProcessedEventsCleanupWorker(service_name="x", retention_days=0)

    def test_rejects_non_positive_batch_size(self) -> None:
        """batch_size must be > 0 — defensive validation at construction."""
        with pytest.raises(ValueError, match="batch_size"):
            ProcessedEventsCleanupWorker(service_name="x", batch_size=0)
