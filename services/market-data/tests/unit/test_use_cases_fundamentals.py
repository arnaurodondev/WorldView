"""Unit tests for fundamentals query use cases."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_data.application.use_cases.query_fundamentals import GetFundamentalsSectionUseCase
from market_data.domain.entities import FundamentalsRecord
from market_data.domain.enums import FundamentalsSection, PeriodType

pytestmark = pytest.mark.unit


def _make_record(section: FundamentalsSection = FundamentalsSection.INCOME_STATEMENT) -> FundamentalsRecord:
    return FundamentalsRecord(
        id="rec-001",
        security_id="instr-001",
        section=section,
        period_end=datetime(2024, 12, 31, tzinfo=UTC),
        period_type=PeriodType.ANNUAL,
        data={"revenue": 100_000_000, "net_income": 25_000_000},
        source="eodhd",
        ingested_at=datetime(2024, 1, 16, tzinfo=UTC),
    )


def _make_uow(records: list[FundamentalsRecord] | None = None) -> MagicMock:
    uow = MagicMock()
    repo = MagicMock()
    repo.find_by_section = AsyncMock(return_value=records or [])
    uow.fundamentals_read = repo
    return uow


@pytest.mark.asyncio
async def test_execute_returns_records_for_section() -> None:
    records = [_make_record(FundamentalsSection.INCOME_STATEMENT)]
    uow = _make_uow(records=records)
    uc = GetFundamentalsSectionUseCase(uow)
    result = await uc.execute("instr-001", FundamentalsSection.INCOME_STATEMENT)
    assert result == records
    # Backend-gaps wave 3 (2026-06-11): execute() now forwards an optional
    # period_type (default None) so statement endpoints can select ANNUAL rows.
    uow.fundamentals_read.find_by_section.assert_awaited_once_with(
        "instr-001", FundamentalsSection.INCOME_STATEMENT, None
    )


@pytest.mark.asyncio
async def test_execute_returns_empty_list_when_no_records() -> None:
    uow = _make_uow(records=[])
    uc = GetFundamentalsSectionUseCase(uow)
    result = await uc.execute("instr-001", FundamentalsSection.BALANCE_SHEET)
    assert result == []


@pytest.mark.asyncio
async def test_execute_all_sections_aggregates_all_sections() -> None:
    """execute_all_sections iterates over every FundamentalsSection member."""
    records_per_section = [_make_record()]
    uow = _make_uow(records=records_per_section)
    uc = GetFundamentalsSectionUseCase(uow)
    result = await uc.execute_all_sections("instr-001")
    # One record per section → total = len(FundamentalsSection)
    assert len(result) == len(FundamentalsSection)
    assert uow.fundamentals_read.find_by_section.await_count == len(FundamentalsSection)


@pytest.mark.asyncio
async def test_execute_all_sections_returns_empty_when_no_records() -> None:
    uow = _make_uow(records=[])
    uc = GetFundamentalsSectionUseCase(uow)
    result = await uc.execute_all_sections("instr-001")
    assert result == []


@pytest.mark.asyncio
async def test_execute_all_sections_concatenates_results() -> None:
    """Records from different sections are all collected into one list."""
    inc = _make_record(FundamentalsSection.INCOME_STATEMENT)
    bal = _make_record(FundamentalsSection.BALANCE_SHEET)
    call_count = 0

    async def _side_effect(instrument_id: str, section: FundamentalsSection) -> list[FundamentalsRecord]:
        nonlocal call_count
        call_count += 1
        if section == FundamentalsSection.INCOME_STATEMENT:
            return [inc]
        if section == FundamentalsSection.BALANCE_SHEET:
            return [bal]
        return []

    uow = MagicMock()
    uow.fundamentals_read = MagicMock()
    uow.fundamentals_read.find_by_section = AsyncMock(side_effect=_side_effect)

    uc = GetFundamentalsSectionUseCase(uow)
    result = await uc.execute_all_sections("instr-001")
    assert inc in result
    assert bal in result
