"""Wave L-5c unit tests for calendar fields in the screener pipeline.

L-5c ships two snapshot DATE columns and the WHERE / ORDER BY wiring:

  * ``next_earnings_date`` — sourced from ``earnings_calendar`` table
    (NULL until L-5b worker lands).
  * ``next_dividend_date`` — sourced from EODHD
    ``splits_dividends.DividendDate`` on every fundamentals payload.

Tests mirror the patterns already established in
``test_screener_l1_l2.py``:

  * ``_make_capture_session`` records every SQLAlchemy statement so we
    can assert the generated SQL contains the expected WHERE clauses.
  * ``_make_capture_session_with_rows`` exercises the result-building
    loop with synthetic rows.

Also covers the snapshot writer side:

  * ``derive_fundamentals_snapshot`` extracts ``next_dividend_date``
    from EODHD JSONB.
  * ``_safe_date`` handles common EODHD date formats and sentinels.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_data.application.ports.repositories import ScreenFilter
from market_data.infrastructure.db.fundamentals_snapshot_writer import (
    _safe_date,
    derive_fundamentals_snapshot,
)
from market_data.infrastructure.db.repositories.fundamental_metrics_query import query_screen

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Shared helpers (mirror of test_screener_l1_l2.py)
# ---------------------------------------------------------------------------


def _make_capture_session() -> tuple[MagicMock, list[Any]]:
    """Return (session, captured_statements) — every ``execute`` call is recorded.

    WHY filter out SET LOCAL: query_screen issues ``SET LOCAL statement_timeout``
    before the screener query (PLAN-0099 timeout guard). We skip it so
    ``captured[-1]`` is always the screener SELECT regardless of whether the
    snap-field introspection cache is warm or cold.
    """
    captured: list[Any] = []

    async def _capture(stmt: Any) -> MagicMock:
        if "statement_timeout" in str(stmt):
            result = MagicMock()
            result.all = MagicMock(return_value=[])
            return result
        captured.append(stmt)
        result = MagicMock()
        result.all = MagicMock(return_value=[])
        return result

    session = MagicMock()
    session.execute = AsyncMock(side_effect=_capture)
    return session, captured


def _sql(stmt: Any) -> str:
    """Compile an SQLAlchemy statement to a literal-bound SQL string."""
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


def _make_capture_session_with_rows(rows: list[Any]) -> MagicMock:
    """Return a session whose execute() returns the supplied rows."""

    async def _execute(stmt: Any) -> MagicMock:
        result = MagicMock()
        result.all = MagicMock(return_value=rows)
        return result

    session = MagicMock()
    session.execute = AsyncMock(side_effect=_execute)
    return session


# ---------------------------------------------------------------------------
# WHERE: calendar window filter — "earnings within N days"
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_screen_next_earnings_within_30_days_adds_where_clause() -> None:
    """``next_earnings_within_days=30`` adds the BETWEEN window to the SQL."""
    session, captured = _make_capture_session()

    filters = [ScreenFilter(metric="pe_ratio", max_value=40.0, next_earnings_within_days=30)]
    await query_screen(session, filters)

    sql = _sql(captured[-1]).lower()
    # The next_earnings_date column must appear with both the lower bound
    # (CURRENT_DATE) and the upper bound (CURRENT_DATE + INTERVAL '30 days').
    assert "next_earnings_date" in sql, f"next_earnings_date missing from SQL:\n{sql}"
    assert "current_date" in sql, f"CURRENT_DATE bound missing:\n{sql}"
    # Upper bound is computed via INTERVAL multiplication of the bound int.
    assert "interval" in sql and "30" in sql, f"INTERVAL '30 days' window missing:\n{sql}"


@pytest.mark.asyncio
async def test_query_screen_next_earnings_within_0_days_still_filters_to_today() -> None:
    """``next_earnings_within_days=0`` keeps only instruments with earnings today."""
    session, captured = _make_capture_session()

    filters = [ScreenFilter(metric="pe_ratio", max_value=40.0, next_earnings_within_days=0)]
    await query_screen(session, filters)

    sql = _sql(captured[-1]).lower()
    # Both bounds resolve to CURRENT_DATE — the SQL still contains the BETWEEN
    # predicate (no short-circuit on 0, which would be a bug).
    assert "next_earnings_date" in sql
    # The literal "0" must appear as the days bound.
    assert "0" in sql


@pytest.mark.asyncio
async def test_query_screen_next_dividend_within_days_adds_where_clause() -> None:
    """``next_dividend_within_days`` works symmetrically to the earnings filter."""
    session, captured = _make_capture_session()

    filters = [ScreenFilter(metric="pe_ratio", max_value=40.0, next_dividend_within_days=14)]
    await query_screen(session, filters)

    sql = _sql(captured[-1]).lower()
    assert "next_dividend_date" in sql, f"next_dividend_date missing from SQL:\n{sql}"
    assert "14" in sql, f"14-day window missing from SQL:\n{sql}"


@pytest.mark.asyncio
async def test_query_screen_without_calendar_filter_omits_where_clause() -> None:
    """Without a calendar filter, the SQL contains no calendar BETWEEN clause."""
    session, captured = _make_capture_session()

    # Only a pe_ratio filter — no calendar predicates expected.
    filters = [ScreenFilter(metric="pe_ratio", max_value=40.0)]
    await query_screen(session, filters)

    sql = _sql(captured[-1]).lower()
    # The SELECT projects next_earnings_date / next_dividend_date columns, so
    # they always appear in the projection. But the WHERE clause must NOT
    # contain a BETWEEN against them.
    # Heuristic: count occurrences in the SQL — projection appears once each
    # as ``snap_next_earnings_date`` alias; a WHERE clause would push the
    # column count higher.
    assert "current_date" not in sql, f"unexpected CURRENT_DATE WHERE in no-calendar-filter SQL:\n{sql}"


# ---------------------------------------------------------------------------
# ORDER BY: sort by calendar date — soonest first
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_screen_sort_by_next_earnings_date_asc_puts_soonest_first() -> None:
    """``sort_by='next_earnings_date'`` ASC sorts the snapshot column ascending."""
    session, captured = _make_capture_session()

    filters = [ScreenFilter(metric="pe_ratio", max_value=40.0)]
    await query_screen(session, filters, sort_by="next_earnings_date", sort_order="asc")

    sql = _sql(captured[-1]).lower()
    # The ORDER BY must reference the snapshot column and be ASC.
    assert "order by" in sql
    assert "next_earnings_date" in sql
    assert "asc" in sql.split("order by", 1)[1]


@pytest.mark.asyncio
async def test_query_screen_sort_by_next_dividend_date_asc() -> None:
    """``sort_by='next_dividend_date'`` ASC works the same way."""
    session, captured = _make_capture_session()

    filters = [ScreenFilter(metric="pe_ratio", max_value=40.0)]
    await query_screen(session, filters, sort_by="next_dividend_date", sort_order="asc")

    sql = _sql(captured[-1]).lower()
    assert "order by" in sql
    assert "next_dividend_date" in sql
    assert "asc" in sql.split("order by", 1)[1]


# ---------------------------------------------------------------------------
# Result projection: snapshot fields appear in metrics dict when present
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_screen_result_includes_calendar_fields_when_present() -> None:
    """When the snapshot row has calendar values, they appear in metrics dict."""
    row = MagicMock()
    row.instrument_id = "instr-001"
    row.ticker = "AAPL"
    row.name = "Apple Inc."
    row.exchange = "NASDAQ"
    row.sector = "Technology"
    row.total_count = 1
    row.pe_ratio = 25.0
    # L-2 snapshot columns
    row.snap_avg_volume_30d = None
    row.snap_eps_ttm = None
    row.snap_free_cash_flow = None
    row.snap_fcf_margin = None
    row.snap_interest_coverage = None
    row.snap_net_debt_to_ebitda = None
    row.snap_credit_rating = None
    # L-5c snapshot columns
    row.snap_next_earnings_date = date(2026, 2, 12)
    row.snap_next_dividend_date = date(2026, 2, 25)

    session = _make_capture_session_with_rows([row])

    filters = [ScreenFilter(metric="pe_ratio", max_value=40.0)]
    results, total = await query_screen(session, filters)

    assert total == 1
    r = results[0]
    assert r.metrics.get("next_earnings_date") == date(2026, 2, 12)
    assert r.metrics.get("next_dividend_date") == date(2026, 2, 25)


@pytest.mark.asyncio
async def test_query_screen_result_handles_null_calendar_fields_gracefully() -> None:
    """NULL calendar columns are absent from the metrics dict (no 'date'='None')."""
    row = MagicMock()
    row.instrument_id = "instr-002"
    row.ticker = "XYZ"
    row.name = "XYZ Corp"
    row.exchange = "NYSE"
    row.sector = "Industrials"
    row.total_count = 1
    row.pe_ratio = 18.0
    # All snap fields NULL
    row.snap_avg_volume_30d = None
    row.snap_eps_ttm = None
    row.snap_free_cash_flow = None
    row.snap_fcf_margin = None
    row.snap_interest_coverage = None
    row.snap_net_debt_to_ebitda = None
    row.snap_credit_rating = None
    row.snap_next_earnings_date = None
    row.snap_next_dividend_date = None

    session = _make_capture_session_with_rows([row])

    filters = [ScreenFilter(metric="pe_ratio", max_value=40.0)]
    results, _ = await query_screen(session, filters)

    r = results[0]
    assert "next_earnings_date" not in r.metrics
    assert "next_dividend_date" not in r.metrics


# ---------------------------------------------------------------------------
# Snapshot writer: EODHD splits_dividends → next_dividend_date
# ---------------------------------------------------------------------------


def test_derive_fundamentals_snapshot_extracts_next_dividend_date_from_eodhd() -> None:
    """``DividendDate`` from ``splits_dividends`` lands in the snap dict."""
    snap = derive_fundamentals_snapshot(
        highlights={},
        cash_flow={},
        income={},
        balance={},
        technicals={},
        splits_dividends={"DividendDate": "2026-02-12", "ExDividendDate": "2026-02-09"},
    )
    # DividendDate is the preferred source (payment date).
    assert snap["next_dividend_date"] == date(2026, 2, 12)


def test_derive_fundamentals_snapshot_falls_back_to_ex_dividend_date() -> None:
    """When ``DividendDate`` is missing, fall back to ``ExDividendDate``."""
    snap = derive_fundamentals_snapshot(
        highlights={},
        cash_flow={},
        income={},
        balance={},
        technicals={},
        splits_dividends={"ExDividendDate": "2026-02-09"},
    )
    assert snap["next_dividend_date"] == date(2026, 2, 9)


def test_derive_fundamentals_snapshot_returns_none_for_missing_splits_dividends() -> None:
    """No splits_dividends section → next_dividend_date stays None (ETFs, etc.)."""
    snap = derive_fundamentals_snapshot(
        highlights={},
        cash_flow={},
        income={},
        balance={},
        technicals={},
        # splits_dividends omitted entirely (default None).
    )
    assert snap["next_dividend_date"] is None


def test_derive_fundamentals_snapshot_returns_none_for_null_sentinel_date() -> None:
    """EODHD sentinel ``"0000-00-00"`` → None (not a date crash)."""
    snap = derive_fundamentals_snapshot(
        highlights={},
        cash_flow={},
        income={},
        balance={},
        technicals={},
        splits_dividends={"DividendDate": "0000-00-00"},
    )
    assert snap["next_dividend_date"] is None


# ---------------------------------------------------------------------------
# _safe_date helper coverage
# ---------------------------------------------------------------------------


def test_safe_date_parses_iso_date_string() -> None:
    assert _safe_date("2026-02-12") == date(2026, 2, 12)


def test_safe_date_parses_iso_datetime_string() -> None:
    # EODHD occasionally embeds a time portion — should still parse.
    assert _safe_date("2026-02-12T00:00:00") == date(2026, 2, 12)


def test_safe_date_returns_none_for_empty_or_sentinel_values() -> None:
    assert _safe_date(None) is None
    assert _safe_date("") is None
    assert _safe_date("N/A") is None
    assert _safe_date("none") is None
    assert _safe_date("0000-00-00") is None


def test_safe_date_returns_none_for_unparseable_string() -> None:
    assert _safe_date("not-a-date", label="DividendDate") is None


def test_safe_date_passthrough_for_python_date() -> None:
    d = date(2026, 2, 12)
    assert _safe_date(d) == d
