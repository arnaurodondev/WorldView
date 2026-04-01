"""Unit tests for Portfolio domain value objects."""

from __future__ import annotations

from decimal import Decimal

import pytest
from portfolio.domain.value_objects import InstrumentKey, Money, Quantity

pytestmark = pytest.mark.unit

# ── Money ─────────────────────────────────────────────────────────────────────


class TestMoney:
    def test_zero_returns_zero_amount(self) -> None:
        m = Money.zero("USD")
        assert m.amount == Decimal("0")
        assert m.currency == "USD"

    def test_from_string_parses_decimal(self) -> None:
        m = Money.from_string("123.45", "EUR")
        assert m.amount == Decimal("123.45")
        assert m.currency == "EUR"

    def test_add_same_currency(self) -> None:
        a = Money.from_string("100", "USD")
        b = Money.from_string("50", "USD")
        result = a + b
        assert result.amount == Decimal("150")
        assert result.currency == "USD"

    def test_sub_same_currency(self) -> None:
        a = Money.from_string("100", "USD")
        b = Money.from_string("30", "USD")
        result = a - b
        assert result.amount == Decimal("70")
        assert result.currency == "USD"

    def test_add_different_currencies_raises(self) -> None:
        a = Money.from_string("100", "USD")
        b = Money.from_string("50", "EUR")
        with pytest.raises(ValueError, match="Currency mismatch"):
            _ = a + b

    def test_sub_different_currencies_raises(self) -> None:
        a = Money.from_string("100", "USD")
        b = Money.from_string("50", "GBP")
        with pytest.raises(ValueError, match="Currency mismatch"):
            _ = a - b

    def test_is_positive(self) -> None:
        assert Money.from_string("1", "USD").is_positive() is True
        assert Money.from_string("0", "USD").is_positive() is False
        assert Money.from_string("-1", "USD").is_positive() is False

    def test_is_negative(self) -> None:
        assert Money.from_string("-1", "USD").is_negative() is True
        assert Money.from_string("0", "USD").is_negative() is False
        assert Money.from_string("1", "USD").is_negative() is False

    def test_is_zero(self) -> None:
        assert Money.zero("USD").is_zero() is True
        assert Money.from_string("0.00000001", "USD").is_zero() is False

    def test_neg(self) -> None:
        m = Money.from_string("50", "USD")
        neg = -m
        assert neg.amount == Decimal("-50")
        assert neg.currency == "USD"

    def test_mul_by_decimal(self) -> None:
        m = Money.from_string("10", "USD")
        result = m * Decimal("3")
        assert result.amount == Decimal("30")

    def test_mul_by_int(self) -> None:
        m = Money.from_string("10", "USD")
        result = m * 4
        assert result.amount == Decimal("40")

    def test_precision_is_quantized_to_8_places(self) -> None:
        m = Money.from_string("1.123456789", "USD")
        # Rounded to 8 decimal places using ROUND_HALF_UP
        assert str(m.amount) == "1.12345679"

    def test_frozen_dataclass(self) -> None:
        m = Money.from_string("10", "USD")
        with pytest.raises(Exception):  # noqa: B017
            m.amount = Decimal("20")  # type: ignore[misc]


# ── InstrumentKey ─────────────────────────────────────────────────────────────


class TestInstrumentKey:
    def test_full_symbol_returns_symbol_colon_exchange(self) -> None:
        key = InstrumentKey(symbol="AAPL", exchange="NASDAQ")
        assert key.full_symbol() == "AAPL:NASDAQ"

    def test_full_symbol_with_different_values(self) -> None:
        key = InstrumentKey(symbol="BTC", exchange="COINBASE")
        assert key.full_symbol() == "BTC:COINBASE"

    def test_equality(self) -> None:
        k1 = InstrumentKey(symbol="AAPL", exchange="NASDAQ")
        k2 = InstrumentKey(symbol="AAPL", exchange="NASDAQ")
        assert k1 == k2

    def test_frozen_dataclass(self) -> None:
        key = InstrumentKey(symbol="AAPL", exchange="NASDAQ")
        with pytest.raises(Exception):  # noqa: B017
            key.symbol = "TSLA"  # type: ignore[misc]


# ── Quantity ──────────────────────────────────────────────────────────────────


class TestQuantity:
    def test_zero_returns_zero_value(self) -> None:
        q = Quantity.zero()
        assert q.value == Decimal("0")

    def test_add(self) -> None:
        q1 = Quantity(value=Decimal("10"))
        q2 = Quantity(value=Decimal("5"))
        result = q1 + q2
        assert result.value == Decimal("15")

    def test_sub(self) -> None:
        q1 = Quantity(value=Decimal("10"))
        q2 = Quantity(value=Decimal("3"))
        result = q1 - q2
        assert result.value == Decimal("7")

    def test_mul_by_decimal(self) -> None:
        q = Quantity(value=Decimal("10"))
        result = q * Decimal("2")
        assert result.value == Decimal("20")

    def test_mul_by_int(self) -> None:
        q = Quantity(value=Decimal("10"))
        result = q * 3
        assert result.value == Decimal("30")

    def test_neg(self) -> None:
        q = Quantity(value=Decimal("5"))
        neg = -q
        assert neg.value == Decimal("-5")

    def test_is_positive(self) -> None:
        assert Quantity(value=Decimal("1")).is_positive() is True
        assert Quantity(value=Decimal("0")).is_positive() is False
        assert Quantity(value=Decimal("-1")).is_positive() is False

    def test_is_negative(self) -> None:
        assert Quantity(value=Decimal("-1")).is_negative() is True
        assert Quantity(value=Decimal("0")).is_negative() is False
        assert Quantity(value=Decimal("1")).is_negative() is False

    def test_is_zero(self) -> None:
        assert Quantity.zero().is_zero() is True
        assert Quantity(value=Decimal("0.00000001")).is_zero() is False

    def test_precision_quantized_to_8_places(self) -> None:
        q = Quantity(value=Decimal("1.123456789"))
        assert str(q.value) == "1.12345679"

    def test_frozen_dataclass(self) -> None:
        q = Quantity(value=Decimal("10"))
        with pytest.raises(Exception):  # noqa: B017
            q.value = Decimal("20")  # type: ignore[misc]
