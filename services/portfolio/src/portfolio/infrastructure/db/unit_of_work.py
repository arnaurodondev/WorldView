"""Concrete SQLAlchemy Unit of Work for the Portfolio service."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from portfolio.application.ports.unit_of_work import UnitOfWork
from portfolio.infrastructure.db.repositories.holding import SqlAlchemyHoldingRepository
from portfolio.infrastructure.db.repositories.idempotency import SqlAlchemyIdempotencyRepository
from portfolio.infrastructure.db.repositories.instrument import SqlAlchemyInstrumentRepository
from portfolio.infrastructure.db.repositories.outbox import SqlAlchemyOutboxRepository
from portfolio.infrastructure.db.repositories.portfolio import SqlAlchemyPortfolioRepository
from portfolio.infrastructure.db.repositories.tenant import SqlAlchemyTenantRepository
from portfolio.infrastructure.db.repositories.transaction import SqlAlchemyTransactionRepository
from portfolio.infrastructure.db.repositories.user import SqlAlchemyUserRepository

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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


class SqlAlchemyUnitOfWork(UnitOfWork):
    """Concrete unit of work backed by an async SQLAlchemy session.

    Usage::

        async with SqlAlchemyUnitOfWork(session_factory) as uow:
            tenant = await uow.tenants.get(tenant_id)
            await uow.commit()
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        on_commit: Callable[[], None] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._on_commit = on_commit
        self._session: AsyncSession | None = None
        self._tenants: SqlAlchemyTenantRepository | None = None
        self._users: SqlAlchemyUserRepository | None = None
        self._portfolios: SqlAlchemyPortfolioRepository | None = None
        self._instruments: SqlAlchemyInstrumentRepository | None = None
        self._transactions: SqlAlchemyTransactionRepository | None = None
        self._holdings: SqlAlchemyHoldingRepository | None = None
        self._outbox: SqlAlchemyOutboxRepository | None = None
        self._idempotency: SqlAlchemyIdempotencyRepository | None = None

    async def __aenter__(self) -> SqlAlchemyUnitOfWork:
        self._session = self._session_factory()
        self._tenants = SqlAlchemyTenantRepository(self._session)
        self._users = SqlAlchemyUserRepository(self._session)
        self._portfolios = SqlAlchemyPortfolioRepository(self._session)
        self._instruments = SqlAlchemyInstrumentRepository(self._session)
        self._transactions = SqlAlchemyTransactionRepository(self._session)
        self._holdings = SqlAlchemyHoldingRepository(self._session)
        self._outbox = SqlAlchemyOutboxRepository(self._session)
        self._idempotency = SqlAlchemyIdempotencyRepository(self._session)
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        try:
            if exc_type is not None:
                await self.rollback()
            else:
                await self.commit()
        finally:
            if self._session is not None:
                await self._session.close()
                self._session = None

    @property
    def tenants(self) -> TenantRepository:
        assert self._tenants is not None, "UnitOfWork not entered"
        return self._tenants

    @property
    def users(self) -> UserRepository:
        assert self._users is not None, "UnitOfWork not entered"
        return self._users

    @property
    def portfolios(self) -> PortfolioRepository:
        assert self._portfolios is not None, "UnitOfWork not entered"
        return self._portfolios

    @property
    def instruments(self) -> InstrumentRepository:
        assert self._instruments is not None, "UnitOfWork not entered"
        return self._instruments

    @property
    def transactions(self) -> TransactionRepository:
        assert self._transactions is not None, "UnitOfWork not entered"
        return self._transactions

    @property
    def holdings(self) -> HoldingRepository:
        assert self._holdings is not None, "UnitOfWork not entered"
        return self._holdings

    @property
    def outbox(self) -> OutboxRepository:
        assert self._outbox is not None, "UnitOfWork not entered"
        return self._outbox

    @property
    def idempotency(self) -> IdempotencyRepository:
        assert self._idempotency is not None, "UnitOfWork not entered"
        return self._idempotency

    async def commit(self) -> None:
        assert self._session is not None, "UnitOfWork not entered"
        await self._session.commit()
        if self._on_commit is not None:
            self._on_commit()

    async def rollback(self) -> None:
        assert self._session is not None, "UnitOfWork not entered"
        await self._session.rollback()
