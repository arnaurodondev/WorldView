"""Unit tests for PLAN-0108 RecordTransactionRequest schema changes.

Covers:
- TRADE transaction requires trade_side
- Invalid transaction_type yields 422 (not 500)
- Invalid direction yields 422
- TRADE + valid trade_side is accepted
- Non-TRADE without trade_side is accepted
"""

from __future__ import annotations

import pytest
from portfolio.api.schemas import RecordTransactionRequest
from pydantic import ValidationError

pytestmark = pytest.mark.unit

_COMMON: dict = {
    "portfolio_id": "00000000-0000-0000-0000-000000000001",
    "instrument_id": "00000000-0000-0000-0000-000000000002",
    "quantity": "10",
    "price": "150.00",
    "currency": "USD",
    "executed_at": "2026-01-01T12:00:00Z",
}


class TestRecordTransactionRequestSchema:
    def test_record_transaction_request_trade_requires_side(self) -> None:
        """TRADE without trade_side must fail model_validator with a clear message."""
        with pytest.raises(ValidationError) as exc_info:
            RecordTransactionRequest(
                **_COMMON,
                transaction_type="TRADE",
                direction=None,
                trade_side=None,
            )
        errors = exc_info.value.errors()
        assert any("trade_side" in str(e) for e in errors)

    def test_record_transaction_request_invalid_type(self) -> None:
        """Unknown transaction_type should raise ValidationError (Literal constraint)."""
        with pytest.raises(ValidationError):
            RecordTransactionRequest(
                **_COMMON,
                transaction_type="UNKNOWN",
                direction="INFLOW",
            )

    def test_record_transaction_request_invalid_direction(self) -> None:
        """'BUY' is a valid transaction_type but NOT a valid direction — must raise."""
        with pytest.raises(ValidationError):
            RecordTransactionRequest(
                **_COMMON,
                transaction_type="BUY",
                direction="BUY",  # wrong field — direction must be INFLOW/OUTFLOW
            )

    def test_record_transaction_request_trade_buy_valid(self) -> None:
        """TRADE + trade_side=BUY is a valid request; direction may be omitted."""
        req = RecordTransactionRequest(
            **_COMMON,
            transaction_type="TRADE",
            trade_side="BUY",
        )
        assert req.transaction_type == "TRADE"
        assert req.trade_side == "BUY"

    def test_record_transaction_request_trade_sell_valid(self) -> None:
        """TRADE + trade_side=SELL is a valid request."""
        req = RecordTransactionRequest(
            **_COMMON,
            transaction_type="TRADE",
            trade_side="SELL",
        )
        assert req.trade_side == "SELL"

    def test_record_transaction_request_non_trade_no_side_valid(self) -> None:
        """BUY with direction=INFLOW and no trade_side is the existing happy path."""
        req = RecordTransactionRequest(
            **_COMMON,
            transaction_type="BUY",
            direction="INFLOW",
        )
        assert req.trade_side is None
        assert req.direction == "INFLOW"

    def test_record_transaction_request_all_types_accepted(self) -> None:
        """All valid transaction_type literals round-trip without error."""
        valid_types = ["BUY", "SELL", "DIVIDEND", "DEPOSIT", "WITHDRAWAL", "FEE", "INTEREST"]
        for t in valid_types:
            req = RecordTransactionRequest(
                **_COMMON,
                transaction_type=t,
                direction="INFLOW",
            )
            assert req.transaction_type == t
