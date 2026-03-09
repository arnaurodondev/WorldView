"""Abstract repository interfaces (ports) for the Portfolio application layer."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from portfolio.domain.entities import Holding, InstrumentRef, Portfolio, Tenant, Transaction, User


@dataclass
class OutboxRecord:
    """DTO for an outbox event record."""

    id: UUID
    tenant_id: UUID | None
    event_type: str
    topic: str
    payload: dict[str, Any]
    status: str
    attempt_count: int
    lease_owner: str | None
    lease_expires: datetime | None

    @property
    def attempts(self) -> int:
        return self.attempt_count

    @property
    def leased_until(self) -> datetime | None:
        return self.lease_expires


@dataclass
class IdempotencyRecord:
    """DTO for a consumer idempotency record."""

    event_id: UUID
    processed_at: datetime


class TenantRepository(ABC):
    @abstractmethod
    async def get(self, tenant_id: UUID) -> Tenant | None: ...

    @abstractmethod
    async def save(self, tenant: Tenant) -> None: ...


class UserRepository(ABC):
    @abstractmethod
    async def get(self, user_id: UUID, tenant_id: UUID) -> User | None: ...

    @abstractmethod
    async def get_by_email(self, email: str, tenant_id: UUID) -> User | None: ...

    @abstractmethod
    async def save(self, user: User) -> None: ...


class PortfolioRepository(ABC):
    @abstractmethod
    async def get(self, portfolio_id: UUID, tenant_id: UUID) -> Portfolio | None: ...

    @abstractmethod
    async def list_by_owner(self, owner_id: UUID, tenant_id: UUID) -> list[Portfolio]: ...

    @abstractmethod
    async def save(self, portfolio: Portfolio) -> None: ...


class InstrumentRepository(ABC):
    @abstractmethod
    async def get(self, instrument_id: UUID) -> InstrumentRef | None: ...

    @abstractmethod
    async def get_by_symbol_exchange(self, symbol: str, exchange: str) -> InstrumentRef | None: ...

    @abstractmethod
    async def list_all(self) -> list[InstrumentRef]: ...

    @abstractmethod
    async def upsert(self, instrument: InstrumentRef) -> None: ...


class TransactionRepository(ABC):
    @abstractmethod
    async def get(self, transaction_id: UUID, tenant_id: UUID) -> Transaction | None: ...

    @abstractmethod
    async def list_by_portfolio(self, portfolio_id: UUID, tenant_id: UUID) -> list[Transaction]: ...

    @abstractmethod
    async def save(self, transaction: Transaction) -> None: ...


class HoldingRepository(ABC):
    @abstractmethod
    async def get(self, portfolio_id: UUID, instrument_id: UUID) -> Holding | None: ...

    @abstractmethod
    async def list_by_portfolio(self, portfolio_id: UUID) -> list[Holding]: ...

    @abstractmethod
    async def save(self, holding: Holding) -> None: ...


class OutboxRepository(ABC):
    @abstractmethod
    async def save(self, record: OutboxRecord) -> None: ...

    @abstractmethod
    async def claim_batch(self, worker_id: str, lease_seconds: int, batch_size: int) -> list[OutboxRecord]: ...

    async def fetch_pending(self, worker_id: str, lease_seconds: int, batch_size: int) -> list[OutboxRecord]:
        """Alias for claim_batch — satisfies OutboxRepositoryProtocol from libs/messaging."""
        return await self.claim_batch(worker_id, lease_seconds, batch_size)

    @abstractmethod
    async def mark_published(self, record_id: UUID) -> None: ...

    @abstractmethod
    async def increment_attempts(self, record_id: UUID) -> None: ...

    @abstractmethod
    async def move_to_dead_letter(self, record_id: UUID) -> None: ...


class IdempotencyRepository(ABC):
    @abstractmethod
    async def exists(self, event_id: UUID) -> bool: ...

    @abstractmethod
    async def record(self, event_id: UUID, processed_at: datetime | None = None) -> None: ...
