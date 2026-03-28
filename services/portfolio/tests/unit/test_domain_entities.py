"""Unit tests for Portfolio domain entities."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from portfolio.domain.entities import Holding, InstrumentRef, Portfolio, Tenant, Transaction, User
from portfolio.domain.enums import (
    PortfolioStatus,
    TenantStatus,
    TransactionDirection,
    TransactionType,
    UserStatus,
)
from portfolio.domain.errors import InsufficientHoldingsError, PortfolioArchivedError

pytestmark = pytest.mark.unit

# ── Tenant ────────────────────────────────────────────────────────────────────


class TestTenant:
    def test_default_status_is_active(self) -> None:
        tenant = Tenant(name="Acme Corp")
        assert tenant.status == TenantStatus.ACTIVE

    def test_is_active_returns_true_for_active(self) -> None:
        tenant = Tenant(name="Acme Corp")
        assert tenant.is_active() is True

    def test_is_active_returns_false_for_suspended(self) -> None:
        tenant = Tenant(name="Acme Corp", status=TenantStatus.SUSPENDED)
        assert tenant.is_active() is False

    def test_is_active_returns_false_for_deleted(self) -> None:
        tenant = Tenant(name="Acme Corp", status=TenantStatus.DELETED)
        assert tenant.is_active() is False

    def test_id_is_auto_generated(self) -> None:
        t1 = Tenant(name="A")
        t2 = Tenant(name="B")
        assert t1.id != t2.id

    def test_created_at_is_set(self) -> None:
        tenant = Tenant(name="Acme Corp")
        assert isinstance(tenant.created_at, datetime)


# ── User ──────────────────────────────────────────────────────────────────────


class TestUser:
    def _make_user(self, **kwargs: object) -> User:
        tenant_id = uuid.uuid4()
        return User(tenant_id=tenant_id, email="user@example.com", **kwargs)  # type: ignore[arg-type]

    def test_correct_fields(self) -> None:
        tenant_id = uuid.uuid4()
        user = User(tenant_id=tenant_id, email="test@example.com")
        assert user.tenant_id == tenant_id
        assert user.email == "test@example.com"
        assert user.status == UserStatus.ACTIVE

    def test_is_active_returns_true_for_active(self) -> None:
        user = self._make_user()
        assert user.is_active() is True

    def test_is_active_returns_false_for_inactive(self) -> None:
        user = self._make_user(status=UserStatus.INACTIVE)
        assert user.is_active() is False

    def test_is_active_returns_false_for_deleted(self) -> None:
        user = self._make_user(status=UserStatus.DELETED)
        assert user.is_active() is False

    def test_id_is_auto_generated(self) -> None:
        tenant_id = uuid.uuid4()
        u1 = User(tenant_id=tenant_id, email="a@a.com")
        u2 = User(tenant_id=tenant_id, email="b@b.com")
        assert u1.id != u2.id


# ── Portfolio ─────────────────────────────────────────────────────────────────


class TestPortfolio:
    def _make_portfolio(self, **kwargs: object) -> Portfolio:
        tenant_id = uuid.uuid4()
        owner_id = uuid.uuid4()
        return Portfolio(tenant_id=tenant_id, owner_id=owner_id, name="My Portfolio", **kwargs)  # type: ignore[arg-type]

    def test_owner_id_field_exists(self) -> None:
        owner_id = uuid.uuid4()
        portfolio = Portfolio(tenant_id=uuid.uuid4(), owner_id=owner_id, name="P")
        assert portfolio.owner_id == owner_id

    def test_is_active_for_active_portfolio(self) -> None:
        portfolio = self._make_portfolio()
        assert portfolio.is_active() is True

    def test_is_active_returns_false_for_archived(self) -> None:
        portfolio = self._make_portfolio(status=PortfolioStatus.ARCHIVED)
        assert portfolio.is_active() is False

    def test_rename_changes_name(self) -> None:
        portfolio = self._make_portfolio()
        portfolio.rename("New Name")
        assert portfolio.name == "New Name"

    def test_rename_raises_on_archived_portfolio(self) -> None:
        portfolio = self._make_portfolio()
        portfolio.archive()
        with pytest.raises(PortfolioArchivedError):
            portfolio.rename("Should Fail")

    def test_archive_sets_status_to_archived(self) -> None:
        portfolio = self._make_portfolio()
        portfolio.archive()
        assert portfolio.status == PortfolioStatus.ARCHIVED

    def test_default_currency_is_usd(self) -> None:
        portfolio = self._make_portfolio()
        assert portfolio.currency == "USD"


# ── Transaction ───────────────────────────────────────────────────────────────


class TestTransaction:
    def _make_transaction(self, **kwargs: object) -> Transaction:
        defaults: dict[str, object] = {
            "tenant_id": uuid.uuid4(),
            "portfolio_id": uuid.uuid4(),
            "instrument_id": uuid.uuid4(),
            "transaction_type": TransactionType.BUY,
            "direction": TransactionDirection.INFLOW,
            "quantity": Decimal("10"),
            "price": Decimal("100"),
            "currency": "USD",
            "executed_at": datetime.now(tz=UTC),
            "fees": Decimal("5"),
        }
        defaults.update(kwargs)
        return Transaction(**defaults)  # type: ignore[arg-type]

    def test_gross_amount_is_quantity_times_price(self) -> None:
        txn = self._make_transaction(quantity=Decimal("10"), price=Decimal("100"))
        assert txn.gross_amount() == Decimal("1000")

    def test_gross_amount_does_not_include_fees(self) -> None:
        txn = self._make_transaction(quantity=Decimal("5"), price=Decimal("200"), fees=Decimal("50"))
        assert txn.gross_amount() == Decimal("1000")

    def test_net_amount_inflow_adds_fees(self) -> None:
        txn = self._make_transaction(
            direction=TransactionDirection.INFLOW,
            quantity=Decimal("10"),
            price=Decimal("100"),
            fees=Decimal("5"),
        )
        # INFLOW: gross + fees = 1000 + 5 = 1005
        assert txn.net_amount() == Decimal("1005")

    def test_net_amount_outflow_subtracts_fees(self) -> None:
        txn = self._make_transaction(
            direction=TransactionDirection.OUTFLOW,
            quantity=Decimal("10"),
            price=Decimal("100"),
            fees=Decimal("5"),
        )
        # OUTFLOW: gross - fees = 1000 - 5 = 995
        assert txn.net_amount() == Decimal("995")

    def test_net_amount_with_zero_fees(self) -> None:
        txn = self._make_transaction(
            direction=TransactionDirection.INFLOW,
            quantity=Decimal("10"),
            price=Decimal("100"),
            fees=Decimal("0"),
        )
        assert txn.net_amount() == txn.gross_amount()


# ── Holding ───────────────────────────────────────────────────────────────────


class TestHolding:
    def _make_holding(self, quantity: str = "0", average_cost: str = "0") -> Holding:
        return Holding(
            portfolio_id=uuid.uuid4(),
            instrument_id=uuid.uuid4(),
            currency="USD",
            quantity=Decimal(quantity),
            average_cost=Decimal(average_cost),
        )

    def test_apply_delta_buy_increases_quantity(self) -> None:
        holding = self._make_holding(quantity="10", average_cost="100")
        holding.apply_delta(Decimal("5"), Decimal("100"))
        assert holding.quantity == Decimal("15")

    def test_apply_delta_buy_updates_weighted_average_cost(self) -> None:
        holding = self._make_holding(quantity="10", average_cost="100")
        # Buy 10 more at 200: weighted avg = (10*100 + 10*200) / 20 = 150
        holding.apply_delta(Decimal("10"), Decimal("200"))
        assert holding.average_cost == Decimal("150")

    def test_apply_delta_sell_decreases_quantity(self) -> None:
        holding = self._make_holding(quantity="10", average_cost="100")
        holding.apply_delta(Decimal("-3"), Decimal("120"))
        assert holding.quantity == Decimal("7")

    def test_apply_delta_sell_preserves_average_cost(self) -> None:
        holding = self._make_holding(quantity="10", average_cost="100")
        holding.apply_delta(Decimal("-3"), Decimal("120"))
        assert holding.average_cost == Decimal("100")

    def test_apply_delta_negative_exceeding_quantity_raises(self) -> None:
        holding = self._make_holding(quantity="5", average_cost="100")
        with pytest.raises(InsufficientHoldingsError):
            holding.apply_delta(Decimal("-10"), Decimal("100"))

    def test_apply_delta_sell_to_zero_sets_average_cost_to_zero(self) -> None:
        holding = self._make_holding(quantity="10", average_cost="100")
        holding.apply_delta(Decimal("-10"), Decimal("100"))
        assert holding.quantity == Decimal("0")
        assert holding.average_cost == Decimal("0")

    def test_buy_from_zero(self) -> None:
        holding = self._make_holding(quantity="0", average_cost="0")
        holding.apply_delta(Decimal("5"), Decimal("200"))
        assert holding.quantity == Decimal("5")
        assert holding.average_cost == Decimal("200")


# ── InstrumentRef ──────────────────────────────────────────────────────────────


class TestInstrumentRef:
    def test_source_event_id_field_exists(self) -> None:
        source_event_id = uuid.uuid4()
        instrument = InstrumentRef(
            symbol="AAPL",
            exchange="NASDAQ",
            source_event_id=source_event_id,
        )
        assert instrument.source_event_id == source_event_id

    def test_source_event_id_is_accessible(self) -> None:
        event_id = uuid.uuid4()
        instrument = InstrumentRef(symbol="TSLA", exchange="NYSE", source_event_id=event_id)
        assert instrument.source_event_id is event_id

    def test_optional_fields_default_to_none(self) -> None:
        instrument = InstrumentRef(symbol="MSFT", exchange="NASDAQ", source_event_id=uuid.uuid4())
        assert instrument.name is None
        assert instrument.currency is None
        assert instrument.asset_class is None

    def test_id_auto_generated(self) -> None:
        i1 = InstrumentRef(symbol="A", exchange="B", source_event_id=uuid.uuid4())
        i2 = InstrumentRef(symbol="A", exchange="B", source_event_id=uuid.uuid4())
        assert i1.id != i2.id

    def test_entity_id_can_be_set(self) -> None:
        entity_id = uuid.uuid4()
        instrument = InstrumentRef(symbol="AAPL", exchange="NASDAQ", source_event_id=uuid.uuid4(), entity_id=entity_id)
        assert instrument.entity_id == entity_id

    def test_synced_at_is_set(self) -> None:
        instrument = InstrumentRef(symbol="AAPL", exchange="NASDAQ", source_event_id=uuid.uuid4())
        assert isinstance(instrument.synced_at, datetime)


# ── Transaction extra coverage ────────────────────────────────────────────────


class TestTransactionExtra:
    def test_external_ref_defaults_to_none(self) -> None:
        txn = Transaction(
            tenant_id=uuid.uuid4(),
            portfolio_id=uuid.uuid4(),
            instrument_id=uuid.uuid4(),
            transaction_type=TransactionType.BUY,
            direction=TransactionDirection.INFLOW,
            quantity=Decimal("1"),
            price=Decimal("100"),
            currency="USD",
            executed_at=datetime.now(tz=UTC),
        )
        assert txn.external_ref is None

    def test_id_auto_generated(self) -> None:
        def _make() -> Transaction:
            return Transaction(
                tenant_id=uuid.uuid4(),
                portfolio_id=uuid.uuid4(),
                instrument_id=uuid.uuid4(),
                transaction_type=TransactionType.BUY,
                direction=TransactionDirection.INFLOW,
                quantity=Decimal("1"),
                price=Decimal("100"),
                currency="USD",
                executed_at=datetime.now(tz=UTC),
            )

        assert _make().id != _make().id
