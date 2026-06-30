"""CAT-B B1 unit tests: ``query_screen`` honours ATTRIBUTE-ONLY filters.

Background (docs/audits/2026-06-28-cat-b-screener-missingness.md, B1):
A natural screener request like "top 5 US technology companies by market cap"
expresses its universe constraint as an instrument *attribute*
(``sector="Technology"``) with NO ``fundamental_metrics`` threshold — the ranking
is supplied via ``sort_by=market_capitalization`` instead. Previously:

  * ``ScreenFilterRequest.metric`` was REQUIRED, so the API rejected an
    attribute-only filter with a 422 at the boundary, and
  * even if it slipped through, ``query_screen`` only applied the
    sector/industry WHERE predicates in the metric-filtered branch — whose
    ``base = filter_subqueries[0]`` would IndexError on an empty metric list.

The fix makes ``metric`` optional and routes attribute-only filters through the
no-metric branch, which now applies the same attribute/snapshot WHERE predicates
against ``instruments`` while still honouring ``sort_by``.

These tests assert the SQL emitted by ``query_screen`` for attribute-only filters
contains the right WHERE predicates, by capturing the compiled SQL from a stubbed
``AsyncSession`` (same harness style as ``test_screen_industry_filter.py``).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_data.application.ports.repositories import ScreenFilter
from market_data.infrastructure.db.repositories.fundamental_metrics_query import query_screen

pytestmark = pytest.mark.unit


def _make_capture_session() -> tuple[MagicMock, list[Any]]:
    """Return (session, captured_statements) — every ``execute`` call is recorded.

    The empty page result-set short-circuits the no-metric branch right after the
    page-selection query (``if not page_rows: return [], 0``), so ``captured[-1]``
    is the page-selection SELECT — exactly the statement whose WHERE clause we want
    to assert. SET LOCAL / introspection calls are filtered out so cache state does
    not change which statement lands last.
    """
    captured: list[Any] = []

    async def _capture(stmt: Any) -> MagicMock:
        text = str(stmt)
        if "statement_timeout" in text or "information_schema" in text:
            result = MagicMock()
            result.all = MagicMock(return_value=[])
            return result
        captured.append(stmt)
        result = MagicMock()
        result.all = MagicMock(return_value=[])  # empty page short-circuits
        return result

    session = MagicMock()
    session.execute = AsyncMock(side_effect=_capture)
    return session, captured


def _compiled_sql(stmt: Any) -> str:
    """Return the literal-bound SQL string for an SQLAlchemy statement."""
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


@pytest.mark.asyncio
async def test_attribute_only_sector_filter_emits_sector_predicate() -> None:
    """A filter with ONLY ``sector`` (metric=None) restricts the page query.

    This is the ``iter3_top5_tech_marketcap`` shape: sector=Technology, no metric
    threshold, ranked by market cap. The page query must carry the sector WHERE
    predicate so the universe is genuinely "technology", not the whole table.
    """
    session, captured = _make_capture_session()

    filters = [ScreenFilter(sector="Technology")]  # metric defaults to None
    results, total = await query_screen(
        session,
        filters,
        limit=5,
        sort_by="market_capitalization",
        sort_order="desc",
    )

    assert results == []
    assert total == 0
    assert len(captured) >= 1, "expected the page-selection query to be captured"

    page_sql = _compiled_sql(captured[-1]).lower()
    # The sector predicate must be present on the PAGE query (which drives LIMIT).
    assert "sector" in page_sql
    assert "technology" in page_sql
    # And it must be ordered by the market-cap sort value, descending.
    assert "order by" in page_sql
    assert "desc" in page_sql


@pytest.mark.asyncio
async def test_attribute_only_industry_filter_emits_industry_predicate() -> None:
    """A filter with ONLY ``industry`` (metric=None) restricts the page query.

    This is the ``ru_ai_semi_screener`` universe shape: the caller scopes to
    ``industry="Semiconductors"`` with the >$50B / growth>0 thresholds expressed
    elsewhere. Even with no metric threshold the industry universe must be honoured.
    """
    session, captured = _make_capture_session()

    filters = [ScreenFilter(industry="Semiconductors")]
    await query_screen(session, filters, limit=20, sort_by="market_capitalization", sort_order="desc")

    page_sql = _compiled_sql(captured[-1])
    assert "industry" in page_sql.lower()
    assert "Semiconductors" in page_sql


@pytest.mark.asyncio
async def test_attribute_only_snapshot_filter_joins_snapshot_and_filters() -> None:
    """An attribute-only filter on a SNAPSHOT range joins the snapshot + filters it.

    ``analyst_target_price_min`` lives on ``instrument_fundamentals_snapshot``.
    The no-metric branch must JOIN that table and emit the ``>=`` predicate so the
    universe is restricted, not returned whole.
    """
    session, captured = _make_capture_session()

    filters = [ScreenFilter(analyst_target_price_min=100.0)]
    await query_screen(session, filters, limit=10, sort_by="market_capitalization", sort_order="desc")

    page_sql = _compiled_sql(captured[-1]).lower()
    assert "instrument_fundamentals_snapshot" in page_sql
    assert "analyst_target_price" in page_sql
    assert ">= 100" in page_sql.replace(" ", " ")


@pytest.mark.asyncio
async def test_no_filters_returns_unrestricted_universe() -> None:
    """Empty ``filters`` must NOT emit any attribute WHERE predicate (regression).

    The historical "return ALL instruments" default for an empty filter list must
    be preserved — the no-metric branch only applies predicates when ``filters`` is
    non-empty.
    """
    session, captured = _make_capture_session()

    await query_screen(session, [], limit=5, sort_by="market_capitalization", sort_order="desc")

    page_sql = _compiled_sql(captured[-1]).lower()
    # No sector/industry equality predicate when there are no filters.
    assert "where instruments.sector" not in page_sql
    assert "where instruments.industry" not in page_sql


@pytest.mark.asyncio
async def test_mixed_metric_and_attribute_filters_use_metric_branch() -> None:
    """A MIX of a metric filter + an attribute-only filter still works.

    The metric-filtered branch must iterate only the metric-bearing filter (so it
    does not build a ``m.metric = NULL`` subquery for the attribute-only entry),
    while the attribute predicate is still applied as a WHERE clause.
    """
    session, captured = _make_capture_session()

    filters = [
        ScreenFilter(metric="market_capitalization", min_value=50_000_000_000),
        ScreenFilter(industry="Semiconductors"),  # attribute-only, metric=None
    ]
    results, total = await query_screen(session, filters, limit=20)

    # Empty result short-circuits; the important part is that no exception was
    # raised building the metric subqueries from a None-metric filter.
    assert results == []
    assert total == 0

    sql = _compiled_sql(captured[-1])
    assert "Semiconductors" in sql
    # The metric subquery must filter on the real metric, never on NULL.
    assert "market_capitalization" in sql
    assert "metric IS NULL" not in sql
