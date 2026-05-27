"""Integration-style unit tests for ``GetFundamentalsHistoryUseCase`` periodicity.

PLAN-0097 W1 T-W1-03: replaces the tautological mock-based assertions in
``test_fundamentals_query_defaults.py`` with an end-to-end exercise of the
real use case. We seed BOTH a QUARTERLY and an ANNUAL income-statement row
at the same ``period_end_date`` for the same instrument and assert that the
use case returns the QUARTERLY revenue ($10B), never the ANNUAL one ($40B).

WHY this matters: pre-PLAN-0095 the income_statement JOIN by period_end
allowed an ANNUAL row to shadow the quarterly row when both shared an
end-date (e.g. FY2024 annual + Q4 FY2024 quarterly both reporting
2024-12-31). The audit
``2026-05-27-plan-0097-data-integrity-investigation.md`` Part A identified
this exact pattern as the root of the $26.4B AMD revenue leak. PLAN-0095
W1 added a ``period_type=QUARTERLY`` filter at the use-case layer; this
test pins that filter against a realistic mixed-periodicity dataset and
also verifies the new ``period_type`` per-row label introduced by
PLAN-0097 T-W1-01 (BP-577).

The fake ``find_by_section`` here honours the ``period_type`` kwarg
exactly as the real ``query_fundamentals`` repository does, so this test
exercises the actual contract — not a tautology that mocks the SQL and
asserts the mock.
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


# ── Test data builders ──────────────────────────────────────────────────────


def _make_instrument(symbol: str = "AMD", fy_end: int | None = 12) -> Instrument:
    """Construct a minimum-viable instrument for the use case."""
    return Instrument(
        id=str(uuid4()),
        security_id=str(uuid4()),
        symbol=symbol,
        exchange="NASDAQ",
        flags=InstrumentFlags(),
        fiscal_year_end_month=fy_end,
    )


def _make_record(
    section: FundamentalsSection,
    period_end_iso: str,
    period_type: PeriodType,
    data: dict,
) -> FundamentalsRecord:
    """Build a FundamentalsRecord for a given section + periodicity."""
    period_end = datetime.fromisoformat(period_end_iso).replace(tzinfo=UTC)
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


def _make_uow_with_mixed_periodicity(
    instrument: Instrument,
    *,
    period_end_iso: str = "2024-12-31",
    quarterly_revenue: float = 10_000_000_000.0,
    annual_revenue: float = 40_000_000_000.0,
) -> MagicMock:
    """ReadOnlyUnitOfWork mock that returns BOTH a QUARTERLY and an ANNUAL
    income-statement row at the same period_end_date.

    The fake ``find_by_section`` honours the ``period_type`` kwarg so this
    test verifies the use case's actual filter behaviour against the real
    repository contract (PLAN-0095 T-W1-02).
    """
    quarterly_inc = _make_record(
        FundamentalsSection.INCOME_STATEMENT,
        period_end_iso,
        PeriodType.QUARTERLY,
        {"totalRevenue": quarterly_revenue, "netIncome": 1_500_000_000.0},
    )
    annual_inc = _make_record(
        FundamentalsSection.INCOME_STATEMENT,
        period_end_iso,
        PeriodType.ANNUAL,
        {"totalRevenue": annual_revenue, "netIncome": 6_000_000_000.0},
    )
    earnings = _make_record(
        FundamentalsSection.EARNINGS_HISTORY,
        period_end_iso,
        PeriodType.QUARTERLY,
        {"reportDate": period_end_iso, "epsActual": "1.23"},
    )

    uow = MagicMock()
    uow.instruments_read = MagicMock()
    uow.instruments_read.find_by_id = AsyncMock(return_value=instrument)
    uow.fundamentals_read = MagicMock()

    async def _find(
        _iid: str,
        section: FundamentalsSection,
        period_type: PeriodType | None = None,
    ) -> list[FundamentalsRecord]:
        # Mirror real query_fundamentals semantics: filter by period_type when
        # supplied; return both rows when None. EARNINGS_HISTORY is quarterly-
        # only in EODHD's schema so the period_type kwarg is irrelevant there.
        if section == FundamentalsSection.INCOME_STATEMENT:
            rows = [quarterly_inc, annual_inc]
            if period_type is not None:
                rows = [r for r in rows if r.period_type == period_type]
            return rows
        if section == FundamentalsSection.EARNINGS_HISTORY:
            return [earnings]
        # HIGHLIGHTS — empty so the test focuses on the income-statement leak path.
        return []

    uow.fundamentals_read.find_by_section = AsyncMock(side_effect=_find)
    return uow


# ── Tests ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_quarterly_revenue_not_shadowed_by_same_period_annual_row() -> None:
    """BP-577 regression: when QUARTERLY ($10B) and ANNUAL ($40B) rows share a
    ``period_end_date``, the use case must return the QUARTERLY value.

    Reproduces the $26.4B AMD pattern from the 2026-05-27 chat-eval audit.
    """
    instrument = _make_instrument(symbol="AMD", fy_end=12)
    uow = _make_uow_with_mixed_periodicity(
        instrument,
        period_end_iso="2024-12-31",
        quarterly_revenue=10_000_000_000.0,
        annual_revenue=40_000_000_000.0,
    )
    uc = GetFundamentalsHistoryUseCase(uow=uow)

    result = await uc.execute(instrument_id=uuid4(), periods=8)

    assert result["period_count"] == 1
    period = result["periods"][0]
    # The single returned period must carry the QUARTERLY revenue, NOT the annual.
    assert period["revenue"] == pytest.approx(10_000_000_000.0), (
        f"expected QUARTERLY $10B, got {period['revenue']} " f"(ANNUAL leak risk if this is $40B)"
    )
    # Net income must also be from the QUARTERLY row.
    assert period["net_income"] == pytest.approx(1_500_000_000.0)


@pytest.mark.asyncio
async def test_every_returned_row_carries_explicit_period_type_label() -> None:
    """BP-577 defense-in-depth: every output row must have a non-null
    ``period_type`` field set to ``"QUARTERLY"`` so consumers (and the LLM
    via the rag-chat tool layer) cannot quote a value without knowing its
    periodicity.
    """
    instrument = _make_instrument(symbol="AMD", fy_end=12)
    uow = _make_uow_with_mixed_periodicity(instrument)
    uc = GetFundamentalsHistoryUseCase(uow=uow)

    result = await uc.execute(instrument_id=uuid4(), periods=8)

    assert result["period_count"] >= 1
    for period in result["periods"]:
        # The label is mandatory by PLAN-0097 T-W1-01 contract.
        assert "period_type" in period, f"period missing period_type: {period}"
        assert period["period_type"] == "QUARTERLY", f"unexpected period_type label: {period['period_type']}"


@pytest.mark.asyncio
async def test_use_case_forwards_quarterly_filter_to_repository() -> None:
    """The use case MUST call ``find_by_section`` for INCOME_STATEMENT with
    ``period_type=PeriodType.QUARTERLY`` — that filter is the actual guard
    against the $26.4B leak.

    This complements the row-value assertion above by pinning the contract
    at the port boundary, so a future refactor that drops the filter (and
    relies only on row-level filtering downstream) is caught immediately.
    """
    instrument = _make_instrument(symbol="AMD", fy_end=12)
    uow = _make_uow_with_mixed_periodicity(instrument)
    uc = GetFundamentalsHistoryUseCase(uow=uow)

    await uc.execute(instrument_id=uuid4(), periods=8)

    # Inspect the recorded calls to find_by_section: the INCOME_STATEMENT
    # call must include period_type=QUARTERLY.
    calls = uow.fundamentals_read.find_by_section.await_args_list
    income_calls = [c for c in calls if c.args[1] == FundamentalsSection.INCOME_STATEMENT]
    assert len(income_calls) == 1, f"expected exactly 1 INCOME_STATEMENT call, got {len(income_calls)}"
    # period_type may be passed positionally or via kwarg depending on the
    # use case implementation — accept either.
    call = income_calls[0]
    period_type_arg = call.kwargs.get("period_type")
    if period_type_arg is None and len(call.args) >= 3:
        period_type_arg = call.args[2]
    assert period_type_arg == PeriodType.QUARTERLY, f"INCOME_STATEMENT fetched without QUARTERLY filter: {call}"
