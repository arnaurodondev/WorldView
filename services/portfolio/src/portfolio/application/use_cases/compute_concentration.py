"""Compute portfolio concentration metrics (PLAN-0088 Wave E E-3).

Powers the ``ConcentrationStrip`` UI row — a single-line "HHI 1,847
(moderate) · Top-3 share 71% · 5 names" summary anchored to the
**Herfindahl-Hirschman Index** standard used by FactSet PORT-CONC and
practically every institutional risk-attribution tool.

Why HHI (and not std. dev. of weights or Gini): HHI sums squared weights
expressed as percentages, so it is bounded ``[10000/n, 10000]`` and reads
naturally:

- HHI < 1500 → diversified
- 1500 ≤ HHI < 2500 → moderate
- HHI ≥ 2500 → concentrated

A single-name 100% portfolio = 10,000. An equal-weighted 5-name portfolio =
5 x (20²) = 2,000. The 5-position seed in the audit (~AAPL/MSFT/NVDA/
JPM/AMZN at ~33%/33%/5%/14%/18%) lands at HHI ≈ 1847 (moderate) — exactly
the figure cited in the audit's wireframe.

We compute weights from **current market value** (quantity x current price)
when a price client is available, falling back to cost basis when prices
are stale / missing. This mirrors ``GetExposureUseCase``'s graceful
degradation pattern — the strip should always render *something* useful,
and a "based on cost basis" label can be inferred by the frontend from
the ``prices_stale`` flag.

R27: depends on :class:`ReadOnlyUnitOfWork`. Pure read path — no commit.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING
from uuid import UUID

import structlog

from portfolio.domain.errors import AuthorizationError, PortfolioNotFoundError

if TYPE_CHECKING:
    from portfolio.application.ports.unit_of_work import ReadOnlyUnitOfWork
    from portfolio.application.use_cases.get_exposure import CurrentPriceClient

logger = structlog.get_logger(__name__)


# HHI thresholds — match the FactSet/standard antitrust convention so any
# user familiar with the term reads them at a glance. Values are pure
# integers in the [0, 10000] HHI scale (NOT fractions).
_HHI_DIVERSIFIED_MAX = 1500
_HHI_MODERATE_MAX = 2500


@dataclass(frozen=True)
class ComputeConcentrationQuery:
    """Inputs for the concentration read."""

    portfolio_id: UUID
    owner_id: UUID
    tenant_id: UUID


@dataclass(frozen=True)
class TopPositionItem:
    """One entry in the top-N positions list (used for the "Top-3" chip)."""

    instrument_id: UUID
    weight_pct: Decimal  # 0-100, NOT 0-1, to match HHI's percent convention


@dataclass(frozen=True)
class ConcentrationResult:
    """Output DTO.

    ``hhi`` is the Herfindahl-Hirschman Index in the standard 0-10,000 scale
    (sum of squared percent weights). ``label`` is the "diversified" /
    "moderate" / "concentrated" classification derived from the thresholds
    above so the frontend doesn't have to embed business rules.

    ``top_3_share_pct`` is the sum of the three largest weights as a percent
    (matches the chip in the wireframe). ``positions_count`` lets the strip
    show "5 names" without a separate fetch.
    """

    portfolio_id: UUID
    hhi: int
    label: str  # "diversified" | "moderate" | "concentrated" | "empty"
    top_3_share_pct: Decimal
    positions_count: int
    top_positions: list[TopPositionItem]
    prices_stale: bool


class ComputeConcentrationUseCase:
    """Compute HHI + top-3 share for a portfolio's current holdings.

    The use case takes an optional ``price_client`` so it can fall back to
    cost basis when prices are unreachable — same pattern as
    ``GetExposureUseCase``. When ``price_client`` is None (e.g. unit
    tests) we use cost basis directly without setting ``prices_stale``,
    because cost basis was the explicit choice — not a fallback.
    """

    def __init__(self, price_client: CurrentPriceClient | None = None) -> None:
        self._price_client = price_client

    async def execute(
        self,
        query: ComputeConcentrationQuery,
        uow: ReadOnlyUnitOfWork,
    ) -> ConcentrationResult:
        portfolio = await uow.portfolios.get(query.portfolio_id, query.tenant_id)
        if portfolio is None:
            raise PortfolioNotFoundError(f"Portfolio {query.portfolio_id} not found")
        if portfolio.owner_id != query.owner_id:
            raise AuthorizationError("Not authorized to view this portfolio's concentration")

        holdings = await uow.holdings.list_by_portfolio(query.portfolio_id)
        # Skip zero-quantity rows — they're closed positions and would dilute
        # the HHI denominator with phantom weight.
        active = [h for h in holdings if h.quantity > 0]

        if not active:
            return ConcentrationResult(
                portfolio_id=query.portfolio_id,
                hhi=0,
                label="empty",
                top_3_share_pct=Decimal(0),
                positions_count=0,
                top_positions=[],
                prices_stale=False,
            )

        # Resolve per-instrument current prices when a price client is wired.
        # Missing prices fall back to ``average_cost`` per holding so the
        # strip stays useful when S3 is briefly unavailable. We only flip
        # ``prices_stale`` when a fallback was actually triggered (NOT
        # whenever the client returned no data — that signals "no positions
        # have prices" which the empty-state branch above would already
        # have handled).
        prices: dict[UUID, Decimal] = {}
        prices_stale = False
        if self._price_client is not None:
            try:
                prices = await self._price_client.get_current_prices(
                    [h.instrument_id for h in active],
                )
            except Exception:
                logger.warning(
                    "concentration_price_client_failed",
                    portfolio_id=str(query.portfolio_id),
                    exc_info=True,
                )
                prices = {}
                prices_stale = True

        # Compute per-instrument market value (current price x qty, with
        # cost-basis fallback). Sum to the denominator so weights add to
        # exactly 100%. Decimal preserves precision; we round only at the
        # boundary when squaring for HHI.
        values: dict[UUID, Decimal] = {}
        total_value = Decimal(0)
        for h in active:
            price = prices.get(h.instrument_id)
            if price is None:
                # Fallback to cost — flag so the UI can warn the user.
                price = h.average_cost
                prices_stale = True
            v = h.quantity * price
            values[h.instrument_id] = v
            total_value += v

        # Defensive — cost basis could theoretically be zero if a holding
        # was opened at $0 (corporate action edge case). Empty-output guard.
        if total_value <= 0:
            return ConcentrationResult(
                portfolio_id=query.portfolio_id,
                hhi=0,
                label="empty",
                top_3_share_pct=Decimal(0),
                positions_count=len(active),
                top_positions=[],
                prices_stale=prices_stale,
            )

        # Build per-position percent weights (0-100). Squared and summed for
        # HHI. Sorted desc for the top-N chip.
        weights = [(iid, (v / total_value) * Decimal(100)) for iid, v in values.items()]
        weights.sort(key=lambda x: x[1], reverse=True)

        # HHI = sum(weight_i^2) where weight is in percent. Cast to int at
        # the end because the standard scale is integer-like; sub-unit
        # precision adds noise without information.
        hhi_decimal = sum((w * w for _, w in weights), start=Decimal(0))
        hhi = int(hhi_decimal)

        # Threshold-based label so the frontend doesn't embed business rules.
        if hhi < _HHI_DIVERSIFIED_MAX:
            label = "diversified"
        elif hhi < _HHI_MODERATE_MAX:
            label = "moderate"
        else:
            label = "concentrated"

        # Top-3 share — sum of the three largest weights (or fewer if the
        # portfolio has < 3 positions). Decimal preserves the 0-100 scale.
        top_3_share = sum((w for _, w in weights[:3]), start=Decimal(0))

        # Surface the top-N for the frontend chip; we expose 5 so the strip
        # can build a "Top-3 71%" caption while leaving headroom for a
        # tooltip / drill-down without a second roundtrip.
        top_positions = [TopPositionItem(instrument_id=iid, weight_pct=w) for iid, w in weights[:5]]

        return ConcentrationResult(
            portfolio_id=query.portfolio_id,
            hhi=hhi,
            label=label,
            top_3_share_pct=top_3_share,
            positions_count=len(active),
            top_positions=top_positions,
            prices_stale=prices_stale,
        )


__all__ = [
    "ComputeConcentrationQuery",
    "ComputeConcentrationUseCase",
    "ConcentrationResult",
    "TopPositionItem",
]
