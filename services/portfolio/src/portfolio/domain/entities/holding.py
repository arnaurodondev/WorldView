"""Holding entity — current position of an instrument within a portfolio."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from common.ids import new_uuid  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from portfolio.domain.errors import InsufficientHoldingsError


@dataclass
class Holding:
    """Aggregate quantity and weighted-average cost for one instrument in a portfolio.

    Unique constraint: (portfolio_id, instrument_id).
    """

    portfolio_id: UUID
    instrument_id: UUID
    tenant_id: UUID
    currency: str
    quantity: Decimal = Decimal(0)
    average_cost: Decimal = Decimal(0)
    id: UUID = field(default_factory=new_uuid)
    updated_at: datetime = field(default_factory=utc_now)
    cost_basis_per_unit: Decimal | None = None
    total_cost_basis: Decimal | None = None

    def apply_delta(self, quantity_delta: Decimal, price: Decimal) -> None:
        """Update quantity and recalculate weighted-average cost.

        For a buy (positive delta), recalculate weighted average.
        For a sell (negative delta), validate sufficient holdings and keep avg cost.
        """
        if quantity_delta > Decimal(0):
            # Buy: update weighted average cost
            total_cost = self.quantity * self.average_cost + quantity_delta * price
            new_quantity = self.quantity + quantity_delta
            self.average_cost = total_cost / new_quantity if new_quantity > Decimal(0) else Decimal(0)
            self.quantity = new_quantity
        else:
            # Sell or withdrawal
            abs_delta = abs(quantity_delta)
            if abs_delta > self.quantity:
                raise InsufficientHoldingsError(
                    f"Insufficient holdings: have {self.quantity}, need {abs_delta}",
                    details={"instrument_id": str(self.instrument_id)},
                )
            self.quantity -= abs_delta
            if self.quantity == Decimal(0):
                self.average_cost = Decimal(0)

        self.updated_at = utc_now()
