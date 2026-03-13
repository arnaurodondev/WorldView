"""Tests for TriggerIngestionUseCase (T-MI-13)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from market_ingestion.application.use_cases.trigger_ingestion import TriggerIngestionUseCase
from market_ingestion.domain.enums import DatasetType, Provider


def _make_uow(inserted: int = 1) -> MagicMock:
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.commit = AsyncMock()
    tasks_repo = MagicMock()
    tasks_repo.add_many = AsyncMock(return_value=inserted)
    uow.tasks = tasks_repo
    return uow


@pytest.mark.unit
async def test_single_symbol_creates_one_task() -> None:
    uow = _make_uow(inserted=1)
    uc = TriggerIngestionUseCase(uow)
    result = await uc.execute(Provider.EODHD, DatasetType.OHLCV, ["AAPL"], timeframe="1d")
    assert result.tasks_created == 1
    args = uow.tasks.add_many.call_args[0][0]
    assert len(args) == 1


@pytest.mark.unit
async def test_multi_symbol_creates_n_tasks() -> None:
    uow = _make_uow(inserted=3)
    uc = TriggerIngestionUseCase(uow)
    result = await uc.execute(Provider.EODHD, DatasetType.QUOTES, ["AAPL", "TSLA", "MSFT"])
    assert result.tasks_created == 3
    args = uow.tasks.add_many.call_args[0][0]
    assert len(args) == 3


@pytest.mark.unit
async def test_duplicate_dedupe_key_no_error() -> None:
    uow = _make_uow(inserted=0)  # conflict — nothing inserted
    uc = TriggerIngestionUseCase(uow)
    result = await uc.execute(Provider.EODHD, DatasetType.OHLCV, ["AAPL"], timeframe="1d")
    assert result.tasks_created == 0
    assert result.tasks_skipped == 1


@pytest.mark.unit
async def test_task_fields_match_inputs() -> None:
    uow = _make_uow(inserted=1)
    uc = TriggerIngestionUseCase(uow)
    await uc.execute(
        Provider.EODHD,
        DatasetType.OHLCV,
        ["TSLA"],
        timeframe="1d",
        exchange="US",
    )
    tasks = uow.tasks.add_many.call_args[0][0]
    t = tasks[0]
    assert t.provider == Provider.EODHD
    assert t.dataset_type == DatasetType.OHLCV
    assert t.symbol == "TSLA"
    assert t.exchange == "US"
