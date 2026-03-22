"""Domain events for the Portfolio service."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, ClassVar

from common.ids import new_uuid  # type: ignore[import-untyped]
from common.time import utc_now  # type: ignore[import-untyped]

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


@dataclass
class DomainEvent(ABC):
    """Base class for all Portfolio domain events.

    Class-level constants per subclass:
    - ``EVENT_TYPE: ClassVar[str]`` — e.g. ``"tenant.created"``
    - ``AGGREGATE_TYPE: ClassVar[str]`` — e.g. ``"tenant"``

    Instance fields: ``tenant_id`` (required), plus defaults for the rest.
    ``schema_version`` defaults to 1 and can be overridden per subclass.
    """

    EVENT_TYPE: ClassVar[str]
    AGGREGATE_TYPE: ClassVar[str]

    tenant_id: UUID
    schema_version: int = 1
    event_id: UUID = field(default_factory=new_uuid)
    occurred_at: datetime = field(default_factory=utc_now)
    correlation_id: str | None = None
    causation_id: str | None = None

    @property
    @abstractmethod
    def aggregate_id(self) -> UUID: ...


# ── Tenant events ──────────────────────────────────────────────────────────────


@dataclass
class TenantCreated(DomainEvent):
    EVENT_TYPE: ClassVar[str] = "tenant.created"
    AGGREGATE_TYPE: ClassVar[str] = "tenant"

    tenant_name: str = ""

    @property
    def aggregate_id(self) -> UUID:
        return self.tenant_id


@dataclass
class TenantStatusChanged(DomainEvent):
    EVENT_TYPE: ClassVar[str] = "tenant.status_changed"
    AGGREGATE_TYPE: ClassVar[str] = "tenant"

    old_status: str = ""
    new_status: str = ""

    @property
    def aggregate_id(self) -> UUID:
        return self.tenant_id


# ── User events ────────────────────────────────────────────────────────────────


@dataclass
class UserCreated(DomainEvent):
    EVENT_TYPE: ClassVar[str] = "user.created"
    AGGREGATE_TYPE: ClassVar[str] = "user"

    user_id: UUID = field(default_factory=new_uuid)
    email: str = ""

    @property
    def aggregate_id(self) -> UUID:
        return self.user_id


@dataclass
class UserStatusChanged(DomainEvent):
    EVENT_TYPE: ClassVar[str] = "user.status_changed"
    AGGREGATE_TYPE: ClassVar[str] = "user"

    user_id: UUID = field(default_factory=new_uuid)
    old_status: str = ""
    new_status: str = ""

    @property
    def aggregate_id(self) -> UUID:
        return self.user_id


# ── Portfolio events ───────────────────────────────────────────────────────────


@dataclass
class PortfolioCreated(DomainEvent):
    EVENT_TYPE: ClassVar[str] = "portfolio.created"
    AGGREGATE_TYPE: ClassVar[str] = "portfolio"

    portfolio_id: UUID = field(default_factory=new_uuid)
    owner_id: UUID = field(default_factory=new_uuid)
    name: str = ""
    currency: str = "USD"

    @property
    def aggregate_id(self) -> UUID:
        return self.portfolio_id


@dataclass
class PortfolioRenamed(DomainEvent):
    EVENT_TYPE: ClassVar[str] = "portfolio.renamed"
    AGGREGATE_TYPE: ClassVar[str] = "portfolio"

    portfolio_id: UUID = field(default_factory=new_uuid)
    old_name: str = ""
    new_name: str = ""

    @property
    def aggregate_id(self) -> UUID:
        return self.portfolio_id


@dataclass
class PortfolioArchived(DomainEvent):
    EVENT_TYPE: ClassVar[str] = "portfolio.archived"
    AGGREGATE_TYPE: ClassVar[str] = "portfolio"

    portfolio_id: UUID = field(default_factory=new_uuid)

    @property
    def aggregate_id(self) -> UUID:
        return self.portfolio_id


# ── Transaction events ─────────────────────────────────────────────────────────


@dataclass
class TransactionRecorded(DomainEvent):
    EVENT_TYPE: ClassVar[str] = "transaction.recorded"
    AGGREGATE_TYPE: ClassVar[str] = "transaction"

    transaction_id: UUID = field(default_factory=new_uuid)
    portfolio_id: UUID = field(default_factory=new_uuid)
    instrument_id: UUID = field(default_factory=new_uuid)
    transaction_type: str = ""
    direction: str = ""
    quantity: str = "0"
    price: str = "0"
    fees: str = "0"
    currency: str = "USD"
    executed_at: str = ""

    @property
    def aggregate_id(self) -> UUID:
        return self.transaction_id


@dataclass
class HoldingChanged(DomainEvent):
    EVENT_TYPE: ClassVar[str] = "holding.changed"
    AGGREGATE_TYPE: ClassVar[str] = "holding"

    holding_id: UUID = field(default_factory=new_uuid)
    portfolio_id: UUID = field(default_factory=new_uuid)
    instrument_id: UUID = field(default_factory=new_uuid)
    quantity: str = "0"
    average_cost: str = "0"
    currency: str = "USD"

    @property
    def aggregate_id(self) -> UUID:
        return self.holding_id


# ── Instrument events ──────────────────────────────────────────────────────────


@dataclass
class InstrumentRefCreated(DomainEvent):
    """Emitted when a new instrument reference is synced from the Market Data service."""

    EVENT_TYPE: ClassVar[str] = "instrument_ref.created"
    AGGREGATE_TYPE: ClassVar[str] = "instrument"

    instrument_id: UUID = field(default_factory=new_uuid)
    symbol: str = ""
    exchange: str = ""
    name: str | None = None
    asset_class: str | None = None
    currency: str | None = None
    entity_id: UUID | None = None

    @property
    def aggregate_id(self) -> UUID:
        return self.instrument_id


# ── Watchlist events ───────────────────────────────────────────────────────────


@dataclass
class WatchlistCreated(DomainEvent):
    EVENT_TYPE: ClassVar[str] = "watchlist.created"
    AGGREGATE_TYPE: ClassVar[str] = "watchlist"

    watchlist_id: UUID = field(default_factory=new_uuid)
    user_id: UUID = field(default_factory=new_uuid)
    name: str = ""

    @property
    def aggregate_id(self) -> UUID:
        return self.watchlist_id


@dataclass
class WatchlistDeleted(DomainEvent):
    EVENT_TYPE: ClassVar[str] = "watchlist.deleted"
    AGGREGATE_TYPE: ClassVar[str] = "watchlist"

    watchlist_id: UUID = field(default_factory=new_uuid)
    user_id: UUID = field(default_factory=new_uuid)

    @property
    def aggregate_id(self) -> UUID:
        return self.watchlist_id


@dataclass
class WatchlistItemAdded(DomainEvent):
    EVENT_TYPE: ClassVar[str] = "watchlist.item_added"
    AGGREGATE_TYPE: ClassVar[str] = "watchlist"

    watchlist_id: UUID = field(default_factory=new_uuid)
    user_id: UUID = field(default_factory=new_uuid)
    entity_id: UUID = field(default_factory=new_uuid)
    entity_type: str = "company"

    @property
    def aggregate_id(self) -> UUID:
        return self.watchlist_id


@dataclass
class WatchlistItemDeleted(DomainEvent):
    EVENT_TYPE: ClassVar[str] = "watchlist.item_deleted"
    AGGREGATE_TYPE: ClassVar[str] = "watchlist"

    watchlist_id: UUID = field(default_factory=new_uuid)
    user_id: UUID = field(default_factory=new_uuid)
    entity_id: UUID = field(default_factory=new_uuid)
    entity_type: str = "company"

    @property
    def aggregate_id(self) -> UUID:
        return self.watchlist_id
