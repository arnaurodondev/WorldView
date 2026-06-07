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
    """Return (session, captured_statements) — every ``execute`` call is recorded.

    WHY filter out SET LOCAL: query_screen now issues ``SET LOCAL
    statement_timeout = '8000'`` before the real query as a safety guard
    (PLAN-0099). We skip it here so ``captured`` only contains substantive
    queries (introspection + screener SELECT). Tests use ``captured[-1]``
    to reach the screener SELECT regardless of introspection cache state.
    """
    captured: list[Any] = []

    async def _capture(stmt: Any) -> MagicMock:
        # Skip the statement_timeout SET LOCAL — it is a side-effect, not the
        # query under test. str(text(...)) includes the raw SQL fragment.
        if "statement_timeout" in str(stmt):
            result = MagicMock()
            result.all = MagicMock(return_value=[])
            return result
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
    # WHY >= 1 (not == 1): if _AVAILABLE_SNAP_FIELDS is uncached when this test
    # runs (e.g. after the introspection test suite resets it), query_screen
    # fires an additional information_schema introspection call. The screen
    # SELECT is always the LAST captured statement regardless of cache state.
    assert len(captured) >= 1

    sql = _sql(captured[-1])
    # The country IN(...) predicate must reference the instruments table column.
    assert "country" in sql.lower(), f"country column missing from SQL:\n{sql}"
    assert "USA" in sql, f"country value 'USA' missing from SQL:\n{sql}"


@pytest.mark.asyncio
async def test_query_screen_no_country_filter_omits_clause() -> None:
    """Without ``country`` set, no country predicate is emitted."""
    session, captured = _make_capture_session()

    filters = [ScreenFilter(metric="pe_ratio", max_value=30.0)]
    await query_screen(session, filters)

    sql = _sql(captured[-1])
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

    sql = _sql(captured[-1])
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

    sql = _sql(captured[-1])
    # SQLAlchemy renders ``has_ohlcv = true`` (PostgreSQL dialect) or ``= 1``.
    assert "has_ohlcv" in sql.lower(), f"has_ohlcv predicate missing from SQL:\n{sql}"


@pytest.mark.asyncio
async def test_query_screen_has_ohlcv_none_omits_clause() -> None:
    """Without ``has_ohlcv`` set, no has_ohlcv predicate is emitted."""
    session, captured = _make_capture_session()

    filters = [ScreenFilter(metric="pe_ratio", min_value=5.0)]
    await query_screen(session, filters)

    sql = _sql(captured[-1])
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

    sql = _sql(captured[-1])
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

    sql = _sql(captured[-1])
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

    sql = _sql(captured[-1])
    assert "instrument_fundamentals_snapshot" in sql.lower(), f"snapshot table missing from filter-branch SQL:\n{sql}"


@pytest.mark.asyncio
async def test_query_screen_no_filter_branch_includes_snapshot_join() -> None:
    """The no-filter branch also LEFT JOINs ``instrument_fundamentals_snapshot``."""
    session, captured = _make_capture_session()

    # Empty filters → no-filter branch
    await query_screen(session, [], limit=10)

    sql = _sql(captured[-1])
    assert (
        "instrument_fundamentals_snapshot" in sql.lower()
    ), f"snapshot table missing from no-filter-branch SQL:\n{sql}"


@pytest.mark.asyncio
async def test_query_screen_filter_branch_selects_snapshot_columns() -> None:
    """The filter branch selects snapshot metric columns (avg_volume_30d, eps_ttm, etc.)."""
    session, captured = _make_capture_session()

    filters = [ScreenFilter(metric="pe_ratio", max_value=40.0)]
    await query_screen(session, filters)

    sql = _sql(captured[-1]).lower()
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


# ---------------------------------------------------------------------------
# L-2: WHERE-clause filters on snapshot columns
# ---------------------------------------------------------------------------
#
# These tests assert that supplying ``<field>_min`` / ``<field>_max`` /
# ``credit_ratings`` on a ``ScreenFilter`` produces the corresponding
# WHERE predicate against the LEFT-JOINed ``instrument_fundamentals_snapshot``
# table. They use the same capture-session pattern as the L-1 tests above.


@pytest.mark.asyncio
async def test_query_screen_eps_ttm_min_filter_adds_predicate() -> None:
    """``eps_ttm_min`` emits ``snap.eps_ttm >= <value>`` predicate."""
    session, captured = _make_capture_session()

    filters = [ScreenFilter(metric="pe_ratio", max_value=40.0, eps_ttm_min=2.5)]
    await query_screen(session, filters)

    sql = _sql(captured[-1]).lower()
    assert "eps_ttm" in sql
    # Numeric value 2.5 must be present after literal_binds substitution.
    assert "2.5" in sql, f"eps_ttm_min value missing from SQL:\n{sql}"


@pytest.mark.asyncio
async def test_query_screen_eps_ttm_max_filter_adds_predicate() -> None:
    """``eps_ttm_max`` emits ``snap.eps_ttm <= <value>`` predicate."""
    session, captured = _make_capture_session()

    filters = [ScreenFilter(metric="pe_ratio", max_value=40.0, eps_ttm_max=15.0)]
    await query_screen(session, filters)

    sql = _sql(captured[-1]).lower()
    assert "eps_ttm" in sql
    assert "15.0" in sql


@pytest.mark.asyncio
async def test_query_screen_avg_volume_30d_range_filter_adds_predicates() -> None:
    """Both min and max bounds emit predicates on avg_volume_30d."""
    session, captured = _make_capture_session()

    filters = [
        ScreenFilter(
            metric="pe_ratio",
            max_value=40.0,
            avg_volume_30d_min=1_000_000,
            avg_volume_30d_max=500_000_000,
        )
    ]
    await query_screen(session, filters)

    sql = _sql(captured[-1]).lower()
    assert "avg_volume_30d" in sql
    assert "1000000" in sql
    assert "500000000" in sql


@pytest.mark.asyncio
async def test_query_screen_free_cash_flow_min_filter_adds_predicate() -> None:
    """``free_cash_flow_min`` emits the expected predicate."""
    session, captured = _make_capture_session()

    filters = [ScreenFilter(metric="pe_ratio", max_value=40.0, free_cash_flow_min=1_000_000_000)]
    await query_screen(session, filters)

    sql = _sql(captured[-1]).lower()
    assert "free_cash_flow" in sql
    assert "1000000000" in sql


@pytest.mark.asyncio
async def test_query_screen_fcf_margin_max_filter_adds_predicate() -> None:
    """``fcf_margin_max`` emits the expected predicate."""
    session, captured = _make_capture_session()

    filters = [ScreenFilter(metric="pe_ratio", max_value=40.0, fcf_margin_max=0.5)]
    await query_screen(session, filters)

    sql = _sql(captured[-1]).lower()
    assert "fcf_margin" in sql
    assert "0.5" in sql


@pytest.mark.asyncio
async def test_query_screen_interest_coverage_min_filter_adds_predicate() -> None:
    """``interest_coverage_min`` emits the expected predicate."""
    session, captured = _make_capture_session()

    filters = [ScreenFilter(metric="pe_ratio", max_value=40.0, interest_coverage_min=3.0)]
    await query_screen(session, filters)

    sql = _sql(captured[-1]).lower()
    assert "interest_coverage" in sql
    assert "3.0" in sql


@pytest.mark.asyncio
async def test_query_screen_net_debt_to_ebitda_max_filter_adds_predicate() -> None:
    """``net_debt_to_ebitda_max`` emits the expected predicate."""
    session, captured = _make_capture_session()

    filters = [ScreenFilter(metric="pe_ratio", max_value=40.0, net_debt_to_ebitda_max=2.0)]
    await query_screen(session, filters)

    sql = _sql(captured[-1]).lower()
    assert "net_debt_to_ebitda" in sql
    assert "2.0" in sql


@pytest.mark.asyncio
async def test_query_screen_credit_ratings_in_filter_adds_predicate() -> None:
    """``credit_ratings`` non-empty tuple emits an IN(...) predicate."""
    session, captured = _make_capture_session()

    filters = [
        ScreenFilter(
            metric="pe_ratio",
            max_value=40.0,
            credit_ratings=("AAA", "AA+", "AA"),
        )
    ]
    await query_screen(session, filters)

    sql = _sql(captured[-1])
    # Either an IN ('AAA', 'AA+', 'AA') or = ANY(ARRAY[...]) form — both
    # include the literal rating strings.
    assert "credit_rating" in sql.lower()
    assert "AAA" in sql
    assert "AA+" in sql


@pytest.mark.asyncio
async def test_query_screen_no_l2_filters_emits_no_l2_predicates() -> None:
    """No L-2 filter set → no snapshot WHERE predicates emitted.

    The snapshot columns are still SELECTed (L-2 projection) and LEFT-JOINed,
    but no WHERE clause should reference them.
    """
    session, captured = _make_capture_session()

    filters = [ScreenFilter(metric="pe_ratio", max_value=40.0)]
    await query_screen(session, filters)

    sql = _sql(captured[-1]).lower()
    # SELECT and JOIN reference snapshot table; WHERE clause should not
    # carry a comparison predicate. We assert by checking that the literal
    # operator-value combinations we'd emit for an L-2 filter are absent.
    # (Sentinel: '>= 2.5' style fragments that only arise from L-2 filters.)
    assert "eps_ttm >= " not in sql
    assert "eps_ttm <= " not in sql
    assert "credit_rating in (" not in sql


# ---------------------------------------------------------------------------
# L-2: sort_by on snapshot columns
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_query_screen_sort_by_eps_ttm_orders_by_snapshot_column() -> None:
    """``sort_by='eps_ttm'`` produces an ORDER BY against the snapshot column."""
    session, captured = _make_capture_session()

    filters = [ScreenFilter(metric="pe_ratio", max_value=40.0)]
    await query_screen(session, filters, sort_by="eps_ttm", sort_order="desc")

    sql = _sql(captured[-1]).lower()
    assert "order by" in sql
    # The snapshot column reference appears in the ORDER BY clause
    assert "eps_ttm desc" in sql or "snap_eps_ttm desc" in sql or "eps_ttm" in sql.split("order by", 1)[1]


@pytest.mark.asyncio
async def test_query_screen_sort_by_avg_volume_30d_orders_by_snapshot_column() -> None:
    """``sort_by='avg_volume_30d'`` produces an ORDER BY against the snapshot column."""
    session, captured = _make_capture_session()

    filters = [ScreenFilter(metric="pe_ratio", max_value=40.0)]
    await query_screen(session, filters, sort_by="avg_volume_30d", sort_order="asc")

    sql = _sql(captured[-1]).lower()
    assert "order by" in sql
    assert "avg_volume_30d" in sql.split("order by", 1)[1]


@pytest.mark.asyncio
async def test_query_screen_combined_l2_filters_with_l1_and_sort() -> None:
    """Combined L-2 + L-1 + sort produces all predicates simultaneously."""
    session, captured = _make_capture_session()

    filters = [
        ScreenFilter(
            metric="pe_ratio",
            max_value=40.0,
            country="USA",
            exchange="NASDAQ",
            eps_ttm_min=1.0,
            free_cash_flow_min=500_000_000,
            credit_ratings=("AA", "AA+", "AAA"),
        )
    ]
    await query_screen(session, filters, sort_by="free_cash_flow", sort_order="desc")

    sql = _sql(captured[-1])
    sql_l = sql.lower()
    assert "USA" in sql
    assert "NASDAQ" in sql
    assert "eps_ttm" in sql_l
    assert "free_cash_flow" in sql_l
    assert "credit_rating" in sql_l
    assert "AA" in sql
    assert "order by" in sql_l


# ---------------------------------------------------------------------------
# Wave L-4a: analyst / ownership / short snapshot column filters + sorts
# ---------------------------------------------------------------------------
#
# Mirror of the L-2 filter/sort tests above for the four new L-4a fields
# (PLAN-0089). The four fields share the L-2 ``numeric_snap_filters`` code
# path so the assertions follow the same pattern: confirm the filter value
# is literal-bound into the WHERE clause and the column name appears in
# the ORDER BY clause when sorted.


@pytest.mark.asyncio
async def test_query_screen_analyst_target_price_range_filter_adds_predicates() -> None:
    """``analyst_target_price_{min,max}`` emit predicates on the snapshot column."""
    session, captured = _make_capture_session()

    filters = [
        ScreenFilter(
            metric="pe_ratio",
            max_value=40.0,
            analyst_target_price_min=100.0,
            analyst_target_price_max=500.0,
        )
    ]
    await query_screen(session, filters)

    sql = _sql(captured[-1]).lower()
    assert "analyst_target_price" in sql
    # Literal-bound values appear in the SQL string.
    assert "100.0" in sql
    assert "500.0" in sql


@pytest.mark.asyncio
async def test_query_screen_analyst_consensus_rating_min_filter_adds_predicate() -> None:
    """``analyst_consensus_rating_min`` emits the expected predicate."""
    session, captured = _make_capture_session()

    filters = [ScreenFilter(metric="pe_ratio", max_value=40.0, analyst_consensus_rating_min=4.0)]
    await query_screen(session, filters)

    sql = _sql(captured[-1]).lower()
    assert "analyst_consensus_rating" in sql
    assert "4.0" in sql


@pytest.mark.asyncio
async def test_query_screen_institutional_ownership_pct_range_filter_adds_predicates() -> None:
    """``institutional_ownership_pct_{min,max}`` use the decimal-fraction convention."""
    session, captured = _make_capture_session()

    # 0.5 / 0.9 = 50% / 90% — consistent with the fraction unit convention.
    filters = [
        ScreenFilter(
            metric="pe_ratio",
            max_value=40.0,
            institutional_ownership_pct_min=0.5,
            institutional_ownership_pct_max=0.9,
        )
    ]
    await query_screen(session, filters)

    sql = _sql(captured[-1]).lower()
    assert "institutional_ownership_pct" in sql
    assert "0.5" in sql
    assert "0.9" in sql


@pytest.mark.asyncio
async def test_query_screen_short_percent_max_filter_adds_predicate() -> None:
    """``short_percent_max`` emits the expected predicate (decimal-fraction)."""
    session, captured = _make_capture_session()

    # 0.05 = 5% — fraction convention.
    filters = [ScreenFilter(metric="pe_ratio", max_value=40.0, short_percent_max=0.05)]
    await query_screen(session, filters)

    sql = _sql(captured[-1]).lower()
    assert "short_percent" in sql
    assert "0.05" in sql


@pytest.mark.asyncio
async def test_query_screen_sort_by_analyst_target_price_orders_by_snapshot_column() -> None:
    """``sort_by='analyst_target_price'`` produces an ORDER BY against the snapshot column."""
    session, captured = _make_capture_session()

    filters = [ScreenFilter(metric="pe_ratio", max_value=40.0)]
    await query_screen(session, filters, sort_by="analyst_target_price", sort_order="desc")

    sql = _sql(captured[-1]).lower()
    assert "order by" in sql
    assert "analyst_target_price" in sql.split("order by", 1)[1]


@pytest.mark.asyncio
async def test_query_screen_sort_by_short_percent_orders_by_snapshot_column() -> None:
    """``sort_by='short_percent'`` produces an ORDER BY against the snapshot column."""
    session, captured = _make_capture_session()

    filters = [ScreenFilter(metric="pe_ratio", max_value=40.0)]
    await query_screen(session, filters, sort_by="short_percent", sort_order="asc")

    sql = _sql(captured[-1]).lower()
    assert "order by" in sql
    assert "short_percent" in sql.split("order by", 1)[1]


@pytest.mark.asyncio
async def test_query_screen_filter_branch_selects_l4a_snapshot_columns() -> None:
    """The filter branch SELECTs the four L-4a snapshot columns alongside L-2."""
    session, captured = _make_capture_session()

    filters = [ScreenFilter(metric="pe_ratio", max_value=40.0)]
    await query_screen(session, filters)

    sql = _sql(captured[-1]).lower()
    for field in (
        "analyst_target_price",
        "analyst_consensus_rating",
        "institutional_ownership_pct",
        "short_percent",
    ):
        assert field in sql, f"L-4a snapshot field '{field}' missing from SQL:\n{sql}"
