"""Screener default ORDER BY + no-filter metric-sort (2026-06-12, chat-eval root cause #5).

Before this fix the screener had NO default ordering:

* The no-filter (GET) branch ALWAYS paged by ``symbol`` ASC and applied
  LIMIT/OFFSET before any metric sort, so "top 5 by market cap" (no explicit
  ``sort_by``) returned the first 5 tickers alphabetically (CRM, IBM, …)
  rather than the genuine top-5 by market cap (``iter3_top5_tech_marketcap``).
* An absent ``sort_by`` was forwarded as ``None`` and never resolved to a
  default, so ``total`` was truncated at ``limit`` BEFORE sorting.

These tests pin:
1. ``sort_by=None`` defaults to ``market_capitalization`` DESC when there is
   no metric filter.
2. ``sort_by=None`` defaults to the PRIMARY FILTER METRIC DESC when one is
   supplied.
3. The no-filter page-selection query orders by the (latest) metric value, so
   the LIMIT picks the true top-N (verified via compiled SQL containing a
   metric-sort subquery joined to the page query).

Test strategy mirrors ``test_screener_page_extras.py``: a mocked AsyncSession
that routes statements by compiled-SQL substring.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_data.application.ports.repositories import ScreenFilter
from market_data.infrastructure.db.repositories import fundamental_metrics_query as fmq
from market_data.infrastructure.db.repositories.fundamental_metrics_query import query_screen

pytestmark = pytest.mark.unit


def _capturing_session(
    *,
    page_rows: list[Any] | None = None,
    screen_rows: list[Any] | None = None,
    captured: list[Any] | None = None,
) -> MagicMock:
    """Mocked session that records every statement and returns canned rows.

    Routing (same convention as test_screener_page_extras._route_session):
    - ``statement_timeout`` → no-op
    - ``technicals_snapshots`` / ``ohlcv_bars`` → empty (page-extras)
    - key-metric enrichment DISTINCT (projects ``metric``) → empty
    - count(*) → scalar 1
    - main screener SELECT (km_ aliases) → screen_rows
    - everything else (the page-IDs query, incl. the DISTINCT-ON page-sort) → page_rows

    NOTE on the page-sort DISTINCT: the rewritten page-sort subquery (Theme B fix,
    2026-06-12) uses ``DISTINCT ON (instrument_id)``. Under the non-PostgreSQL
    default dialect SQLAlchemy renders that as a plain ``SELECT DISTINCT
    fundamental_metrics.instrument_id ...`` (DISTINCT ON is PG-only), which would
    otherwise collide with the key-metric enrichment routing. We disambiguate by
    the metric predicate form: the ENRICHMENT query filters ``metric IN (...)``
    (it fans out several display metrics), whereas the PAGE-SORT query filters
    ``metric = :p`` (a single sort metric). Matching the ``metric IN`` form keeps
    the page-sort query flowing to the ``page_rows`` branch.
    """

    async def _execute(stmt: Any) -> MagicMock:
        s = str(stmt)
        result = MagicMock()
        if "statement_timeout" in s:
            result.all = MagicMock(return_value=[])
            return result
        if captured is not None:
            captured.append(stmt)
        flat = s.replace("\n", " ")
        if "technicals_snapshots" in s or "ohlcv_bars" in s:
            result.all = MagicMock(return_value=[])
        elif "DISTINCT fundamental_metrics" in flat and "fundamental_metrics.metric IN" in flat:
            # key-metric enrichment (_fetch_page_extras block 1): filters
            # ``metric IN (...)``. The page-sort DISTINCT filters ``metric = :p``,
            # so this match excludes it (it flows to the page_rows branch).
            result.all = MagicMock(return_value=[])
        elif "count" in s.lower() and "km_" not in s and "total_count" not in s:
            result.scalar_one = MagicMock(return_value=1)
        elif "km_" in s or "total_count" in s:
            result.all = MagicMock(return_value=screen_rows or [])
        else:
            result.all = MagicMock(return_value=page_rows or [])
        return result

    session = MagicMock()
    session.execute = AsyncMock(side_effect=_execute)
    return session


def _get_screen_row(instrument_id: str = "instr-001", **metric_values: Any) -> MagicMock:
    """A no-filter (GET) branch result row with all key-metric/snap cols NULL."""
    row = MagicMock()
    row.instrument_id = instrument_id
    row.ticker = "AAPL"
    row.name = "Apple Inc."
    row.exchange = "NASDAQ"
    row.sector = "Technology"
    row.current_price = None
    for sf in fmq._SNAP_FIELDS:
        setattr(row, f"snap_{sf}", None)
    for km in fmq._KEY_METRICS:
        setattr(row, km, None)
    for k, v in metric_values.items():
        setattr(row, k, v)
    return row


def _page_row(instrument_id: str = "instr-001") -> MagicMock:
    pr = MagicMock()
    pr.id = instrument_id
    return pr


def _main_sql(captured: list[Any]) -> str:
    """Compile the page-selection query (no km_, no total_count, not enrichment).

    Compiles against the **PostgreSQL dialect** (the production driver is
    asyncpg) so the ``DISTINCT ON`` page-sort rewrite renders as real
    ``DISTINCT ON (...)`` rather than the default-dialect ``DISTINCT`` fallback.
    The page-sort subquery (Theme B fix) filters ``metric = :p``, whereas the
    key-metric enrichment DISTINCT filters ``metric IN (...)`` — so we exclude
    the latter by its ``metric IN`` predicate.
    """
    from sqlalchemy.dialects import postgresql

    for stmt in captured:
        flat = str(stmt).replace("\n", " ")
        is_enrichment = "DISTINCT fundamental_metrics" in flat and "fundamental_metrics.metric IN" in flat
        if (
            "km_" not in flat
            and "total_count" not in flat
            and not is_enrichment
            and "technicals_snapshots" not in flat
            and "ohlcv_bars" not in flat
            and "count" not in flat.lower()
        ):
            return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    raise AssertionError("page-selection query not captured")


# ---------------------------------------------------------------------------
# Default ORDER BY resolution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_filter_defaults_to_market_cap_page_sort() -> None:
    """No filters + no sort_by → page query orders by latest market_capitalization.

    This is the core of the "top 5 by market cap" fix: the LIMIT that defines
    the page must be applied AFTER ordering by the market-cap metric, so the
    page-selection SQL must JOIN and ORDER BY a market_capitalization subquery.
    """
    captured: list[Any] = []
    session = _capturing_session(
        page_rows=[_page_row()],
        screen_rows=[_get_screen_row(market_capitalization=Decimal("3e12"))],
        captured=captured,
    )

    results, total = await query_screen(session, [], limit=5)

    assert total == 1
    page_sql = _main_sql(captured)
    # The page query must JOIN the market-cap latest-value subquery and ORDER BY it.
    assert "page_sort_val" in page_sql
    assert "'market_capitalization'" in page_sql
    assert "ORDER BY" in page_sql.upper()
    assert "DESC" in page_sql.upper()


@pytest.mark.asyncio
async def test_no_filter_page_sort_is_distinct_on_not_unscoped_group_by() -> None:
    """The page-sort subquery must use DISTINCT ON, NOT an un-scoped GROUP BY.

    REGRESSION GUARD (Theme B, 2026-06-12 — post-2d71ba1ae): the default-sort
    page selection originally resolved "latest market_capitalization per
    instrument" via

        SELECT instrument_id, MAX(as_of_date) FROM fundamental_metrics
        WHERE metric = 'market_capitalization'
        GROUP BY instrument_id        -- whole-partition aggregate BEFORE LIMIT
        ... self-JOIN back for value ...

    Because the page IDs are not yet known, that aggregate scanned the ENTIRE
    metric partition before the LIMIT — the full-scan-before-LIMIT that blew the
    8 s statement_timeout (504 → screen_universe transport_error).

    The performant rewrite is a single ``DISTINCT ON (instrument_id) ... ORDER
    BY instrument_id, as_of_date DESC`` scan (backed by the covering index
    ``ix_fundamental_metrics_metric_instr_date_val``, migration 038). This test
    pins that SQL SHAPE so the regression cannot silently return:

      * the page-sort subquery MUST contain ``DISTINCT ON``;
      * it MUST NOT contain ``GROUP BY`` (the un-scoped aggregate);
      * it MUST NOT carry a ``MAX(as_of_date)`` aggregate;
      * it MUST still filter ``metric = 'market_capitalization'`` (correctness:
        ranks each instrument's latest market cap, so top-5 stays GOOGL/AVGO/
        META-class, never the alphabetical CRM/IBM).
    """
    captured: list[Any] = []
    session = _capturing_session(
        page_rows=[_page_row()],
        screen_rows=[_get_screen_row(market_capitalization=Decimal("3e12"))],
        captured=captured,
    )

    await query_screen(session, [], limit=5)

    page_sql = _main_sql(captured)
    upper = page_sql.upper()
    # Performant shape present.
    assert "DISTINCT ON" in upper, page_sql
    # Un-scoped full-table aggregate-before-LIMIT shape absent.
    assert "GROUP BY" not in upper, f"un-scoped GROUP-BY-before-LIMIT regressed:\n{page_sql}"
    assert "MAX(" not in upper, f"MAX(as_of_date) aggregate regressed:\n{page_sql}"
    # Correctness: still scoped to the market-cap metric and the latest snapshot.
    assert "'market_capitalization'" in page_sql, page_sql
    assert "AS_OF_DATE DESC" in upper, page_sql


@pytest.mark.asyncio
async def test_no_filter_explicit_sort_by_ticker_uses_symbol() -> None:
    """sort_by='ticker' must NOT inject a metric subquery — order by symbol."""
    captured: list[Any] = []
    session = _capturing_session(
        page_rows=[_page_row()],
        screen_rows=[_get_screen_row()],
        captured=captured,
    )

    await query_screen(session, [], limit=5, sort_by="ticker", sort_order="asc")

    page_sql = _main_sql(captured)
    assert "page_sort_val" not in page_sql
    assert "symbol" in page_sql.lower()


@pytest.mark.asyncio
async def test_no_filter_page_order_preserved_in_results() -> None:
    """Result rows are returned in the page-selection order, not alphabetical.

    Page query returns [B, A]; the enrichment SELECT (IN-list) returns them in
    arbitrary order [A, B]; the function must re-sort back to [B, A].
    """
    row_a = _get_screen_row(instrument_id="A")
    row_a.ticker = "AAA"
    row_b = _get_screen_row(instrument_id="B")
    row_b.ticker = "BBB"

    session = _capturing_session(
        page_rows=[_page_row("B"), _page_row("A")],  # page order: B then A
        screen_rows=[row_a, row_b],  # enrichment returns A then B
    )

    results, _ = await query_screen(session, [], limit=5)

    # Must follow the page order (B, A), NOT the enrichment order (A, B).
    assert [r.instrument_id for r in results] == ["B", "A"]


@pytest.mark.asyncio
async def test_filtered_no_sort_defaults_to_primary_filter_metric_desc() -> None:
    """A metric filter without sort_by sorts by that metric DESC.

    Filtered (POST) branch: the per-filter subquery already projects the metric,
    so ORDER BY resolves to that column. Verified via the compiled main query
    carrying ``ORDER BY`` + ``DESC`` on the filter metric.
    """
    captured: list[Any] = []
    row = MagicMock()
    row.instrument_id = "instr-001"
    row.ticker = "NVDA"
    row.name = "NVIDIA"
    row.exchange = "NASDAQ"
    row.sector = "Technology"
    row.total_count = 1
    row.current_price = None
    row.revenue_growth_yoy = Decimal("0.85")
    for sf in fmq._SNAP_FIELDS:
        setattr(row, f"snap_{sf}", None)

    session = _capturing_session(screen_rows=[row], captured=captured)

    results, total = await query_screen(
        session,
        [ScreenFilter(metric="revenue_growth_yoy", min_value=0.2)],
        limit=10,
    )

    assert total == 1
    main_stmts = [s for s in captured if "total_count" in str(s)]
    assert main_stmts, "filtered main query must be captured"
    compiled = str(main_stmts[0].compile(compile_kwargs={"literal_binds": True})).upper()
    assert "ORDER BY" in compiled
    assert "DESC" in compiled
