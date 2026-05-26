"""Unit tests for `_period_label` and the use-case-level missing-quarter warning.

FIX-LIVE-P regression tests (2026-05-25):
  Pre-fix, `_period_label` used calendar months to derive the quarter,
  mislabelling fiscal periods for any issuer whose fiscal year does not
  align with the calendar. This test file pins the post-fix behaviour for
  the four major non-calendar issuers + the fiscal-year-unknown fallback.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from datetime import UTC
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import structlog
from market_data.application.use_cases.get_fundamentals_history import (
    GetFundamentalsHistoryUseCase,
    _normalise_quarter_label,
    _period_label,
)
from market_data.domain.entities import FundamentalsRecord, Instrument
from market_data.domain.enums import FundamentalsSection, PeriodType
from market_data.domain.value_objects import InstrumentFlags

pytestmark = pytest.mark.unit


# ── _period_label: fiscal-quarter computation ───────────────────────────────


@pytest.mark.parametrize(
    ("report_date", "fy_end", "expected"),
    [
        # NVIDIA: fiscal year ends late January → FY26 ends 2026-01-31.
        # Pre-fix this was "Q1 2026" (calendar quarter). Post-fix: Q4 FY2026.
        ("2026-01-31", 1, "Q4 FY2026"),
        ("2025-10-31", 1, "Q3 FY2026"),  # NVDA Q3FY26 reported in Nov 2025
        ("2025-04-30", 1, "Q1 FY2026"),
        # Apple: fiscal year ends late September → FY26 ends 2026-09-30.
        # Pre-fix this was "Q3 2026" (calendar quarter). Post-fix: Q4 FY2026.
        ("2026-09-30", 9, "Q4 FY2026"),
        ("2025-12-31", 9, "Q1 FY2026"),  # Dec is first month of Apple FY26
        ("2026-03-31", 9, "Q2 FY2026"),
        ("2026-06-30", 9, "Q3 FY2026"),
        # Microsoft: fiscal year ends June 30 → FY26 ends 2026-06-30.
        ("2026-06-30", 6, "Q4 FY2026"),
        ("2025-09-30", 6, "Q1 FY2026"),  # first quarter of MSFT FY26
        ("2025-12-31", 6, "Q2 FY2026"),
        ("2026-03-31", 6, "Q3 FY2026"),
        # AMD: fiscal year ends in December → fiscal = calendar.
        ("2026-03-31", 12, "Q1 FY2026"),
        ("2026-06-30", 12, "Q2 FY2026"),
        ("2026-09-30", 12, "Q3 FY2026"),
        ("2026-12-31", 12, "Q4 FY2026"),
    ],
)
def test_period_label_fiscal_quarter_correct(report_date: str, fy_end: int, expected: str) -> None:
    """`_period_label` returns the correct fiscal quarter when fy_end is known."""
    assert _period_label(report_date, fiscal_year_end_month=fy_end, ticker="TEST") == expected


def test_period_label_fallback_when_fy_end_unknown() -> None:
    """When fiscal_year_end_month is None, fall back to calendar-quarter labels."""
    # No FY name suffix in the fallback — the old "Q1 2026" form is preserved
    # so the response shape is unchanged for unseeded instruments.
    assert _period_label("2026-03-31", fiscal_year_end_month=None) == "Q1 2026"
    assert _period_label("2025-12-31", fiscal_year_end_month=None) == "Q4 2025"


@pytest.mark.parametrize("bad_month", [0, 13, -1, 99])
def test_period_label_fallback_when_fy_end_out_of_range(bad_month: int) -> None:
    """Out-of-range fy_end values are treated as unknown (defensive)."""
    assert _period_label("2026-03-31", fiscal_year_end_month=bad_month) == "Q1 2026"


def test_period_label_invalid_date_passes_through() -> None:
    """Unparseable dates are returned unchanged (preserves the original behaviour)."""
    assert _period_label("not-a-date") == "not-a-date"
    assert _period_label("not-a-date", fiscal_year_end_month=9) == "not-a-date"


def test_period_label_emits_warning_when_fy_end_unknown(caplog: pytest.LogCaptureFixture) -> None:
    """The fallback path emits a structured ``fiscal_year_end_unknown`` warning."""
    # structlog routes through stdlib logging by default; capture at WARNING.
    with _capturing_structlog_warnings(caplog):
        _period_label("2026-03-31", fiscal_year_end_month=None, ticker="UNKNOWN")
    assert any(
        "fiscal_year_end_unknown" in rec.getMessage() for rec in caplog.records
    ), f"expected fiscal_year_end_unknown warning, got: {[r.getMessage() for r in caplog.records]}"


# ── _normalise_quarter_label: tolerant matching ──────────────────────────────


@pytest.mark.parametrize(
    ("a", "b"),
    [
        ("Q4 FY2026", "Q4 2026"),
        ("Q4 FY2026", "q4 fy 2026"),
        ("Q4 FY2026", "Q4-FY26"),
        ("Q1 FY2026", "Q1 fy2026"),
    ],
)
def test_normalise_quarter_label_equivalence(a: str, b: str) -> None:
    """Variant quarter labels normalise to the same canonical form."""
    assert _normalise_quarter_label(a) == _normalise_quarter_label(b)


def test_normalise_quarter_label_distinguishes_different_quarters() -> None:
    """Different quarters or years normalise to DIFFERENT canonical forms."""
    assert _normalise_quarter_label("Q3 FY2026") != _normalise_quarter_label("Q4 FY2026")
    assert _normalise_quarter_label("Q4 FY2025") != _normalise_quarter_label("Q4 FY2026")


# ── execute(): missing-quarter observability ──────────────────────────────────


def _make_instrument(symbol: str = "NVDA", fy_end: int | None = 1) -> Instrument:
    return Instrument(
        id=str(uuid4()),
        security_id=str(uuid4()),
        symbol=symbol,
        exchange="NASDAQ",
        flags=InstrumentFlags(),
        fiscal_year_end_month=fy_end,
    )


def _make_record(period_end_iso: str, report_date_iso: str | None = None) -> FundamentalsRecord:
    """Build a FundamentalsRecord that mimics the EARNINGS_HISTORY shape."""
    from datetime import datetime

    period_end = datetime.fromisoformat(period_end_iso).replace(tzinfo=UTC)
    return FundamentalsRecord(
        id=str(uuid4()),
        security_id=str(uuid4()),
        section=FundamentalsSection.EARNINGS_HISTORY,
        period_end=period_end,
        period_type=PeriodType.QUARTERLY,
        data={"reportDate": report_date_iso or period_end_iso, "epsActual": "1.23"},
        source="eodhd",
        ingested_at=period_end,
    )


def _make_uow(
    *,
    instrument: Instrument | None,
    earnings: list[FundamentalsRecord],
) -> MagicMock:
    """Construct a ReadOnlyUnitOfWork mock with the minimum surface the UC touches."""
    uow = MagicMock()
    uow.instruments_read = MagicMock()
    uow.instruments_read.find_by_id = AsyncMock(return_value=instrument)

    uow.fundamentals_read = MagicMock()

    async def _find(
        _iid: str,
        section: FundamentalsSection,
        period_type: PeriodType | None = None,  # PLAN-0095 W1 T-W1-01: filter param added
    ) -> list[FundamentalsRecord]:
        if section == FundamentalsSection.EARNINGS_HISTORY:
            return earnings
        return []  # income statement / highlights — empty for these tests

    uow.fundamentals_read.find_by_section = AsyncMock(side_effect=_find)
    return uow


@pytest.mark.asyncio
async def test_execute_labels_nvda_period_as_fiscal_q4(caplog: pytest.LogCaptureFixture) -> None:
    """NVDA's 2026-01-31 period must surface as ``Q4 FY2026`` end-to-end."""
    instr = _make_instrument(symbol="NVDA", fy_end=1)
    rec = _make_record("2026-01-31")
    uc = GetFundamentalsHistoryUseCase(uow=_make_uow(instrument=instr, earnings=[rec]))
    result = await uc.execute(instrument_id=uuid4(), periods=8)
    assert result["period_count"] == 1
    assert result["periods"][0]["period"] == "Q4 FY2026"


@pytest.mark.asyncio
async def test_execute_emits_missing_quarter_warning(caplog: pytest.LogCaptureFixture) -> None:
    """When requested_quarter is absent from the periods, emit a warning."""
    instr = _make_instrument(symbol="NVDA", fy_end=1)
    # Only Q3 FY2026 present (period_end 2025-10-31), but the user asked for Q4 FY2026.
    rec = _make_record("2025-10-31")
    uc = GetFundamentalsHistoryUseCase(uow=_make_uow(instrument=instr, earnings=[rec]))

    with _capturing_structlog_warnings(caplog):
        result = await uc.execute(
            instrument_id=uuid4(),
            periods=8,
            requested_quarter="Q4 FY2026",
        )

    assert result["period_count"] == 1
    assert result["periods"][0]["period"] == "Q3 FY2026"
    assert any("fundamentals_quarterly_missing" in rec.getMessage() for rec in caplog.records), (
        f"expected fundamentals_quarterly_missing warning, got: " f"{[r.getMessage() for r in caplog.records]}"
    )


@pytest.mark.asyncio
async def test_execute_does_not_warn_when_requested_quarter_present(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """No warning when the requested quarter IS in the returned periods."""
    instr = _make_instrument(symbol="NVDA", fy_end=1)
    rec = _make_record("2026-01-31")  # Q4 FY2026
    uc = GetFundamentalsHistoryUseCase(uow=_make_uow(instrument=instr, earnings=[rec]))

    with _capturing_structlog_warnings(caplog):
        await uc.execute(
            instrument_id=uuid4(),
            periods=8,
            requested_quarter="Q4 FY2026",
        )

    assert not any("fundamentals_quarterly_missing" in rec.getMessage() for rec in caplog.records)


@pytest.mark.asyncio
async def test_execute_falls_back_when_instrument_unknown() -> None:
    """If the instrument is not found, fall back to calendar-quarter labels (no crash)."""
    rec = _make_record("2026-01-31")
    uc = GetFundamentalsHistoryUseCase(uow=_make_uow(instrument=None, earnings=[rec]))
    result = await uc.execute(instrument_id=uuid4(), periods=8)
    # No FY annotation when fy_end is unknown.
    assert result["periods"][0]["period"] == "Q1 2026"


# ── helpers ──────────────────────────────────────────────────────────────────


@contextmanager
def _capturing_structlog_warnings(caplog: pytest.LogCaptureFixture) -> Any:
    """Ensure structlog warnings reach the stdlib logger that caplog reads.

    WHY THIS IS NEEDED: the project uses structlog exclusively, but pytest's
    `caplog` listens on the stdlib logging chain. structlog's default
    configuration is "configure_once" with processors that print to stderr,
    NOT route through stdlib. For tests we temporarily reconfigure structlog
    to forward to stdlib logging at WARNING and re-enable propagation.
    """
    # Save & restore: structlog has process-global config, so be careful.
    original = structlog.get_config()
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.KeyValueRenderer(key_order=["event"]),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )
    caplog.set_level(logging.WARNING)
    try:
        yield
    finally:
        structlog.configure(**original)
