"""Repo-level tests for the market-aggregation queries in PgOHLCVRepository.

2026-06-10 frontend-audit data-gap fixes:
* Gap #4: ``get_period_movers`` rows now carry ``last_price`` (latest daily
  close — already materialised by the LATERAL subquery) so consumers no
  longer need a second /internal/v1/price batch call.
* Gap #5: ``get_sector_period_returns`` rows now carry ``top_mover_ticker``
  and ``top_mover_return_pct`` (largest ABSOLUTE period move per sector) so
  the heatmap no longer client-side-joins /market/period-movers.

Strategy: mock the AsyncSession and feed canned ``mappings().all()`` rows —
these tests pin the row→dict mapping contract (names, rounding, None-safety),
not the SQL execution itself.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from market_data.infrastructure.db.repositories.ohlcv_repo import PgOHLCVRepository

pytestmark = pytest.mark.unit


def _session_with_mapping_rows(rows: list[dict[str, Any]]) -> tuple[MagicMock, list[Any]]:
    """Session mock whose execute() result supports .mappings().all()."""
    captured: list[Any] = []

    async def _execute(stmt: Any, params: Any = None) -> MagicMock:
        captured.append((stmt, params))
        result = MagicMock()
        result.mappings.return_value.all.return_value = rows
        return result

    session = MagicMock()
    session.execute = AsyncMock(side_effect=_execute)
    return session, captured


# ---------------------------------------------------------------------------
# Gap #4 — get_period_movers carries last_price
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_period_movers_row_includes_last_price() -> None:
    session, captured = _session_with_mapping_rows(
        [
            {
                "instrument_id": "instr-001",
                "ticker": "SNOW",
                "name": "Snowflake Inc.",
                "last_price": Decimal("231.4500"),
                "period_return_pct": Decimal("61.6312"),
            }
        ]
    )
    repo = PgOHLCVRepository(session)

    rows = await repo.get_period_movers(lookback_days=7, mover_type="gainers", limit=10)

    assert rows == [
        {
            "instrument_id": "instr-001",
            "ticker": "SNOW",
            "name": "Snowflake Inc.",
            "last_price": 231.45,
            "period_return_pct": 61.63,
        }
    ]
    # The SQL itself must project latest.close as last_price.
    sql = str(captured[0][0])
    assert "latest.close AS last_price" in sql


@pytest.mark.asyncio
async def test_period_movers_null_last_price_stays_null() -> None:
    """NULL close (defensive) maps to None, never 0.0."""
    session, _ = _session_with_mapping_rows(
        [
            {
                "instrument_id": "instr-002",
                "ticker": "XYZ",
                "name": "XYZ Corp",
                "last_price": None,
                "period_return_pct": None,
            }
        ]
    )
    repo = PgOHLCVRepository(session)

    rows = await repo.get_period_movers(lookback_days=30, mover_type="losers", limit=5)

    assert rows[0]["last_price"] is None
    assert rows[0]["period_return_pct"] is None


# ---------------------------------------------------------------------------
# Gap #5 — get_sector_period_returns carries per-sector top mover
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sector_returns_row_includes_top_mover() -> None:
    session, captured = _session_with_mapping_rows(
        [
            {
                "name": "Technology",
                "change_pct": Decimal("3.4812"),
                "instrument_count": 91,
                "top_mover_ticker": "SNOW",
                "top_mover_return_pct": Decimal("61.6312"),
            }
        ]
    )
    repo = PgOHLCVRepository(session)

    rows = await repo.get_sector_period_returns(lookback_days=7)

    assert rows == [
        {
            "name": "Technology",
            "change_pct": 3.48,
            "instrument_count": 91,
            "top_mover_ticker": "SNOW",
            "top_mover_return_pct": 61.63,
        }
    ]
    # WHY ABS ordering: "top mover" = largest absolute move (gainer OR loser),
    # matching how the frontend labels heatmap tiles.
    sql = str(captured[0][0])
    assert "ABS(return_pct) DESC" in sql
    assert "DISTINCT ON (sector)" in sql


@pytest.mark.asyncio
async def test_sector_returns_top_mover_nullable() -> None:
    """Sectors with no computable return carry explicit nulls (LEFT JOIN miss)."""
    session, _ = _session_with_mapping_rows(
        [
            {
                "name": "Utilities",
                "change_pct": None,
                "instrument_count": 3,
                "top_mover_ticker": None,
                "top_mover_return_pct": None,
            }
        ]
    )
    repo = PgOHLCVRepository(session)

    rows = await repo.get_sector_period_returns(lookback_days=30)

    assert rows[0]["top_mover_ticker"] is None
    assert rows[0]["top_mover_return_pct"] is None
    assert rows[0]["change_pct"] is None
