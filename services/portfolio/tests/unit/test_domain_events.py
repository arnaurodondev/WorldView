"""Unit tests for Portfolio domain events."""

from __future__ import annotations

import dataclasses
import uuid

from portfolio.domain.events import (
    DomainEvent,
    HoldingChanged,
    InstrumentRefCreated,
    PortfolioArchived,
    PortfolioCreated,
    PortfolioRenamed,
    TenantCreated,
    TenantStatusChanged,
    TransactionRecorded,
    UserCreated,
    UserStatusChanged,
)

# ── Instantiation ─────────────────────────────────────────────────────────────


class TestEventInstantiation:
    def test_tenant_created_instantiation(self) -> None:
        tenant_id = uuid.uuid4()
        event = TenantCreated(tenant_id=tenant_id, tenant_name="Acme")
        assert event.tenant_id == tenant_id
        assert event.tenant_name == "Acme"

    def test_tenant_status_changed_instantiation(self) -> None:
        tenant_id = uuid.uuid4()
        event = TenantStatusChanged(tenant_id=tenant_id, old_status="active", new_status="suspended")
        assert event.old_status == "active"
        assert event.new_status == "suspended"

    def test_user_created_instantiation(self) -> None:
        tenant_id = uuid.uuid4()
        user_id = uuid.uuid4()
        event = UserCreated(tenant_id=tenant_id, user_id=user_id, email="u@example.com")
        assert event.email == "u@example.com"

    def test_user_status_changed_instantiation(self) -> None:
        tenant_id = uuid.uuid4()
        event = UserStatusChanged(tenant_id=tenant_id, old_status="active", new_status="inactive")
        assert event.old_status == "active"

    def test_portfolio_created_instantiation(self) -> None:
        tenant_id = uuid.uuid4()
        portfolio_id = uuid.uuid4()
        owner_id = uuid.uuid4()
        event = PortfolioCreated(
            tenant_id=tenant_id,
            portfolio_id=portfolio_id,
            owner_id=owner_id,
            name="Growth",
            currency="USD",
        )
        assert event.name == "Growth"
        assert event.currency == "USD"

    def test_portfolio_renamed_instantiation(self) -> None:
        tenant_id = uuid.uuid4()
        event = PortfolioRenamed(tenant_id=tenant_id, old_name="Old", new_name="New")
        assert event.new_name == "New"

    def test_portfolio_archived_instantiation(self) -> None:
        tenant_id = uuid.uuid4()
        event = PortfolioArchived(tenant_id=tenant_id)
        assert event.tenant_id == tenant_id

    def test_transaction_recorded_instantiation(self) -> None:
        tenant_id = uuid.uuid4()
        event = TransactionRecorded(
            tenant_id=tenant_id,
            transaction_type="BUY",
            direction="INFLOW",
        )
        assert event.transaction_type == "BUY"

    def test_holding_changed_instantiation(self) -> None:
        tenant_id = uuid.uuid4()
        event = HoldingChanged(tenant_id=tenant_id, quantity="10", average_cost="100")
        assert event.quantity == "10"

    def test_instrument_ref_created_instantiation(self) -> None:
        tenant_id = uuid.uuid4()
        event = InstrumentRefCreated(
            tenant_id=tenant_id,
            symbol="AAPL",
            exchange="NASDAQ",
            name="Apple Inc.",
            asset_class="EQUITY",
            currency="USD",
        )
        assert event.symbol == "AAPL"
        assert event.exchange == "NASDAQ"


# ── aggregate_id ──────────────────────────────────────────────────────────────


class TestAggregateId:
    def test_tenant_created_aggregate_id_is_tenant_id(self) -> None:
        tenant_id = uuid.uuid4()
        event = TenantCreated(tenant_id=tenant_id)
        assert event.aggregate_id == tenant_id

    def test_tenant_status_changed_aggregate_id_is_tenant_id(self) -> None:
        tenant_id = uuid.uuid4()
        event = TenantStatusChanged(tenant_id=tenant_id)
        assert event.aggregate_id == tenant_id

    def test_user_created_aggregate_id_is_user_id(self) -> None:
        tenant_id = uuid.uuid4()
        user_id = uuid.uuid4()
        event = UserCreated(tenant_id=tenant_id, user_id=user_id)
        assert event.aggregate_id == user_id

    def test_user_status_changed_aggregate_id_is_user_id(self) -> None:
        tenant_id = uuid.uuid4()
        user_id = uuid.uuid4()
        event = UserStatusChanged(tenant_id=tenant_id, user_id=user_id)
        assert event.aggregate_id == user_id

    def test_portfolio_created_aggregate_id_is_portfolio_id(self) -> None:
        tenant_id = uuid.uuid4()
        portfolio_id = uuid.uuid4()
        event = PortfolioCreated(tenant_id=tenant_id, portfolio_id=portfolio_id)
        assert event.aggregate_id == portfolio_id

    def test_portfolio_renamed_aggregate_id_is_portfolio_id(self) -> None:
        tenant_id = uuid.uuid4()
        portfolio_id = uuid.uuid4()
        event = PortfolioRenamed(tenant_id=tenant_id, portfolio_id=portfolio_id)
        assert event.aggregate_id == portfolio_id

    def test_portfolio_archived_aggregate_id_is_portfolio_id(self) -> None:
        tenant_id = uuid.uuid4()
        portfolio_id = uuid.uuid4()
        event = PortfolioArchived(tenant_id=tenant_id, portfolio_id=portfolio_id)
        assert event.aggregate_id == portfolio_id

    def test_transaction_recorded_aggregate_id_is_transaction_id(self) -> None:
        tenant_id = uuid.uuid4()
        transaction_id = uuid.uuid4()
        event = TransactionRecorded(tenant_id=tenant_id, transaction_id=transaction_id)
        assert event.aggregate_id == transaction_id

    def test_holding_changed_aggregate_id_is_holding_id(self) -> None:
        tenant_id = uuid.uuid4()
        holding_id = uuid.uuid4()
        event = HoldingChanged(tenant_id=tenant_id, holding_id=holding_id)
        assert event.aggregate_id == holding_id

    def test_instrument_ref_created_aggregate_id_is_instrument_id(self) -> None:
        tenant_id = uuid.uuid4()
        instrument_id = uuid.uuid4()
        event = InstrumentRefCreated(tenant_id=tenant_id, instrument_id=instrument_id)
        assert event.aggregate_id == instrument_id


# ── schema_version ────────────────────────────────────────────────────────────


class TestSchemaVersion:
    def test_schema_version_defaults_to_1(self) -> None:
        event = TenantCreated(tenant_id=uuid.uuid4())
        assert event.schema_version == 1

    def test_schema_version_default_on_all_event_types(self) -> None:
        tenant_id = uuid.uuid4()
        events: list[DomainEvent] = [
            TenantCreated(tenant_id=tenant_id),
            TenantStatusChanged(tenant_id=tenant_id),
            UserCreated(tenant_id=tenant_id),
            UserStatusChanged(tenant_id=tenant_id),
            PortfolioCreated(tenant_id=tenant_id),
            PortfolioRenamed(tenant_id=tenant_id),
            PortfolioArchived(tenant_id=tenant_id),
            TransactionRecorded(tenant_id=tenant_id),
            HoldingChanged(tenant_id=tenant_id),
            InstrumentRefCreated(tenant_id=tenant_id),
        ]
        for event in events:
            assert event.schema_version == 1, f"Expected schema_version=1 on {type(event).__name__}"


# ── Dataclass characteristics ─────────────────────────────────────────────────


class TestDataclassCharacteristics:
    def test_events_are_dataclasses(self) -> None:
        event_classes = [
            TenantCreated,
            TenantStatusChanged,
            UserCreated,
            UserStatusChanged,
            PortfolioCreated,
            PortfolioRenamed,
            PortfolioArchived,
            TransactionRecorded,
            HoldingChanged,
            InstrumentRefCreated,
        ]
        for cls in event_classes:
            assert dataclasses.is_dataclass(cls), f"{cls.__name__} must be a dataclass"

    def test_events_are_not_frozen(self) -> None:
        """Events are mutable dataclasses (not frozen)."""
        event = TenantCreated(tenant_id=uuid.uuid4(), tenant_name="Original")
        # Should not raise — events are mutable
        event.tenant_name = "Modified"
        assert event.tenant_name == "Modified"

    def test_event_id_is_auto_generated(self) -> None:
        # D-009: event_id is a UUIDv7 hex string for Avro portability.
        e1 = TenantCreated(tenant_id=uuid.uuid4())
        e2 = TenantCreated(tenant_id=uuid.uuid4())
        assert e1.event_id != e2.event_id
        assert isinstance(e1.event_id, str)

    def test_occurred_at_is_set(self) -> None:
        # D-009: occurred_at is a string (ISO-8601 with Z suffix) for Avro portability.
        event = TenantCreated(tenant_id=uuid.uuid4())
        assert isinstance(event.occurred_at, str)
        assert event.occurred_at.endswith("Z")


# ── InstrumentRefCreated specific fields ──────────────────────────────────────


class TestInstrumentRefCreatedFields:
    def test_has_symbol_field(self) -> None:
        event = InstrumentRefCreated(tenant_id=uuid.uuid4(), symbol="AAPL")
        assert event.symbol == "AAPL"

    def test_has_exchange_field(self) -> None:
        event = InstrumentRefCreated(tenant_id=uuid.uuid4(), exchange="NYSE")
        assert event.exchange == "NYSE"

    def test_has_name_field(self) -> None:
        event = InstrumentRefCreated(tenant_id=uuid.uuid4(), name="Apple Inc.")
        assert event.name == "Apple Inc."

    def test_has_asset_class_field(self) -> None:
        event = InstrumentRefCreated(tenant_id=uuid.uuid4(), asset_class="EQUITY")
        assert event.asset_class == "EQUITY"

    def test_has_currency_field(self) -> None:
        event = InstrumentRefCreated(tenant_id=uuid.uuid4(), currency="USD")
        assert event.currency == "USD"

    def test_optional_fields_default_to_none(self) -> None:
        event = InstrumentRefCreated(tenant_id=uuid.uuid4())
        assert event.name is None
        assert event.asset_class is None
        assert event.currency is None


# ── PortfolioCreated specific fields ──────────────────────────────────────────


class TestPortfolioCreatedFields:
    def test_has_owner_id_field(self) -> None:
        owner_id = uuid.uuid4()
        event = PortfolioCreated(tenant_id=uuid.uuid4(), owner_id=owner_id)
        assert event.owner_id == owner_id

    def test_has_portfolio_id_field(self) -> None:
        portfolio_id = uuid.uuid4()
        event = PortfolioCreated(tenant_id=uuid.uuid4(), portfolio_id=portfolio_id)
        assert event.portfolio_id == portfolio_id

    def test_has_name_field(self) -> None:
        event = PortfolioCreated(tenant_id=uuid.uuid4(), name="My Portfolio")
        assert event.name == "My Portfolio"

    def test_has_currency_field(self) -> None:
        event = PortfolioCreated(tenant_id=uuid.uuid4(), currency="EUR")
        assert event.currency == "EUR"

    def test_currency_defaults_to_usd(self) -> None:
        event = PortfolioCreated(tenant_id=uuid.uuid4())
        assert event.currency == "USD"


# ── EVENT_TYPE and AGGREGATE_TYPE class vars ──────────────────────────────────


class TestEventTypeConstants:
    def test_tenant_created_event_type(self) -> None:
        assert TenantCreated.EVENT_TYPE == "tenant.created"
        assert TenantCreated.AGGREGATE_TYPE == "tenant"

    def test_tenant_status_changed_event_type(self) -> None:
        assert TenantStatusChanged.EVENT_TYPE == "tenant.status_changed"
        assert TenantStatusChanged.AGGREGATE_TYPE == "tenant"

    def test_user_created_event_type(self) -> None:
        assert UserCreated.EVENT_TYPE == "user.created"
        assert UserCreated.AGGREGATE_TYPE == "user"

    def test_user_status_changed_event_type(self) -> None:
        assert UserStatusChanged.EVENT_TYPE == "user.status_changed"
        assert UserStatusChanged.AGGREGATE_TYPE == "user"

    def test_portfolio_created_event_type(self) -> None:
        assert PortfolioCreated.EVENT_TYPE == "portfolio.created"
        assert PortfolioCreated.AGGREGATE_TYPE == "portfolio"

    def test_portfolio_renamed_event_type(self) -> None:
        assert PortfolioRenamed.EVENT_TYPE == "portfolio.renamed"
        assert PortfolioRenamed.AGGREGATE_TYPE == "portfolio"

    def test_portfolio_archived_event_type(self) -> None:
        assert PortfolioArchived.EVENT_TYPE == "portfolio.archived"
        assert PortfolioArchived.AGGREGATE_TYPE == "portfolio"

    def test_transaction_recorded_event_type(self) -> None:
        assert TransactionRecorded.EVENT_TYPE == "transaction.recorded"
        assert TransactionRecorded.AGGREGATE_TYPE == "transaction"

    def test_holding_changed_event_type(self) -> None:
        assert HoldingChanged.EVENT_TYPE == "holding.changed"
        assert HoldingChanged.AGGREGATE_TYPE == "holding"

    def test_instrument_ref_created_event_type(self) -> None:
        assert InstrumentRefCreated.EVENT_TYPE == "instrument_ref.created"
        assert InstrumentRefCreated.AGGREGATE_TYPE == "instrument"
