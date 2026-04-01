"""Unit tests for ClaimTasksUseCase."""

from __future__ import annotations

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
