"""Unit tests for PLAN-0104 W32 — unified query_fundamentals use case.

Covers:
  * snapshot-only mode (periods=0, include_snapshot=True)
  * per-period series projection over multiple raw metrics
  * derived metrics (gross_margin, operating_margin, fcf_yield)
  * coverage flag flagging (ok / partial / missing)
  * unknown metric names degrade to "missing" without 500
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from market_data.application.use_cases.query_fundamentals_metrics import QueryFundamentalsUseCase
from market_data.domain.entities import FundamentalsRecord, Instrument
from market_data.domain.enums import FundamentalsSection, PeriodType
from market_data.domain.value_objects import InstrumentFlags

pytestmark = pytest.mark.unit


def _instrument() -> Instrument:
    return Instrument(
        id=str(uuid4()),
        security_id=str(uuid4()),
        symbol="AAPL",
        exchange="NASDAQ",
        flags=InstrumentFlags(),
        fiscal_year_end_month=9,
    )


def _record(
    section: FundamentalsSection, period_end: datetime, data: dict, period_type: PeriodType = PeriodType.QUARTERLY
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


def _uow(records: dict[FundamentalsSection, list[FundamentalsRecord]], instrument: Instrument) -> MagicMock:
    async def _find(
        _iid: str, section: FundamentalsSection, period_type: PeriodType | None = None
    ) -> list[FundamentalsRecord]:
        return records.get(section, [])

    uow = MagicMock()
    uow.instruments_read = MagicMock()
    uow.instruments_read.find_by_id = AsyncMock(return_value=instrument)
    uow.fundamentals_read = MagicMock()
    uow.fundamentals_read.find_by_section = AsyncMock(side_effect=_find)
    return uow


@pytest.mark.asyncio
async def test_snapshot_only_returns_highlights_scalars() -> None:
    """periods=0 + snapshot metrics → snapshot populated, no period rows."""
    inst = _instrument()
    pe_date = datetime(2026, 3, 31, tzinfo=UTC)
    highlights = [
        _record(
            FundamentalsSection.HIGHLIGHTS,
            pe_date,
            {
                "PERatio": 30.4,
                "ForwardPE": 27.8,
                "PEGRatio": 2.15,
                "EVToEBITDA": 22.0,
                "MarketCapitalization": 3_000_000_000_000,
            },
        )
    ]
    uow = _uow({FundamentalsSection.HIGHLIGHTS: highlights}, inst)
    uc = QueryFundamentalsUseCase(uow)
    out = await uc.execute(
        instrument_id=uuid4(),
        metrics=["forward_pe", "peg_ratio", "ev_ebitda", "market_cap"],
        periods=0,
    )
    assert out["snapshot"] is not None
    assert out["snapshot"]["forward_pe"] == pytest.approx(27.8)
    assert out["snapshot"]["peg_ratio"] == pytest.approx(2.15)
    assert out["snapshot"]["market_cap"] == 3_000_000_000_000
    assert out["coverage"]["forward_pe"] == "ok"
    assert out["coverage"]["market_cap"] == "ok"
    assert out["metrics_by_period"] == []


@pytest.mark.asyncio
async def test_per_period_series_revenue_and_eps() -> None:
    """Quarterly revenue + EPS pulled from income_statement / earnings_history."""
    inst = _instrument()
    p1 = datetime(2025, 12, 31, tzinfo=UTC)
    p2 = datetime(2026, 3, 31, tzinfo=UTC)
    earnings = [
        _record(FundamentalsSection.EARNINGS_HISTORY, p1, {"reportDate": "2026-02-01", "epsActual": 1.95}),
        _record(FundamentalsSection.EARNINGS_HISTORY, p2, {"reportDate": "2026-05-01", "epsActual": 2.01}),
    ]
    income = [
        _record(
            FundamentalsSection.INCOME_STATEMENT, p1, {"totalRevenue": 90_000_000_000, "grossProfit": 39_000_000_000}
        ),
        _record(
            FundamentalsSection.INCOME_STATEMENT, p2, {"totalRevenue": 95_000_000_000, "grossProfit": 42_000_000_000}
        ),
    ]
    uow = _uow(
        {
            FundamentalsSection.EARNINGS_HISTORY: earnings,
            FundamentalsSection.INCOME_STATEMENT: income,
        },
        inst,
    )
    uc = QueryFundamentalsUseCase(uow)
    out = await uc.execute(
        instrument_id=uuid4(),
        metrics=["revenue", "eps"],
        periods=2,
        include_snapshot=False,
    )
    rows = out["metrics_by_period"]
    assert len(rows) == 2
    # ASC order — first row is the older period.
    assert rows[0]["revenue"] == 90_000_000_000
    assert rows[0]["eps"] == pytest.approx(1.95)
    assert rows[1]["revenue"] == 95_000_000_000
    assert rows[1]["eps"] == pytest.approx(2.01)
    assert out["coverage"]["revenue"] == "ok"
    assert out["coverage"]["eps"] == "ok"


@pytest.mark.asyncio
async def test_derived_gross_margin_computed() -> None:
    """gross_margin = gross_profit / revenue, loaded transitively."""
    inst = _instrument()
    p1 = datetime(2026, 3, 31, tzinfo=UTC)
    earnings = [_record(FundamentalsSection.EARNINGS_HISTORY, p1, {"reportDate": "2026-05-01", "epsActual": 2.0})]
    income = [
        _record(
            FundamentalsSection.INCOME_STATEMENT,
            p1,
            {"totalRevenue": 100_000_000_000, "grossProfit": 44_000_000_000, "operatingIncome": 30_000_000_000},
        )
    ]
    uow = _uow(
        {
            FundamentalsSection.EARNINGS_HISTORY: earnings,
            FundamentalsSection.INCOME_STATEMENT: income,
        },
        inst,
    )
    uc = QueryFundamentalsUseCase(uow)
    out = await uc.execute(
        instrument_id=uuid4(),
        metrics=["gross_margin", "operating_margin"],
        periods=1,
        include_snapshot=False,
    )
    row = out["metrics_by_period"][0]
    assert row["gross_margin"] == pytest.approx(0.44)
    assert row["operating_margin"] == pytest.approx(0.30)
    # Dependencies (revenue, gross_profit, operating_income) MUST NOT leak
    # into the row when the caller did not request them.
    assert "revenue" not in row
    assert "gross_profit" not in row
    assert out["coverage"]["gross_margin"] == "ok"


@pytest.mark.asyncio
async def test_coverage_partial_when_some_periods_missing() -> None:
    """Mix of populated + null periods → coverage = 'partial'."""
    inst = _instrument()
    p1 = datetime(2025, 12, 31, tzinfo=UTC)
    p2 = datetime(2026, 3, 31, tzinfo=UTC)
    earnings = [
        _record(FundamentalsSection.EARNINGS_HISTORY, p1, {"reportDate": "2026-02-01", "epsActual": 1.95}),
        _record(FundamentalsSection.EARNINGS_HISTORY, p2, {"reportDate": "2026-05-01", "epsActual": 2.01}),
    ]
    # Only one income_statement row → revenue partial.
    income = [_record(FundamentalsSection.INCOME_STATEMENT, p2, {"totalRevenue": 95_000_000_000})]
    uow = _uow(
        {
            FundamentalsSection.EARNINGS_HISTORY: earnings,
            FundamentalsSection.INCOME_STATEMENT: income,
        },
        inst,
    )
    uc = QueryFundamentalsUseCase(uow)
    out = await uc.execute(
        instrument_id=uuid4(),
        metrics=["revenue", "eps"],
        periods=2,
        include_snapshot=False,
    )
    assert out["coverage"]["revenue"] == "partial"
    assert out["coverage"]["eps"] == "ok"


@pytest.mark.asyncio
async def test_unknown_metric_flagged_missing_not_500() -> None:
    """Speculative metric names get a 'missing' flag instead of an exception."""
    inst = _instrument()
    uow = _uow({}, inst)
    uc = QueryFundamentalsUseCase(uow)
    out = await uc.execute(
        instrument_id=uuid4(),
        metrics=["this_metric_does_not_exist", "forward_pe"],
        periods=0,
    )
    assert out["coverage"]["this_metric_does_not_exist"] == "missing"
    assert out["coverage"]["forward_pe"] == "missing"  # no highlights row loaded


@pytest.mark.asyncio
async def test_revenue_request_auto_includes_derived_margins() -> None:
    """PLAN-0104 W39: a bare ``revenue`` request also surfaces the three margin
    derivations when their components are available — so "TSLA revenue trend"
    questions get gross/operating/net margin context without an extra round-trip.
    """
    inst = _instrument()
    p1 = datetime(2025, 12, 31, tzinfo=UTC)
    p2 = datetime(2026, 3, 31, tzinfo=UTC)
    earnings = [
        _record(FundamentalsSection.EARNINGS_HISTORY, p1, {"reportDate": "2026-02-01", "epsActual": 1.95}),
        _record(FundamentalsSection.EARNINGS_HISTORY, p2, {"reportDate": "2026-05-01", "epsActual": 2.01}),
    ]
    income = [
        _record(
            FundamentalsSection.INCOME_STATEMENT,
            p1,
            {
                "totalRevenue": 100_000_000_000,
                "grossProfit": 44_000_000_000,
                "operatingIncome": 30_000_000_000,
                "netIncome": 25_000_000_000,
            },
        ),
        _record(
            FundamentalsSection.INCOME_STATEMENT,
            p2,
            {
                "totalRevenue": 110_000_000_000,
                "grossProfit": 50_000_000_000,
                "operatingIncome": 35_000_000_000,
                "netIncome": 28_000_000_000,
            },
        ),
    ]
    uow = _uow(
        {
            FundamentalsSection.EARNINGS_HISTORY: earnings,
            FundamentalsSection.INCOME_STATEMENT: income,
        },
        inst,
    )
    uc = QueryFundamentalsUseCase(uow)
    out = await uc.execute(
        instrument_id=uuid4(),
        metrics=["revenue"],
        periods=2,
        include_snapshot=False,
    )
    rows = out["metrics_by_period"]
    assert len(rows) == 2
    # Revenue still present (caller asked for it).
    assert rows[0]["revenue"] == 100_000_000_000
    # Auto-added derivations: gross_margin / operating_margin / net_margin.
    assert rows[0]["gross_margin"] == pytest.approx(0.44)
    assert rows[0]["operating_margin"] == pytest.approx(0.30)
    assert rows[0]["net_margin"] == pytest.approx(0.25)
    assert rows[1]["gross_margin"] == pytest.approx(0.4545, rel=1e-3)
    # Coverage flags the auto-added margins too.
    assert out["coverage"]["gross_margin"] == "ok"
    assert out["coverage"]["operating_margin"] == "ok"
    assert out["coverage"]["net_margin"] == "ok"


@pytest.mark.asyncio
async def test_revenue_auto_margins_none_when_components_missing() -> None:
    """PLAN-0104 W39: when revenue is present but gross_profit/operating_income/
    net_income are absent, the auto-added margin cells are None (not fabricated).
    """
    inst = _instrument()
    p1 = datetime(2026, 3, 31, tzinfo=UTC)
    earnings = [_record(FundamentalsSection.EARNINGS_HISTORY, p1, {"reportDate": "2026-05-01", "epsActual": 2.0})]
    # Revenue only — no gross_profit / operating_income / net_income.
    income = [_record(FundamentalsSection.INCOME_STATEMENT, p1, {"totalRevenue": 100_000_000_000})]
    uow = _uow(
        {FundamentalsSection.EARNINGS_HISTORY: earnings, FundamentalsSection.INCOME_STATEMENT: income},
        inst,
    )
    uc = QueryFundamentalsUseCase(uow)
    out = await uc.execute(
        instrument_id=uuid4(),
        metrics=["revenue"],
        periods=1,
        include_snapshot=False,
    )
    row = out["metrics_by_period"][0]
    assert row["revenue"] == 100_000_000_000
    # Margins MUST be None — never fabricated from a missing dependency.
    assert row["gross_margin"] is None
    assert row["operating_margin"] is None
    assert row["net_margin"] is None
    assert out["coverage"]["gross_margin"] == "missing"


@pytest.mark.asyncio
async def test_snapshot_includes_as_of_when_highlights_present() -> None:
    """include_snapshot=True with a HIGHLIGHTS row stamps as_of + source."""
    inst = _instrument()
    pe_date = datetime(2026, 3, 31, tzinfo=UTC)
    highlights = [_record(FundamentalsSection.HIGHLIGHTS, pe_date, {"PERatio": 30.4})]
    uow = _uow({FundamentalsSection.HIGHLIGHTS: highlights}, inst)
    uc = QueryFundamentalsUseCase(uow)
    out = await uc.execute(
        instrument_id=uuid4(),
        metrics=["pe_ratio"],
        periods=0,
        include_snapshot=True,
    )
    snap = out["snapshot"]
    assert snap is not None
    assert snap["as_of"] == "2026-03-31"
    assert snap["source"] == "highlights"
    assert snap["pe_ratio"] == pytest.approx(30.4)
