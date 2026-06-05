"""Unit tests for InsiderTransactionsConsumer helpers (PLAN-0089 Wave L-4b).

These cover the pure parsing/derivation helpers — the integration with
Kafka + S3 + UoW is exercised by ``tests/integration`` (out of scope for
the L-4b unit ring per BP-590 risk profile).
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from market_data.infrastructure.messaging.consumers.insider_transactions_consumer import (
    _coerce_date,
    _coerce_decimal,
    _coerce_transaction_type,
    _compute_net_value,
)

pytestmark = pytest.mark.unit

# ── _coerce_transaction_type ───────────────────────────────────────────────


def test_coerce_transaction_type_eodhd_codes() -> None:
    """EODHD ships single-letter codes P/S/G → BUY/SELL/GIFT (CHECK vocab)."""
    assert _coerce_transaction_type("P") == "BUY"
    assert _coerce_transaction_type("S") == "SELL"
    assert _coerce_transaction_type("G") == "GIFT"


def test_coerce_transaction_type_full_words() -> None:
    """Long-form codes (defensive — some providers send them lowercase)."""
    assert _coerce_transaction_type("buy") == "BUY"
    assert _coerce_transaction_type(" SELL ") == "SELL"
    assert _coerce_transaction_type("Gift") == "GIFT"


def test_coerce_transaction_type_unknown_falls_back_to_other() -> None:
    """Unknown codes collapse to OTHER — the CHECK constraint admits 4 values."""
    assert _coerce_transaction_type("X") == "OTHER"
    assert _coerce_transaction_type("") == "OTHER"
    assert _coerce_transaction_type(None) == "OTHER"  # type: ignore[arg-type]
    assert _coerce_transaction_type(42) == "OTHER"  # type: ignore[arg-type]


# ── _coerce_decimal ────────────────────────────────────────────────────────


def test_coerce_decimal_happy_paths() -> None:
    assert _coerce_decimal("123.45") == Decimal("123.45")
    assert _coerce_decimal(100) == Decimal("100")
    assert _coerce_decimal(1.5) == Decimal("1.5")


def test_coerce_decimal_nullish_inputs_return_none() -> None:
    """Empty string / None / unparseable garbage → None, not exception."""
    assert _coerce_decimal(None) is None
    assert _coerce_decimal("") is None
    assert _coerce_decimal("not-a-number") is None
    assert _coerce_decimal([1, 2]) is None  # type: ignore[arg-type]


# ── _coerce_date ───────────────────────────────────────────────────────────


def test_coerce_date_iso_string() -> None:
    """ISO-8601 date strings parse correctly; tolerates trailing time."""
    from datetime import date

    assert _coerce_date("2026-01-15") == date(2026, 1, 15)
    # EODHD sometimes sends YYYY-MM-DD HH:MM:SS — we take the date prefix.
    assert _coerce_date("2026-01-15T09:30:00") == date(2026, 1, 15)


def test_coerce_date_invalid_returns_none() -> None:
    assert _coerce_date(None) is None
    assert _coerce_date("") is None
    assert _coerce_date("not-a-date") is None
    assert _coerce_date(20260115) is None  # type: ignore[arg-type]


# ── _compute_net_value ─────────────────────────────────────────────────────


def test_compute_net_value_buy_is_positive() -> None:
    net = _compute_net_value(
        shares=Decimal("100"),
        price_per_share=Decimal("150.25"),
        transaction_type="BUY",
    )
    assert net == Decimal("15025.00")


def test_compute_net_value_sell_is_negative() -> None:
    net = _compute_net_value(
        shares=Decimal("100"),
        price_per_share=Decimal("150.00"),
        transaction_type="SELL",
    )
    assert net == Decimal("-15000.00")


def test_compute_net_value_gift_is_negative() -> None:
    """GIFT mirrors SELL — insider disposes of shares without cash inflow."""
    net = _compute_net_value(
        shares=Decimal("50"),
        price_per_share=Decimal("100.00"),
        transaction_type="GIFT",
    )
    assert net == Decimal("-5000.00")


def test_compute_net_value_other_keeps_positive_sign() -> None:
    """OTHER transactions are direction-ambiguous → keep raw positive value."""
    net = _compute_net_value(
        shares=Decimal("10"),
        price_per_share=Decimal("200.00"),
        transaction_type="OTHER",
    )
    assert net == Decimal("2000.00")


@pytest.mark.parametrize(
    ("shares", "price"),
    [
        (None, Decimal("100")),
        (Decimal("100"), None),
        (None, None),
    ],
)
def test_compute_net_value_returns_none_when_either_factor_missing(
    shares: Decimal | None,
    price: Decimal | None,
) -> None:
    """Missing factors → None so the rollup SUM correctly excludes the row.

    Storing 0 would silently inflate the denominator (treating "no price
    data" as "zero-value transaction"). NULL preserves the data-loss
    boundary the rollup respects via WHERE net_value_usd IS NOT NULL.
    """
    net = _compute_net_value(shares=shares, price_per_share=price, transaction_type="BUY")
    assert net is None
