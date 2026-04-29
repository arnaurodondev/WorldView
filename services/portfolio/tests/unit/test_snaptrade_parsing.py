"""Unit tests for SnapTrade adapter parsing of amount/fee + positions snapshot.

PLAN-0046 Wave 1 — covers BP-263 (dropped amount/fee) and BP-264 (snapshot path).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from portfolio.application.ports.brokerage_client import SnapTradePosition
from portfolio.infrastructure.brokerage.snaptrade_client import SnapTradeClient

pytestmark = pytest.mark.unit


# ── Test fixtures ─────────────────────────────────────────────────────────────


def _make_client_without_init() -> SnapTradeClient:
    """Build a SnapTradeClient without calling __init__ — we only test pure parsers."""
    return SnapTradeClient.__new__(SnapTradeClient)


def _activity(
    *,
    activity_id: str = "act-1",
    activity_type: str = "BUY",
    symbol: str = "AAPL",
    units: float | None = 10,
    price: float | None = 150.0,
    amount: float | None = None,
    fee: float | None = None,
    currency: str = "USD",
    trade_date: str = "2026-04-28",
) -> dict[str, Any]:
    """Build a SnapTrade-shaped activity dict for parsing tests."""
    return {
        "id": activity_id,
        "type": activity_type,
        "symbol": {"symbol": symbol},
        "units": units,
        "price": price,
        "amount": amount,
        "fee": fee,
        "currency": {"code": currency},
        "trade_date": trade_date,
        "institution": "Fake Brokerage",
    }


# ── _parse_activity_list (BP-263) ─────────────────────────────────────────────


class TestParseActivityList:
    """The adapter MUST capture amount + fee from UniversalActivity (BP-263)."""

    def test_dividend_amount_captured(self) -> None:
        # SnapTrade encodes dividends as units≈0, price≈0, amount=<cash>
        client = _make_client_without_init()
        items = [_activity(activity_type="DIVIDEND", units=0, price=0, amount=12.34, fee=None)]

        activities = client._parse_activity_list(items)

        assert len(activities) == 1
        assert activities[0].activity_type == "DIVIDEND"
        # The crucial assertion — without BP-263 fix, this is None.
        assert activities[0].amount == Decimal("12.34")
        assert activities[0].fee is None

    def test_buy_with_fee_captured(self) -> None:
        client = _make_client_without_init()
        items = [_activity(activity_type="BUY", units=10, price=150.0, amount=1500.0, fee=0.99)]

        activities = client._parse_activity_list(items)

        assert activities[0].fee == Decimal("0.99")
        assert activities[0].amount == Decimal("1500.0")

    def test_missing_amount_and_fee_yield_none(self) -> None:
        # Defensive: brokers may omit amount/fee on rows where they are not
        # applicable. The parser should NOT crash and should produce None.
        client = _make_client_without_init()
        items = [_activity(amount=None, fee=None)]

        activities = client._parse_activity_list(items)

        assert activities[0].amount is None
        assert activities[0].fee is None

    def test_empty_string_amount_yields_none(self) -> None:
        # Some SDK serializers emit "" for absent decimals — handle gracefully.
        client = _make_client_without_init()
        items = [_activity(amount="")]  # type: ignore[arg-type]

        activities = client._parse_activity_list(items)

        assert activities[0].amount is None

    # ── PLAN-0051 / T-A-1-06 — F-P-010 ───────────────────────────────────────

    def test_dividend_missing_amount_emits_warning(self) -> None:
        """A DIVIDEND row with no ``amount`` MUST emit a structured warning.

        The row is still persisted (so we don't silently drop data) but
        operators get a stable log signal — ``snaptrade_dividend_missing_amount``
        — to triage missing dividend payouts surfaced through SnapTrade.
        """
        from structlog.testing import capture_logs

        client = _make_client_without_init()
        items = [_activity(activity_type="DIVIDEND", units=0, price=0, amount=None)]

        with capture_logs() as cap:
            activities = client._parse_activity_list(items)

        # Activity is still persisted (visibility, not data loss).
        assert len(activities) == 1
        # Exactly one warning, with the expected event name + identifying
        # fields so log-search can pivot on snaptrade_transaction_id.
        warnings = [r for r in cap if r.get("event") == "snaptrade_dividend_missing_amount"]
        assert len(warnings) == 1
        assert warnings[0]["snaptrade_transaction_id"] == "act-1"
        assert warnings[0]["symbol"] == "AAPL"
        # ``log_level`` is added by structlog's testing capture; match on the
        # canonical "warning" string so the assertion survives stdlib changes.
        assert warnings[0]["log_level"] == "warning"

    def test_dividend_zero_amount_emits_warning(self) -> None:
        """Amount==0 is functionally indistinguishable from missing — warn."""
        from structlog.testing import capture_logs

        client = _make_client_without_init()
        items = [_activity(activity_type="DIVIDEND", units=0, price=0, amount=0)]

        with capture_logs() as cap:
            client._parse_activity_list(items)

        events = [r["event"] for r in cap]
        assert "snaptrade_dividend_missing_amount" in events

    def test_div_alias_emits_warning(self) -> None:
        """The brokerage may shorten the type to ``DIV`` — same warning."""
        from structlog.testing import capture_logs

        client = _make_client_without_init()
        items = [_activity(activity_type="DIV", units=0, price=0, amount=None)]

        with capture_logs() as cap:
            client._parse_activity_list(items)

        events = [r["event"] for r in cap]
        assert "snaptrade_dividend_missing_amount" in events

    def test_dividend_with_positive_amount_does_not_warn(self) -> None:
        """Happy path: a populated dividend amount must NOT warn."""
        from structlog.testing import capture_logs

        client = _make_client_without_init()
        items = [_activity(activity_type="DIVIDEND", units=0, price=0, amount=5.25)]

        with capture_logs() as cap:
            activities = client._parse_activity_list(items)

        events = [r.get("event") for r in cap]
        assert "snaptrade_dividend_missing_amount" not in events
        assert activities[0].amount == Decimal("5.25")

    def test_buy_with_missing_amount_does_not_warn(self) -> None:
        """The dividend warning is scoped — a BUY with no amount stays quiet."""
        from structlog.testing import capture_logs

        client = _make_client_without_init()
        items = [_activity(activity_type="BUY", units=10, price=150, amount=None)]

        with capture_logs() as cap:
            client._parse_activity_list(items)

        events = [r.get("event") for r in cap]
        assert "snaptrade_dividend_missing_amount" not in events


# ── get_account_positions parsing (BP-264) ────────────────────────────────────


class _FakeResult:
    """Stand-in for the SDK's ApiResponse — exposes a ``body`` list."""

    def __init__(self, body: list[Any]) -> None:
        self.body = body


def _position(
    *,
    symbol: str = "AAPL",
    units: float = 10,
    avg: float | None = 150.0,
    currency: str = "USD",
) -> dict[str, Any]:
    """SnapTrade position structure: position.symbol.symbol.symbol = ticker."""
    return {
        "symbol": {
            "symbol": {
                "symbol": symbol,
                "currency": {"code": currency},
            },
        },
        "units": units,
        "average_purchase_price": avg,
    }


class TestGetAccountPositions:
    @pytest.mark.asyncio
    async def test_returns_position_list_with_quantity_and_avg(self) -> None:
        client = _make_client_without_init()
        # Stub the SDK call — use a sync-callable returning a FakeResult; the
        # adapter dispatches via run_in_executor.

        class _Stub:
            def get_user_account_positions(self, **_kwargs: Any) -> _FakeResult:
                return _FakeResult([_position(symbol="AAPL", units=10, avg=150.0)])

        client._account_info = _Stub()  # type: ignore[attr-defined]
        from portfolio.application.ports.brokerage_client import SnapTradeUser

        positions = await client.get_account_positions(
            SnapTradeUser(snaptrade_user_id="u", snaptrade_user_secret="s"),
            account_id="acc-1",
        )

        assert len(positions) == 1
        assert isinstance(positions[0], SnapTradePosition)
        assert positions[0].symbol == "AAPL"
        assert positions[0].quantity == Decimal(10)
        assert positions[0].average_purchase_price == Decimal("150.0")
        assert positions[0].currency == "USD"
        assert positions[0].account_id == "acc-1"

    @pytest.mark.asyncio
    async def test_zero_quantity_position_included(self) -> None:
        # A closed position (quantity=0) MUST be returned so the upsert use
        # case can delete the corresponding holdings row.
        client = _make_client_without_init()

        class _Stub:
            def get_user_account_positions(self, **_kwargs: Any) -> _FakeResult:
                return _FakeResult([_position(symbol="MSFT", units=0, avg=None)])

        client._account_info = _Stub()  # type: ignore[attr-defined]
        from portfolio.application.ports.brokerage_client import SnapTradeUser

        positions = await client.get_account_positions(
            SnapTradeUser(snaptrade_user_id="u", snaptrade_user_secret="s"),
            account_id="acc-1",
        )

        assert len(positions) == 1
        assert positions[0].quantity == Decimal(0)
        assert positions[0].average_purchase_price is None

    @pytest.mark.asyncio
    async def test_missing_symbol_skipped(self) -> None:
        client = _make_client_without_init()

        class _Stub:
            def get_user_account_positions(self, **_kwargs: Any) -> _FakeResult:
                # Both an empty-symbol row and a valid one — only valid is kept.
                return _FakeResult(
                    [
                        {"symbol": {"symbol": {"symbol": "", "currency": {"code": "USD"}}}, "units": 5},
                        _position(symbol="GOOG"),
                    ],
                )

        client._account_info = _Stub()  # type: ignore[attr-defined]
        from portfolio.application.ports.brokerage_client import SnapTradeUser

        positions = await client.get_account_positions(
            SnapTradeUser(snaptrade_user_id="u", snaptrade_user_secret="s"),
            account_id="acc-1",
        )

        assert len(positions) == 1
        assert positions[0].symbol == "GOOG"
