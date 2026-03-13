"""Tests for ClaimTasksUseCase (T-MI-11)."""

from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_ingestion.application.use_cases.claim_tasks import ClaimTasksUseCase
from market_ingestion.domain.entities.ingestion_task import IngestionTask
from market_ingestion.domain.enums import Provider
from market_ingestion.domain.value_objects import DateRange, Timeframe

from common.time import utc_now  # type: ignore[import-untyped]


def _make_task() -> IngestionTask:
    now = utc_now()
    dr = DateRange(start=now - timedelta(days=1), end=now)
    return IngestionTask.create_ohlcv_task(
        provider=Provider.EODHD, symbol="AAPL", timeframe=Timeframe("1d"), date_range=dr
    )


def _make_uow(tasks: list[IngestionTask]) -> MagicMock:
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.commit = AsyncMock()
    tasks_repo = MagicMock()
    tasks_repo.claim_batch = AsyncMock(return_value=tasks)
    uow.tasks = tasks_repo
    return uow


@pytest.mark.unit
async def test_returns_claimed_tasks() -> None:
    task = _make_task()
    uow = _make_uow([task])
    uc = ClaimTasksUseCase(uow)
    result = await uc.execute(worker_id="w1", batch_size=10)
    assert len(result) == 1
    assert result[0] is task


@pytest.mark.unit
async def test_returns_empty_when_no_tasks() -> None:
    uow = _make_uow([])
    uc = ClaimTasksUseCase(uow)
    result = await uc.execute(worker_id="w1", batch_size=5)
    assert result == []


@pytest.mark.unit
async def test_worker_id_propagated_to_repo() -> None:
    uow = _make_uow([])
    uc = ClaimTasksUseCase(uow)
    await uc.execute(worker_id="worker-99", batch_size=3)
    uow.tasks.claim_batch.assert_awaited_once()
    kwargs = uow.tasks.claim_batch.call_args[1]
    assert kwargs["worker_id"] == "worker-99"


@pytest.mark.unit
async def test_batch_size_propagated_to_repo() -> None:
    uow = _make_uow([])
    uc = ClaimTasksUseCase(uow)
    await uc.execute(worker_id="w1", batch_size=42)
    kwargs = uow.tasks.claim_batch.call_args[1]
    assert kwargs["limit"] == 42


@pytest.mark.unit
async def test_commit_called_after_claim() -> None:
    uow = _make_uow([])
    uc = ClaimTasksUseCase(uow)
    await uc.execute(worker_id="w1", batch_size=1)
    uow.commit.assert_awaited_once()
