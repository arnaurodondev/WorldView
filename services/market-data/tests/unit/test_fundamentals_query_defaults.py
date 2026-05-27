"""Unit tests for the defensive ``period_type=QUARTERLY`` default in
``query_fundamentals`` for balance_sheet / cash_flow (PLAN-0096 T-W1-01, BP-546).

These tests intercept the SQLAlchemy statement passed to ``session.execute``
and inspect its compiled WHERE clause for a ``period_type = :period_type``
binding. This avoids spinning up a real DB while still proving the SQL the
repo emits — which is the exact contract the audit cares about.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_data.domain.enums import FundamentalsSection, PeriodType
from market_data.infrastructure.db.repositories.fundamentals_query import query_fundamentals

pytestmark = pytest.mark.unit


def _make_session_capturing_stmt() -> tuple[Any, list[Any]]:
    """Return (mock_session, captured_stmts) where every execute() call is
    appended to captured_stmts. The execute mock returns an empty result so the
    caller path falls through cleanly without exercising row mapping."""
    captured: list[Any] = []

    async def _execute(stmt: Any, *args: Any, **kwargs: Any) -> Any:
        captured.append(stmt)
        result = MagicMock()
        scalars = MagicMock()
        scalars.all = MagicMock(return_value=[])
        result.scalars = MagicMock(return_value=scalars)
        return result

    session = MagicMock()
    session.execute = AsyncMock(side_effect=_execute)
    return session, captured


def _where_sql(stmt: Any) -> str:
    """Return only the WHERE-clause text of the compiled statement.

    We slice off the SELECT-list / FROM / ORDER BY so a column named
    ``period_type`` in the projection list cannot mask the actual filter
    presence/absence we want to assert on.
    """
    full = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    where_idx = full.upper().find("WHERE")
    order_idx = full.upper().find("ORDER BY")
    if where_idx == -1:
        return ""
    end = order_idx if order_idx != -1 else len(full)
    return full[where_idx:end]


@pytest.mark.asyncio
async def test_query_fundamentals_defaults_balance_sheet_to_quarterly() -> None:
    """BP-546 — when caller omits period_type for BALANCE_SHEET, the repo
    must add a defensive ``period_type = 'quarterly'`` filter."""
    session, captured = _make_session_capturing_stmt()
    await query_fundamentals(
        session,
        security_id="00000000-0000-0000-0000-000000000001",
        section=FundamentalsSection.BALANCE_SHEET,
        period_type=None,
    )
    assert len(captured) == 1
    sql = _where_sql(captured[0])
    assert "period_type" in sql
    assert "QUARTERLY" in sql


@pytest.mark.asyncio
async def test_query_fundamentals_defaults_cash_flow_to_quarterly() -> None:
    """BP-546 — same defensive default applies to CASH_FLOW."""
    session, captured = _make_session_capturing_stmt()
    await query_fundamentals(
        session,
        security_id="00000000-0000-0000-0000-000000000001",
        section=FundamentalsSection.CASH_FLOW,
        period_type=None,
    )
    sql = _where_sql(captured[0])
    assert "period_type" in sql
    assert "QUARTERLY" in sql


@pytest.mark.asyncio
async def test_query_fundamentals_explicit_annual_overrides_default() -> None:
    """The defensive default must NOT shadow explicit caller-supplied
    period_type=ANNUAL — the repo should emit the annual filter as-is."""
    session, captured = _make_session_capturing_stmt()
    await query_fundamentals(
        session,
        security_id="00000000-0000-0000-0000-000000000001",
        section=FundamentalsSection.BALANCE_SHEET,
        period_type=PeriodType.ANNUAL,
    )
    sql = _where_sql(captured[0])
    assert "period_type" in sql
    assert "ANNUAL" in sql
    assert "QUARTERLY" not in sql


@pytest.mark.asyncio
async def test_query_fundamentals_income_statement_no_default() -> None:
    """Income statement deliberately does NOT get a repo-layer default —
    the use case (GetFundamentalsHistoryUseCase) owns that decision per
    PLAN-0095 T-W1-02. Verifies the SQL has no period_type filter when the
    caller passes None for INCOME_STATEMENT."""
    session, captured = _make_session_capturing_stmt()
    await query_fundamentals(
        session,
        security_id="00000000-0000-0000-0000-000000000001",
        section=FundamentalsSection.INCOME_STATEMENT,
        period_type=None,
    )
    sql = _where_sql(captured[0])
    # No period_type predicate should be present at all.
    assert "period_type" not in sql
