"""Transaction entity."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from common.ids import new_uuid  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]
from portfolio.domain.enums import TransactionDirection, TransactionType


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
    # ``amount`` is the broker-reported cash amount for the transaction. It is
    # OPTIONAL and only populated by SnapTrade-sourced rows (PLAN-0046 Wave 1,
    # BP-263). For DIVIDEND activities SnapTrade reports ``units≈0, price≈0,
    # amount=<cash_paid>``; dropping this field made dividends appear as $0.
    # For BUY/SELL it usually equals ``quantity * price`` and is informational.
    amount: Decimal | None = None
    external_ref: str | None = None
    # P2-E: broker-supplied human-readable description for the transaction
    # (e.g. "Dividend Payment - AAPL"). Optional — not all brokers / activity
    # types populate this field. None when SnapTrade omits it.
    description: str | None = None
    # P2-E: the date on which the trade settles (T+1 for equities, T+2 legacy).
    # Distinct from ``executed_at`` (trade date). None when SnapTrade omits it.
    settlement_date: date | None = None
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
