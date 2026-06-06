"""E2E tests for POST /api/v1/fundamentals/query (PLAN-0104 W32/W30/W39).

Scenarios:
  1. Auto-derived margins (W39): asking for ``revenue`` auto-includes
     ``gross_margin`` / ``operating_margin`` / ``net_margin`` on each
     period row when the underlying income-statement data is present.
  2. CurrentSnapshot surfaces ``forward_pe`` + ``peg_ratio`` (W30):
     when the HIGHLIGHTS section carries ``ForwardPE`` and ``PEGRatio``
     scalars, the snapshot block exposes them.
  3. Unknown metrics flagged as ``"missing"`` in coverage rather than
     422'ing the request.

Requires: docker-compose.test.yml --profile market-data-test up & healthy.
Run with: cd services/market-data && make test -- tests/e2e/ -m e2e -v
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from httpx import AsyncClient
    from sqlalchemy.ext.asyncio import AsyncSession

pytestmark = [pytest.mark.e2e, pytest.mark.slow]


async def _seed_income_statement(
    session: AsyncSession,
    instrument_id: str,
    *,
    period_end: datetime,
    revenue: float,
    gross_profit: float,
    operating_income: float,
    net_income: float,
) -> None:
    """Insert one INCOME_STATEMENT row with revenue + derived-margin numerators."""
    from market_data.domain.entities import FundamentalsRecord
    from market_data.domain.enums import FundamentalsSection, PeriodType
    from market_data.infrastructure.db.repositories.fundamentals_repo import PgFundamentalsRepository

    repo = PgFundamentalsRepository(session)
    rec = FundamentalsRecord(
        security_id=instrument_id,
        section=FundamentalsSection.INCOME_STATEMENT,
        period_end=period_end,
        period_type=PeriodType.QUARTERLY,
        data={
            "totalRevenue": revenue,
            "grossProfit": gross_profit,
            "operatingIncome": operating_income,
            "netIncome": net_income,
        },
        source="e2e-seed",
    )
    await repo.upsert_income_statement(rec)
    await session.commit()


async def _seed_highlights(
    session: AsyncSession,
    instrument_id: str,
    *,
    data: dict,
) -> None:
    """Insert one HIGHLIGHTS row (TTM/live snapshot)."""
    from market_data.domain.entities import FundamentalsRecord
    from market_data.domain.enums import FundamentalsSection, PeriodType
    from market_data.infrastructure.db.repositories.fundamentals_repo import PgFundamentalsRepository

    repo = PgFundamentalsRepository(session)
    rec = FundamentalsRecord(
        security_id=instrument_id,
        section=FundamentalsSection.HIGHLIGHTS,
        period_end=datetime(2026, 6, 1, tzinfo=UTC),
        period_type=PeriodType.QUARTERLY,
        data=data,
        source="e2e-seed",
    )
    await repo.upsert_highlights(rec)
    await session.commit()


# ── Tests ─────────────────────────────────────────────────────────────────────


async def test_query_fundamentals_revenue_auto_includes_derived_margins(
    e2e_client: AsyncClient,
    seeded_instrument: dict,
    e2e_db_session: AsyncSession,
) -> None:
    """W39: revenue request auto-emits gross_margin / operating_margin / net_margin."""
    await _seed_income_statement(
        e2e_db_session,
        seeded_instrument["instrument_id"],
        period_end=datetime(2026, 3, 31, tzinfo=UTC),
        revenue=100_000_000.0,
        gross_profit=44_000_000.0,
        operating_income=30_000_000.0,
        net_income=25_000_000.0,
    )

    resp = await e2e_client.post(
        "/api/v1/fundamentals/query",
        json={
            "instrument_id": seeded_instrument["instrument_id"],
            "metrics": ["revenue"],
            "periods": 4,
            "period_type": "quarterly",
            "include_snapshot": False,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    rows = body["metrics_by_period"]
    assert len(rows) >= 1
    first = rows[0]
    # W39 contract: gross_margin = gross_profit / revenue (0.44)
    assert first.get("gross_margin") == pytest.approx(0.44, rel=1e-3)
    assert first.get("operating_margin") == pytest.approx(0.30, rel=1e-3)
    assert first.get("net_margin") == pytest.approx(0.25, rel=1e-3)


async def test_query_fundamentals_snapshot_surfaces_forward_pe_and_peg(
    e2e_client: AsyncClient,
    seeded_instrument: dict,
    e2e_db_session: AsyncSession,
) -> None:
    """W30: snapshot exposes forward_pe + peg_ratio drawn from HIGHLIGHTS."""
    await _seed_highlights(
        e2e_db_session,
        seeded_instrument["instrument_id"],
        data={"ForwardPE": 27.80, "PEGRatio": 2.15, "PERatio": 37.73},
    )

    resp = await e2e_client.post(
        "/api/v1/fundamentals/query",
        json={
            "instrument_id": seeded_instrument["instrument_id"],
            "metrics": ["forward_pe", "peg_ratio", "pe_ratio"],
            "periods": 0,
            "include_snapshot": True,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    snap = body["snapshot"]
    assert snap is not None
    assert snap["forward_pe"] == pytest.approx(27.80)
    assert snap["peg_ratio"] == pytest.approx(2.15)
    assert snap["pe_ratio"] == pytest.approx(37.73)
    assert body["coverage"]["forward_pe"] == "ok"
    assert body["coverage"]["peg_ratio"] == "ok"


async def test_query_fundamentals_unknown_metric_flagged_missing(
    e2e_client: AsyncClient,
    seeded_instrument: dict,
) -> None:
    """Unknown metric names echo back as coverage=missing rather than 422."""
    resp = await e2e_client.post(
        "/api/v1/fundamentals/query",
        json={
            "instrument_id": seeded_instrument["instrument_id"],
            "metrics": ["nonexistent_metric_xyz"],
            "periods": 4,
            "include_snapshot": False,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["coverage"]["nonexistent_metric_xyz"] == "missing"
