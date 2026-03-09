"""Abstract Unit of Work for the Portfolio application layer."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from portfolio.application.ports.repositories import (
        HoldingRepository,
        IdempotencyRepository,
        InstrumentRepository,
        OutboxRepository,
        PortfolioRepository,
        TenantRepository,
        TransactionRepository,
        UserRepository,
    )


class UnitOfWork(ABC):
    """Abstract unit of work providing access to all 8 repositories."""

    @property
    @abstractmethod
    def tenants(self) -> TenantRepository: ...

    @property
    @abstractmethod
    def users(self) -> UserRepository: ...

    @property
    @abstractmethod
    def portfolios(self) -> PortfolioRepository: ...

    @property
    @abstractmethod
    def instruments(self) -> InstrumentRepository: ...

    @property
    @abstractmethod
    def transactions(self) -> TransactionRepository: ...

    @property
    @abstractmethod
    def holdings(self) -> HoldingRepository: ...

    @property
    @abstractmethod
    def outbox(self) -> OutboxRepository: ...

    @property
    @abstractmethod
    def idempotency(self) -> IdempotencyRepository: ...

    @abstractmethod
    async def commit(self) -> None: ...

    @abstractmethod
    async def rollback(self) -> None: ...

    async def __aenter__(self) -> UnitOfWork:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if exc_type is not None:
            await self.rollback()
        else:
            await self.commit()
