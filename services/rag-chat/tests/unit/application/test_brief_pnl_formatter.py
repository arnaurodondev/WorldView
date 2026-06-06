"""PLAN-0102 W2 T-W2-04 — formatter tests for real P&L + sector aggregates.

Validates that ``BriefContextFormatter.format_portfolio_morning`` renders:
  * Per-holding lines with ``"AAPL +1.45% pre-mkt — +$280"`` shape.
  * Total overnight P&L footer.
  * Sector mix footer with up to 5 top sectors.
  * Falls back to the legacy weight-only rendering when ``portfolio_pnl``
    is None (backward-compat with existing brief paths).
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
    SectorExposure,
)
from rag_chat.application.use_cases.brief_context_formatter import BriefContextFormatter

pytestmark = pytest.mark.unit


def _make_portfolio() -> PortfolioSnapshot:
    return PortfolioSnapshot(
        user_id=uuid4(),
        holdings=[
            HoldingItem(
                ticker="AAPL",
                entity_id=uuid4(),
                canonical_name="Apple Inc.",
                quantity=Decimal("100"),
                current_weight=0.5,
            ),
            HoldingItem(
                ticker="MSFT",
                entity_id=uuid4(),
                canonical_name="Microsoft Corp.",
                quantity=Decimal("50"),
                current_weight=0.5,
            ),
        ],
        watchlist=[],
        total_positions=2,
    )


def _make_pnl(portfolio: PortfolioSnapshot) -> PortfolioPnLSnapshot:
    held = portfolio.holdings
    return PortfolioPnLSnapshot(
        user_id=portfolio.user_id,
        holdings=[
            PortfolioPnLItem(
                symbol="AAPL",
                entity_id=held[0].entity_id,
                instrument_id=uuid4(),
                qty=100.0,
                last_close_usd=192.50,
                current_price_usd=195.30,
                overnight_pnl_usd=280.0,
                overnight_pnl_pct=0.0145,
            ),
            PortfolioPnLItem(
                symbol="MSFT",
                entity_id=held[1].entity_id,
                instrument_id=uuid4(),
                qty=50.0,
                last_close_usd=415.00,
                current_price_usd=420.00,
                overnight_pnl_usd=250.0,
                overnight_pnl_pct=0.0120,
            ),
        ],
        total_overnight_pnl_usd=530.0,
        total_overnight_pnl_pct=0.0132,
    )


def _make_ctx(
    portfolio: PortfolioSnapshot,
    *,
    pnl: PortfolioPnLSnapshot | None = None,
    sector: SectorExposure | None = None,
) -> object:
    """Build a minimal duck-typed ctx object — avoids MagicMock attribute leaks."""

    class _Ctx:
        pass

    ctx = _Ctx()
    ctx.portfolio = portfolio  # type: ignore[attr-defined]
    ctx.portfolio_pnl = pnl  # type: ignore[attr-defined]
    ctx.sector_exposure = sector  # type: ignore[attr-defined]
    return ctx


def test_format_portfolio_morning_with_pnl_shows_per_holding_lines() -> None:
    """Each holding line shows symbol, signed %, and signed dollar amount."""
    formatter = BriefContextFormatter()
    portfolio = _make_portfolio()
    pnl = _make_pnl(portfolio)

    out = formatter.format_portfolio_morning(_make_ctx(portfolio, pnl=pnl))

    # Per-holding lines: "AAPL +1.45% pre-mkt — +$280"
    assert "AAPL" in out
    assert "+1.45%" in out
    assert "+$280" in out
    assert "MSFT" in out
    assert "+1.20%" in out
    assert "+$250" in out


def test_format_portfolio_morning_shows_total_overnight_footer() -> None:
    """Footer summarises portfolio-wide P&L in dollars and percent."""
    formatter = BriefContextFormatter()
    portfolio = _make_portfolio()
    pnl = _make_pnl(portfolio)

    out = formatter.format_portfolio_morning(_make_ctx(portfolio, pnl=pnl))

    assert "Total overnight P&L:" in out
    assert "+$530" in out
    assert "+1.32%" in out


def test_format_portfolio_morning_renders_sector_mix() -> None:
    """Top sectors listed in descending share with percent rounded to whole %."""
    formatter = BriefContextFormatter()
    portfolio = _make_portfolio()
    sector = SectorExposure(
        by_sector={
            "Information Technology": 0.65,
            "Energy": 0.18,
            "Financials": 0.12,
            "Healthcare": 0.05,
        },
    )

    out = formatter.format_portfolio_morning(_make_ctx(portfolio, sector=sector))

    assert "Sector mix:" in out
    # Highest share appears first; whole-percent formatting.
    assert "Information Technology 65%" in out
    assert "Energy 18%" in out
    assert "Financials 12%" in out


def test_format_portfolio_morning_handles_negative_pnl() -> None:
    """A down day renders ``- $...`` with negative percent (no double-minus)."""
    formatter = BriefContextFormatter()
    portfolio = _make_portfolio()
    pnl = PortfolioPnLSnapshot(
        user_id=portfolio.user_id,
        holdings=[
            PortfolioPnLItem(
                symbol="AAPL",
                entity_id=portfolio.holdings[0].entity_id,
                instrument_id=uuid4(),
                qty=100.0,
                last_close_usd=200.0,
                current_price_usd=195.0,
                overnight_pnl_usd=-500.0,
                overnight_pnl_pct=-0.025,
            ),
        ],
        total_overnight_pnl_usd=-500.0,
        total_overnight_pnl_pct=-0.025,
    )

    out = formatter.format_portfolio_morning(_make_ctx(portfolio, pnl=pnl))

    # Down day: negative % shown without the '+', dollar sign emerges from sign branch.
    assert "-2.50%" in out
    # Footer: "Total overnight P&L: -$500"
    assert "-$500" in out


def test_format_portfolio_morning_falls_back_when_pnl_missing() -> None:
    """No P&L snapshot → legacy weight-only rendering still works."""
    formatter = BriefContextFormatter()
    portfolio = _make_portfolio()

    out = formatter.format_portfolio_morning(_make_ctx(portfolio, pnl=None))

    # Legacy fallback: "Holdings (2 positions):" / "Apple Inc.: 100 units, weight 50.0%"
    assert "Apple Inc." in out
    assert "50.0%" in out
    # No P&L sentinel.
    assert "Total overnight P&L" not in out
    assert "pre-mkt" not in out
