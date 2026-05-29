"""Unit tests for the sector-exposure aggregation helper (PLAN-0102 W2 T-W2-03).

Exercises ``_compute_sector_exposure`` directly so the math is verified
independently of the S1/S7 upstream call orchestration.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from rag_chat.application.models.briefing_context import (
    HoldingItem,
    PortfolioPnLItem,
    PortfolioPnLSnapshot,
    PortfolioSnapshot,
)
from rag_chat.application.use_cases.briefing_context import _compute_sector_exposure

pytestmark = pytest.mark.unit


def test_sector_exposure_dollar_basis_when_pnl_available() -> None:
    """Per-sector share = sum(current_price x qty) / total — dollar basis."""
    aapl_eid = uuid4()
    msft_eid = uuid4()
    xom_eid = uuid4()
    portfolio = PortfolioSnapshot(
        user_id=uuid4(),
        holdings=[
            HoldingItem(
                ticker="AAPL",
                entity_id=aapl_eid,
                canonical_name="Apple",
                quantity=Decimal("100"),
                current_weight=0.5,
            ),
            HoldingItem(
                ticker="MSFT",
                entity_id=msft_eid,
                canonical_name="Microsoft",
                quantity=Decimal("50"),
                current_weight=0.3,
            ),
            HoldingItem(
                ticker="XOM",
                entity_id=xom_eid,
                canonical_name="Exxon",
                quantity=Decimal("10"),
                current_weight=0.2,
            ),
        ],
        watchlist=[],
        total_positions=3,
    )
    # Values: AAPL 100x195=19500, MSFT 50x420=21000, XOM 10x100=1000 ⇒ 41500.
    # Sectors: AAPL→Tech, MSFT→Tech, XOM→Energy. Tech = 40500/41500, Energy = 1000/41500.
    pnl = PortfolioPnLSnapshot(
        user_id=portfolio.user_id,
        holdings=[
            PortfolioPnLItem(
                symbol="AAPL",
                entity_id=aapl_eid,
                instrument_id=uuid4(),
                qty=100.0,
                last_close_usd=192.0,
                current_price_usd=195.0,
                overnight_pnl_usd=300.0,
                overnight_pnl_pct=0.015,
            ),
            PortfolioPnLItem(
                symbol="MSFT",
                entity_id=msft_eid,
                instrument_id=uuid4(),
                qty=50.0,
                last_close_usd=415.0,
                current_price_usd=420.0,
                overnight_pnl_usd=250.0,
                overnight_pnl_pct=0.012,
            ),
            PortfolioPnLItem(
                symbol="XOM",
                entity_id=xom_eid,
                instrument_id=uuid4(),
                qty=10.0,
                last_close_usd=98.0,
                current_price_usd=100.0,
                overnight_pnl_usd=20.0,
                overnight_pnl_pct=0.02,
            ),
        ],
        total_overnight_pnl_usd=570.0,
        total_overnight_pnl_pct=0.014,
    )
    sector_map = {aapl_eid: "Tech", msft_eid: "Tech", xom_eid: "Energy"}

    exposure = _compute_sector_exposure(
        portfolio_snapshot=portfolio,
        pnl_snapshot=pnl,
        sector_map=sector_map,
    )

    assert exposure is not None
    assert exposure.by_sector["Tech"] == pytest.approx(40500 / 41500, abs=1e-4)
    assert exposure.by_sector["Energy"] == pytest.approx(1000 / 41500, abs=1e-4)
    # Total normalised to 1.0.
    assert sum(exposure.by_sector.values()) == pytest.approx(1.0, abs=1e-6)


def test_sector_exposure_buckets_unknown_into_explicit_label() -> None:
    """Holdings without sector data go under 'Unknown' so totals sum to 1.0."""
    eid_a = uuid4()
    eid_b = uuid4()
    portfolio = PortfolioSnapshot(
        user_id=uuid4(),
        holdings=[
            HoldingItem(
                ticker="A",
                entity_id=eid_a,
                canonical_name="A",
                quantity=Decimal("10"),
                current_weight=0.5,
            ),
            HoldingItem(
                ticker="B",
                entity_id=eid_b,
                canonical_name="B",
                quantity=Decimal("10"),
                current_weight=0.5,
            ),
        ],
        watchlist=[],
        total_positions=2,
    )
    pnl = PortfolioPnLSnapshot(
        user_id=portfolio.user_id,
        holdings=[
            PortfolioPnLItem(
                symbol="A",
                entity_id=eid_a,
                instrument_id=uuid4(),
                qty=10.0,
                last_close_usd=100.0,
                current_price_usd=100.0,
                overnight_pnl_usd=0.0,
                overnight_pnl_pct=0.0,
            ),
            PortfolioPnLItem(
                symbol="B",
                entity_id=eid_b,
                instrument_id=uuid4(),
                qty=10.0,
                last_close_usd=100.0,
                current_price_usd=100.0,
                overnight_pnl_usd=0.0,
                overnight_pnl_pct=0.0,
            ),
        ],
        total_overnight_pnl_usd=0.0,
        total_overnight_pnl_pct=0.0,
    )
    # Only A has a sector; B is unknown.
    sector_map = {eid_a: "Tech"}

    exposure = _compute_sector_exposure(
        portfolio_snapshot=portfolio,
        pnl_snapshot=pnl,
        sector_map=sector_map,
    )

    assert exposure is not None
    assert exposure.by_sector["Tech"] == pytest.approx(0.5, abs=1e-4)
    assert exposure.by_sector["Unknown"] == pytest.approx(0.5, abs=1e-4)


def test_sector_exposure_falls_back_to_weights_when_pnl_unavailable() -> None:
    """No P&L snapshot → uses ``current_weight`` for per-holding share."""
    eid = uuid4()
    portfolio = PortfolioSnapshot(
        user_id=uuid4(),
        holdings=[
            HoldingItem(
                ticker="A",
                entity_id=eid,
                canonical_name="A",
                quantity=Decimal("1"),
                current_weight=0.8,
            ),
        ],
        watchlist=[],
        total_positions=1,
    )
    sector_map = {eid: "Tech"}

    exposure = _compute_sector_exposure(
        portfolio_snapshot=portfolio,
        pnl_snapshot=None,
        sector_map=sector_map,
    )

    assert exposure is not None
    # Normalised — single holding with any positive weight becomes 100% Tech.
    assert exposure.by_sector["Tech"] == pytest.approx(1.0, abs=1e-6)


def test_sector_exposure_returns_none_for_empty_portfolio() -> None:
    """Zero holdings → returns None (caller skips the section)."""
    portfolio = PortfolioSnapshot(
        user_id=uuid4(),
        holdings=[],
        watchlist=[],
        total_positions=0,
    )

    exposure = _compute_sector_exposure(
        portfolio_snapshot=portfolio,
        pnl_snapshot=None,
        sector_map={},
    )

    assert exposure is None
