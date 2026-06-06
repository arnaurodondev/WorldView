"""Regression tests for PLAN-0103 W25 / BP-640 — snapshot-vs-period-row P/E.

WHY: The HIGHLIGHTS section is a single TTM/live valuation snapshot, not a
per-period stream. Pre-W25 ``GetFundamentalsHistoryUseCase`` injected the
TTM PERatio + MarketCapitalization into EVERY period row, causing the LLM
to either (a) quote the TTM ratio as a per-period figure (fabrication) or
(b) refuse because the per-period pe_ratio cell looked empty.

W25 splits the response into:
  * ``periods`` — flow/operating metrics per period; ``pe_ratio`` and
    ``market_cap`` are now ALWAYS None on every row.
  * ``current_snapshot`` — a sibling dict with the TTM/live ratios + an
    explicit ``as_of`` date sourced from the most-recent HIGHLIGHTS row.

These tests pin the new shape so a future refactor cannot silently re-
introduce the snapshot-leak bug.
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
    """Glue helper: a MagicMock UoW that dispatches by section enum."""

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
async def test_current_snapshot_is_populated_when_highlights_exist() -> None:
    """A live PERatio from HIGHLIGHTS surfaces in ``current_snapshot``, not periods."""
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
            {"totalRevenue": "95000000000", "netIncome": "23000000000"},
        )
    ]
    highlights = [
        _make_record(
            FundamentalsSection.HIGHLIGHTS,
            datetime(2026, 6, 1, tzinfo=UTC),
            {
                "PERatio": "30.4",
                "MarketCapitalization": "3000000000000",
                "EVToEBITDA": "22.5",
                "PriceBookMRQ": "45.6",
                "DividendYield": "0.0054",
            },
            period_type=PeriodType.SNAPSHOT,
        )
    ]

    uow = _build_uow(earnings, income, highlights, instrument)
    uc = GetFundamentalsHistoryUseCase(uow=uow)
    result = await uc.execute(instrument_id=uuid4(), periods=1)

    # Period rows MUST NOT carry the snapshot fields any more.
    assert result["period_count"] == 1
    period = result["periods"][0]
    assert period["pe_ratio"] is None, "TTM P/E leaked into the period row (BP-640 regression)"
    assert period["market_cap"] is None, "TTM market cap leaked into the period row"

    # The sibling snapshot block must carry the live valuation ratios.
    snap = result["current_snapshot"]
    assert snap is not None, "expected a current_snapshot block when HIGHLIGHTS exists"
    assert snap["pe_ratio"] == pytest.approx(30.4)
    assert snap["market_cap_usd"] == pytest.approx(3_000_000_000_000.0)
    assert snap["ev_ebitda"] == pytest.approx(22.5)
    assert snap["price_to_book"] == pytest.approx(45.6)
    assert snap["dividend_yield"] == pytest.approx(0.0054)
    # ``as_of`` is the period_end of the most-recent HIGHLIGHTS row.
    assert snap["as_of"].isoformat() == "2026-06-01"
    assert snap["source"] == "highlights"


@pytest.mark.asyncio
async def test_current_snapshot_is_none_when_highlights_empty() -> None:
    """No HIGHLIGHTS rows → ``current_snapshot`` is None (not an empty dict)."""
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
    uow = _build_uow(earnings, income, [], instrument)
    uc = GetFundamentalsHistoryUseCase(uow=uow)
    result = await uc.execute(instrument_id=uuid4(), periods=1)
    assert result["current_snapshot"] is None
    # And per-row snapshot fields stay None too (no leakage path remains).
    assert result["periods"][0]["pe_ratio"] is None
    assert result["periods"][0]["market_cap"] is None
