"""Wave L-1 / L-2 unit tests for ``query_screen``.

L-1: instrument-attribute filters (country, exchange, has_fundamentals, has_ohlcv)
     applied via WHERE clauses against the ``instruments`` table.

L-2: LEFT JOIN on ``instrument_fundamentals_snapshot`` to expose avg_volume_30d,
     eps_ttm, free_cash_flow, fcf_margin, interest_coverage, net_debt_to_ebitda,
     credit_rating in the ``metrics`` dict of every ``ScreenResult``.

Test strategy: same capture-session pattern as ``test_screen_industry_filter.py``.
We stub ``AsyncSession.execute`` to record every SQLAlchemy statement and return an
empty result-set (which short-circuits the result-building loop).  We then compile
the captured statement to a SQL string and assert that the expected WHERE clauses
and JOIN targets appear (or don't appear) in the SQL text.

WHY compile with literal_binds: bind-parameter placeholders (:param_1) do not
include the actual value, so assertions like ``assert "USA" in sql`` would fail.
``literal_binds=True`` substitutes the Python value directly into the SQL string.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_data.application.ports.repositories import ScreenFilter
from market_data.infrastructure.db.repositories.fundamental_metrics_query import query_screen

pytestmark = pytest.mark.unit

# ---------------------------------------------------------------------------
# Shared helpers (mirrors test_screen_industry_filter.py)
# ---------------------------------------------------------------------------


def _make_capture_session() -> tuple[MagicMock, list[Any]]:
    """Return (session, captured_statements) — every ``execute`` call is recorded."""
    captured: list[Any] = []

    async def _capture(stmt: Any) -> MagicMock:
        captured.append(stmt)
        result = MagicMock()
        # WHY return []: empty result-set triggers early return so we never try to
        # read columns that don't exist on the MagicMock row objects.
        result.all = MagicMock(return_value=[])
        return result

    session = MagicMock()
    session.execute = AsyncMock(side_effect=_capture)
    return session, captured


def _sql(stmt: Any) -> str:
    """Compile an SQLAlchemy statement to a literal-bound SQL string."""
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


# ---------------------------------------------------------------------------
# L-1: country filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_screen_country_filter_adds_where_clause() -> None:
    """When a filter sets ``country``, the SQL contains ``instruments.country IN ('USA')``."""
    session, captured = _make_capture_session()

    filters = [
        ScreenFilter(metric="pe_ratio", max_value=30.0, country="USA"),
    ]
    results, total = await query_screen(session, filters, limit=50, offset=0)

    assert results == []
    assert total == 0
    assert len(captured) == 1

    sql = _sql(captured[0])
    # The country IN(...) predicate must reference the instruments table column.
    assert "country" in sql.lower(), f"country column missing from SQL:\n{sql}"
    assert "USA" in sql, f"country value 'USA' missing from SQL:\n{sql}"


@pytest.mark.asyncio
async def test_query_screen_no_country_filter_omits_clause() -> None:
    """Without ``country`` set, no country predicate is emitted."""
    session, captured = _make_capture_session()

    filters = [ScreenFilter(metric="pe_ratio", max_value=30.0)]
    await query_screen(session, filters)

    sql = _sql(captured[0])
    # Must not emit a WHERE instruments.country = ... or IN (...)
    # (the instruments table name appears in FROM/JOIN but not in a WHERE for country).
    assert "country" not in sql.lower() or "instruments.country" not in sql.lower()


# ---------------------------------------------------------------------------
# L-1: exchange filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_screen_exchange_filter_adds_where_clause() -> None:
    """When a filter sets ``exchange``, the SQL contains an exchange IN predicate."""
    session, captured = _make_capture_session()

    filters = [
        ScreenFilter(metric="market_capitalization", min_value=1e9, exchange="NASDAQ"),
    ]
    await query_screen(session, filters)

    sql = _sql(captured[0])
    assert "NASDAQ" in sql, f"exchange value 'NASDAQ' missing from SQL:\n{sql}"


# ---------------------------------------------------------------------------
# L-1: has_ohlcv filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_screen_has_ohlcv_true_filter_adds_where_clause() -> None:
    """When ``has_ohlcv=True``, the SQL contains a boolean equality predicate."""
    session, captured = _make_capture_session()

    filters = [
        ScreenFilter(metric="pe_ratio", min_value=5.0, has_ohlcv=True),
    ]
    await query_screen(session, filters)

    sql = _sql(captured[0])
    # SQLAlchemy renders ``has_ohlcv = true`` (PostgreSQL dialect) or ``= 1``.
    assert "has_ohlcv" in sql.lower(), f"has_ohlcv predicate missing from SQL:\n{sql}"


@pytest.mark.asyncio
async def test_query_screen_has_ohlcv_none_omits_clause() -> None:
    """Without ``has_ohlcv`` set, no has_ohlcv predicate is emitted."""
    session, captured = _make_capture_session()

    filters = [ScreenFilter(metric="pe_ratio", min_value=5.0)]
    await query_screen(session, filters)

    sql = _sql(captured[0])
    assert "has_ohlcv" not in sql.lower(), f"unexpected has_ohlcv predicate in SQL:\n{sql}"


# ---------------------------------------------------------------------------
# L-1: has_fundamentals filter
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_screen_has_fundamentals_true_filter_adds_where_clause() -> None:
    """When ``has_fundamentals=True``, the SQL contains a boolean equality predicate."""
    session, captured = _make_capture_session()

    filters = [
        ScreenFilter(metric="revenue_usd", min_value=100e6, has_fundamentals=True),
    ]
    await query_screen(session, filters)

    sql = _sql(captured[0])
    assert "has_fundamentals" in sql.lower(), f"has_fundamentals predicate missing from SQL:\n{sql}"


# ---------------------------------------------------------------------------
# L-1 + existing: combined filters (country + sector + industry)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_screen_combined_l1_and_existing_filters() -> None:
    """L-1 filters combine correctly with existing sector / industry filters."""
    session, captured = _make_capture_session()

    filters = [
        ScreenFilter(
            metric="pe_ratio",
            max_value=30.0,
            sector="Technology",
            industry="Semiconductors",
            country="USA",
            exchange="NASDAQ",
        ),
    ]
    await query_screen(session, filters)

    sql = _sql(captured[0])
    assert "Technology" in sql
    assert "Semiconductors" in sql
    assert "USA" in sql
    assert "NASDAQ" in sql


# ---------------------------------------------------------------------------
# L-2: snapshot LEFT JOIN present in filter branch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_screen_filter_branch_includes_snapshot_join() -> None:
    """The filter branch LEFT JOINs ``instrument_fundamentals_snapshot``."""
    session, captured = _make_capture_session()

    filters = [ScreenFilter(metric="pe_ratio", max_value=40.0)]
    await query_screen(session, filters)

    sql = _sql(captured[0])
    assert "instrument_fundamentals_snapshot" in sql.lower(), f"snapshot table missing from filter-branch SQL:\n{sql}"


@pytest.mark.asyncio
async def test_query_screen_no_filter_branch_includes_snapshot_join() -> None:
    """The no-filter branch also LEFT JOINs ``instrument_fundamentals_snapshot``."""
    session, captured = _make_capture_session()

    # Empty filters → no-filter branch
    await query_screen(session, [], limit=10)

    sql = _sql(captured[0])
    assert (
        "instrument_fundamentals_snapshot" in sql.lower()
    ), f"snapshot table missing from no-filter-branch SQL:\n{sql}"


@pytest.mark.asyncio
async def test_query_screen_filter_branch_selects_snapshot_columns() -> None:
    """The filter branch selects snapshot metric columns (avg_volume_30d, eps_ttm, etc.)."""
    session, captured = _make_capture_session()

    filters = [ScreenFilter(metric="pe_ratio", max_value=40.0)]
    await query_screen(session, filters)

    sql = _sql(captured[0]).lower()
    # All seven snapshot fields must appear as selected columns.
    for field in (
        "avg_volume_30d",
        "eps_ttm",
        "free_cash_flow",
        "fcf_margin",
        "interest_coverage",
        "net_debt_to_ebitda",
        "credit_rating",
    ):
        assert field in sql, f"snapshot field '{field}' missing from SQL:\n{sql}"


# ---------------------------------------------------------------------------
# L-2: result construction — snapshot fields in metrics dict
# ---------------------------------------------------------------------------


def _make_capture_session_with_rows(rows: list[Any]) -> MagicMock:
    """Return a session whose execute() returns the supplied rows."""

    async def _execute(stmt: Any) -> MagicMock:
        result = MagicMock()
        result.all = MagicMock(return_value=rows)
        return result

    session = MagicMock()
    session.execute = AsyncMock(side_effect=_execute)
    return session


@pytest.mark.asyncio
async def test_query_screen_result_includes_snapshot_fields_when_present() -> None:
    """When the snapshot row exists, snapshot fields are included in metrics."""
    # Build a mock row with all expected columns set.
    row = MagicMock()
    row.instrument_id = "instr-001"
    row.ticker = "AAPL"
    row.name = "Apple Inc."
    row.exchange = "NASDAQ"
    row.sector = "Technology"
    row.total_count = 1
    # Metric columns (from filter subquery)
    row.pe_ratio = Decimal("25.0")
    # Snapshot columns (prefixed "snap_" in the SELECT alias)
    row.snap_avg_volume_30d = 75_000_000
    row.snap_eps_ttm = Decimal("6.43")
    row.snap_free_cash_flow = Decimal("90000000000.00")
    row.snap_fcf_margin = Decimal("0.245")
    row.snap_interest_coverage = Decimal("22.5")
    row.snap_net_debt_to_ebitda = Decimal("-0.3")
    row.snap_credit_rating = "AA+"

    session = _make_capture_session_with_rows([row])

    filters = [ScreenFilter(metric="pe_ratio", max_value=40.0)]
    results, total = await query_screen(session, filters, limit=50, offset=0)

    assert total == 1
    assert len(results) == 1
    r = results[0]

    # Core metric must be present
    assert "pe_ratio" in r.metrics

    # Snapshot fields must be present (L-2)
    assert r.metrics.get("avg_volume_30d") == 75_000_000
    assert r.metrics.get("eps_ttm") == Decimal("6.43")
    assert r.metrics.get("free_cash_flow") == Decimal("90000000000.00")
    assert r.metrics.get("fcf_margin") == Decimal("0.245")
    assert r.metrics.get("interest_coverage") == Decimal("22.5")
    assert r.metrics.get("net_debt_to_ebitda") == Decimal("-0.3")
    assert r.metrics.get("credit_rating") == "AA+"


@pytest.mark.asyncio
async def test_query_screen_result_handles_null_snapshot_gracefully() -> None:
    """When snapshot columns are NULL, they are absent from the metrics dict."""
    row = MagicMock()
    row.instrument_id = "instr-002"
    row.ticker = "XYZ"
    row.name = "XYZ Corp"
    row.exchange = "NYSE"
    row.sector = "Industrials"
    row.total_count = 1
    row.pe_ratio = Decimal("18.0")
    # All snapshot columns NULL (LEFT JOIN returned no matching row)
    row.snap_avg_volume_30d = None
    row.snap_eps_ttm = None
    row.snap_free_cash_flow = None
    row.snap_fcf_margin = None
    row.snap_interest_coverage = None
    row.snap_net_debt_to_ebitda = None
    row.snap_credit_rating = None

    session = _make_capture_session_with_rows([row])

    filters = [ScreenFilter(metric="pe_ratio", max_value=40.0)]
    results, total = await query_screen(session, filters)

    assert total == 1
    r = results[0]

    # Core metric present
    assert "pe_ratio" in r.metrics

    # Snapshot fields must NOT appear when NULL (front-end renders "—" for absent keys)
    for snap_field in (
        "avg_volume_30d",
        "eps_ttm",
        "free_cash_flow",
        "fcf_margin",
        "interest_coverage",
        "net_debt_to_ebitda",
        "credit_rating",
    ):
        assert snap_field not in r.metrics, f"NULL snapshot field '{snap_field}' should not appear in metrics dict"


@pytest.mark.asyncio
async def test_query_screen_no_filter_result_includes_snapshot_fields() -> None:
    """No-filter branch also includes snapshot fields in the metrics dict."""
    row = MagicMock()
    row.instrument_id = "instr-003"
    row.ticker = "MSFT"
    row.name = "Microsoft Corp"
    row.exchange = "NASDAQ"
    row.sector = "Technology"
    row.total_count = 1
    # Key metrics from no-filter subqueries
    row.market_capitalization = Decimal("3000000000000.00")
    row.pe_ratio = None
    row.daily_return = None
    row.beta = None
    row.revenue_usd = None
    # Snapshot columns
    row.snap_avg_volume_30d = None
    row.snap_eps_ttm = Decimal("12.50")
    row.snap_free_cash_flow = None
    row.snap_fcf_margin = None
    row.snap_interest_coverage = None
    row.snap_net_debt_to_ebitda = None
    row.snap_credit_rating = None

    session = _make_capture_session_with_rows([row])

    # Empty filters → no-filter branch
    results, total = await query_screen(session, [], limit=50, offset=0)

    assert total == 1
    r = results[0]

    # Snapshot field with a value must appear
    assert r.metrics.get("eps_ttm") == Decimal("12.50")
    # Snapshot fields that are NULL must be absent
    assert "avg_volume_30d" not in r.metrics
