"""2026-06-10 frontend-audit data-gap fixes — screener page-extras enrichment.

Covers ``_fetch_page_extras`` and its integration into both ``query_screen``
branches:

* Gap #1 (HIGHEST LEVERAGE): the filtered (POST) branch previously projected
  ONLY the metrics the user filtered on — applying any filter blanked
  MKT CAP / P/E / CHG% / REV in the screener table. The ``_KEY_METRICS``
  display set is now unioned in via a page-bounded DISTINCT ON query.
* Gap #2: ``dist_from_52w_high_pct`` / ``dist_from_52w_low_pct`` joined the
  default (GET) key-metric projection; absolute ``high_52w`` / ``low_52w``
  come from the latest ``technicals_snapshots`` JSONB row.
* Gap #3: latest daily ``volume`` (1d OHLCV bar) ships with every row so the
  frontend can render volume-vs-30d-average.

Test strategy: mocked AsyncSession routing statements by compiled-SQL
substrings (same pattern as test_screener_snap_field_introspection.py).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_data.application.ports.repositories import ScreenFilter
from market_data.infrastructure.db.repositories import fundamental_metrics_query as fmq
from market_data.infrastructure.db.repositories.fundamental_metrics_query import (
    _fetch_page_extras,
    query_screen,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _route_session(
    *,
    metric_rows: list[tuple[Any, str, Any]] | None = None,
    volume_rows: list[tuple[Any, Any]] | None = None,
    technicals_rows: list[tuple[Any, Any, Any]] | None = None,
    screen_rows: list[Any] | None = None,
    page_rows: list[Any] | None = None,
    captured: list[Any] | None = None,
) -> MagicMock:
    """Session mock that routes each statement to the right canned result.

    Routing keys (checked against ``str(stmt)``, which renders table names):
    - ``statement_timeout`` → no-op guard
    - ``information_schema`` → never hit (cache prefilled by conftest)
    - ``technicals_snapshots`` → technicals_rows
    - ``ohlcv_bars`` → volume_rows
    - ``fundamental_metrics`` + ``DISTINCT`` → metric_rows (page enrichment)
    - everything else → screen_rows (main query) / page_rows (page-IDs query)
    """

    async def _execute(stmt: Any) -> MagicMock:
        s = str(stmt)
        result = MagicMock()
        if "statement_timeout" in s:
            result.all = MagicMock(return_value=[])
            return result
        if captured is not None:
            captured.append(stmt)
        if "technicals_snapshots" in s:
            result.all = MagicMock(return_value=technicals_rows or [])
        elif "ohlcv_bars" in s:
            result.all = MagicMock(return_value=volume_rows or [])
        elif "SELECT DISTINCT fundamental_metrics" in s.replace("\n", " "):
            result.all = MagicMock(return_value=metric_rows or [])
        elif "count" in s.lower() and "km_" not in s and "total_count" not in s:
            result.scalar_one = MagicMock(return_value=1)
        elif "km_" in s or "total_count" in s:
            # Main screener statement (GET: km_ aliases; POST: total_count col).
            result.all = MagicMock(return_value=screen_rows or [])
        else:
            result.all = MagicMock(return_value=page_rows or [])
        return result

    session = MagicMock()
    session.execute = AsyncMock(side_effect=_execute)
    return session


def _post_row(**metric_values: Any) -> MagicMock:
    """A filtered-branch result row with all snap fields NULL."""
    row = MagicMock()
    row.instrument_id = "instr-001"
    row.ticker = "AAPL"
    row.name = "Apple Inc."
    row.exchange = "NASDAQ"
    row.sector = "Technology"
    row.total_count = 1
    row.current_price = None
    for sf in fmq._SNAP_FIELDS:
        setattr(row, f"snap_{sf}", None)
    for k, v in metric_values.items():
        setattr(row, k, v)
    return row


# ---------------------------------------------------------------------------
# _fetch_page_extras unit behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_page_extras_empty_page_short_circuits() -> None:
    """No page IDs → no queries, empty mapping."""
    session = MagicMock()
    session.execute = AsyncMock()
    extras = await _fetch_page_extras(session, [], ("pe_ratio",))
    assert extras == {}
    session.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_fetch_page_extras_merges_all_three_sources() -> None:
    """Key metrics, daily volume, and 52w levels land under the instrument key."""
    session = _route_session(
        metric_rows=[("instr-001", "market_capitalization", Decimal("3e12"))],
        volume_rows=[("instr-001", 55_000_000)],
        technicals_rows=[("instr-001", Decimal("199.62"), Decimal("124.17"))],
    )
    extras = await _fetch_page_extras(session, ["instr-001"], ("market_capitalization",))
    assert extras["instr-001"]["market_capitalization"] == Decimal("3e12")
    assert extras["instr-001"]["volume"] == 55_000_000
    assert extras["instr-001"]["high_52w"] == Decimal("199.62")
    assert extras["instr-001"]["low_52w"] == Decimal("124.17")


@pytest.mark.asyncio
async def test_fetch_page_extras_skips_metric_query_when_no_extra_metrics() -> None:
    """GET branch passes () — only the volume + technicals queries run."""
    captured: list[Any] = []
    session = _route_session(captured=captured)
    await _fetch_page_extras(session, ["instr-001"], ())
    sqls = [str(s) for s in captured]
    assert not any("fundamental_metrics" in s for s in sqls), "metric query must be skipped"
    assert any("ohlcv_bars" in s for s in sqls)
    assert any("technicals_snapshots" in s for s in sqls)


@pytest.mark.asyncio
async def test_fetch_page_extras_null_values_omitted() -> None:
    """NULL volume / 52w values must not produce keys (frontend renders '—')."""
    session = _route_session(
        volume_rows=[("instr-001", None)],
        technicals_rows=[("instr-001", None, None)],
    )
    extras = await _fetch_page_extras(session, ["instr-001"], ())
    assert extras["instr-001"] == {}


@pytest.mark.asyncio
async def test_fetch_page_extras_is_fail_open() -> None:
    """A failing enrichment query must degrade to missing keys, never raise.

    Same philosophy as the BP-635 introspection guard: display-only extras
    must not convert a working screener page into a 500.
    """

    async def _execute(stmt: Any) -> MagicMock:
        raise RuntimeError("boom")

    session = MagicMock()
    session.execute = AsyncMock(side_effect=_execute)
    extras = await _fetch_page_extras(session, ["instr-001"], ("pe_ratio",))
    assert extras == {"instr-001": {}}


# ---------------------------------------------------------------------------
# POST (filtered) branch — gap #1 key-metric union
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_filtered_screen_unions_key_metrics_into_results() -> None:
    """Applying a pe_ratio filter must still return MKT CAP / REV / CHG% etc."""
    row = _post_row(pe_ratio=Decimal("20.3"))
    session = _route_session(
        screen_rows=[row],
        metric_rows=[
            ("instr-001", "market_capitalization", Decimal("3000000000000")),
            ("instr-001", "revenue_ttm", Decimal("390000000000")),
            ("instr-001", "daily_return", Decimal("0.0123")),
        ],
        volume_rows=[("instr-001", 48_000_000)],
        technicals_rows=[("instr-001", Decimal("199.62"), Decimal("124.17"))],
    )

    results, total = await query_screen(session, [ScreenFilter(metric="pe_ratio", max_value=40.0)])

    assert total == 1
    metrics = results[0].metrics
    # The filtered metric is projected by its own subquery as before.
    assert metrics["pe_ratio"] == Decimal("20.3")
    # Gap #1: key metrics now present even though they were not filtered on.
    assert metrics["market_capitalization"] == Decimal("3000000000000")
    assert metrics["revenue_ttm"] == Decimal("390000000000")
    assert metrics["daily_return"] == Decimal("0.0123")
    # Gap #3: latest daily volume.
    assert metrics["volume"] == 48_000_000
    # Gap #2: absolute 52w levels.
    assert metrics["high_52w"] == Decimal("199.62")
    assert metrics["low_52w"] == Decimal("124.17")


@pytest.mark.asyncio
async def test_filtered_screen_filter_value_wins_over_enrichment() -> None:
    """The filter subquery's (period_type-scoped) value must beat the extras value."""
    row = _post_row(pe_ratio=Decimal("20.3"))
    session = _route_session(
        screen_rows=[row],
        # Enrichment must never request pe_ratio (it IS a filter metric), but
        # even if a stale/duplicate value sneaks in, projection must win.
        metric_rows=[("instr-001", "pe_ratio", Decimal("99.9"))],
    )

    results, _ = await query_screen(session, [ScreenFilter(metric="pe_ratio", max_value=40.0)])
    assert results[0].metrics["pe_ratio"] == Decimal("20.3")


@pytest.mark.asyncio
async def test_filtered_screen_enrichment_excludes_filtered_metrics() -> None:
    """The enrichment query must only request _KEY_METRICS not already filtered."""
    captured: list[Any] = []
    row = _post_row(pe_ratio=Decimal("20.3"))
    session = _route_session(screen_rows=[row], captured=captured)

    await query_screen(session, [ScreenFilter(metric="pe_ratio", max_value=40.0)])

    metric_stmts = [s for s in captured if "SELECT DISTINCT fundamental_metrics" in str(s).replace("\n", " ")]
    assert len(metric_stmts) == 1, "exactly one page-bounded metric enrichment query expected"
    compiled = str(metric_stmts[0].compile(compile_kwargs={"literal_binds": True}))
    # Filtered metric excluded; the rest of _KEY_METRICS requested.
    assert "'pe_ratio'" not in compiled
    assert "'market_capitalization'" in compiled
    assert "'dist_from_52w_high_pct'" in compiled
    assert "'dist_from_52w_low_pct'" in compiled


# ---------------------------------------------------------------------------
# GET (no-filter) branch — gaps #2/#3 in the default view
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_view_includes_52w_distances_volume_and_levels() -> None:
    """No-filter rows carry dist_from_52w_*, volume and high/low_52w."""
    page_row = MagicMock()
    page_row.id = "instr-001"

    row = MagicMock()
    row.instrument_id = "instr-001"
    row.ticker = "AAPL"
    row.name = "Apple Inc."
    row.exchange = "NASDAQ"
    row.sector = "Technology"
    row.current_price = None
    for sf in fmq._SNAP_FIELDS:
        setattr(row, f"snap_{sf}", None)
    for km in fmq._KEY_METRICS:
        setattr(row, km, None)
    row.dist_from_52w_high_pct = Decimal("-0.12")
    row.dist_from_52w_low_pct = Decimal("0.35")

    session = _route_session(
        page_rows=[page_row],
        screen_rows=[row],
        volume_rows=[("instr-001", 61_000_000)],
        technicals_rows=[("instr-001", Decimal("199.62"), Decimal("124.17"))],
    )

    results, _ = await query_screen(session, [])

    metrics = results[0].metrics
    assert metrics["dist_from_52w_high_pct"] == Decimal("-0.12")
    assert metrics["dist_from_52w_low_pct"] == Decimal("0.35")
    assert metrics["volume"] == 61_000_000
    assert metrics["high_52w"] == Decimal("199.62")
    assert metrics["low_52w"] == Decimal("124.17")
