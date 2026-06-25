"""FIX-LIVE-M unit tests: ``query_screen`` honours the ``industry`` filter.

Background (docs/audits/2026-05-24-inv-live-jklm-investigation-report.md, F-LIVE-M):
NVDA/AMD/AVGO/TSM/INTC are GICS-tagged ``sector=Technology, industry=Semiconductors``.
A query for "AI chip companies" reduces to ``industry='Semiconductors'``; the prior
``sector``-only filter path either returned 0 rows (sector="Semiconductors") or
hundreds of unrelated SaaS / IT tickers (sector="Technology"). The fix wires the
existing ``industry`` column on ``instruments`` through ``ScreenFilter`` end-to-end.

We assert here that the SQL emitted by ``query_screen`` includes an ``industry =``
WHERE-clause when a filter sets ``industry``, by capturing the compiled SQL from a
stubbed ``AsyncSession``.
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

    WHY filter out SET LOCAL: query_screen issues ``SET LOCAL statement_timeout``
    before the screener query (PLAN-0099 timeout guard). We skip it so
    ``captured[-1]`` is always the screener SELECT regardless of cache state.
    """
    captured: list[Any] = []

    async def _capture(stmt: Any) -> MagicMock:
        if "statement_timeout" in str(stmt):
            result = MagicMock()
            result.all = MagicMock(return_value=[])
            return result
        captured.append(stmt)
        result = MagicMock()
        result.all = MagicMock(return_value=[])  # empty result-set short-circuits
        return result

    session = MagicMock()
    session.execute = AsyncMock(side_effect=_capture)
    return session, captured


def _compiled_sql(stmt: Any) -> str:
    """Return the literal-bound SQL string for an SQLAlchemy statement."""
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


@pytest.mark.asyncio
async def test_query_screen_industry_filter_adds_where_clause() -> None:
    """When a filter sets ``industry``, the compiled SQL contains ``industry = '...'``."""
    session, captured = _make_capture_session()

    filters = [
        ScreenFilter(
            metric="pe_ratio",
            max_value=30.0,
            industry="Semiconductors",
        ),
    ]

    results, total = await query_screen(session, filters, limit=50, offset=0)

    # Empty result-set short-circuits, but the statement was issued and captured.
    assert results == []
    assert total == 0
    # WHY >= 1 (not == 1): if _AVAILABLE_SNAP_FIELDS is uncached, query_screen
    # fires an extra introspection call. The screener SELECT is always last.
    assert len(captured) >= 1, "expected at least one execute() call"

    sql = _compiled_sql(captured[-1])
    # The industry filter must surface as a WHERE predicate against instruments.industry.
    assert "industry" in sql.lower(), f"industry column missing from SQL: {sql}"
    assert "Semiconductors" in sql, f"industry value missing from SQL: {sql}"


@pytest.mark.asyncio
async def test_query_screen_omits_industry_clause_when_none() -> None:
    """Without an ``industry`` filter, no industry-equals predicate is emitted.

    Sector-only behaviour must remain unchanged (no regression on existing callers).
    """
    session, captured = _make_capture_session()

    filters = [ScreenFilter(metric="pe_ratio", max_value=30.0, sector="Technology")]
    await query_screen(session, filters, limit=50, offset=0)

    sql = _compiled_sql(captured[-1])
    # Sector predicate is present; no instruments.industry = ... predicate.
    assert "Technology" in sql
    assert "Semiconductors" not in sql
    # Guard against an accidental ``WHERE instruments.industry = NULL`` emission.
    assert "industry =" not in sql.lower() or "industry IS" in sql


@pytest.mark.asyncio
async def test_query_screen_industry_and_sector_combined() -> None:
    """A filter that sets BOTH sector and industry emits both predicates (AND)."""
    session, captured = _make_capture_session()

    filters = [
        ScreenFilter(
            metric="pe_ratio",
            max_value=30.0,
            sector="Technology",
            industry="Semiconductors",
        ),
    ]
    await query_screen(session, filters, limit=50, offset=0)

    sql = _compiled_sql(captured[-1])
    assert "Technology" in sql
    assert "Semiconductors" in sql
