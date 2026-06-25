"""Unit tests for PLAN-0108 enum additions: TransactionType.TRADE and TradeSide."""

from __future__ import annotations

import pytest
from portfolio.domain.enums import TradeSide, TransactionType

pytestmark = pytest.mark.unit


class TestTransactionTypeTrade:
    def test_transaction_type_trade_valid(self) -> None:
        """TransactionType("TRADE") must resolve to TransactionType.TRADE."""
        assert TransactionType("TRADE") == TransactionType.TRADE

    def test_transaction_type_trade_is_str(self) -> None:
        """TRADE is a StrEnum value so str(TransactionType.TRADE) == 'TRADE'."""
        assert str(TransactionType.TRADE) == "TRADE"

    def test_transaction_type_existing_values_unaffected(self) -> None:
        """Adding TRADE must not break existing enum values."""
        assert TransactionType("BUY") == TransactionType.BUY
        assert TransactionType("SELL") == TransactionType.SELL
        assert TransactionType("INTEREST") == TransactionType.INTEREST


class TestTradeSideEnum:
    def test_trade_side_buy_round_trips(self) -> None:
        """TradeSide('BUY') must resolve to TradeSide.BUY."""
        assert TradeSide("BUY") == TradeSide.BUY

    def test_trade_side_sell_round_trips(self) -> None:
        """TradeSide('SELL') must resolve to TradeSide.SELL."""
        assert TradeSide("SELL") == TradeSide.SELL

    def test_trade_side_rejects_invalid(self) -> None:
        """Values outside BUY/SELL must raise ValueError (StrEnum contract)."""
        with pytest.raises(ValueError):
            TradeSide("HOLD")

    def test_trade_side_is_str(self) -> None:
        """TradeSide is a StrEnum so str() returns the raw value."""
        assert str(TradeSide.BUY) == "BUY"
        assert str(TradeSide.SELL) == "SELL"
