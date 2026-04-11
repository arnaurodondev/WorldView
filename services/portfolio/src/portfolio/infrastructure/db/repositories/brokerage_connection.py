"""SQLAlchemy implementation of BrokerageConnectionRepository.

Security invariants (AD-3 / PRD-0022 F-19):
- ``snaptrade_user_secret`` is encrypted at rest using Fernet symmetric encryption when
  a cipher is provided.  In dev mode (empty key), plaintext is stored.
- The cipher key and any decrypted secret MUST NEVER appear in logs, tracebacks, or
  structured fields.  Only ``connection_id``, ``user_id``, and ``brokerage_name`` are
  safe to log.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

from portfolio.application.ports.repositories import BrokerageConnectionRepository
from portfolio.domain.entities.brokerage_connection import BrokerageConnection
from portfolio.domain.enums import ConnectionStatus
from portfolio.infrastructure.db.models.brokerage_connection import BrokerageConnectionModel

if TYPE_CHECKING:
    from uuid import UUID

    from cryptography.fernet import Fernet
    from sqlalchemy.ext.asyncio import AsyncSession


class SqlAlchemyBrokerageConnectionRepository(BrokerageConnectionRepository):
    """SQLAlchemy repository for :class:`BrokerageConnection` entities.

    Args:
        session: The active async SQLAlchemy session.
        cipher: Optional Fernet cipher for encrypting/decrypting
            ``snaptrade_user_secret`` at rest.  Pass ``None`` in dev mode
            (empty ``SNAPTRADE_SECRET_ENCRYPTION_KEY``).
    """

    def __init__(self, session: AsyncSession, cipher: Fernet | None = None) -> None:
        self._session = session
        self._cipher = cipher

    # ── Encryption helpers ─────────────────────────────────────────────────────

    def _encrypt(self, plaintext: str) -> str:
        """Encrypt plaintext → ciphertext string if cipher is configured."""
        return self._cipher.encrypt(plaintext.encode()).decode() if self._cipher else plaintext  # type: ignore[no-any-return]

    def _decrypt(self, ciphertext: str) -> str:
        """Decrypt ciphertext → plaintext string if cipher is configured."""
        return self._cipher.decrypt(ciphertext.encode()).decode() if self._cipher else ciphertext  # type: ignore[no-any-return]

    # ── ORM → domain mapping ───────────────────────────────────────────────────

    def _to_entity(self, row: BrokerageConnectionModel) -> BrokerageConnection:
        return BrokerageConnection(
            id=row.id,
            tenant_id=row.tenant_id,
            user_id=row.user_id,
            portfolio_id=row.portfolio_id,
            snaptrade_user_id=row.snaptrade_user_id,
            snaptrade_user_secret=self._decrypt(row.snaptrade_user_secret),
            authorization_id=row.authorization_id,
            brokerage_name=row.brokerage_name,
            status=ConnectionStatus(row.status),
            snaptrade_tos_accepted_at=row.snaptrade_tos_accepted_at,
            last_synced_at=row.last_synced_at,
            last_sync_cursor=row.last_sync_cursor,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    # ── Repository methods ─────────────────────────────────────────────────────

    async def get(self, connection_id: UUID, tenant_id: UUID) -> BrokerageConnection | None:
        result = await self._session.execute(
            select(BrokerageConnectionModel).where(
                BrokerageConnectionModel.id == connection_id,
                BrokerageConnectionModel.tenant_id == tenant_id,
            ),
        )
        row = result.scalar_one_or_none()
        return self._to_entity(row) if row else None

    async def get_by_user(
        self,
        connection_id: UUID,
        user_id: UUID,
        tenant_id: UUID,
    ) -> BrokerageConnection | None:
        result = await self._session.execute(
            select(BrokerageConnectionModel).where(
                BrokerageConnectionModel.id == connection_id,
                BrokerageConnectionModel.user_id == user_id,
                BrokerageConnectionModel.tenant_id == tenant_id,
            ),
        )
        row = result.scalar_one_or_none()
        return self._to_entity(row) if row else None

    async def list_by_user(
        self,
        user_id: UUID,
        tenant_id: UUID,
        portfolio_id: UUID | None = None,
    ) -> list[BrokerageConnection]:
        stmt = select(BrokerageConnectionModel).where(
            BrokerageConnectionModel.user_id == user_id,
            BrokerageConnectionModel.tenant_id == tenant_id,
        )
        if portfolio_id is not None:
            stmt = stmt.where(BrokerageConnectionModel.portfolio_id == portfolio_id)
        stmt = stmt.order_by(BrokerageConnectionModel.created_at.desc())
        result = await self._session.execute(stmt)
        return [self._to_entity(r) for r in result.scalars()]

    async def list_active_or_error(self) -> list[BrokerageConnection]:
        result = await self._session.execute(
            select(BrokerageConnectionModel).where(
                BrokerageConnectionModel.status.in_(["active", "error"]),
            ),
        )
        return [self._to_entity(r) for r in result.scalars()]

    async def save(self, connection: BrokerageConnection) -> None:
        """Upsert a brokerage connection (INSERT … ON CONFLICT (id) DO UPDATE).

        BP-076: asyncpg does not support ``:param::type`` cast syntax — use
        ``cast(:param AS type)`` instead.  Here we avoid raw SQL casts entirely
        by using the ORM upsert via ``merge``.
        """
        encrypted_secret = self._encrypt(connection.snaptrade_user_secret)

        # Use session.merge for upsert semantics: loads existing row if present,
        # otherwise creates a new one.  All mutable fields are set explicitly so
        # the session tracks them as dirty.
        row = await self._session.get(BrokerageConnectionModel, connection.id)
        if row is None:
            row = BrokerageConnectionModel(
                id=connection.id,
                tenant_id=connection.tenant_id,
                user_id=connection.user_id,
                portfolio_id=connection.portfolio_id,
                snaptrade_user_id=connection.snaptrade_user_id,
                snaptrade_user_secret=encrypted_secret,
                authorization_id=connection.authorization_id,
                brokerage_name=connection.brokerage_name,
                status=str(connection.status),
                snaptrade_tos_accepted_at=connection.snaptrade_tos_accepted_at,
                last_synced_at=connection.last_synced_at,
                last_sync_cursor=connection.last_sync_cursor,
                created_at=connection.created_at,
                updated_at=connection.updated_at,
            )
            self._session.add(row)
        else:
            # Update all mutable fields on the existing row
            row.snaptrade_user_secret = encrypted_secret
            row.authorization_id = connection.authorization_id
            row.brokerage_name = connection.brokerage_name
            row.status = str(connection.status)
            row.last_synced_at = connection.last_synced_at
            row.last_sync_cursor = connection.last_sync_cursor
            row.updated_at = connection.updated_at
