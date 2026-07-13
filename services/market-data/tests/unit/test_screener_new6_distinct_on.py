"""NEW-6 (2026-07-06) — screener statement-timeout root-cause regression guards.

Audit ``docs/audits/2026-07-06-r1-final-exhaustive-qa.md`` (NEW-6): the screener
(``query_screen``) timed out (~114 s in R1 → ``QueryCanceledError`` / 504 under
host load in R2), so the screener + market-movers surfaces returned no data.

``EXPLAIN (ANALYZE)`` on the live DB isolated the METRIC-FILTER branch's per-filter
subquery: it ran a whole-partition ``GROUP BY instrument_id MAX(as_of_date)``
aggregate self-JOINed back for the value — the GroupAggregate scanned the entire
``metric = X`` partition (~14 k index rows, ~7 s, ~4.7 k heap fetches) BEFORE the
LIMIT. The fix rewrites it to a single ``DISTINCT ON (instrument_id) ... ORDER BY
instrument_id, as_of_date DESC`` scan, backed by the existing covering index
``ix_fundamental_metrics_metric_instr_date_val`` (migration 038). Measured live:
7,280 ms → 160 ms for a ``market_capitalization >= 1e9`` screen, identical result
set (612 = 612, symmetric diff 0/0).

These tests pin the SQL SHAPE of BOTH latest-value-per-instrument code paths
(metric-filter branch + default-branch key-metric enrichment) so the aggregate-
before-LIMIT anti-pattern cannot silently return, and pin the newly-configurable
statement-timeout ceiling.

Test strategy mirrors ``test_screener_default_sort.py``: a mocked AsyncSession
that records every statement and routes by compiled-SQL substring. DISTINCT ON is
PostgreSQL-only, so assertions compile against the postgresql dialect (the
production driver is asyncpg).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_data.application.ports.repositories import ScreenFilter
from market_data.infrastructure.db.repositories import fundamental_metrics_query as fmq
from market_data.infrastructure.db.repositories.fundamental_metrics_query import query_screen
from sqlalchemy.dialects import postgresql

pytestmark = pytest.mark.unit


def _capturing_session(
    *,
    page_rows: list[Any] | None = None,
    screen_rows: list[Any] | None = None,
    captured: list[Any] | None = None,
    timeout_stmts: list[str] | None = None,
) -> MagicMock:
    """Mocked session that records statements and returns canned rows.

    Same routing convention as ``test_screener_default_sort._capturing_session``;
    additionally records the ``SET LOCAL statement_timeout`` string so the
    configurable-ceiling test can assert on it.
    """

    async def _execute(stmt: Any) -> MagicMock:
        s = str(stmt)
        result = MagicMock()
        if "statement_timeout" in s:
            if timeout_stmts is not None:
                # Render bind params inline so the numeric ceiling is visible.
                timeout_stmts.append(str(stmt.compile(compile_kwargs={"literal_binds": True})))
            result.all = MagicMock(return_value=[])
            return result
        if captured is not None:
            captured.append(stmt)
        flat = s.replace("\n", " ")
        if "technicals_snapshots" in s or "ohlcv_bars" in s:
            result.all = MagicMock(return_value=[])
        elif "DISTINCT fundamental_metrics" in flat and "fundamental_metrics.metric IN" in flat:
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


def _page_row(instrument_id: str = "instr-001") -> MagicMock:
    pr = MagicMock()
    pr.id = instrument_id
    return pr


def _filtered_row(metric_col: str, value: Decimal) -> MagicMock:
    row = MagicMock()
    row.instrument_id = "instr-001"
    row.ticker = "NVDA"
    row.name = "NVIDIA"
    row.exchange = "NASDAQ"
    row.sector = "Technology"
    row.total_count = 1
    row.current_price = None
    setattr(row, metric_col, value)
    for sf in fmq._SNAP_FIELDS:
        setattr(row, f"snap_{sf}", None)
    return row


def _pg(stmt: Any) -> str:
    """Compile a captured statement against the PostgreSQL dialect (asyncpg prod)."""
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


# ---------------------------------------------------------------------------
# Metric-filter branch (the NEW-6 line-998 culprit)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_metric_filter_subquery_is_distinct_on_not_group_by() -> None:
    """The per-metric filter subquery MUST be DISTINCT ON, not GROUP BY MAX.

    REGRESSION GUARD (NEW-6). Pins the metric-filter branch SQL shape:
      * the filtered main query MUST contain ``DISTINCT ON`` (the SkipScan-able
        latest-per-instrument shape);
      * it MUST NOT contain ``GROUP BY`` (the whole-partition aggregate);
      * it MUST NOT carry a ``max(as_of_date)`` aggregate;
      * it MUST still order the per-instrument pick by ``as_of_date DESC`` and
        filter ``metric = 'market_capitalization'`` (correctness: latest value
        per instrument).
    """
    captured: list[Any] = []
    session = _capturing_session(
        screen_rows=[_filtered_row("market_capitalization", Decimal("3e12"))],
        captured=captured,
    )

    results, total = await query_screen(
        session,
        [ScreenFilter(metric="market_capitalization", min_value=1_000_000_000)],
        limit=20,
        sort_by="market_capitalization",
        sort_order="desc",
    )

    assert total == 1
    assert len(results) == 1
    main_stmts = [s for s in captured if "total_count" in str(s)]
    assert main_stmts, "filtered main query must be captured"
    sql = _pg(main_stmts[0])
    upper = sql.upper()
    assert "DISTINCT ON" in upper, sql
    assert "GROUP BY" not in upper, f"whole-partition GROUP-BY-before-LIMIT regressed:\n{sql}"
    assert "MAX(" not in upper, f"MAX(as_of_date) aggregate regressed:\n{sql}"
    assert "'market_capitalization'" in sql, sql
    assert "AS_OF_DATE DESC" in upper, sql


@pytest.mark.asyncio
async def test_metric_filter_period_type_predicate_preserved() -> None:
    """A period_type filter must still bind (against the latest row's period_type).

    The rewrite carries ``period_type`` out of the DISTINCT ON subquery and
    filters it in the outer wrapper, matching the old "latest date, then require
    this period_type" semantics. Guards that the predicate is not silently dropped.
    """
    captured: list[Any] = []
    session = _capturing_session(
        screen_rows=[_filtered_row("pe_ratio", Decimal("18"))],
        captured=captured,
    )

    await query_screen(
        session,
        [ScreenFilter(metric="pe_ratio", max_value=30, period_type="TTM")],
        limit=20,
    )

    main_stmts = [s for s in captured if "total_count" in str(s)]
    assert main_stmts
    sql = _pg(main_stmts[0])
    assert "period_type" in sql, sql
    assert "'TTM'" in sql, sql


# ---------------------------------------------------------------------------
# Default-branch key-metric enrichment (same anti-pattern, scoped to page_ids)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_branch_key_metric_enrichment_is_distinct_on() -> None:
    """The default-branch per-metric enrichment subqueries use DISTINCT ON.

    REGRESSION GUARD (NEW-6): ``_latest_metric_sq`` was also a GROUP BY MAX +
    self-JOIN (scoped to page_ids). It is now DISTINCT ON. Pin that the enrichment
    SELECT (``km_`` aliases) contains no ``GROUP BY`` / ``max(as_of_date)``.
    """
    captured: list[Any] = []
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
    session = _capturing_session(page_rows=[_page_row()], screen_rows=[row], captured=captured)

    await query_screen(session, [], limit=5)

    enrichment = [s for s in captured if "km_" in str(s)]
    assert enrichment, "key-metric enrichment SELECT must be captured"
    sql = _pg(enrichment[0])
    upper = sql.upper()
    assert "DISTINCT ON" in upper, sql
    assert "GROUP BY" not in upper, f"scoped GROUP-BY enrichment regressed:\n{sql}"
    assert "MAX(" not in upper, f"MAX(as_of_date) enrichment aggregate regressed:\n{sql}"


# ---------------------------------------------------------------------------
# Configurable statement-timeout ceiling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_statement_timeout_default_is_8000() -> None:
    """The screen sets SET LOCAL statement_timeout to the configured default."""
    fmq._screen_statement_timeout_ms.cache_clear()
    timeouts: list[str] = []
    session = _capturing_session(page_rows=[], timeout_stmts=timeouts)

    await query_screen(session, [], limit=5)

    assert timeouts, "SET LOCAL statement_timeout must be issued"
    assert "8000" in timeouts[0], timeouts[0]


@pytest.mark.asyncio
async def test_statement_timeout_is_configurable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Raising the tunable changes the SET LOCAL statement_timeout value.

    Guards that the ceiling is env-driven (``MARKET_DATA_SCREEN_STATEMENT_TIMEOUT_MS``)
    and no longer hardcoded to 8000.
    """
    monkeypatch.setattr(fmq, "_screen_statement_timeout_ms", lambda: 15000)
    timeouts: list[str] = []
    session = _capturing_session(page_rows=[], timeout_stmts=timeouts)

    await query_screen(session, [], limit=5)

    assert timeouts
    assert "15000" in timeouts[0], timeouts[0]
    assert "8000" not in timeouts[0], timeouts[0]
