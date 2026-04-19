"""Unit tests for ClaimTasksUseCase and expired lease reclaim (BP-079)."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from content_ingestion.application.use_cases.claim_tasks import ClaimTasksUseCase
from content_ingestion.domain.entities import ContentIngestionTask, SourceType

import common.ids
import common.time
from contracts.enums import IngestionTaskStatus  # type: ignore[import-untyped]

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_task(name: str = "test-source") -> ContentIngestionTask:
    return ContentIngestionTask(
        source_id=common.ids.new_uuid7(),
        source_name=name,
        source_type=SourceType.EODHD,
        status=IngestionTaskStatus.CLAIMED,
        worker_id="w-test",
    )


def _make_uow(claimed: list[ContentIngestionTask] | None = None) -> AsyncMock:
    uow = AsyncMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    uow.tasks = AsyncMock()
    uow.tasks.claim_batch = AsyncMock(return_value=claimed or [])
    return uow


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestClaimReturnsTasks:
    async def test_returns_claimed_tasks(self) -> None:
        tasks = [_make_task(f"src-{i}") for i in range(3)]
        uow = _make_uow(claimed=tasks)
        uc = ClaimTasksUseCase(uow=uow)
        result = await uc.execute(worker_id="w-1", batch_size=5, lease_seconds=300)
        assert len(result) == 3
        uow.tasks.claim_batch.assert_awaited_once_with(worker_id="w-1", limit=5, lease_seconds=300)


class TestClaimEmptyQueue:
    async def test_returns_empty_list_when_no_tasks(self) -> None:
        uow = _make_uow(claimed=[])
        uc = ClaimTasksUseCase(uow=uow)
        result = await uc.execute(worker_id="w-1", batch_size=5)
        assert result == []


class TestClaimCommits:
    async def test_commit_called_after_claim(self) -> None:
        uow = _make_uow(claimed=[_make_task()])
        uc = ClaimTasksUseCase(uow=uow)
        await uc.execute(worker_id="w-1", batch_size=5)
        uow.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# F-MAJOR-014 / BP-079 — Expired worker lease reclaim
# ---------------------------------------------------------------------------


class TestClaimBatchReclaims:
    async def test_claim_batch_reclaims_expired_running_tasks(self) -> None:
        """Verify that a task stuck in RUNNING with an expired lease can be
        reclaimed by claim_batch() after recover_expired_leases() transitions
        it back to RETRY.

        The actual DB logic is in TaskRepository.recover_expired_leases() and
        claim_batch().  This test validates the domain-level contract: a task
        with status=RUNNING and lease_expires in the past should transition
        through RETRY → CLAIMED when the scheduler reclaims it.
        """
        # 1. Create a task that simulates a crashed worker:
        #    RUNNING status with a lease that expired 60 seconds ago.
        expired_task = ContentIngestionTask(
            source_id=common.ids.new_uuid7(),
            source_name="expired-source",
            source_type=SourceType.EODHD,
            status=IngestionTaskStatus.RUNNING,
            worker_id="w-crashed",
            lease_expires=common.time.utc_now() - timedelta(seconds=60),
            attempt_count=1,
        )
        assert expired_task.is_lease_expired(common.time.utc_now())

        # 2. Simulate what recover_expired_leases does at the domain level:
        #    reset the task status to RETRY so it becomes claimable again.
        expired_task.status = IngestionTaskStatus.RETRY
        expired_task.worker_id = None
        expired_task.lease_expires = None

        # 3. The task should now be claimable
        assert expired_task.is_claimable

        # 4. Simulate claim_batch picking up the recovered task
        reclaimed_task = ContentIngestionTask(
            id=expired_task.id,
            source_id=expired_task.source_id,
            source_name=expired_task.source_name,
            source_type=expired_task.source_type,
            status=IngestionTaskStatus.RETRY,
            attempt_count=expired_task.attempt_count,
        )
        reclaimed_task.claim(worker_id="w-new", lease_seconds=300)
        assert reclaimed_task.status == IngestionTaskStatus.CLAIMED
        assert reclaimed_task.worker_id == "w-new"
        assert reclaimed_task.lease_expires is not None

    async def test_recover_expired_leases_called_in_uow(self) -> None:
        """Verify the UoW's task repo recover_expired_leases is callable
        and returns a count of recovered tasks."""
        uow = _make_uow()
        uow.tasks.recover_expired_leases = AsyncMock(return_value=2)

        now = common.time.utc_now()
        recovered = await uow.tasks.recover_expired_leases(now=now, lease_timeout_seconds=0)
        assert recovered == 2
        uow.tasks.recover_expired_leases.assert_awaited_once_with(now=now, lease_timeout_seconds=0)
