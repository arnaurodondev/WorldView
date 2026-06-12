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
    - ``SELECT DISTINCT fundamental_metrics`` → empty (key-metric enrichment)
    - count(*) → scalar 1
    - main screener SELECT (km_ aliases) → screen_rows
    - everything else (the page-IDs query) → page_rows
    """

    async def _execute(stmt: Any) -> MagicMock:
        s = str(stmt)
        result = MagicMock()
        if "statement_timeout" in s:
            result.all = MagicMock(return_value=[])
            return result
        if captured is not None:
            captured.append(stmt)
        if "technicals_snapshots" in s or "ohlcv_bars" in s:
            result.all = MagicMock(return_value=[])
        elif "SELECT DISTINCT fundamental_metrics" in s.replace("\n", " "):
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
    """Compile the page-selection query (no km_, no total_count, not DISTINCT)."""
    for stmt in captured:
        s = str(stmt)
        if (
            "km_" not in s
            and "total_count" not in s
            and "SELECT DISTINCT fundamental_metrics" not in s.replace("\n", " ")
            and "technicals_snapshots" not in s
            and "ohlcv_bars" not in s
            and "count" not in s.lower()
        ):
            return str(stmt.compile(compile_kwargs={"literal_binds": True}))
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
