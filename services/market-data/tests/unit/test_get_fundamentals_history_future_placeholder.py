"""Regression test for PLAN-0103 W22 / BP-639 — future-dated placeholder drop.

WHY: EODHD's EARNINGS_HISTORY section pre-emits a row for the next scheduled
report date with ``epsActual=None``. After DESC-sort + slice [:1] this row
wins, the rag-chat LLM sees a "row" with every metric as "—", and FABRICATES
a P/E / EPS value (audit
``docs/audits/2026-06-01-chat-quality-aapl-pe-investigation.md`` — AAPL P/E
was answered as "37.7x" for the future-dated 2026-06-30 placeholder).

The defensive predicate in ``GetFundamentalsHistoryUseCase`` drops only rows
whose ``period_end`` is strictly in the future AND whose section-specific
driver metric (epsActual for QUARTERLY) is null. A legitimately-late filing
that lacks an unrelated optional field must still be returned.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
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


@pytest.mark.asyncio
async def test_future_dated_null_eps_placeholder_is_dropped() -> None:
    """Reproduces the AAPL 2026-06-30 placeholder bug.

    Two EARNINGS_HISTORY rows:
      - 2026-03-31 epsActual=2.01 (real, in the past)
      - <today+N> epsActual=None  (placeholder, in the future)

    With periods=1 the use case must return ONLY the 2026-03-31 row.
    Before the fix it returned the placeholder, which the LLM then quoted
    as the latest reported EPS.
    """
    instrument = _make_instrument()

    past_period_end = datetime(2026, 3, 31, tzinfo=UTC)
    # Future = today + 60 days so this test is stable regardless of the
    # actual calendar date when CI runs it.
    future_period_end = datetime.now(tz=UTC) + timedelta(days=60)

    real_row = _make_record(
        FundamentalsSection.EARNINGS_HISTORY,
        past_period_end,
        {"reportDate": "2026-04-30", "epsActual": "2.01"},
    )
    placeholder_row = _make_record(
        FundamentalsSection.EARNINGS_HISTORY,
        future_period_end,
        # Mirrors the real EODHD payload shape — only the report metadata is
        # populated, every metric is null.
        {"reportDate": future_period_end.strftime("%Y-%m-%d"), "epsActual": None},
    )

    async def _find(
        _iid: str,
        section: FundamentalsSection,
        period_type: PeriodType | None = None,
    ) -> list[FundamentalsRecord]:
        if section == FundamentalsSection.EARNINGS_HISTORY:
            return [real_row, placeholder_row]
        return []

    uow = MagicMock()
    uow.instruments_read = MagicMock()
    uow.instruments_read.find_by_id = AsyncMock(return_value=instrument)
    uow.fundamentals_read = MagicMock()
    uow.fundamentals_read.find_by_section = AsyncMock(side_effect=_find)

    uc = GetFundamentalsHistoryUseCase(uow=uow)
    result = await uc.execute(instrument_id=uuid4(), periods=1)

    assert result["period_count"] == 1
    period = result["periods"][0]
    assert (
        period["period_end_date"] == "2026-03-31"
    ), f"future placeholder leaked through: got period_end_date={period['period_end_date']}"
    assert period["eps"] == pytest.approx(2.01)


@pytest.mark.asyncio
async def test_past_row_with_null_eps_is_not_dropped() -> None:
    """Defensive predicate must not drop legitimate past rows.

    A reported quarter that happens to have a null epsActual (rare but
    possible — e.g. a restated row or a non-EPS-reporting issuer) must
    survive the filter because it is NOT in the future.
    """
    instrument = _make_instrument()

    past_period_end = datetime(2025, 12, 31, tzinfo=UTC)
    past_null_row = _make_record(
        FundamentalsSection.EARNINGS_HISTORY,
        past_period_end,
        {"reportDate": "2026-01-30", "epsActual": None},
    )

    async def _find(
        _iid: str,
        section: FundamentalsSection,
        period_type: PeriodType | None = None,
    ) -> list[FundamentalsRecord]:
        if section == FundamentalsSection.EARNINGS_HISTORY:
            return [past_null_row]
        return []

    uow = MagicMock()
    uow.instruments_read = MagicMock()
    uow.instruments_read.find_by_id = AsyncMock(return_value=instrument)
    uow.fundamentals_read = MagicMock()
    uow.fundamentals_read.find_by_section = AsyncMock(side_effect=_find)

    uc = GetFundamentalsHistoryUseCase(uow=uow)
    result = await uc.execute(instrument_id=uuid4(), periods=1)

    # Past rows with null EPS still surface — only the future-dated null-EPS
    # placeholder pattern is dropped.
    assert result["period_count"] == 1
    assert result["periods"][0]["eps"] is None
