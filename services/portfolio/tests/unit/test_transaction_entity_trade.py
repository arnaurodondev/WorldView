"""Unit tests for PLAN-0108 Transaction entity changes (trade_side invariant)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from portfolio.domain.entities.transaction import Transaction
from portfolio.domain.enums import TradeSide, TransactionDirection, TransactionType

pytestmark = pytest.mark.unit


def _make_transaction(**kwargs: object) -> Transaction:
    """Build a valid Transaction with sensible defaults; override via kwargs."""
    defaults: dict[str, object] = {
        "tenant_id": uuid.uuid4(),
        "portfolio_id": uuid.uuid4(),
        "instrument_id": uuid.uuid4(),
        "transaction_type": TransactionType.BUY,
        "direction": TransactionDirection.INFLOW,
        "quantity": Decimal(10),
        "price": Decimal(100),
        "currency": "USD",
        "executed_at": datetime.now(tz=UTC),
    }
    defaults.update(kwargs)
    return Transaction(**defaults)  # type: ignore[arg-type]


class TestTransactionTradeSideInvariant:
    def test_transaction_entity_trade_buy_valid(self) -> None:
        """TRADE + TradeSide.BUY + INFLOW direction is a well-formed entity."""
        t = _make_transaction(
            transaction_type=TransactionType.TRADE,
            direction=TransactionDirection.INFLOW,
            trade_side=TradeSide.BUY,
        )
        assert t.trade_side == TradeSide.BUY
        assert t.transaction_type == TransactionType.TRADE

    def test_transaction_entity_trade_sell_valid(self) -> None:
        """TRADE + TradeSide.SELL + OUTFLOW direction is a well-formed entity."""
        t = _make_transaction(
            transaction_type=TransactionType.TRADE,
            direction=TransactionDirection.OUTFLOW,
            trade_side=TradeSide.SELL,
        )
        assert t.trade_side == TradeSide.SELL

    def test_transaction_entity_trade_side_invariant(self) -> None:
        """TRADE transaction with trade_side=None must raise ValueError."""
        with pytest.raises(ValueError, match="trade_side must be set for TRADE transactions"):
            _make_transaction(
                transaction_type=TransactionType.TRADE,
                direction=TransactionDirection.INFLOW,
                trade_side=None,
            )

    def test_transaction_entity_non_trade_side_invariant(self) -> None:
        """Non-TRADE transaction with a trade_side set must raise ValueError."""
        with pytest.raises(ValueError, match="trade_side must be None for non-TRADE transactions"):
            _make_transaction(
                transaction_type=TransactionType.BUY,
                direction=TransactionDirection.INFLOW,
                trade_side=TradeSide.BUY,
            )

    def test_transaction_entity_non_trade_no_side(self) -> None:
        """Non-TRADE transaction with trade_side=None is valid (default behaviour)."""
        t = _make_transaction(
            transaction_type=TransactionType.BUY,
            direction=TransactionDirection.INFLOW,
            trade_side=None,
        )
        assert t.trade_side is None

    def test_transaction_entity_trade_side_default_is_none(self) -> None:
        """Existing code that doesn't pass trade_side still constructs BUY/SELL correctly."""
        t = _make_transaction(
            transaction_type=TransactionType.SELL,
            direction=TransactionDirection.OUTFLOW,
        )
        assert t.trade_side is None
