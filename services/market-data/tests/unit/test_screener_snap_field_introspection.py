"""PLAN-0103 W16 (BP-635) regression — schema-introspection guard for query_screen.

The screener projects every column in ``_SNAP_FIELDS`` unconditionally. When
the deployed DB lags the ORM (e.g. migrations 028 calendar columns or 030
insider_net_buy_90d not yet applied), the generated SQL referenced
non-existent columns and asyncpg raised
``UndefinedColumnError: column instrument_fundamentals_snapshot.next_earnings_date does not exist``,
surfacing as a 500 to ``/v1/fundamentals/screen``.

The fix introspects ``information_schema.columns`` once per process and
projects only the columns the deployed schema actually carries. These tests
exercise that path with a captured session that simulates a partial schema.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_data.application.ports.repositories import ScreenFilter
from market_data.infrastructure.db.repositories import fundamental_metrics_query as fmq
from market_data.infrastructure.db.repositories.fundamental_metrics_query import query_screen

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_snap_field_cache() -> None:
    """Ensure each test starts with an empty introspection cache."""
    fmq._AVAILABLE_SNAP_FIELDS = None
    yield
    fmq._AVAILABLE_SNAP_FIELDS = None


def _make_session(present_columns: set[str], screen_rows: list[Any] | None = None) -> MagicMock:
    """Return an AsyncSession mock that:
    - returns ``present_columns`` when introspection runs (first call)
    - returns ``screen_rows`` (or []) for the subsequent screener query

    The handler distinguishes the introspection statement by checking for
    the ``information_schema`` substring in its compiled SQL.
    """
    screen_rows = screen_rows or []

    async def _execute(stmt: Any) -> MagicMock:
        # The introspection helper uses ``text(...)`` — its compiled form
        # contains the ``information_schema`` table reference.
        s = str(stmt)
        result = MagicMock()
        if "information_schema" in s:
            # Each row is a tuple-like (column_name,)
            result.all = MagicMock(return_value=[(c,) for c in present_columns])
        else:
            result.all = MagicMock(return_value=screen_rows)
        return result

    session = MagicMock()
    session.execute = AsyncMock(side_effect=_execute)
    return session


def _sql(stmt: Any) -> str:
    """Compile a statement to literal-bound SQL for substring assertions."""
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


@pytest.mark.asyncio
async def test_query_screen_skips_missing_calendar_columns() -> None:
    """A pre-028 schema (no next_earnings_date / next_dividend_date) must not 500.

    Simulates the exact production gap that caused PLAN-0103 W16's Q2
    ``ru_ai_semi_screener`` 500: alembic head 025 + ORM forward of that.
    """
    captured: list[Any] = []
    # Realistic subset — pre-028 columns only (no calendar, no insider).
    present = {
        "avg_volume_30d",
        "eps_ttm",
        "free_cash_flow",
        "fcf_margin",
        "interest_coverage",
        "net_debt_to_ebitda",
        "credit_rating",
        "analyst_target_price",
        "analyst_consensus_rating",
        "institutional_ownership_pct",
        "short_percent",
    }

    async def _execute(stmt: Any) -> MagicMock:
        captured.append(stmt)
        result = MagicMock()
        if "information_schema" in str(stmt):
            result.all = MagicMock(return_value=[(c,) for c in present])
        else:
            result.all = MagicMock(return_value=[])
        return result

    session = MagicMock()
    session.execute = AsyncMock(side_effect=_execute)

    filters = [
        ScreenFilter(metric="market_capitalization", min_value=50_000_000_000),
        ScreenFilter(metric="quarterly_revenue_growth_yoy", min_value=0.0),
    ]
    # Must not raise — and the compiled screener SQL must NOT reference the
    # missing calendar columns in its projection.
    await query_screen(session, filters)

    # Second captured statement is the screener query (first is introspection).
    screen_stmt = captured[1]
    sql = _sql(screen_stmt).lower()
    assert "next_earnings_date" not in sql, f"projection leaked missing column:\n{sql}"
    assert "next_dividend_date" not in sql, f"projection leaked missing column:\n{sql}"
    assert "insider_net_buy_90d" not in sql, f"projection leaked missing column:\n{sql}"
    # But present columns should still be projected.
    assert "eps_ttm" in sql, "present column missing from projection"


@pytest.mark.asyncio
async def test_query_screen_skips_insider_filter_when_column_missing() -> None:
    """Filtering on insider_net_buy_90d when the column doesn't exist must be a no-op.

    Without the guard, the WHERE clause would generate
    ``snap.insider_net_buy_90d >= :v`` and asyncpg would 500.
    """
    captured: list[Any] = []
    present: set[str] = set()  # nothing — extreme case

    async def _execute(stmt: Any) -> MagicMock:
        captured.append(stmt)
        result = MagicMock()
        if "information_schema" in str(stmt):
            result.all = MagicMock(return_value=[(c,) for c in present])
        else:
            result.all = MagicMock(return_value=[])
        return result

    session = MagicMock()
    session.execute = AsyncMock(side_effect=_execute)

    filters = [
        ScreenFilter(
            metric="pe_ratio",
            max_value=40.0,
            insider_net_buy_90d_min=1_000_000,
        )
    ]
    await query_screen(session, filters)

    sql = _sql(captured[1]).lower()
    assert "insider_net_buy_90d" not in sql


@pytest.mark.asyncio
async def test_query_screen_projects_all_snap_fields_when_schema_complete() -> None:
    """When every _SNAP_FIELDS column is present, projection is unchanged.

    Sanity check that the introspection guard isn't accidentally stripping
    columns on a fully-migrated schema (the production-target invariant).
    """
    captured: list[Any] = []
    present = set(fmq._SNAP_FIELDS)

    async def _execute(stmt: Any) -> MagicMock:
        captured.append(stmt)
        result = MagicMock()
        if "information_schema" in str(stmt):
            result.all = MagicMock(return_value=[(c,) for c in present])
        else:
            result.all = MagicMock(return_value=[])
        return result

    session = MagicMock()
    session.execute = AsyncMock(side_effect=_execute)

    await query_screen(session, [ScreenFilter(metric="pe_ratio", max_value=40.0)])

    sql = _sql(captured[1]).lower()
    # Every snap field appears as ``snap_<field>`` alias in the projection.
    for field in fmq._SNAP_FIELDS:
        assert f"snap_{field}" in sql, f"{field} missing from full-schema projection"


@pytest.mark.asyncio
async def test_query_screen_caches_introspection_across_calls() -> None:
    """The information_schema query must fire ONCE per process, not per call."""
    introspect_calls = 0

    async def _execute(stmt: Any) -> MagicMock:
        nonlocal introspect_calls
        result = MagicMock()
        if "information_schema" in str(stmt):
            introspect_calls += 1
            result.all = MagicMock(return_value=[(c,) for c in fmq._SNAP_FIELDS])
        else:
            result.all = MagicMock(return_value=[])
        return result

    session = MagicMock()
    session.execute = AsyncMock(side_effect=_execute)

    filters = [ScreenFilter(metric="pe_ratio", max_value=40.0)]
    await query_screen(session, filters)
    await query_screen(session, filters)
    await query_screen(session, filters)

    assert introspect_calls == 1, f"introspection ran {introspect_calls} times — cache broken"
