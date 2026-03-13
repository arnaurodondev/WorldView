"""Tests for BackfillUseCase (T-MI-14)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_ingestion.application.use_cases.backfill import BackfillUseCase
from market_ingestion.domain.enums import Provider


def _make_uow(inserted: int = 3) -> MagicMock:
    uow = MagicMock()
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=False)
    uow.commit = AsyncMock()
    tasks_repo = MagicMock()
    tasks_repo.add_many = AsyncMock(return_value=inserted)
    uow.tasks = tasks_repo
    return uow


@pytest.mark.unit
async def test_90_day_range_creates_3_chunks() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = start + timedelta(days=90)  # exactly 90 days → 3 chunks of 30
    uow = _make_uow(inserted=3)
    uc = BackfillUseCase(uow)
    result = await uc.execute(Provider.EODHD, "AAPL", start, end, "1d", chunk_days=30)
    assert result.chunks == 3
    tasks = uow.tasks.add_many.call_args[0][0]
    assert len(tasks) == 3


@pytest.mark.unit
async def test_single_day_range_creates_1_chunk() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2024, 1, 2, tzinfo=UTC)
    uow = _make_uow(inserted=1)
    uc = BackfillUseCase(uow)
    result = await uc.execute(Provider.EODHD, "AAPL", start, end, "1d")
    assert result.chunks == 1


@pytest.mark.unit
async def test_range_spanning_year_boundary_correct_chunks() -> None:
    start = datetime(2023, 12, 1, tzinfo=UTC)
    end = datetime(2024, 2, 1, tzinfo=UTC)
    uow = _make_uow(inserted=3)
    uc = BackfillUseCase(uow)
    result = await uc.execute(Provider.EODHD, "AAPL", start, end, "1d", chunk_days=30)
    # Dec 1 → Dec 31 → Jan 30 → Feb 1  = 3 chunks
    assert result.chunks >= 2


@pytest.mark.unit
async def test_max_100_chunks_enforced() -> None:
    start = datetime(2020, 1, 1, tzinfo=UTC)
    end = datetime(2024, 12, 31, tzinfo=UTC)  # ~1826 days / 1 = 1826 chunks
    uow = _make_uow(inserted=0)
    uc = BackfillUseCase(uow)
    with pytest.raises(ValueError, match="100"):
        await uc.execute(Provider.EODHD, "AAPL", start, end, "1d", chunk_days=1)


@pytest.mark.unit
async def test_101_chunks_raises_value_error() -> None:
    start = datetime(2020, 1, 1, tzinfo=UTC)
    # 101 * 1 day = 101 days, chunk_days=1
    end = start + timedelta(days=101)
    uow = _make_uow(inserted=0)
    uc = BackfillUseCase(uow)
    with pytest.raises(ValueError):
        await uc.execute(Provider.EODHD, "AAPL", start, end, "1d", chunk_days=1)


@pytest.mark.unit
async def test_idempotent_same_range_same_dedupe_keys() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    end = datetime(2024, 2, 1, tzinfo=UTC)
    uow1 = _make_uow(inserted=1)
    uow2 = _make_uow(inserted=0)  # second call: 0 inserted (conflict)

    uc1 = BackfillUseCase(uow1)
    uc2 = BackfillUseCase(uow2)

    await uc1.execute(Provider.EODHD, "AAPL", start, end, "1d")
    await uc2.execute(Provider.EODHD, "AAPL", start, end, "1d")

    tasks1 = uow1.tasks.add_many.call_args[0][0]
    tasks2 = uow2.tasks.add_many.call_args[0][0]
    assert {t.dedupe_key for t in tasks1} == {t.dedupe_key for t in tasks2}
