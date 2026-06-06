"""Regression tests for PLAN-0104 W30 / BP-649 — forward P/E + PEG snapshot.

Pre-W30 the CurrentSnapshot schema dropped ``ForwardPE`` and ``PEGRatio``
from EODHD HIGHLIGHTS even though ``metric_extractor.py:109`` parsed them
into the underlying record. Round 3 benchmark Q6 ("What's AAPL forward
P/E?") failed because the LLM had no grounded path to a forward valuation
ratio. W30 surfaces both fields as nullable scalars on ``current_snapshot``.

These tests pin:
  * presence — both fields populated when HIGHLIGHTS supplies them,
  * absence — both fields are ``None`` when HIGHLIGHTS omits them (the
    schema default keeps the response backward-compatible for tickers
    without forward analyst coverage, e.g. micro-caps and most ETFs).
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from market_data.application.use_cases.get_fundamentals_history import (
    GetFundamentalsHistoryUseCase,
)
from market_data.domain.entities import FundamentalsRecord, Instrument
from market_data.domain.enums import FundamentalsSection, PeriodType
from market_data.domain.value_objects import InstrumentFlags

pytestmark = pytest.mark.unit


def _make_instrument() -> Instrument:
    return Instrument(
        id=str(uuid4()),
        security_id=str(uuid4()),
        symbol="AAPL",
        exchange="NASDAQ",
        flags=InstrumentFlags(),
        fiscal_year_end_month=9,
    )


def _make_record(
    section: FundamentalsSection,
    period_end: datetime,
    data: dict,
    period_type: PeriodType = PeriodType.QUARTERLY,
) -> FundamentalsRecord:
    return FundamentalsRecord(
        id=str(uuid4()),
        security_id=str(uuid4()),
        section=section,
        period_end=period_end,
        period_type=period_type,
        data=data,
        source="eodhd",
        ingested_at=period_end,
    )


def _build_uow(
    earnings_rows: list[FundamentalsRecord],
    income_rows: list[FundamentalsRecord],
    highlights_rows: list[FundamentalsRecord],
    instrument: Instrument,
) -> MagicMock:
    async def _find(
        _iid: str,
        section: FundamentalsSection,
        period_type: PeriodType | None = None,
    ) -> list[FundamentalsRecord]:
        if section == FundamentalsSection.EARNINGS_HISTORY:
            return earnings_rows
        if section == FundamentalsSection.INCOME_STATEMENT:
            return income_rows
        if section == FundamentalsSection.HIGHLIGHTS:
            return highlights_rows
        return []

    uow = MagicMock()
    uow.instruments_read = MagicMock()
    uow.instruments_read.find_by_id = AsyncMock(return_value=instrument)
    uow.fundamentals_read = MagicMock()
    uow.fundamentals_read.find_by_section = AsyncMock(side_effect=_find)
    return uow


@pytest.mark.asyncio
async def test_current_snapshot_includes_forward_pe_and_peg_when_present() -> None:
    """ForwardPE + PEGRatio in HIGHLIGHTS surface as floats on the snapshot."""
    instrument = _make_instrument()
    past_period_end = datetime(2026, 3, 31, tzinfo=UTC)
    earnings = [
        _make_record(
            FundamentalsSection.EARNINGS_HISTORY,
            past_period_end,
            {"reportDate": "2026-04-30", "epsActual": "2.01"},
        )
    ]
    income = [
        _make_record(
            FundamentalsSection.INCOME_STATEMENT,
            past_period_end,
            {"totalRevenue": "95000000000"},
        )
    ]
    highlights = [
        _make_record(
            FundamentalsSection.HIGHLIGHTS,
            datetime(2026, 6, 1, tzinfo=UTC),
            {
                "PERatio": "30.4",
                "ForwardPE": "27.8",
                "PEGRatio": "2.15",
                "MarketCapitalization": "3000000000000",
            },
            period_type=PeriodType.SNAPSHOT,
        )
    ]
    uow = _build_uow(earnings, income, highlights, instrument)
    uc = GetFundamentalsHistoryUseCase(uow=uow)
    result = await uc.execute(instrument_id=uuid4(), periods=1)

    snap = result["current_snapshot"]
    assert snap is not None
    assert snap["forward_pe"] == pytest.approx(27.8)
    assert snap["peg_ratio"] == pytest.approx(2.15)


@pytest.mark.asyncio
async def test_current_snapshot_forward_pe_and_peg_are_none_when_absent() -> None:
    """Missing ForwardPE/PEGRatio in HIGHLIGHTS → snapshot fields are None.

    The schema defaults keep the response backward-compatible for tickers
    without forward analyst coverage (micro-caps, most ETFs).
    """
    instrument = _make_instrument()
    past_period_end = datetime(2026, 3, 31, tzinfo=UTC)
    earnings = [
        _make_record(
            FundamentalsSection.EARNINGS_HISTORY,
            past_period_end,
            {"reportDate": "2026-04-30", "epsActual": "2.01"},
        )
    ]
    income = [
        _make_record(
            FundamentalsSection.INCOME_STATEMENT,
            past_period_end,
            {"totalRevenue": "95000000000"},
        )
    ]
    highlights = [
        _make_record(
            FundamentalsSection.HIGHLIGHTS,
            datetime(2026, 6, 1, tzinfo=UTC),
            {"PERatio": "30.4"},  # no ForwardPE/PEGRatio keys
            period_type=PeriodType.SNAPSHOT,
        )
    ]
    uow = _build_uow(earnings, income, highlights, instrument)
    uc = GetFundamentalsHistoryUseCase(uow=uow)
    result = await uc.execute(instrument_id=uuid4(), periods=1)

    snap = result["current_snapshot"]
    assert snap is not None
    assert snap["forward_pe"] is None
    assert snap["peg_ratio"] is None
