"""Transaction entity."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING

from common.ids import new_uuid  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from portfolio.domain.enums import TransactionDirection, TransactionType

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


@dataclass
class Transaction:
    tenant_id: UUID
    portfolio_id: UUID
    instrument_id: UUID
    transaction_type: TransactionType
    direction: TransactionDirection
    quantity: Decimal
    price: Decimal
    currency: str
    executed_at: datetime
    fees: Decimal = Decimal(0)
    external_ref: str | None = None
    id: UUID = field(default_factory=new_uuid)
    created_at: datetime = field(default_factory=utc_now)

    def gross_amount(self) -> Decimal:
        """Quantity * price, before fees."""
        return self.quantity * self.price

    def net_amount(self) -> Decimal:
        """Gross amount adjusted for fees.

        Fees are subtracted for outflows (sell/withdrawal) and added for inflows (buy/deposit).
        """
        if self.direction == TransactionDirection.INFLOW:
            return self.gross_amount() + self.fees
        return self.gross_amount() - self.fees
